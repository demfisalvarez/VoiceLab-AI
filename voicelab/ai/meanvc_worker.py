"""Proceso aparte para la «Voz instantánea en directo» (MeanVC2, PyTorch en CPU).

Se ejecuta con el Python del entorno ``vc-runtime`` (donde está PyTorch), nunca
dentro de la aplicación principal: así el audio en tiempo real no compite con
el intérprete de PyTorch por el GIL y, si algo falla, la app sigue en pie.

Protocolo binario por stdin/stdout. Cada mensaje es::

    1 byte de tipo · 4 bytes de longitud (uint32, little endian) · datos

Peticiones (app → proceso):
    E  float32[256]   fijar la huella de voz (embedding) del hablante destino
    R  float32[n]     calcular la huella a partir de audio de referencia a 16 kHz
    A  float32[n]     convertir un bloque de audio a 16 kHz (``chunk`` muestras, ver «hello»)
    Z  -              reiniciar el estado del streaming
    Q  -              terminar

Respuestas (proceso → app):
    J  JSON           estado / errores (``{"ok": true, ...}``)
    E  float32[256]   huella calculada
    A  float32[m]     audio convertido a 16 kHz (m puede ser 0)

Este archivo no importa nada de VoiceLab: la app lo lanza por ruta con
``python -I meanvc_worker.py --code … --weights …``.
"""

from __future__ import annotations

import json
import os
import struct
import sys

HEADER = struct.Struct("<cI")
SR = 16000
CHUNK = 2560
# Bloque natural de cada modelo (múltiplo del paso del reconocedor): 160 ms para el
# de 120 ms (reconocedor de 160 ms) y 80 ms para el de 40 ms (reconocedor de 80 ms).
CHUNKS = {"120ms": 2560, "40ms": 1280}
# Ventana y paso del reconocedor (tramas de 10 ms) y paso de la conversión (tramas).
ASR_GEOMETRY = {"120ms": (19, 16), "40ms": (11, 8)}
VC_CHUNK = {"120ms": 12, "40ms": 4}
EMB_DIM = 256
MAX_REF_S = 30

# Arquitectura de WavLM-Large (la misma que el «cfg» de WavLM-Large.pt y que
# config.json de microsoft/wavlm-large). Evita descargar 1,26 GB solo para
# leer esta configuración. Los pesos se validan al cargarlos: si la estructura
# no encajara, faltarían pesos y el proceso lo avisa en vez de seguir.
WAVLM_LARGE_CFG = {
    "extractor_mode": "layer_norm",
    "encoder_layers": 24,
    "encoder_embed_dim": 1024,
    "encoder_ffn_embed_dim": 4096,
    "encoder_attention_heads": 16,
    "activation_fn": "gelu",
    "layer_norm_first": True,
    "conv_feature_layers": "[(512,10,5)] + [(512,3,2)] * 4 + [(512,2,2)] * 2",
    "conv_bias": False,
    "feature_grad_mult": 0.0,
    "normalize": True,
    "dropout": 0.0, "attention_dropout": 0.0, "activation_dropout": 0.0,
    "encoder_layerdrop": 0.0, "dropout_input": 0.0, "dropout_features": 0.0,
    "conv_pos": 128,
    "conv_pos_groups": 16,
    "relative_position_embedding": True,
    "num_buckets": 320,
    "max_distance": 800,
    "gru_rel_pos": True,
}

WEIGHT_FILES = {
    "120ms": ("fastu2pp_160ms.pt", "meanvc2_120ms_40ms.safetensors", "vocos.pt"),
    "40ms": ("fastu2pp_80ms.pt", "meanvc2_40ms_40ms.safetensors", "vocos.pt"),
}
SPEAKER_FILE = "wavlm_large_finetune.pth"


def alignment(model: str, chunk: int) -> int:
    """Muestras a descartar tras reiniciar para que cada ventana del reconocedor se
    complete justo al llegar un bloque (sin tramas esperando de más = menos retraso)."""
    window = ASR_GEOMETRY[model][0]
    need = (window - 1) * 160 + 400                 # muestras para la primera ventana completa
    k = -(-need // chunk)
    return k * chunk - need


def hold(model: str, chunk: int) -> tuple[float, float]:
    """Audio retenido dentro del modelo tras cada bloque, en ms (con la alineación):
    el máximo y cuánto varía de un bloque a otro (ráfagas, p. ej. 120/120/240 ms)."""
    window, stride = ASR_GEOMETRY[model]
    asr = ((window - stride) * 160 + 240) / 16      # contexto del reconocedor + solape de la última trama
    per_call = chunk // 160                         # tramas de 10 ms que aporta cada bloque
    vc, block = VC_CHUNK[model], 4
    left, seen = 0, []
    for i in range(24):                             # ciclo de la conversión
        left += per_call
        while left >= vc + block:
            left -= vc
        if i >= 12:
            seen.append(left)
    return asr + max(seen) * 10 + 10, (max(seen) - min(seen)) * 10.0   # + solape del vocoder


def encode_any(self, samples):
    """``VCRunner._encode_chunk`` de MeanVC2 para bloques de cualquier tamaño.

    Idéntica al original salvo la interpolación ×4 de las tramas del reconocedor
    (40 ms) a tramas de mel (10 ms): el original la fija a 16 tramas (bloques de
    160 ms); aquí es 4 × las tramas nuevas, así que con bloques de 160 ms da lo
    mismo y con bloques de 80 ms no estira ni comprime el tiempo.
    """
    import numpy as np
    import torch
    import torch.nn.functional as F
    import torchaudio.compliance.kaldi as kaldi

    with torch.no_grad():
        padded = np.concatenate((self.samples_cache, samples)) if self.samples_cache.size else samples
        if len(padded) < 400:
            self.samples_cache = padded
            return None
        wav_t = torch.from_numpy(np.ascontiguousarray(padded * (1 << 15), dtype=np.float32)).unsqueeze(0)
        fbanks = kaldi.fbank(wav_t, frame_length=25, frame_shift=10, snip_edges=True, num_mel_bins=80,
                             energy_floor=0.0, dither=0.0, sample_frequency=16000)
        self.samples_cache = padded[160 * fbanks.shape[0]:]
        if self.frame_cache is not None:
            fbanks = torch.cat([self.frame_cache, fbanks], dim=0)
        if self.asr_offset >= 4000:
            cache_t = self.asr_att_cache.size(2) if self.asr_att_cache.dim() > 0 else 0
            self.asr_offset = max(cache_t, self.asr_offset - 4000)
        bns = []
        i = 0
        while i + self._bn_window <= fbanks.shape[0]:
            out, self.asr_att_cache, self.asr_cnn_cache = self.asr(
                fbanks[i:i + self._bn_window].unsqueeze(0),
                torch.tensor(self.asr_offset, dtype=torch.int64),
                torch.tensor(self._required_cache_size, dtype=torch.int64),
                self.asr_att_cache, self.asr_cnn_cache,
            )
            bns.append(out.squeeze(0).detach())
            self.asr_offset += self._asr_offset_step
            i += self._bn_stride
        self.frame_cache = fbanks[i:]
        if not bns:
            return None
        bn = torch.cat(bns, dim=0).unsqueeze(0)                     # [1, N, 256]
        n_new = bn.shape[1]
        prev = self.encoder_output_cache if self.encoder_output_cache is not None else bn[:, :1, :]
        bn = torch.cat([prev, bn], dim=1)
        self.encoder_output_cache = bn[:, -1:, :]
        up = F.interpolate(bn.transpose(1, 2), size=4 * n_new + 1, mode="linear", align_corners=True)
        return up.transpose(1, 2)[:, 1:, :]


# ------------------------------------------------------------------ protocolo
def read_exact(f, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        part = f.read(n - len(buf))
        if not part:
            raise EOFError("canal cerrado")
        buf += part
    return bytes(buf)


def send(f, kind: bytes, payload: bytes = b"") -> None:
    f.write(HEADER.pack(kind, len(payload)))
    if payload:
        f.write(payload)
    f.flush()


def recv(f) -> tuple[bytes, bytes]:
    kind, n = HEADER.unpack(read_exact(f, HEADER.size))
    return kind, (read_exact(f, n) if n else b"")


def send_json(f, obj: dict) -> None:
    send(f, b"J", json.dumps(obj, ensure_ascii=False).encode("utf-8"))


# --------------------------------------------------------------------- modelo
class Engine:
    def __init__(self, code: str, weights: str, model: str, threads: int = 1, hd: str | None = None,
                 chunk: int | None = None):
        import types

        import numpy as np
        import torch

        self.np, self.torch = np, torch
        self.weights, self.model = weights, model
        missing = [f for f in WEIGHT_FILES[model] if not os.path.isfile(os.path.join(weights, f))]
        if missing:
            raise FileNotFoundError("Faltan archivos del modelo: " + ", ".join(missing))
        sys.path.insert(0, code)
        sys.path.insert(0, os.path.join(code, "runtime"))

        # Los modelos TorchScript se cargan siempre en la CPU.
        _jit_load = torch.jit.load
        torch.jit.load = lambda f, *a, **k: _jit_load(f, *a, **{"map_location": "cpu", **k})

        import run_rt  # MeanVC2 sin modificar

        paths = run_rt.MODEL_PATHS[model]
        paths["asr_ckpt"] = os.path.join(weights, os.path.basename(paths["asr_ckpt"]))
        paths["ckpt"] = os.path.join(weights, os.path.basename(paths["ckpt"]))
        run_rt.VOCODER_PATH = os.path.join(weights, "vocos.pt")
        # La huella del hablante se calcula aparte (y se guarda en el perfil),
        # así el modelo de 1,3 GB solo se carga cuando hace falta.
        run_rt.init_speaker_model = lambda *a, **k: None
        run_rt.extract_embedding = lambda *a, **k: torch.zeros(1, EMB_DIM)
        self.runner = run_rt.VCRunner(target_wav="", device="cpu", model=model)
        self.runner._encode_chunk = types.MethodType(encode_any, self.runner)
        self.chunk = int(chunk or CHUNKS[model])
        if self.chunk % 160:
            raise ValueError("El bloque debe ser múltiplo de 160 muestras")
        self.align = alignment(model, self.chunk)
        self.hold_ms, self.burst_ms = hold(model, self.chunk)
        torch.set_num_threads(max(1, threads))
        torch.manual_seed(0)
        self.has_speaker = False
        silence = np.zeros(self.chunk, np.float32)
        for _ in range(6):                       # calentamiento de TorchScript
            self.runner.process_chunk(silence)
        self.runner._init_cache()
        # Alta definición: AP-BWE amplía la salida de 16 kHz a 48 kHz (graves intactos, agudos nuevos).
        self.bwe = None
        self.out_sr = SR
        if hd:
            if not os.path.isfile(hd):
                raise FileNotFoundError("Faltan los pesos de alta definición: " + hd)
            sys.path.insert(0, os.path.join(os.path.dirname(code), "apbwe"))
            import bwe as apbwe
            model_bwe, h = apbwe.load(hd)
            self.bwe = apbwe.StreamingBWE(model_bwe, h)
            self.out_sr = h["hr_sampling_rate"]
            self.hold_ms += (self.bwe.latency + self.bwe.hop) * 1000 / self.bwe.sr   # contexto futuro de la HD
            self.bwe.process(np.zeros(self.chunk, np.float32))     # calentamiento
            self.bwe.reset()

    def set_embedding(self, emb) -> None:
        t = self.torch.from_numpy(emb.reshape(1, EMB_DIM).astype("float32").copy())
        with self.torch.no_grad():
            self.runner.vc_spk_emb = t
            self.runner.vc_gtm_kv = self.runner.vc.gtm(t)
        self.reset()
        self.has_speaker = True

    def compute_embedding(self, audio):
        import gc

        torch, np = self.torch, self.np
        from src.speaker import ECAPA_TDNN_SMALL

        ckpt = os.path.join(self.weights, SPEAKER_FILE)
        if not os.path.isfile(ckpt):
            raise FileNotFoundError("Falta " + SPEAKER_FILE)
        cfg = os.path.join(self.weights, "wavlm_large_cfg.pt")
        if not os.path.isfile(cfg):
            torch.save(dict(WAVLM_LARGE_CFG), cfg)
        audio = audio[: MAX_REF_S * SR]
        model = ECAPA_TDNN_SMALL(feat_dim=1024, emb_dim=EMB_DIM, feat_type="wavlm_large",
                                 feature_selection="hidden_states", update_extract=False, config_path=cfg)
        state = torch.load(ckpt, map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model" in state:
            state = state["model"]
        res = model.load_state_dict(state, strict=False)
        lost = [k for k in res.missing_keys if not k.endswith("num_batches_tracked")]
        if lost:
            raise RuntimeError(f"El codificador de hablante no coincide con sus pesos ({len(lost)} sin cargar, p. ej. {lost[:3]})")
        model.eval()
        threads = torch.get_num_threads()
        torch.set_num_threads(max(threads, min(8, os.cpu_count() or 1)))   # cálculo puntual: más núcleos
        try:
            with torch.no_grad():
                emb = model(torch.from_numpy(np.ascontiguousarray(audio, np.float32)).unsqueeze(0))
        finally:
            torch.set_num_threads(threads)
        del model, state
        gc.collect()
        return emb.reshape(-1).numpy().astype(np.float32)

    def process(self, chunk):
        out = self.runner.process_chunk(chunk.astype(self.np.float32))
        out = self.np.zeros(0, self.np.float32) if out is None else self.np.asarray(out, self.np.float32)
        if self.bwe is not None:
            out = self.bwe.process(out) if out.shape[0] else self.np.zeros(0, self.np.float32)
        return out

    def reset(self) -> None:
        self.runner._init_cache()
        if self.bwe is not None:
            self.bwe.reset()


def main(argv=None) -> int:
    import argparse
    import traceback

    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--model", default="120ms", choices=tuple(WEIGHT_FILES))
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--hd", default=None, help="pesos de AP-BWE para salir a 48 kHz")
    ap.add_argument("--chunk", type=int, default=0, help="muestras por bloque (0 = el natural del modelo)")
    args = ap.parse_args(argv)

    # El canal binario es una copia de stdout; cualquier print() de las
    # bibliotecas acaba en stderr (el registro) y no puede corromperlo.
    out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    inp = sys.stdin.buffer

    try:
        import numpy as np
        eng = Engine(args.code, args.weights, args.model, args.threads, args.hd, args.chunk or None)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        msg = f"{type(exc).__name__}: {exc}"
        if "dll" in msg.lower():
            msg += (" — Puede faltar el «Microsoft Visual C++ Redistributable (x64)»: instálalo desde "
                    "https://aka.ms/vs/17/release/vc_redist.x64.exe y vuelve a intentarlo.")
        send_json(out, {"ok": False, "error": msg})
        return 2
    import torch
    send_json(out, {"ok": True, "model": args.model, "chunk": eng.chunk, "align": eng.align,
                    "hold_ms": round(eng.hold_ms, 1), "burst_ms": eng.burst_ms, "sr": SR, "out_sr": eng.out_sr,
                    "hd": eng.bwe is not None, "torch": torch.__version__})

    while True:
        try:
            kind, data = recv(inp)
        except EOFError:
            return 0
        try:
            if kind == b"A":
                if not eng.has_speaker:
                    raise RuntimeError("No se ha fijado la voz de destino")
                send(out, b"A", eng.process(np.frombuffer(data, np.float32)).tobytes())
            elif kind == b"E":
                eng.set_embedding(np.frombuffer(data, np.float32))
                send_json(out, {"ok": True})
            elif kind == b"R":
                send(out, b"E", eng.compute_embedding(np.frombuffer(data, np.float32)).tobytes())
            elif kind == b"Z":
                eng.reset()
                send_json(out, {"ok": True})
            elif kind == b"Q":
                return 0
            else:
                send_json(out, {"ok": False, "error": f"petición desconocida {kind!r}"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            send_json(out, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    sys.exit(main())
