import pathlib

import pytest
from trovify.config.umbrales import cargar

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config"


@pytest.fixture
def umbrales():
    return cargar(RAIZ / "umbrales.yaml")
