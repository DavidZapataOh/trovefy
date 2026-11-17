"""Confirmación guiada de una pantalla con controles (plan 18, Tarea 8; resolución 20).

`capturado` de una pantalla escribible solo lo pone el usuario con su pantalla real delante: la confirmación
queda en el vault (`config/pantallas-confirmadas.yaml`) atada a la huella de la pantalla del mapa y a la URL
real que vio; si el mapa cambia, deja de valer. Ruling I-1: solo cuenta con «sí», con su captura en
`config/evidencia/` (archivo normal, sin enlaces) y con fecha no futura; un YAML manipulado no desbloquea nada.
"""

import copy
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy.mapa import capturado_de
from trovefy.mapa import cargar as cargar_mapa
from trovefy.tienda.confirmacion import (
    RUTA,
    confirmar_pantalla,
    huella_pantalla,
    mapa_con_confirmaciones,
)

MAPA = Path(__file__).resolve().parents[3] / "templates" / "impultienda" / "mapa.yaml"
AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
REAL = "https://app.impultienda.ar/dashboard/tienda/123/diseno?tab=contenido"
EVIDENCIA = "config/evidencia/p05-diseno-contenido-2026-11-17.png"
HOY = date(2026, 11, 17)


@pytest.fixture
def v(tmp_path):
    v = tmp_path / "v"
    (v / "config" / "evidencia").mkdir(parents=True)
    (v / EVIDENCIA).write_bytes(b"\x89PNG captura")
    return v


def confirmar(v, m, **kw):
    """Una confirmación como la deja `trovefy landing capturar`: «sí», hoy y con su captura."""
    return confirmar_pantalla(v, "impultienda", m, "diseno_contenido", REAL, kw.pop("respuesta", "sí"), AHORA,
                              evidencia=kw.pop("evidencia", EVIDENCIA), **kw)


def manipular(v, **cambios):
    datos = yaml.safe_load((v / RUTA).read_text(encoding="utf-8"))
    datos["impultienda"]["diseno_contenido"].update(cambios)
    (v / RUTA).write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


def confirmado(v, m, hoy=HOY):
    return capturado_de(mapa_con_confirmaciones(v, "impultienda", m, hoy=hoy), "diseno_contenido")


def test_sin_confirmar_el_mapa_no_cambia(v):
    m = cargar_mapa(MAPA)
    assert mapa_con_confirmaciones(v, "impultienda", m) == m
    assert capturado_de(m, "diseno_contenido") is None


def test_confirmar_y_mapa_confirmado(v):
    m = cargar_mapa(MAPA)
    original = copy.deepcopy(m)
    entrada = confirmar_pantalla(v, "impultienda", m, "diseno_contenido", REAL + "#x", "Sí", AHORA,
                                 evidencia=EVIDENCIA)
    assert entrada["fecha"] == "2026-11-17" and entrada["respuesta"] == "Sí" and entrada["url"] == REAL
    assert m == original  # no muta el mapa que recibe
    datos = yaml.safe_load((v / RUTA).read_text(encoding="utf-8"))
    assert datos["impultienda"]["diseno_contenido"]["huella"] == huella_pantalla(m["pantallas"]["diseno_contenido"])
    c = mapa_con_confirmaciones(v, "impultienda", m, hoy=HOY)
    assert capturado_de(c, "diseno_contenido") == "2026-11-17"
    assert c["pantallas"]["diseno_contenido"]["url"] == REAL
    assert capturado_de(c, "plan") is None and c["pantallas"]["plan"] == m["pantallas"]["plan"]
    assert "diseno_contenido" in (v / "log.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("respuesta", ["no", "", "si, pero", "vale"])
def test_sin_un_si_no_se_registra(v, respuesta):
    with pytest.raises(ValueError, match="no se confirma"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", REAL, respuesta, AHORA)
    assert not (v / RUTA).exists()


@pytest.mark.parametrize("url", ["https://otro.test/x", "http://app.impultienda.ar/x",
                                 "https://app.impultienda.ar/login", "https://app.impultienda.ar/pagos/tarjeta"])
def test_url_fuera_del_mapa_o_de_login_o_cobro(v, url):
    with pytest.raises(ValueError):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", url, "si", AHORA)
    assert not (v / RUTA).exists()


def test_pantalla_prohibida_no_se_confirma(v):
    with pytest.raises(ValueError, match="prohibida"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "pasarelas", REAL, "si", AHORA)


def test_pantalla_sin_controles_no_hace_falta(v):
    with pytest.raises(ValueError, match="controles"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "plan", REAL, "si", AHORA)


def test_si_el_mapa_cambia_la_confirmacion_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    assert confirmado(v, m) == "2026-11-17"
    cambiado = copy.deepcopy(m)
    cambiado["pantallas"]["diseno_contenido"]["firma"].append("Otra cosa")
    assert confirmado(v, cambiado) is None


def test_una_url_editada_a_mano_fuera_del_mapa_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, url="https://malo.test/x")
    assert confirmado(v, m) is None


# --- I-1: la confirmación exige un humano (un YAML manipulado no desbloquea nada) -----------------------


@pytest.mark.parametrize("respuesta", ["no", "", "vale", "si, pero", None, 1])
def test_yaml_manipulado_respuesta_que_no_es_si_no_vale(v, respuesta):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, respuesta=respuesta)
    assert confirmado(v, m) is None


@pytest.mark.parametrize("respuesta", ["sí", "Sí", " si ", "SÍ"])
def test_respuestas_si_valen(v, respuesta):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, respuesta=respuesta)
    assert confirmado(v, m) == "2026-11-17"


def test_sin_evidencia_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    (v / EVIDENCIA).unlink()
    assert confirmado(v, m) is None
    manipular(v, evidencia=None)
    assert confirmado(v, m) is None


@pytest.mark.parametrize("evidencia", ["config/otra/x.png", "../x.png", "config/evidencia/../../x.png",
                                       "config/evidencia/../otra/x.png", "config/evidencia", "config/evidencia/",
                                       "/etc/hosts", 7])
def test_evidencia_fuera_de_config_evidencia_no_vale(v, evidencia):
    for ruta in (v / "config" / "otra" / "x.png", v / "x.png", v.parent / "x.png"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"png")
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, evidencia=evidencia)
    assert confirmado(v, m) is None


def test_evidencia_enlace_simbolico_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    fuera = v.parent / "fuera.png"
    fuera.write_bytes(b"png")
    (v / EVIDENCIA).unlink()
    os.symlink(fuera, v / EVIDENCIA)
    assert confirmado(v, m) is None


def test_evidencia_bajo_carpeta_enlazada_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    fuera = v.parent / "ev-fuera"
    fuera.mkdir()
    (fuera / "p05-diseno-contenido-2026-11-17.png").write_bytes(b"png")
    (v / EVIDENCIA).unlink()
    (v / "config" / "evidencia").rmdir()
    os.symlink(fuera, v / "config" / "evidencia")
    assert confirmado(v, m) is None


def test_fecha_futura_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, fecha="2026-11-18")
    assert confirmado(v, m) is None
    assert confirmado(v, m, hoy=date(2026, 11, 18)) == "2026-11-18"


def test_sin_hoy_usa_la_fecha_de_negocio(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, fecha="2999-01-01")
    assert capturado_de(mapa_con_confirmaciones(v, "impultienda", m), "diseno_contenido") is None


def test_huella_manipulada_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, huella="0" * 64)
    assert confirmado(v, m) is None


def test_el_capturado_del_codigo_manda(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    m["pantallas"]["diseno_contenido"]["capturado"] = "2026-12-01"
    c = mapa_con_confirmaciones(v, "impultienda", m, hoy=HOY)
    assert capturado_de(c, "diseno_contenido") == "2026-12-01"
    assert c["pantallas"]["diseno_contenido"]["url"] == m["pantallas"]["diseno_contenido"]["url"]


def test_archivo_roto_no_se_pisa(v):
    (v / RUTA).write_text("{roto", encoding="utf-8")
    with pytest.raises(ValueError, match="no se puede leer"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", REAL, "si", AHORA)
    assert (v / RUTA).read_text(encoding="utf-8") == "{roto"
    m = cargar_mapa(MAPA)
    assert mapa_con_confirmaciones(v, "impultienda", m) == m  # leer roto: sin confirmación, sin excepción
