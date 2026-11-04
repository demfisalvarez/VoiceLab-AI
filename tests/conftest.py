import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Cada prueba usa su propia carpeta de datos (no toca la real)."""
    monkeypatch.setenv("VOICELAB_DATA_DIR", str(tmp_path / "data"))
    yield
