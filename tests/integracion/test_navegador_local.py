import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.integracion


@pytest.fixture(autouse=True)
def _navegadores_reales(monkeypatch):
    # los tests cambian HOME; Playwright debe seguir encontrando los navegadores ya instalados
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))


@pytest.fixture
def servidor_local(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "hola.html").write_text("<html><body><h1>Hola Trovefy</h1></body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_capturar_pagina_local(servidor_local, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovefy.navegador import capturar

    c = capturar("prueba", servidor_local + "/hola.html", esperar_ms=200, visible=False, captura_png=tmp_path / "x.png")
    assert "Hola Trovefy" in c.texto and "Hola Trovefy" in c.html
    assert c.url_final.endswith("/hola.html") and (tmp_path / "x.png").exists()
    assert c.png == tmp_path / "x.png"


def test_error_de_navegacion_es_claro(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovefy.navegador import NavegadorError, capturar

    with pytest.raises(NavegadorError):
        capturar("prueba", "http://127.0.0.1:9/", esperar_ms=0, visible=False)


def test_abrir_con_cierre_automatico(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovefy.navegador import abrir

    abrir("prueba", "about:blank", cierre_auto_ms=1500)
