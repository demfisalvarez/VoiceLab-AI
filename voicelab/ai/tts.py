"""Texto a voz con clonación instantánea: Chatterbox Multilingual en ONNX.

Implementa el mismo flujo que el script de referencia de la exportación ONNX
(speech_encoder → embed_tokens → language_model con caché KV →
conditional_decoder), con:
- textos largos divididos por frases,
- estabilidad (decodificación voraz o muestreo con temperatura),
- expresividad (parámetro «exaggeration» del modelo),
- velocidad (cambio de tempo sin alterar el tono).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import numpy as np

from . import models, runtime

SR = 24000
START, STOP = 6561, 6562
TOKEN_SAMPLES = 960            # 25 tokens de voz por segundo
LANGUAGES = {"es": "Español", "en": "Inglés", "fr": "Francés", "de": "Alemán", "it": "Italiano",
             "pt": "Portugués", "nl": "Neerlandés", "pl": "Polaco", "ru": "Ruso", "sv": "Sueco",
             "da": "Danés", "no": "Noruego", "fi": "Finés", "el": "Griego", "tr": "Turco",
             "ar": "Árabe", "he": "Hebreo", "hi": "Hindi", "ms": "Malayo", "sw": "Suajili",
             "ja": "Japonés", "ko": "Coreano", "zh": "Chino"}


REF_SECONDS = 10               # como el original (DEC_COND_LEN): más referencia solo ralentiza


class TTSError(RuntimeError):
    def __init__(self, message: str, cancelled: bool = False):
        super().__init__(message)
        self.cancelled = cancelled


def split_text(text: str, max_chars: int = 220) -> list[str]:
    """Divide en fragmentos por frases (y por comas si una frase es muy larga)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?¡¿…;:])\s+", text)
    chunks, cur = [], ""
    for s in sentences:
        parts = [s] if len(s) <= max_chars else re.split(r"(?<=,)\s+", s)
        for p in parts:
            while len(p) > max_chars:                      # palabra a palabra como último recurso
                cut = p.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                chunks.append(p[:cut].strip())
                p = p[cut:].strip()
            if len(cur) + len(p) + 1 <= max_chars:
                cur = (cur + " " + p).strip()
            else:
                if cur:
                    chunks.append(cur)
                cur = p
    if cur:
        chunks.append(cur)
    return chunks


def korean_normalize(text: str) -> str:
    out = []
    for ch in text:
        if "가" <= ch <= "힯":
            b = ord(ch) - 0xAC00
            out.append(chr(0x1100 + b // 588) + chr(0x1161 + (b % 588) // 28) + (chr(0x11A7 + b % 28) if b % 28 else ""))
        else:
            out.append(ch)
    return "".join(out)


class RepetitionPenalty:
    def __init__(self, penalty: float = 1.2):
        self.penalty = penalty

    def __call__(self, ids: np.ndarray, scores: np.ndarray) -> np.ndarray:
        s = np.take_along_axis(scores, ids, axis=1)
        s = np.where(s < 0, s * self.penalty, s / self.penalty)
        out = scores.copy()
        np.put_along_axis(out, ids, s, axis=1)
        return out


class ChatterboxTTS:
    LAYERS, HEADS, HEAD_DIM = 30, 16, 64

    def __init__(self, model_key: str, sessions: dict | None = None, tokenizer=None, prefer_gpu: bool = False,
                 stage=None, cancel=None):
        self.model_key = model_key
        self.device = "cpu"
        if sessions is None:
            if not models.installed(model_key):
                raise TTSError("El modelo de texto a voz no está descargado. Instálalo en Ajustes → Motor de IA.")
            if not runtime.available():
                raise TTSError("Falta el motor de IA (ONNX Runtime). Instálalo en Ajustes → Motor de IA.")
            d = models.model_dir(model_key)
            spec = models.CATALOG[model_key]
            parts = [("encoder", "onnx/speech_encoder.onnx", "codificador de voz"),
                     ("embed", "onnx/embed_tokens.onnx", "vocabulario"),
                     ("lm", spec["lm"], "modelo de lenguaje"),
                     ("decoder", "onnx/conditional_decoder.onnx", "generador de audio")]
            sessions = {}
            for i, (key, rel, label) in enumerate(parts, 1):
                if stage:
                    stage(f"Cargando el {label} ({i}/4)…")
                sessions[key] = runtime.session(d / rel, prefer_gpu=prefer_gpu)
            provs = sessions["lm"].get_providers() if hasattr(sessions["lm"], "get_providers") else []
            self.device = "gpu" if provs and provs[0] != "CPUExecutionProvider" else "cpu"
            from tokenizers import Tokenizer
            tokenizer = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.s = sessions
        self.tok = tokenizer
        self.cancelled = cancel if cancel is not None else threading.Event()
        self._external_cancel = cancel is not None
        self._ref_cache: tuple | None = None
        self.info = {"model": model_key, "device": self.device}
        self.ref_seconds = REF_SECONDS
        self.text_mode = "raw"
        self.lang_tag: str | None = None      # None: el del idioma; "" sin etiqueta (pruebas)
        self.last_stats: dict = {}

    # --------------------------------------------------------------- texto
    def encode(self, text: str, lang: str) -> np.ndarray:
        if self.text_mode == "lower":                     # como el tokenizador multilingüe oficial
            import unicodedata
            text = unicodedata.normalize("NFKD", text.lower())
        if lang == "ko":
            text = korean_normalize(text)
        tag = self.lang_tag if self.lang_tag is not None else lang
        text = f"[{tag}]{text}" if tag else text
        ids = self.tok.encode(text).ids
        return np.array([ids], dtype=np.int64)

    # ---------------------------------------------------------- referencia
    def reference(self, ref_path: Path) -> tuple:
        key = (str(ref_path), ref_path.stat().st_mtime, self.ref_seconds)
        if self._ref_cache and self._ref_cache[0] == key:
            return self._ref_cache[1]
        from ..audio import mediaio
        audio = mediaio.load_audio(ref_path, SR)[: int(SR * self.ref_seconds)]
        out = self.s["encoder"].run(None, {"audio_values": audio[None, :].astype(np.float32)})
        self._ref_cache = (key, tuple(out))
        return tuple(out)

    # ----------------------------------------------------------- generación
    def _tokens(self, input_ids: np.ndarray, cond: tuple, exaggeration: float, stability: float,
                max_new: int, rng: np.random.Generator, on_token=None) -> np.ndarray:
        cond_emb, prompt_token = cond[0], cond[1]
        position_ids = np.where(input_ids >= START, 0, np.arange(input_ids.shape[1])[None, :] - 1).astype(np.int64)
        feed = {"input_ids": input_ids, "position_ids": position_ids,
                "exaggeration": np.array([exaggeration], dtype=np.float32)}
        # Estabilidad 100 %: decodificación voraz (como el script de referencia de la exportación ONNX).
        # Por debajo: muestreo como el Chatterbox oficial (temperatura 0,8 al 50 %, min_p 0,05, penalización 2,0).
        temperature = 0.0 if stability >= 0.99 else 0.5 + 0.6 * (1.0 - stability)
        penalty = RepetitionPenalty(1.2 if temperature == 0.0 else 2.0)
        generated = np.array([[START]], dtype=np.int64)
        past, mask = None, None
        for i in range(max_new):
            if self.cancelled.is_set():
                raise TTSError("Generación cancelada.", cancelled=True)
            emb = self.s["embed"].run(None, feed)[0]
            if i == 0:
                emb = np.concatenate((cond_emb, emb), axis=1)
                b, n, _ = emb.shape
                past = {f"past_key_values.{l}.{kv}": np.zeros((b, self.HEADS, 0, self.HEAD_DIM), np.float32)
                        for l in range(self.LAYERS) for kv in ("key", "value")}
                mask = np.ones((b, n), dtype=np.int64)
            logits, *present = self.s["lm"].run(None, {"inputs_embeds": emb, "attention_mask": mask, **past})
            scores = penalty(generated, logits[:, -1, :])
            # Solo son válidos los tokens de voz (0–6560) y el de fin; el resto rompería el decodificador.
            scores[:, START] = -np.inf
            scores[:, STOP + 1:] = -np.inf
            if temperature == 0.0:
                nxt = np.argmax(scores, axis=-1, keepdims=True).astype(np.int64)
            else:
                z = scores[0] / temperature
                p = np.exp(z - z.max())
                p[p < 0.05 * p.max()] = 0.0                    # min_p
                p /= p.sum()
                nxt = np.array([[rng.choice(p.shape[0], p=p)]], dtype=np.int64)
            generated = np.concatenate((generated, nxt), axis=1)
            if on_token:
                on_token(i)
            if int(nxt[0, 0]) == STOP:
                break
            feed["input_ids"] = nxt
            feed["position_ids"] = np.full((1, 1), i + 1, dtype=np.int64)
            mask = np.concatenate([mask, np.ones((mask.shape[0], 1), np.int64)], axis=1)
            for j, k in enumerate(past):
                past[k] = present[j]
        tokens = generated[:, 1:]
        stopped = bool(tokens.shape[1] and tokens[0, -1] == STOP)
        tokens = tokens[:, tokens[0] < START]                  # como «drop_invalid_tokens» del original
        self.last_stats = {"tokens": int(tokens.shape[1]), "fin": stopped, "max": max_new,
                           "prompt": int(prompt_token.shape[1])}
        return np.concatenate([prompt_token, tokens], axis=1)

    def synthesize(self, text: str, ref_path: Path, lang: str = "es", exaggeration: float = 0.5,
                   stability: float = 1.0, speed: float = 1.0, seed: int | None = None, progress=None) -> np.ndarray:
        if lang not in LANGUAGES:
            raise TTSError(f"Idioma no admitido: {lang}")
        chunks = split_text(text)
        if not chunks:
            raise TTSError("Escribe algún texto.")
        if not self._external_cancel:        # en el proceso aparte lo limpia la app antes de llamar
            self.cancelled.clear()
        cond = self.reference(ref_path)
        rng = np.random.default_rng(seed)
        pieces, gap = [], np.zeros(int(SR * 0.18), np.float32)
        for ci, chunk in enumerate(chunks):
            max_new = int(min(1000, 60 + 2.6 * len(chunk)))

            def on_token(i, ci=ci, max_new=max_new):
                if progress:
                    progress((ci + min(1.0, i / (max_new * 0.6))) / len(chunks) * 0.95)

            speech = self._tokens(self.encode(chunk, lang), cond, exaggeration, stability, max_new, rng, on_token)
            wav = self.s["decoder"].run(None, {"speech_tokens": speech, "speaker_embeddings": cond[2],
                                               "speaker_features": cond[3]})[0]
            wav = np.squeeze(wav, axis=0).astype(np.float32)
            if wav.shape[0] > TOKEN_SAMPLES:
                wav = wav[:-TOKEN_SAMPLES]
            pieces += [wav, gap]
        out = np.concatenate(pieces[:-1])
        if abs(speed - 1.0) > 0.01:
            from ..audio.effects import time_stretch
            out = time_stretch(out, speed)
        peak = float(np.max(np.abs(out))) or 1.0
        return (out / peak * 0.89 if peak > 0.89 else out).astype(np.float32)


def open_engine(model_key: str, prefer_gpu: bool = False, stage=None, cancel=None) -> ChatterboxTTS:
    """Fábrica para el proceso aparte (ver ``procs.Remote``)."""
    return ChatterboxTTS(model_key, prefer_gpu=prefer_gpu, stage=stage, cancel=cancel)


# ------------------------------------------------- servicio en proceso aparte
class TTSService:
    """Mantiene el modelo cargado en un proceso aparte entre generaciones.

    * La ventana nunca se congela (la carga del modelo bloquea su intérprete).
    * Si la GPU falla o se cuelga, se reintenta con la CPU automáticamente.
    """

    def __init__(self, remote_factory=None):
        self._remote = None
        self._key: tuple | None = None
        self._lock = threading.Lock()
        self._factory = remote_factory or self._spawn
        self.last_device: str | None = None
        self.state = "idle"            # idle · loading · ready · error
        self.stage = ""
        self.error: str | None = None

    def _set_stage(self, text: str) -> None:
        self.stage = text

    def status(self) -> dict:
        r = self._remote
        ready = r is not None and r.alive
        state = "ready" if ready and self.state != "loading" else self.state
        return {"state": state, "stage": self.stage, "error": self.error,
                "device": (r.info or {}).get("device") if ready else None}

    def preload(self, model_key: str, gpu: bool) -> None:
        """Carga el modelo en segundo plano (p. ej. al abrir la página de texto a voz)."""
        if self._lock.locked() or (self._remote is not None and self._remote.alive and self._key == (model_key, gpu)):
            return

        def run():
            from .procs import RemoteError
            with self._lock:
                self.state, self.error = "loading", None
                try:
                    self._ensure(model_key, gpu, self._set_stage)
                    self.state = "ready"
                except RemoteError as exc:
                    self.state, self.error = "error", str(exc)
                    if gpu:                              # la GPU no sirve: se queda preparada la CPU
                        try:
                            self._ensure(model_key, False, self._set_stage)
                            self.state, self.error = "ready", None
                        except RemoteError as exc2:
                            self.error = str(exc2)
        threading.Thread(target=run, name="precarga-texto-a-voz", daemon=True).start()

    @staticmethod
    def _spawn(model_key: str, gpu: bool, on_stage):
        from .procs import Remote
        return Remote("voicelab.ai.tts:open_engine", (model_key, gpu), name="motor de texto a voz",
                      log_name="texto-a-voz", load_timeout=600, on_stage=on_stage)

    def _ensure(self, model_key: str, gpu: bool, on_stage):
        key = (model_key, gpu)
        if self._remote is not None and (self._key != key or not self._remote.alive):
            self._remote.close()
            self._remote = None
        if self._remote is None:
            on_stage("Preparando el motor de texto a voz…")
            self._remote = self._factory(model_key, gpu, on_stage)
            self._key = key
        return self._remote

    def synthesize(self, model_key: str, gpu: bool, args: tuple, progress, on_stage) -> tuple[np.ndarray, dict]:
        try:
            return self._synthesize(model_key, gpu, args, progress, on_stage)
        finally:
            if self.state == "loading":
                self.state = "ready" if self._remote is not None and self._remote.alive else "idle"

    def _synthesize(self, model_key: str, gpu: bool, args: tuple, progress, on_stage) -> tuple[np.ndarray, dict]:
        """Devuelve (audio, info). ``info`` dice qué dispositivo se usó y si hubo que pasar a la CPU."""
        from .procs import RemoteError
        if self._lock.locked():
            on_stage("Terminando de cargar el modelo…")
        with self._lock:
            self.state = "loading"
            info = {"device": "gpu" if gpu else "cpu", "fallback": None}
            try:
                r = self._ensure(model_key, gpu, on_stage)
                info["device"] = (r.info or {}).get("device", info["device"])
                wav = r.call("synthesize", *args, progress=progress, timeout=180, on_stage=on_stage)
            except RemoteError as exc:
                if exc.kind == "cancelled":
                    raise TTSError("Generación cancelada.", cancelled=True) from None
                if not gpu:
                    raise TTSError(str(exc)) from None
                info["fallback"] = str(exc)                 # la GPU falló: se repite con la CPU
                if self._remote is not None:
                    self._remote.close()
                    self._remote = None
                on_stage("La GPU ha fallado; se repite con la CPU…")
                try:
                    r = self._ensure(model_key, False, on_stage)
                    wav = r.call("synthesize", *args, progress=progress, timeout=180, on_stage=on_stage)
                except RemoteError as exc2:
                    if exc2.kind == "cancelled":
                        raise TTSError("Generación cancelada.", cancelled=True) from None
                    raise TTSError(str(exc2)) from None
                info["device"] = "cpu"
            self.last_device = info["device"]
            self.state, self.error = "ready", None
            return wav, info

    def cancel(self) -> None:
        r = self._remote
        if r is not None:
            r.cancel()

    def unload(self) -> None:
        with self._lock:
            if self._remote is not None:
                self._remote.close()
                self._remote = None


_service: TTSService | None = None


def service() -> TTSService:
    global _service
    if _service is None:
        _service = TTSService()
    return _service


def unload() -> None:
    if _service is not None:
        _service.unload()
