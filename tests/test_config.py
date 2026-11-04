import json

import pytest

from voicelab.config import Settings, SettingsError


def test_defaults_and_persistence(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(p)
    assert s.get("audio", "sample_rate") == 48000
    changed = s.update({"audio": {"input_gain_db": 6, "monitor_enabled": True}})
    assert changed == {"audio": {"input_gain_db": 6.0, "monitor_enabled": True}}
    assert Settings(p).get("audio", "input_gain_db") == 6.0


def test_values_are_clamped(tmp_path):
    s = Settings(tmp_path / "s.json")
    s.update({"audio": {"input_gain_db": 99, "buffer_blocks": 0}})
    assert s.get("audio", "input_gain_db") == 24.0
    assert s.get("audio", "buffer_blocks") == 1


def test_invalid_values_rejected_atomically(tmp_path):
    s = Settings(tmp_path / "s.json")
    with pytest.raises(SettingsError):
        s.update({"audio": {"input_gain_db": 3, "block_size": 333}})
    assert s.get("audio", "input_gain_db") == 0.0  # nada aplicado
    with pytest.raises(SettingsError):
        s.update({"audio": {"no_existe": 1}})
    with pytest.raises(SettingsError):
        s.update({"hacker": {}})


def test_unchanged_values_not_reported(tmp_path):
    s = Settings(tmp_path / "s.json")
    assert s.update({"audio": {"sample_rate": 48000}}) == {}


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ esto no es json", encoding="utf-8")
    s = Settings(p)
    assert s.get("audio", "block_size") == 256
    assert (tmp_path / "s.json.bak").exists()


def test_partially_invalid_file_keeps_valid_values(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"audio": {"block_size": 512, "sample_rate": 12345}}), encoding="utf-8")
    s = Settings(p)
    assert s.get("audio", "block_size") == 512
    assert s.get("audio", "sample_rate") == 48000
