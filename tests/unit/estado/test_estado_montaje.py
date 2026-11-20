"""Máquina de estados de la fase 3: lo que toca a /montar (plan 22, Tarea 7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy.estado import ESTADOS_FASE3, TRANSICIONES, permitida
from trovefy.estado.montaje import tras_activar, tras_montaje
from trovefy.vault import frontmatter
from trovefy.vault.producto import EstadoInesperado, avanzar_estado

P = "p-0099-prueba-abc123"
AHORA = datetime(2026, 11, 19, 9, 30, tzinfo=ZoneInfo("America/Bogota"))


@dataclass
class R:
    estado: str
    parcial: bool = False


def test_tabla_de_la_fase3_en_minusculas():
    assert ESTADOS_FASE3 == ("montado", "test", "muerto", "candidato")
    assert dict(TRANSICIONES) == {"listo": {"montado"}, "montado": {"test"}, "test": {"muerto", "candidato"}}
    assert permitida("listo", "montado") and not permitida("listo", "test")


@pytest.mark.parametrize(("estado", "res", "nuevo", "aviso"), [
    ("listo", R("ejecutada"), "montado", None),
    ("listo", R("fallida"), None, "falló sin crear nada"),
    ("listo", R("fallida", parcial=True), None, "estado parcial"),
    ("listo", R("discrepancia"), None, "estado parcial"),
])
def test_tras_montaje(estado, res, nuevo, aviso):
    p = tras_montaje(estado, res)
    assert p.nuevo == nuevo
    if aviso:
        assert aviso in p.avisos[0]


def test_tras_montaje_desde_otro_estado():
    with pytest.raises(ValueError, match="solo avanza desde listo"):
        tras_montaje("con_checkout", R("ejecutada"))


@pytest.mark.parametrize(("res", "nuevo", "veto", "aviso"), [
    (R("ejecutada"), "test", False, None),
    (R("rechazada"), None, True, "PAUSED"),
    (R("caducada"), None, False, "trovefy montar activar"),
    (R("discrepancia"), None, False, "discrepancia"),
])
def test_tras_activar(res, nuevo, veto, aviso):
    p = tras_activar("montado", res)
    assert (p.nuevo, p.veto) == (nuevo, veto)
    if aviso:
        assert aviso in p.avisos[0]


def test_tras_activar_desde_listo_no():
    with pytest.raises(ValueError):
        tras_activar("listo", R("ejecutada"))


def _producto(vault, estado):
    frontmatter.escribir(vault / "productos" / P / "PRODUCTO.md",
                         {"tipo": "producto", "paises": {"ZZ": {"estado": estado}}}, "# P\n")


def test_listo_a_montado_con_evidencia(tmp_path):
    _producto(tmp_path, "listo")
    avanzar_estado(tmp_path, P, "ZZ", "listo", "montado", "propuestas/P-20261119-002.md", "/montar", AHORA)
    meta, _ = frontmatter.leer(tmp_path / "productos" / P / "PRODUCTO.md")
    assert meta["paises"]["ZZ"]["estado"] == "montado"
    assert meta["paises"]["ZZ"]["historial"][-1]["evidencia"] == ["propuestas/P-20261119-002.md"]


def test_montado_a_listo_no_permitido(tmp_path):
    _producto(tmp_path, "montado")
    with pytest.raises(ValueError, match="paso no permitido"):
        avanzar_estado(tmp_path, P, "ZZ", "montado", "listo", "x", "/montar", AHORA)


def test_salto_listo_a_test_no_permitido(tmp_path):
    _producto(tmp_path, "listo")
    with pytest.raises(ValueError, match="paso no permitido"):
        avanzar_estado(tmp_path, P, "ZZ", "listo", "test", "x", "/montar", AHORA)


def test_estado_inesperado(tmp_path):
    _producto(tmp_path, "con_checkout")
    with pytest.raises(EstadoInesperado):
        avanzar_estado(tmp_path, P, "ZZ", "listo", "montado", "x", "/montar", AHORA)


def test_fase2_sin_cambios(tmp_path):
    _producto(tmp_path, "con_checkout")
    avanzar_estado(tmp_path, P, "ZZ", "con_checkout", "listo", "x", "/listo", AHORA)
    with pytest.raises(ValueError):
        avanzar_estado(tmp_path, P, "ZZ", "aprobado", "producido", "x", "/x", AHORA)
