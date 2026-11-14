"""Fixtures comunes de los tests de la referencia."""

import pytest
from trovefy.caza.presupuesto import Presupuesto


@pytest.fixture(autouse=True)
def _sin_pausas(monkeypatch):
    """Las pausas con ruido de la caza no duermen en los tests de `ver`."""
    monkeypatch.setattr(Presupuesto, "pausa", lambda self: 0.0)
