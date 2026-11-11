import pathlib

import pytest
from trovefy.config.umbrales import cargar

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config"


@pytest.fixture
def umbrales():
    return cargar(RAIZ / "umbrales.yaml")
