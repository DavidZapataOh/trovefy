import pytest
import yaml
from trovify.mapa import FirmaAusente, MapaInvalido, cargar, leer_pantalla

PANTALLA = {"firma": ["Mi plan"], "campos": {"plan": {"patron": r"Plan actual:\s*(\w+)"}}}


def test_lee_campos():
    assert leer_pantalla(PANTALLA, "Mi plan · Plan actual: Free") == {"plan": "Free"}


def test_firma_ausente_detiene():
    with pytest.raises(FirmaAusente):
        leer_pantalla(PANTALLA, "Página rediseñada")


def test_campo_que_no_casa_es_none():
    assert leer_pantalla(PANTALLA, "Mi plan") == {"plan": None}


def _mapa(tmp_path, **cambios):
    base = {
        "capturado": None,
        "fuente": "documentación https://ejemplo.test 2026-11-10",
        "pantallas": {"plan": {"url": "https://ejemplo.test/plan", "firma": ["Mi plan"], "campos": {"plan": {"patron": r"Plan: (\w+)"}}}},
    }
    base.update(cambios)
    ruta = tmp_path / "mapa.yaml"
    ruta.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    return ruta


def test_cargar_valida(tmp_path):
    assert cargar(_mapa(tmp_path))["capturado"] is None
    assert cargar(_mapa(tmp_path, capturado="2026-12-01"))["capturado"] == "2026-12-01"


def test_cargar_acepta_fecha_yaml_sin_comillas(tmp_path):
    ruta = _mapa(tmp_path)
    ruta.write_text(ruta.read_text().replace("capturado: null", "capturado: 2026-12-01"), encoding="utf-8")
    assert cargar(ruta)["capturado"] == "2026-12-01"


@pytest.mark.parametrize(
    "cambios",
    [
        {"capturado": "ayer"},
        {"fuente": ""},
        {"pantallas": {}},
        {"pantallas": {"p": {"url": "http://x.test", "firma": ["a"]}}},
        {"pantallas": {"p": {"url": "https://x.test", "firma": []}}},
        {"pantallas": {"p": {"url": "https://x.test", "firma": ["a"], "campos": {"c": {"patron": "(a)(b)"}}}}},
        {"pantallas": {"p": {"url": "https://x.test", "firma": ["a"], "campos": {"c": {"patron": "(["}}}}},
    ],
)
def test_cargar_rechaza_estructura_mala(tmp_path, cambios):
    with pytest.raises(MapaInvalido):
        cargar(_mapa(tmp_path, **cambios))


def test_cargar_rechaza_sin_capturado(tmp_path):
    ruta = _mapa(tmp_path)
    ruta.write_text(ruta.read_text().replace("capturado: null\n", ""), encoding="utf-8")
    with pytest.raises(MapaInvalido):
        cargar(ruta)
