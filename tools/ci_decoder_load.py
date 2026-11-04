"""¿Por qué tarda tanto en cargar el decodificador de Chatterbox? Prueba de opciones de ONNX Runtime."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ci-out").resolve()
os.environ.setdefault("VOICELAB_DATA_DIR", str(OUT / "datos"))

import onnxruntime as ort  # noqa: E402

from voicelab.ai import models  # noqa: E402

if not models.installed("chatterbox-v2"):
    models.install("chatterbox-v2", lambda p: None)
d = models.model_dir("chatterbox-v2") / "onnx"
dec = d / "conditional_decoder.onnx"
print("tamaño datos:", round((d / "conditional_decoder.onnx_data").stat().st_size / 1e6), "MB", flush=True)


def load(path, level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL, **cfg):
    so = ort.SessionOptions()
    so.graph_optimization_level = level
    opt_path = cfg.pop("save", None)
    if opt_path:
        so.optimized_model_filepath = str(opt_path)
        so.add_session_config_entry("session.optimized_model_external_initializers_file_name", opt_path.name + ".data")
        so.add_session_config_entry("session.optimized_model_external_initializers_min_size_in_bytes", "1024")
    for k, v in cfg.items():
        so.add_session_config_entry(k, v)
    t0 = time.perf_counter()
    s = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    return s, round(time.perf_counter() - t0, 1)


_, t = load(dec, ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
print("sin optimizar:", t, "s", flush=True)
_, t = load(dec, ort.GraphOptimizationLevel.ORT_DISABLE_ALL, **{"session.disable_prepacking": "1"})
print("sin optimizar y sin prepacking:", t, "s", flush=True)
opt = d / "conditional_decoder.opt-cpu.onnx"
_, t = load(dec, ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED, save=opt)
print("extendida + guardar optimizado:", t, "s", flush=True)
_, t = load(opt, ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
print("recargar el optimizado:", t, "s", flush=True)
_, t = load(opt, ort.GraphOptimizationLevel.ORT_DISABLE_ALL, **{"session.disable_prepacking": "1"})
print("recargar el optimizado sin prepacking:", t, "s", flush=True)
import onnx  # noqa: E402

m = onnx.load(str(dec), load_external_data=False)
from collections import Counter  # noqa: E402

ops = Counter(n.op_type for n in m.graph.node)
print("nodos:", len(m.graph.node), "inicializadores:", len(m.graph.initializer), "más comunes:", ops.most_common(12), flush=True)
sub = sum(1 for n in m.graph.node for a in n.attribute if a.type == onnx.AttributeProto.GRAPH)
print("subgrafos (If/Loop):", sub, flush=True)
