"""Listado por lote MCP o Biblioteca pública, más medios (sin red)."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from trovefy.caza.cliente import PaginaCapturada
from trovefy.referencia import fuente

FIX = Path(__file__).resolve().parents[2] / "fixtures/referencia"
PLANTILLA = Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml"
HOY = date(2026, 11, 13)
PID = "800000000001"


class NavFalso:
    def __init__(self, paginas):
        self.paginas, self.llamadas = list(paginas), []

    def abrir(self, url, max_anuncios):
        self.llamadas.append(url)
        p = self.paginas.pop(0)
        if isinstance(p, Exception):
            raise p
        return p


def pag(nombre="pagina_con_medios.json", html=None):
    d = json.loads((FIX / nombre).read_text())
    return PaginaCapturada(d["url_final"], html or d["html_final"], "", [])


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(PLANTILLA, tmp_path / "config/umbrales.yaml")
    return tmp_path


def test_listar_desde_lote(vault):
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=FIX / "lote_pagina.json", sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.via == "mcp" and [a.library_id for a in r.anuncios] == ["900000000000001"]
    assert r.via_medios == "publica" and r.medios["900000000000001"].formato == "video"
    assert r.parada is None and len(nav.llamadas) == 1


def test_lote_sin_la_busqueda_no_cae_a_publica(vault):
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", "800000000999", lote=FIX / "lote_pagina.json", sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.via == "mcp" and r.anuncios == [] and "fuera del lote" in r.motivo
    assert len(nav.llamadas) == 1  # solo los medios


def test_listar_sin_lote_una_sola_busqueda(vault):
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=None, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.via == "publica" and len(r.anuncios) == 4 and len(nav.llamadas) == 1
    assert r.via_medios == "publica" and len(r.medios) == 4


def test_bloqueo_es_parada(vault):
    d = json.loads((FIX / "pagina_con_medios.json").read_text())
    html = d["html_final"].replace('"xfb_ad_library_is_captcha_required":false', '"xfb_ad_library_is_captcha_required":true')
    nav = NavFalso([pag(html=html), pag()])
    r = fuente.listar(vault, "RO", PID, lote=None, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.parada == "meta" and r.medios == {} and len(nav.llamadas) == 1


def test_sin_navegador_no_mide_medios(vault):
    nav = NavFalso([])
    r = fuente.listar(vault, "RO", PID, lote=FIX / "lote_pagina.json", sin_navegador=True, navegador=nav, hoy=HOY)
    assert r.via == "mcp" and r.medios == {} and r.via_medios is None
    assert r.motivo_medios == "no medido: sin navegador (pedido por el usuario)" and nav.llamadas == []


def test_presupuesto_cuenta_la_busqueda(vault):
    fuente.listar(vault, "RO", PID, lote=None, sin_navegador=False, navegador=NavFalso([pag()]), hoy=HOY)
    datos = json.loads((vault / "data/caza/presupuesto" / f"{HOY.isoformat()}.json").read_text())
    assert 1 in [v for v in datos.values() if isinstance(v, int)]
