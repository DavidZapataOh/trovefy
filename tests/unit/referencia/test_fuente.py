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
    assert nav.llamadas == []  # con lote, la vía pública nunca da el listado y sin listado no se gasta búsqueda
    assert r.parada is None and r.motivo_medios
    assert not (vault / "data/caza/presupuesto" / f"{HOY.isoformat()}.json").exists()


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
    assert datos["usadas"] == 1


def test_lote_invalido_es_no_medido(vault, tmp_path):
    malo = tmp_path / "malo.json"
    malo.write_text("no es json")
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=malo, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.via == "mcp" and r.anuncios == []
    assert r.motivo == "no medido: lote inválido (el lote no es JSON)"
    assert "no es json" not in r.motivo


def _lote_con(tmp_path, respuesta):
    d = json.loads((FIX / "lote_pagina.json").read_text())
    for b in d["busquedas"]:
        b["respuesta"] = respuesta
    p = tmp_path / "lote-error.json"
    p.write_text(json.dumps(d))
    return p


def test_lote_bloqueado_para_el_dia_sin_navegador(vault, tmp_path):
    lote = _lote_con(tmp_path, {"results": json.dumps({"error": {"message": "limit", "code": 4}})})
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=lote, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.parada == "meta" and r.anuncios == [] and nav.llamadas == []
    datos = json.loads((vault / "data/caza/presupuesto" / f"{HOY.isoformat()}.json").read_text())
    assert datos.get("parada") and datos.get("usadas", 0) == 0


def test_lote_con_error_no_abre_navegador(vault, tmp_path):
    lote = _lote_con(tmp_path, {"error": {"message": "bad", "code": 100}})
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=lote, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.parada is None and r.anuncios == [] and "error" in r.motivo and nav.llamadas == []
    assert not (vault / "data/caza/presupuesto" / f"{HOY.isoformat()}.json").exists()


def test_parada_del_dia_tiene_su_motivo(vault):
    d = vault / "data/caza/presupuesto"
    d.mkdir(parents=True)
    (d / f"{HOY.isoformat()}.json").write_text(json.dumps({"usadas": 1, "rutina": 0, "parada": "bloqueo de Meta: x"}))
    nav = NavFalso([pag()])
    r = fuente.listar(vault, "RO", PID, lote=None, sin_navegador=False, navegador=nav, hoy=HOY)
    assert r.parada == "meta" and r.motivo_medios == "Meta ya bloqueó hoy; vuelve mañana" and nav.llamadas == []
