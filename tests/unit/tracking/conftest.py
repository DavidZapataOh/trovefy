"""Nunca el HOME real: cada test de esta carpeta corre con HOME en su tmp_path (L-9)."""

import pytest


@pytest.fixture(autouse=True)
def _home_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    """Los GET de `leer_pixel_publico` esperan 5–8 s entre páginas del mismo dominio (contrato 8): en los tests no."""
    from trovefy.tracking import publico

    monkeypatch.setattr(publico, "_esperar", lambda host: None)
