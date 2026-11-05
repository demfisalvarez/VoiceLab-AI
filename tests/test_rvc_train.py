"""Entrenar voz fiel: troceado del material, comprobaciones y estado (sin PyTorch)."""

import numpy as np
import pytest

from voicelab.ai import rvc_train

SR = 48000


def speech_like(seconds_on, seconds_off, n):
    t = np.arange(int(seconds_on * SR)) / SR
    on = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    off = np.zeros(int(seconds_off * SR), np.float32)
    return np.concatenate([np.concatenate([on, off]) for _ in range(n)])


def test_slice_pieces_cuts_at_silences_and_in_3_7_s_pieces():
    x = speech_like(10.0, 1.0, 3)                      # 3 frases de 10 s separadas por 1 s de silencio
    pieces = rvc_train.slice_pieces(x, SR)
    lens = [p.shape[0] / SR for p in pieces]
    assert all(0.6 <= n <= 4.4 for n in lens), lens
    assert 7 <= len(pieces) <= 12
    total = sum(lens)
    assert 29 <= total <= 36                          # la voz entera (con solapes), sin los silencios largos


def test_short_phrases_are_kept_whole():
    pieces = rvc_train.slice_pieces(speech_like(1.0, 0.8, 5), SR)
    assert len(pieces) == 5 and all(0.9 < p.shape[0] / SR < 1.5 for p in pieces)


def test_normalize_like_rvc():
    p = (np.ones(100) * 0.1).astype(np.float32)
    out = rvc_train.normalize(p)
    assert np.isclose(out.max(), 0.9 * 0.75 + 0.25 * 0.1)
    assert np.all(rvc_train.normalize(np.zeros(10, np.float32)) == 0)


def test_manager_refuses_without_material(tmp_path):
    m = rvc_train.TrainingManager()
    with pytest.raises(rvc_train.TrainError):
        m.start({"id": "x", "name": "Voz", "cloning": {}}, tmp_path, 60, lambda r: None)
    (tmp_path / "material.wav").write_bytes(b"x")
    with pytest.raises(rvc_train.TrainError, match="1 minuto"):
        m.start({"id": "x", "name": "Voz", "cloning": {"analysis": {"speech_s": 30}}}, tmp_path, 60, lambda r: None)
    assert m.status()["state"] == "idle"


def test_trainer_command_has_everything(monkeypatch):
    monkeypatch.setattr(rvc_train.meanvc, "runtime_python", lambda: "py.exe")
    cmd = rvc_train.trainer_command(rvc_train.Path("d.npz"), rvc_train.Path("out"), 90, threads=3, extend=True)
    assert cmd[0] == "py.exe" and "-I" in cmd and cmd[cmd.index("--minutes") + 1] == "90"
    assert cmd[cmd.index("--threads") + 1] == "3" and "--extend" in cmd
    assert cmd[cmd.index("--pretrain-g") + 1].endswith("f0G40k.pth")
