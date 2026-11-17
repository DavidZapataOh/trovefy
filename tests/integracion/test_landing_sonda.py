"""Plan 18, Tarea 8: la sonda de Impultienda con Chromium real contra un panel falso en 127.0.0.1."""

import os
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


def _sondar(tmp_path, estado):
    from integracion.impultienda_falsa import impultienda_falsa, mapa_local
    from trovefy.landing.hosting import sondear
    from unit.landing.conftest import P, vault_demo

    v = vault_demo(tmp_path)
    with impultienda_falsa(estado) as base:
        c = sondear(v, P, "ZZ", base + "/tienda", True, mapa=mapa_local(base), visible=False,
                    dormir=lambda _s: None, ahora=AHORA)
    return v, c


def test_sonda_todo_bien(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.landing.hosting import HTML_SONDA

    estado = Estado()
    original = estado.contenido
    v, c = _sondar(tmp_path, estado)
    assert (c.html_propio, c.script, c.estilos, c.titulo_propio, c.sin_marco) == (True,) * 5
    assert c.limite_caracteres is None
    assert estado.contenido == original  # restaurado byte a byte
    assert estado.posts == [HTML_SONDA, original]
    assert (v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json").is_file()


def test_sonda_script_quitado_es_false(tmp_path):
    from integracion.impultienda_falsa import Estado

    estado = Estado(sin_script=True)
    original = estado.contenido
    _, c = _sondar(tmp_path, estado)
    assert c.script is False and c.estilos is True and c.titulo_propio is True
    assert estado.contenido == original


def test_sonda_detecta_recorte(tmp_path):
    from integracion.impultienda_falsa import Estado

    estado = Estado(recorte=50_000)
    original = estado.contenido
    _, c = _sondar(tmp_path, estado)
    assert c.limite_caracteres == 50_000
    assert estado.contenido == original


def test_sonda_con_marco_es_false(tmp_path):
    from integracion.impultienda_falsa import Estado

    _, c = _sondar(tmp_path, Estado(marco=True))
    assert c.sin_marco is False and c.html_propio is True


def test_sonda_firma_ausente_no_toca(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.tienda.conductor import FirmaNoCasa

    estado = Estado(firma=False)
    with pytest.raises(FirmaNoCasa, match="HTML completo de la tienda"):
        _sondar(tmp_path, estado)
    assert estado.posts == []


def test_sonda_url_de_otro_host_rechazada(tmp_path):
    from integracion.impultienda_falsa import Estado, impultienda_falsa, mapa_local
    from trovefy.landing.hosting import sondear
    from unit.landing.conftest import P, vault_demo

    estado = Estado()
    with impultienda_falsa(estado) as base, pytest.raises(ValueError, match="127.0.0.1"):
        sondear(vault_demo(tmp_path), P, "ZZ", base + "/tienda", True, "https://otro.test/panel",
                mapa=mapa_local(base), visible=False, dormir=lambda _s: None, ahora=AHORA)
    assert estado.posts == []


def test_capturar_pantalla_confirma_sin_clics(tmp_path):
    from integracion.impultienda_falsa import Estado, impultienda_falsa, mapa_local
    from trovefy.landing.panel import capturar_pantalla
    from trovefy.mapa import capturado_de
    from trovefy.tienda.confirmacion import mapa_con_confirmaciones

    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    estado = Estado()
    avisos = []
    with impultienda_falsa(estado) as base:
        mapa = mapa_local(base, capturado=None)
        entrada = capturar_pantalla(v, mapa=mapa, esperar=avisos.append, preguntar=lambda _t: "sí",
                                    visible=False, dormir=lambda _s: None, ahora=AHORA)
    assert estado.posts == []  # ni un guardado
    assert entrada["url"] == base + "/panel" and avisos
    assert (v / entrada["evidencia"]).stat().st_size > 0
    assert capturado_de(mapa_con_confirmaciones(v, "impultienda", mapa), "diseno_contenido") == "2026-11-17"
