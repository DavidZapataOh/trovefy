"""Conductor con Chromium real contra páginas propias servidas en 127.0.0.1 (sin red ni sesiones reales)."""

import functools
import http.server
import os
import shutil
import stat
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.integracion

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/tienda"


@pytest.fixture(autouse=True)
def _entorno(tmp_path, monkeypatch):
    # HOME de prueba (perfil en tmp_path); Playwright debe seguir encontrando los navegadores ya instalados
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def servidor_local(tmp_path):
    web = tmp_path / "web"
    shutil.copytree(FIXTURES, web)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def mapa_local(base: str) -> dict:
    # http:// solo aquí: es un mapa en memoria contra 127.0.0.1 (cargar() exige https)
    controles = {
        "precio": {"etiqueta": "Precio", "rol": "textbox", "tipo": "precio"},
        "moneda": {"etiqueta": "Moneda", "tipo": "select"},
        "activo": {"etiqueta": "Activar bump", "tipo": "interruptor"},
        "token": {"etiqueta": "Token de acceso", "tipo": "texto", "secreto": True},
        "entrega": {"etiqueta": "Entregable", "tipo": "archivo"},
        "guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"},
    }
    return {
        "capturado": "2026-11-20",
        "fuente": "páginas de prueba propias",
        "hosts": ["127.0.0.1"],
        "pantallas": {
            "producto": {"url": base + "/producto.html", "firma": ["Editar producto"], "controles": controles},
            "cambiada": {"url": base + "/producto-cambiada.html", "firma": ["Editar producto"], "controles": controles},
            "login": {"url": base + "/login.html", "firma": ["Iniciar sesión"]},
        },
    }


def _conductor(page, base):
    from trovefy.tienda.conductor import Conductor

    return Conductor(page, mapa_local(base), "prueba", dormir=lambda _s: None)


def test_conductor_rellena_y_relee_local(servidor_local, tmp_path):
    from trovefy.navegador import sesion

    pdf = tmp_path / "entrega.pdf"
    pdf.write_bytes(b"%PDF-1.4 prueba")
    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        assert "Editar producto" in c.ir("producto")
        assert c.leer("producto", "precio") == "13.90"
        c.poner("producto", "precio", "14.90")
        c.poner("producto", "moneda", "USD")
        c.poner("producto", "activo", False)
        c.poner("producto", "entrega", pdf)
        assert c.leer("producto", "precio") == "14.90"
        assert c.leer("producto", "moneda") == "USD"
        assert c.leer("producto", "activo") is False
        assert c.configurado("producto", "token") is True
        c.pulsar("producto", "guardar")
        assert page.inner_text("#estado") == "Guardado"
        captura = c.capturar(tmp_path / "capturas" / "producto.png")
        assert captura.stat().st_size > 0 and stat.S_IMODE(captura.stat().st_mode) == 0o600


def test_conductor_para_si_la_pagina_cambia(servidor_local):
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import FirmaNoCasa, Parada

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        with pytest.raises(FirmaNoCasa):
            c.ir("cambiada")
        with pytest.raises(Parada):
            c.poner("cambiada", "precio", "99.00")
        assert page.locator("#precio").input_value() == "13.90"


def test_conductor_para_si_la_sesion_caduco(servidor_local):
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import SesionCaducada

    with sesion("prueba", visible=False) as page, pytest.raises(SesionCaducada, match="trovefy navegador abrir prueba"):
        _conductor(page, servidor_local).ir("login")


def test_sesion_efimera_con_viewport(servidor_local, tmp_path):
    from trovefy.navegador import sesion

    with sesion("comprador", visible=False, perfil_persistente=False, viewport=(390, 844)) as page:
        page.goto(servidor_local + "/producto.html")
        assert page.evaluate("window.innerWidth") == 390
    assert not (tmp_path / ".config/trovefy/pw-comprador").exists()
