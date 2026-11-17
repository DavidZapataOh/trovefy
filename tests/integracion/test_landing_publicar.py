"""Plan 18, Tarea 9: publicar en la Impultienda falsa (127.0.0.1) con Chromium real, relectura y SHA-256."""

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.integracion

AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))


@pytest.fixture(autouse=True)
def _entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _capacidades():
    from trovefy.landing.hosting import CAPACIDADES_FASE0

    return replace(CAPACIDADES_FASE0, script=True, estilos=True, titulo_propio=True, sin_marco=True,
                   dominio_propio=True, fecha="2026-11-17", fuente="prueba")


def _publicar(tmp_path, estado, engordar=False):
    from integracion.impultienda_falsa import impultienda_falsa, mapa_local
    from trovefy.landing.publicar import publicar_impultienda
    from unit.landing.conftest import cargar
    from unit.landing.test_hosting import montar

    v = montar(tmp_path)
    if engordar:
        from unit.landing.test_publicar import engordar as engordar_

        engordar_(v)
    with impultienda_falsa(estado) as base:
        url = publicar_impultienda(v, cargar(v), _capacidades(), mapa=mapa_local(base), visible=False,
                                   dormir=lambda _s: None, ahora=AHORA)
    return v, url


def test_publicar_impultienda_relee_igual(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.hosting import empaquetar_en_linea
    from unit.landing.conftest import DOMINIO, P

    estado = Estado()
    original = estado.contenido
    v, url = _publicar(tmp_path, estado)
    assert url == f"https://{DOMINIO}/"
    assert estado.contenido == empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17.html"
    assert respaldo.read_text(encoding="utf-8") == original


def test_publicar_detecta_recorte(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.landing.publicar import HtmlRecortado
    from unit.landing.conftest import P

    estado = Estado(recorte=50_000)
    original = estado.contenido
    with pytest.raises(HtmlRecortado, match="50000 de") as e:
        _publicar(tmp_path, estado, engordar=True)
    assert "He vuelto a dejar lo que había" in str(e.value)
    assert estado.contenido == original
    meta = (tmp_path / "v" / "productos" / P / "PRODUCTO.md").read_text(encoding="utf-8")
    assert "con_landing" not in meta and "landing:" not in meta


def test_publicar_firma_ausente_no_toca(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.tienda.conductor import FirmaNoCasa

    estado = Estado(firma=False)
    with pytest.raises(FirmaNoCasa):
        _publicar(tmp_path, estado)
    assert estado.posts == []
