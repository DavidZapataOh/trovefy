"""Nunca el HOME real: cada test de esta carpeta corre con HOME en su tmp_path (L-9)."""

import pytest


@pytest.fixture(autouse=True)
def _home_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
