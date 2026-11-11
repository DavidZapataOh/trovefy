import pathlib

import pytest
from trovefy.config.umbrales import cargar

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config"


@pytest.fixture(autouse=True)
def _sin_cambio_del_bce(monkeypatch):
    """La caza pide el cambio del BCE por defecto: en las pruebas, nunca a la red (sin cambio)."""
    from trovefy.caza import orquestador

    monkeypatch.setattr(orquestador, "_cambio_del_dia", lambda vault, hoy: None)


@pytest.fixture
def umbrales():
    return cargar(RAIZ / "umbrales.yaml")
