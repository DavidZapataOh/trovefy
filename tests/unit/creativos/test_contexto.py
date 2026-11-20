"""Contexto de la tanda desde el vault (plan 21, Tarea 2)."""

from decimal import Decimal

import pytest
from trovefy.creativos.config import cargar_config
from trovefy.creativos.contexto import (
    EstadoNoPermite,
    cargar_contexto,
    ruta_tanda,
    siguiente_tanda,
    url_con_utm,
)
from trovefy.tracking.modelo import PLANTILLA_UTM

from .ejemplos import LANDING, PAIS, P, crear_vault


def test_contexto_ficticio(tmp_path):
    vault = crear_vault(tmp_path)
    ctx = cargar_contexto(vault, P, PAIS, cargar_config(vault))
    assert ctx.precio_front == Decimal("13.90") and ctx.precio_texto == "13,90 €"
    assert ctx.url_anuncio == LANDING + "?" + PLANTILLA_UTM
    assert ctx.tipografias == {"titulos": "Ubuntu", "texto": "Noto Sans"}
    assert ctx.idioma == "bg" and ctx.mecanismo == "Ruta Calma 3R"
    assert ctx.objeciones == ("нямам време", "не вярвам")
    assert ctx.pdf_vigente is not None and ctx.pdf_vigente.name == "v1.pdf"
    assert set(ctx.medios_propios) == {"mockup", "portada", "ficha-01"}


def test_estado_producido_no_permite(tmp_path):
    vault = crear_vault(tmp_path, estado="producido")
    with pytest.raises(EstadoNoPermite, match="primero /listo"):
        cargar_contexto(vault, P, PAIS)


def test_renovar_exige_estado_de_trafico(tmp_path):
    vault = crear_vault(tmp_path, estado="listo")
    with pytest.raises(EstadoNoPermite):
        cargar_contexto(vault, P, PAIS, renovar=True)
    vault2 = crear_vault(tmp_path / "otro", estado="test")
    assert cargar_contexto(vault2, P, PAIS, renovar=True).estado == "test"


def test_mezcla_no_medida(tmp_path):
    ctx = cargar_contexto(crear_vault(tmp_path), P, PAIS)
    assert ctx.mezcla_imagenes_pct is None
    assert any(m.startswith("no medido: mezcla") for m in ctx.motivos)


def test_mezcla_medida_85(tmp_path):
    vault = crear_vault(tmp_path, mezcla="# Mezcla\n\n## Top (20 ganadores)\n\n- vídeo 15 % (3)\n- imagen 85 % (17)\n")
    assert cargar_contexto(vault, P, PAIS).mezcla_imagenes_pct == 85
    vault2 = crear_vault(tmp_path / "b", mezcla="## Top\n\n85 % imagen\n")
    assert cargar_contexto(vault2, P, PAIS).mezcla_imagenes_pct == 85


def test_url_con_query_previa():
    assert url_con_utm("https://prueba.example/?a=1") == "https://prueba.example/?a=1&" + PLANTILLA_UTM


def test_landing_http_rechazada():
    with pytest.raises(ValueError):
        url_con_utm("http://prueba.example/")
    with pytest.raises(ValueError):
        url_con_utm("https://prueba.example/ x")


def test_siguiente_tanda(tmp_path):
    vault = crear_vault(tmp_path)
    assert siguiente_tanda(vault, P, PAIS) == ("t1", 1)
    ruta_tanda(vault, P, PAIS, "t1").mkdir(parents=True)
    ruta_tanda(vault, P, PAIS, "t3").mkdir(parents=True)
    assert siguiente_tanda(vault, P, PAIS) == ("t4", 4)
