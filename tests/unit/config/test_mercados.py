import pathlib

from trovify.config.mercados import cargar

PLANTILLA = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/mercados.yaml"


def test_semilla_de_mercados():
    m = cargar(PLANTILLA)
    assert set(m) >= {"RO", "MD", "CZ", "HU", "BG", "IT", "FR", "ES", "PT", "PL", "GR"}
    assert len(m) == 15
    assert m["BG"].moneda == "EUR"
    assert m["RO"].banda_eur == (11.90, 15.90)
    assert m["RO"].precio_referencia == "79 RON"
    assert m["MD"].precio_referencia is None
