"""Entrenamiento de una voz RVC v2 (40 kHz) a partir de material preparado por la app.

Se ejecuta con el Python del entorno de PyTorch de la app (``vc-runtime``), en un
proceso aparte y con prioridad baja, así el PC se puede seguir usando:

    python -I rvc_trainer.py --code <vendor> --data <dataset.npz> --out <carpeta>
                             --pretrain-g f0G40k.pth --pretrain-d f0D40k.pth
                             [--minutes 60 | --steps N] [--threads 7] [--batch 8]

Habla por la salida estándar con líneas JSON:
    {"type": "ready", "pieces": n, "minutes": m, "resumed_step": s}
    {"type": "progress", "step": s, "total": t, "eta_s": e, "loss_mel": l, "s_per_step": x}
    {"type": "saved", "step": s}
    {"type": "exported", "path": ".../model.onnx", "step": s}
    {"type": "error", "message": "..."}

Para pararlo sin perder nada: crear el archivo ``<out>/STOP``. Guarda el punto de
control, exporta lo aprendido hasta ese momento a ONNX y termina. Si se vuelve a
lanzar con la misma carpeta, continúa donde lo dejó.

El modelo y las pérdidas son los de RVC-Project (MIT, ``vendor/rvc``); el bucle es
el de ``train/train.py`` simplificado para la CPU y un solo proceso.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

SR = 40000
HOP = 400
SEGMENT = 12800                       # muestras que genera el decodificador en cada paso (0,32 s)
HP = {
    "data": {"filter_length": 2048, "hop_length": HOP, "win_length": 2048, "n_mel_channels": 125,
             "mel_fmin": 0.0, "mel_fmax": None},
    "model": {"inter_channels": 192, "hidden_channels": 192, "filter_channels": 768, "n_heads": 2,
              "n_layers": 6, "kernel_size": 3, "p_dropout": 0, "resblock": "1",
              "resblock_kernel_sizes": [3, 7, 11], "resblock_dilation_sizes": [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
              "upsample_rates": [10, 10, 2, 2], "upsample_initial_channel": 512,
              "upsample_kernel_sizes": [16, 16, 4, 4], "spk_embed_dim": 109, "gin_channels": 256},
    "train": {"learning_rate": 1e-4, "betas": (0.8, 0.99), "eps": 1e-9, "c_mel": 45, "c_kl": 1.0},
}


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def coarse_f0(f0):
    """Igual que ``voicelab.ai.rvc.coarse_f0`` (y que RVC): tono a 255 casillas en escala mel."""
    import numpy as np
    f0_min, f0_max = 50.0, 1100.0
    mel_min, mel_max = 1127 * np.log(1 + f0_min / 700), 1127 * np.log(1 + f0_max / 700)
    mel = 1127 * np.log(1 + f0 / 700)
    pos = mel > 0
    mel[pos] = (mel[pos] - mel_min) * 254 / (mel_max - mel_min) + 1
    mel[mel <= 1] = 1
    mel[mel > 255] = 255
    return np.rint(mel).astype(np.int64)


class Dataset:
    """Trozos de voz ya preparados: audio a 40 kHz, rasgos de contenido (50/s) y tono (100/s)."""

    def __init__(self, path: Path, max_frames: int):
        import numpy as np
        z = np.load(path)
        self.wav, self.wav_off = z["wav"], z["wav_off"]
        self.feat, self.feat_off = z["feat"], z["feat_off"]
        self.f0, self.f0_off = z["f0"], z["f0_off"]
        self.max_frames = max_frames
        self.items = []
        for i in range(len(self.wav_off) - 1):
            n = min((self.wav_off[i + 1] - self.wav_off[i]) // HOP,
                    2 * (self.feat_off[i + 1] - self.feat_off[i]),
                    self.f0_off[i + 1] - self.f0_off[i])
            if n >= SEGMENT // HOP + 8:
                self.items.append((i, int(n)))
        self.seconds = sum(n for _, n in self.items) * HOP / SR

    def get(self, k: int):
        import numpy as np
        i, n = self.items[k]
        frames = min(n, self.max_frames)
        s = random.randint(0, n - frames)
        w0 = self.wav_off[i] + s * HOP
        wav = self.wav[w0:w0 + frames * HOP].astype(np.float32) / 32768.0
        f = self.feat[self.feat_off[i]:self.feat_off[i + 1]]
        feat = np.repeat(f, 2, axis=0)[s:s + frames].astype(np.float32)
        f0 = self.f0[self.f0_off[i] + s:self.f0_off[i] + s + frames].astype(np.float32)
        return wav, feat, f0

    def batch(self, size: int):
        import numpy as np
        import torch
        from rvc.mel_processing import spectrogram_torch
        picks = [self.get(random.randrange(len(self.items))) for _ in range(size)]
        t = max(p[1].shape[0] for p in picks)
        phone = np.zeros((size, t, 768), np.float32)
        pitchf = np.zeros((size, t), np.float32)
        wave = np.zeros((size, 1, t * HOP), np.float32)
        lens = np.zeros(size, np.int64)
        for b, (w, f, p) in enumerate(picks):
            n = f.shape[0]
            phone[b, :n], pitchf[b, :n], wave[b, 0, :n * HOP], lens[b] = f, p, w[:n * HOP], n
        wave_t = torch.from_numpy(wave)
        d = HP["data"]
        spec = spectrogram_torch(wave_t.squeeze(1), d["filter_length"], SR, d["hop_length"], d["win_length"],
                                 center=False)[:, :, :t]
        lens_t = torch.from_numpy(lens)
        return (torch.from_numpy(phone), lens_t, torch.from_numpy(coarse_f0(pitchf.copy())),
                torch.from_numpy(pitchf), spec, lens_t, wave_t)


class Exportable:
    """Inferencia de RVC para ONNX con «skip_head»: el decodificador (lo caro) solo
    procesa las tramas finales; en directo el contexto anterior no se vuelve a sintetizar."""

    @staticmethod
    def build(net_g):
        import torch
        from torch import nn

        class Infer(nn.Module):
            def __init__(self, g):
                super().__init__()
                self.g = g

            def forward(self, phone, phone_lengths, pitch, pitchf, ds, rnd, skip_head):
                g = self.g.emb_g(ds).unsqueeze(-1)
                m_p, logs_p, x_mask = self.g.enc_p(phone, pitch, phone_lengths)
                z_p = (m_p + torch.exp(logs_p) * rnd * 0.66666) * x_mask
                z = self.g.flow(z_p, x_mask, g=g, reverse=True)
                idx = torch.arange(skip_head[0], phone.shape[1], dtype=torch.int64)
                z = torch.index_select(z, 2, idx) * torch.index_select(x_mask, 2, idx)
                return self.g.dec(z, torch.index_select(pitchf, 1, idx), g=g)

        return Infer(net_g)


def new_generator():
    from rvc.models import SynthesizerTrnMs768NSFsid
    d = HP["data"]
    return SynthesizerTrnMs768NSFsid(d["filter_length"] // 2 + 1, SEGMENT // HOP, **HP["model"], is_half=False, sr=SR)


def _export_safe_attention() -> None:
    """Atención relativa sin ``int()``/``max()`` de Python sobre la longitud.

    Al exportar con trazado, esas conversiones dejan fija la longitud del ejemplo y el
    modelo falla (o se equivoca) con otras. Estas versiones hacen lo mismo con
    operaciones que ONNX mantiene dinámicas (como el exportador de RVC original).
    """
    import torch.nn.functional as F
    from rvc import attentions
    mha = attentions.MultiHeadAttention
    pad_max = 4096                                         # hasta 41 s por llamada

    def get_relative_embeddings(self, rel, length):
        start = pad_max + self.window_size + 1 - length
        return F.pad(rel, [0, 0, pad_max, pad_max, 0, 0])[:, start:start + 2 * length - 1]

    def rel_to_abs(self, x):
        batch, heads, length, _ = x.size()
        x = F.pad(x, [0, 1, 0, 0, 0, 0, 0, 0])
        x_flat = F.pad(x.view([batch, heads, length * 2 * length]), [0, length - 1, 0, 0, 0, 0])
        return x_flat.view([batch, heads, length + 1, 2 * length - 1])[:, :, :length, length - 1:]

    def abs_to_rel(self, x):
        batch, heads, length, _ = x.size()
        x = F.pad(x, [0, length - 1, 0, 0, 0, 0, 0, 0])
        x_flat = F.pad(x.view([batch, heads, length * length + length * (length - 1)]), [length, 0, 0, 0, 0, 0])
        return x_flat.view([batch, heads, length, 2 * length])[:, :, :, 1:]

    mha._get_relative_embeddings = get_relative_embeddings
    mha._relative_position_to_absolute_position = rel_to_abs
    mha._absolute_position_to_relative_position = abs_to_rel


def export_onnx(net_g, path: Path) -> None:
    import torch
    _export_safe_attention()
    g = new_generator()                        # copia limpia (deepcopy no admite weight_norm tras entrenar)
    g.load_state_dict(net_g.state_dict())
    g = g.float().eval()
    g.dec.remove_weight_norm()
    g.flow.remove_weight_norm()
    if hasattr(g, "enc_q"):
        del g.enc_q
    model = Exportable.build(g).eval()
    t = 200
    args = (torch.randn(1, t, 768), torch.tensor([t], dtype=torch.int64), torch.randint(1, 255, (1, t)),
            torch.rand(1, t) * 300 + 80, torch.zeros(1, dtype=torch.int64), torch.randn(1, 192, t),
            torch.tensor([150], dtype=torch.int64))
    tmp = path.with_suffix(".tmp.onnx")
    with torch.no_grad():
        torch.onnx.export(model, args, str(tmp), opset_version=17, do_constant_folding=True,
                          input_names=["phone", "phone_lengths", "pitch", "pitchf", "ds", "rnd", "skip_head"],
                          output_names=["audio"],
                          dynamic_axes={"phone": [1], "pitch": [1], "pitchf": [1], "rnd": [2], "audio": [2]})
    os.replace(tmp, path)


def load_state(path: Path):
    import torch
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except Exception:  # noqa: BLE001  (pesos antiguos con objetos de Python: archivo verificado por SHA-256)
        return torch.load(path, map_location="cpu", weights_only=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="carpeta vendor (contiene «rvc»)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pretrain-g", required=True)
    ap.add_argument("--pretrain-d", required=True)
    ap.add_argument("--minutes", type=float, default=60.0, help="tiempo de entrenamiento (si no hay --steps)")
    ap.add_argument("--steps", type=int, default=0)
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2 - 1))
    ap.add_argument("--batch", type=int, default=4, help="como RVC: más pasos por hora en la CPU")
    ap.add_argument("--max-frames", type=int, default=200, help="tramas por ejemplo (2 s): más rápido en CPU")
    ap.add_argument("--save-every", type=float, default=600.0, help="segundos entre puntos de control")
    ap.add_argument("--extend", action="store_true", help="seguir entrenando «--minutes» más tras terminar")
    args = ap.parse_args()
    sys.path.insert(0, args.code)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stop_file = out / "STOP"
    if stop_file.exists():
        stop_file.unlink()
    try:
        import torch
        import torch.nn.functional as F
        from rvc import commons
        from rvc.losses import discriminator_loss, feature_loss, generator_loss, kl_loss
        from rvc.mel_processing import mel_spectrogram_torch, spec_to_mel_torch
        from rvc.models import MultiPeriodDiscriminatorV2

        torch.set_num_threads(max(1, args.threads))
        random.seed(1234)
        torch.manual_seed(1234)
        data = Dataset(Path(args.data), args.max_frames)
        if not data.items:
            raise RuntimeError("No hay trozos de voz suficientes para entrenar.")
        d = HP["data"]
        net_g = new_generator()
        net_d = MultiPeriodDiscriminatorV2(False)
        tr = HP["train"]
        optim_g = torch.optim.AdamW(net_g.parameters(), tr["learning_rate"], betas=tr["betas"], eps=tr["eps"])
        optim_d = torch.optim.AdamW(net_d.parameters(), tr["learning_rate"], betas=tr["betas"], eps=tr["eps"])
        ckpt = out / "checkpoint.pt"
        step, spent = 0, 0.0
        if ckpt.exists():
            st = torch.load(ckpt, map_location="cpu", weights_only=True)
            net_g.load_state_dict(st["g"])
            net_d.load_state_dict(st["d"])
            optim_g.load_state_dict(st["og"])
            optim_d.load_state_dict(st["od"])
            step, spent = int(st["step"]), float(st["spent"])
            total = 0 if args.extend else int(st["total"])
        else:
            net_g.load_state_dict(load_state(Path(args.pretrain_g))["model"])
            net_d.load_state_dict(load_state(Path(args.pretrain_d))["model"])
            total = args.steps or 0
        emit(type="ready", pieces=len(data.items), minutes=round(data.seconds / 60, 1), resumed_step=step,
             threads=torch.get_num_threads())

        def save():
            tmp = ckpt.with_suffix(".tmp")
            torch.save({"g": net_g.state_dict(), "d": net_d.state_dict(), "og": optim_g.state_dict(),
                        "od": optim_d.state_dict(), "step": step, "spent": spent, "total": total}, tmp)
            os.replace(tmp, ckpt)
            emit(type="saved", step=step)

        net_g.train()
        net_d.train()
        sid = torch.zeros(args.batch, dtype=torch.int64)
        last_save = last_emit = time.monotonic()
        started, step0, mel_avg = time.monotonic(), step, None
        while total == 0 or step < total:
            if stop_file.exists():
                break
            t0 = time.monotonic()
            phone, plen, pitch, pitchf, spec, slen, wave = data.batch(args.batch)
            y_hat, ids, _x_mask, z_mask, (_z, z_p, m_p, logs_p, _m_q, logs_q) = net_g(
                phone, plen, pitch, pitchf, spec, slen, sid)
            mel = spec_to_mel_torch(spec, d["filter_length"], d["n_mel_channels"], SR, d["mel_fmin"], d["mel_fmax"])
            y_mel = commons.slice_segments(mel, ids, SEGMENT // HOP)
            y_hat_mel = mel_spectrogram_torch(y_hat.float().squeeze(1), d["filter_length"], d["n_mel_channels"], SR,
                                              HOP, d["win_length"], d["mel_fmin"], d["mel_fmax"])
            wave = commons.slice_segments(wave, ids * HOP, SEGMENT)
            y_d_r, y_d_g, _, _ = net_d(wave, y_hat.detach())
            loss_disc, _, _ = discriminator_loss(y_d_r, y_d_g)
            optim_d.zero_grad()
            loss_disc.backward()
            optim_d.step()
            y_d_r, y_d_g, fmap_r, fmap_g = net_d(wave, y_hat)
            loss_mel = F.l1_loss(y_mel, y_hat_mel) * tr["c_mel"]
            loss_kl = kl_loss(z_p, logs_q, m_p, logs_p, z_mask) * tr["c_kl"]
            loss_gen, _ = generator_loss(y_d_g)
            loss = loss_gen + feature_loss(fmap_r, fmap_g) + loss_mel + loss_kl
            optim_g.zero_grad()
            loss.backward()
            optim_g.step()
            step += 1
            dt = time.monotonic() - t0
            spent += dt
            lm = float(loss_mel.item())
            mel_avg = lm if mel_avg is None else 0.95 * mel_avg + 0.05 * lm
            per_step = (time.monotonic() - started) / max(1, step - step0)
            if total == 0 and step - step0 >= 5:          # presupuesto en minutos → pasos
                total = max(step + 1, step0 + int(args.minutes * 60 / per_step))
            now = time.monotonic()
            if now - last_emit >= 5 or step == total:
                last_emit = now
                emit(type="progress", step=step, total=total, loss_mel=round(mel_avg, 3),
                     s_per_step=round(per_step, 2), eta_s=int(max(0, total - step) * per_step))
            if now - last_save >= args.save_every:
                last_save = now
                save()
        save()
        model = out / "model.onnx"
        export_onnx(net_g, model)
        emit(type="exported", path=str(model), step=step, total=total, loss_mel=round(mel_avg or 0.0, 3))
        if stop_file.exists():
            stop_file.unlink()
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        emit(type="error", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
