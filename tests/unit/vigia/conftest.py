import pytest


@pytest.fixture(autouse=True)
def _cache_referencia_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_CACHE_REFERENCIA", str(tmp_path / "cache-referencia-aislada"))
