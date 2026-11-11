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


MERCADO = ("{p}:\n  idioma: nb\n  moneda: NOK\n  zona: Europe/Oslo\n  banda_eur: [11.90, 15.90]\n"
           "  estado: candidato\n")


def test_plantilla_tiene_noruega_como_texto():
    m = cargar(PLANTILLA)
    assert "NO" in m and False not in m
    assert m["NO"].pais == "NO" and m["NO"].moneda == "NOK"
    assert all(isinstance(k, str) for k in m)


def test_no_sin_comillas_es_noruega(tmp_path):
    """Los cerebros ya creados tienen «NO:» sin comillas: el cargador no lo lee como False."""
    ruta = tmp_path / "mercados.yaml"
    ruta.write_text(MERCADO.format(p="NO") + MERCADO.format(p="RO"), encoding="utf-8")
    m = cargar(ruta)
    assert list(m) == ["NO", "RO"] and m["NO"].pais == "NO"


def test_yes_on_off_siguen_siendo_texto(tmp_path):
    from trovify.config.yaml_config import cargar_yaml

    datos = cargar_yaml("a: NO\nb: yes\nc: on\nd: off\ne: true\nf: false\ng: n\nYES: 1\n")
    assert datos == {"a": "NO", "b": "yes", "c": "on", "d": "off", "e": True, "f": False, "g": "n", "YES": 1}


def test_clave_que_no_es_texto_da_error_claro(tmp_path):
    import pytest

    ruta = tmp_path / "mercados.yaml"
    ruta.write_text(MERCADO.format(p="123"), encoding="utf-8")
    with pytest.raises(ValueError, match="entre comillas"):
        cargar(ruta)
    ruta.write_text(MERCADO.format(p="true"), encoding="utf-8")
    with pytest.raises(ValueError, match="entre comillas"):
        cargar(ruta)
