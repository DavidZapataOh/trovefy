"""Aislamiento de /cierre: nunca la red, el HOME real, /var/spool, systemd real ni el vault real."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "vault"))
