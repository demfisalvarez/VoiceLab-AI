"""Calidad y retraso de la voz instantánea en directo con los modelos REALES (Windows).

Para cada configuración (modelo «120ms» o «40ms», tamaño de bloque, alta definición)
convierte la voz A (David) hacia la voz B (Zira) y mide:

* se entiende: Whisper sobre la voz convertida;
* se parece a B: similitud de huellas de voz (el mismo codificador que usa el modelo);
* entonación: correlación del contorno de tono con el original, rango de tono (semitonos)
  respecto al original y temblor entre tramas (lo que suena «robótico»);
* calidad estimada: DNSMOS P.835 (SIG = voz, BAK = fondo, OVRL = global);
* tiempo de cálculo por bloque;
* en tiempo real, con el procesador de la app (bloques de 256 muestras a 48 kHz a ritmo
  real): retraso total medido, huecos y entrada descartada.

También compara «Limpiar mi voz» con ruido de fondo (con y sin limpieza).

Uso: python tools/ci_live_quality.py salida/
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ci_real_models as R  # noqa: E402  (voces de Windows, Whisper, rutas)

from voicelab.ai import meanvc  # noqa: E402
from voicelab.audio import mediaio  # noqa: E402
from voicelab.audio.polish import InputCleaner  # noqa: E402
from voicelab.audio.resampler import StreamResampler  # noqa: E402

OUT = R.OUT
SR = 48000
REPORT: dict = {}


# --------------------------------------------------------------- medidas
def f0_track(x: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Tono por tramas de 10 ms (autocorrelación normalizada); 0 = sin voz."""
    n, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / 450), int(sr / 70)
    out = np.zeros(max(0, (x.shape[0] - n) // hop), np.float32)
    level = np.sqrt(np.mean(x ** 2)) + 1e-9
    for i in range(out.shape[0]):
        seg = x[i * hop: i * hop + n]
        seg = seg - seg.mean()
        if np.sqrt(np.mean(seg ** 2)) < 0.1 * level:
            continue
        ac = np.fft.irfft(np.abs(np.fft.rfft(seg, 2 * n)) ** 2)[: hi + 2]
        if ac[0] <= 0:
            continue
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] / ac[0] > 0.5:
            a, b, c = ac[k - 1], ac[k], ac[k + 1]                      # interpolación parabólica
            d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
            out[i] = sr / (k + d)
    return out


def envelope_lag(x: np.ndarray, y: np.ndarray, sr: int = 16000, max_s: float = 1.2) -> float:
    """Retraso de «y» respecto a «x» (s) por correlación de envolventes logarítmicas de 10 ms."""
    h = sr // 100

    def env(z):
        z = z[: z.shape[0] // h * h].reshape(-1, h)
        e = np.log(np.mean(z ** 2, 1) + 1e-8)
        return e - e.mean()
    ex, ey = env(x), env(y)
    m = min(ex.shape[0], ey.shape[0])
    lags = range(0, min(int(max_s * 100), m // 2))
    best = max(lags, key=lambda d: float(np.dot(ex[: m - d], ey[d:m])) / (m - d))
    return best / 100


def prosody(x16: np.ndarray, y16: np.ndarray) -> dict:
    lag = envelope_lag(x16, y16)
    d = int(round(lag * 100))
    fx, fy = f0_track(x16), f0_track(y16)
    fy = fy[d:]
    m = min(fx.shape[0], fy.shape[0])
    fx, fy = fx[:m], fy[:m]
    both = (fx > 0) & (fy > 0)
    st = lambda f: 12 * np.log2(f)  # noqa: E731
    res = {"desfase_contenido_ms": round(lag * 1000), "tramas_con_tono": int(both.sum())}
    if both.sum() > 50:
        a, b = st(fx[both]), st(fy[both])
        res["correlacion_tono"] = round(float(np.corrcoef(a, b)[0, 1]), 3)
        res["rango_tono_relativo"] = round(float(np.std(b) / (np.std(a) + 1e-9)), 2)
    vy = fy > 0
    jumps = np.abs(np.diff(st(np.where(vy, fy, 1.0))))[(vy[1:] & vy[:-1])]
    vx = fx > 0
    jx = np.abs(np.diff(st(np.where(vx, fx, 1.0))))[(vx[1:] & vx[:-1])]
    if jumps.size > 20:
        res["temblor_tono_st"] = round(float(np.median(jumps)), 3)
        res["temblor_tono_original_st"] = round(float(np.median(jx)), 3) if jx.size else None
        res["saltos_grandes_pct"] = round(float(np.mean(jumps > 1.5) * 100), 1)    # > 1,5 semitonos en 10 ms
    res["voz_con_tono_pct"] = round(float(vy[: m].mean() * 100), 1)
    return res


_DNSMOS = None
DNSMOS_URL = "https://github.com/microsoft/DNS-Challenge/raw/master/DNSMOS/DNSMOS/sig_bak_ovr.onnx"


def dnsmos(x16: np.ndarray) -> dict:
    """DNSMOS P.835 (no personalizado), media de ventanas de 9 s."""
    global _DNSMOS
    import onnxruntime as ort
    if _DNSMOS is None:
        path = OUT / "sig_bak_ovr.onnx"
        if not path.exists():
            urllib.request.urlretrieve(DNSMOS_URL, path)
        _DNSMOS = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    sess = _DNSMOS
    n = int(9.01 * 16000)
    a = x16.astype(np.float32)
    while a.shape[0] < n:
        a = np.concatenate([a, a])
    p_ovr = np.poly1d([-0.06766283, 1.11546468, 0.04602535])
    p_sig = np.poly1d([-0.08397278, 1.22083953, 0.0052439])
    p_bak = np.poly1d([-0.13166888, 1.60915514, -0.39604546])
    vals = []
    for start in range(0, a.shape[0] - n + 1, 16000):
        raw = sess.run(None, {sess.get_inputs()[0].name: a[start:start + n][None, :]})[0][0]
        vals.append((p_sig(raw[0]), p_bak(raw[1]), p_ovr(raw[2])))
    s, b, o = np.mean(vals, 0)
    return {"SIG": round(float(s), 2), "BAK": round(float(b), 2), "OVRL": round(float(o), 2)}


def cos(a, b) -> float:
    return round(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)), 3)


def to16(y: np.ndarray, sr: int) -> np.ndarray:
    return y if sr == 16000 else mediaio.resample(y, sr, 16000)


# ----------------------------------------------------------- utilidades
def run_offline(w, x16: np.ndarray) -> tuple[np.ndarray, list[float]]:
    c = int(w.hello["chunk"])
    outs, times = [], []
    for i in range(0, x16.shape[0] - c + 1, c):
        t0 = time.perf_counter()
        outs.append(w.process(x16[i:i + c]))
        times.append(time.perf_counter() - t0)
    return np.concatenate(outs), times


def run_realtime(proc, x48: np.ndarray, block: int = 256) -> np.ndarray:
    outs, t0 = [], time.perf_counter()
    for k, i in enumerate(range(0, x48.shape[0] - block + 1, block)):
        outs.append(proc.process(x48[i:i + block]))
        wait = t0 + (k + 1) * block / SR - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
    return np.concatenate(outs)


def judge(name: str, y16: np.ndarray, x16: np.ndarray, emb_w, emb_b, ref_text: str) -> dict:
    res = {}
    try:
        res["oido"] = R.oir(y16[: 16000 * 14], 16000, "en")
        res["inteligible"] = R.parecido(res["oido"], ref_text)
    except Exception as exc:  # noqa: BLE001
        res["oido_error"] = str(exc)
    try:
        res["parecido_con_B"] = cos(emb_w.compute_embedding(y16[: 16000 * 12]), emb_b)
    except Exception as exc:  # noqa: BLE001
        res["huella_error"] = str(exc)
    try:
        res.update(prosody(x16, y16))
    except Exception as exc:  # noqa: BLE001
        res["tono_error"] = f"{type(exc).__name__}: {exc}"
    try:
        res["dnsmos"] = dnsmos(y16)
    except Exception as exc:  # noqa: BLE001
        res["dnsmos_error"] = f"{type(exc).__name__}: {exc}"
    mediaio.save_wav(OUT / f"calidad_{name}.wav", y16, 16000)
    return res


def step(name, fn):
    t0 = time.perf_counter()
    print(f"\n=== {name} ===", flush=True)
    try:
        REPORT[name] = {"ok": True, **(fn() or {})}
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        REPORT[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    REPORT[name]["s"] = round(time.perf_counter() - t0, 1)
    print(json.dumps(REPORT[name], indent=2, ensure_ascii=False), flush=True)


# ------------------------------------------------------------------ main
def main() -> int:
    t0 = time.perf_counter()
    inst = meanvc.install(lambda p: None)
    hd_ok = True
    try:
        meanvc.install_hd(lambda p: None)
    except Exception as exc:  # noqa: BLE001
        hd_ok = False
        REPORT["hd_instalacion_error"] = str(exc)
    REPORT["instalacion"] = {"s": round(time.perf_counter() - t0, 1), "bench": inst.get("bench")}
    a, b = R.voices()
    a = a[: SR * 24]
    x16 = mediaio.resample(a, SR, 16000)
    ref_text = R.oir(a[: SR * 14], SR, "en")
    REPORT["original"] = {"oido": ref_text, "dnsmos": dnsmos(x16), **prosody(x16, x16)}

    emb_w = meanvc.MeanVCWorker(meanvc.worker_command("40ms"))       # para las huellas
    emb_b = emb_w.compute_embedding(mediaio.resample(b, SR, 16000))
    REPORT["original"]["parecido_con_B"] = cos(emb_w.compute_embedding(x16[: 16000 * 12]), emb_b)
    emb_w.set_embedding(emb_b)

    configs = [("120ms", 2560, False), ("40ms", 2560, False), ("40ms", 1280, False),
               ("120ms", 2560, True), ("40ms", 1280, True)]
    for variant, chunk, hd in configs:
        if hd and not hd_ok:
            continue
        name = f"{variant}_{chunk * 1000 // 16000}ms{'_hd' if hd else ''}"

        def offline(variant=variant, chunk=chunk, hd=hd, name=name):
            w = meanvc.MeanVCWorker(meanvc.worker_command(variant, threads=2 if hd else 1, hd=hd, chunk=chunk))
            try:
                w.set_embedding(emb_b)
                y, times = run_offline(w, x16)
                hello = w.hello
            finally:
                w.close()
            y16 = to16(y, int(hello.get("out_sr", 16000)))
            res = {"chunk_ms": chunk / 16, "hold_ms": hello.get("hold_ms"), "burst_ms": hello.get("burst_ms"),
                   "ms_por_bloque": round(float(np.median(times[2:])) * 1000, 1),
                   "ms_por_bloque_p95": round(float(np.percentile(times[2:], 95)) * 1000, 1),
                   "rtf": round(float(np.median(times[2:])) / (chunk / 16000), 3)}
            res.update(judge(name, y16, x16, emb_w, emb_b, ref_text))
            return res
        step(name, offline)

    # ---- en tiempo real con el procesador de la app (lo que oye la otra persona, sin el cable)
    for variant, chunk, hd in [("40ms", 1280, False), ("40ms", 1280, True), ("120ms", 2560, False),
                               ("40ms", 2560, False)]:
        if hd and not hd_ok:
            continue
        name = f"directo_{variant}_{chunk * 1000 // 16000}ms{'_hd' if hd else ''}"

        def live(variant=variant, chunk=chunk, hd=hd):
            w = meanvc.MeanVCWorker(meanvc.worker_command(variant, threads=2 if hd else 1, hd=hd, chunk=chunk),
                                    realtime=True)
            w.set_embedding(emb_b)
            proc = meanvc.RealtimeMeanVC(w, SR, variant)
            try:
                y = run_realtime(proc, a[: SR * 20])
            finally:
                proc.close()
            lag = envelope_lag(x16[: 16000 * 20], to16(y, SR))
            return {"retraso_medido_ms": round(lag * 1000), "retraso_app_ms": round(proc.latency_samples / SR * 1000),
                    "huecos": proc.underruns, "descartado_ms": round(proc.dropped / SR * 1000),
                    "recortado_ms": round(proc.trimmed / SR * 1000), "margen_ms": round(proc.margin / SR * 1000),
                    "calculo_ms": round(proc.infer_ms, 1), "align_ms": proc.align16 / 16}
        step(name, live)

    # ---- «Limpiar mi voz» con ruido de fondo
    rng = np.random.default_rng(3)
    noise = np.cumsum(rng.standard_normal(a.shape[0])).astype(np.float32)     # ruido grave (ventilador)
    noise = noise - np.convolve(noise, np.ones(480) / 480, "same")
    noise += 0.5 * rng.standard_normal(a.shape[0]).astype(np.float32)
    noise *= np.sqrt(np.mean(a ** 2)) / np.sqrt(np.mean(noise ** 2)) / 10 ** (15 / 20)   # SNR 15 dB
    noisy = (a + noise).astype(np.float32)
    for clean in (False, True):
        name = f"ruido_{'con' if clean else 'sin'}_limpieza"

        def noisy_run(clean=clean, name=name):
            x = noisy
            if clean:
                ic = InputCleaner(SR)
                x = np.concatenate([ic.process(x[i:i + 256]) for i in range(0, x.shape[0] - 255, 256)])
            w = meanvc.MeanVCWorker(meanvc.worker_command("40ms"))
            try:
                w.set_embedding(emb_b)
                xin = StreamResampler(SR, 16000).process(x)
                y, _ = run_offline(w, xin)
            finally:
                w.close()
            return judge(name, y, to16(a, SR)[: y.shape[0]], emb_w, emb_b, ref_text)
        step(name, noisy_run)
    emb_w.close()

    (OUT / "calidad_directo.json").write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Calidad de la voz en directo\n\n```json\n" + json.dumps(REPORT, indent=2, ensure_ascii=False)
                    + "\n```\n")
    print("\nINFORME:\n" + json.dumps(REPORT, indent=2, ensure_ascii=False))
    bad = [k for k, v in REPORT.items() if isinstance(v, dict) and v.get("ok") is False]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
