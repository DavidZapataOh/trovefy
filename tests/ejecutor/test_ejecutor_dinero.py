import pytest
from trovefy_ejecutor.dinero import (
    Moneda,
    MonedaNoConfigurada,
    es_importe,
    formatear,
    moneda_configurada,
)

USD, COP = Moneda("USD", 100), Moneda("COP", 1)

@pytest.mark.parametrize("u,m,txt", [(650, USD, "6,50 USD"), (5, USD, "0,05 USD"), (123456789, USD, "1.234.567,89 USD"),
                                     (20000, COP, "20.000 COP"), (-650, USD, "-6,50 USD"), (0, COP, "0 COP")])
def test_formatear(u, m, txt):
    assert formatear(u, m) == txt

def test_sin_offset_no_se_adivina():
    with pytest.raises(MonedaNoConfigurada, match="P-21"):
        moneda_configurada("COP", None)

@pytest.mark.parametrize("c,o", [("cop", 1), ("COP", 3), ("COPX", 1)])
def test_moneda_invalida(c, o):
    with pytest.raises(ValueError):
        Moneda(c, o)

def test_es_importe():
    assert es_importe(1) and not es_importe(0) and not es_importe(True) and not es_importe(1.0) and not es_importe("5")


def test_offsets_oficiales():
    from trovefy_ejecutor.dinero import OFFSETS_OFICIALES
    assert dict(OFFSETS_OFICIALES) == {"COP": 1, "USD": 100}
