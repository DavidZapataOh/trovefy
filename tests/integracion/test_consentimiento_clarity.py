"""Plan 19, Tarea 7: `templates/landing/consentimiento.js` en Chromium real, contra una página en 127.0.0.1.

Sin pulsar nada no sale ninguna petición a Clarity; «Отказвам» tampoco; «Приемам» sí (la respuesta se simula:
no sale a la red)."""

import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest
from trovefy.tracking.clarity import (
    CONSENTIMIENTO_JS,
    bloque_consentimiento,
    es_peticion_clarity,
)

pytestmark = pytest.mark.integracion

PAGINA = """<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8"></head><body>
<main id="tf-landing"><h1>Тяло</h1>{aviso}<a href="#" data-tf-consentimiento-cambiar>Бисквитки</a></main>
<script src="assets/consentimiento.js" defer></script></body></html>"""


@pytest.fixture(autouse=True)
def _navegadores_reales(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    web = tmp_path_factory.mktemp("web")
    (web / "assets").mkdir()
    shutil.copyfile(CONSENTIMIENTO_JS, web / "assets" / "consentimiento.js")
    aviso = bloque_consentimiento("abcde12345", texto="Бисквитки за анализ?", aceptar="Приемам",
                                  rechazar="Отказвам")
    (web / "index.html").write_text(PAGINA.format(aviso=aviso), encoding="utf-8")
    handler = functools.partial(_Silencioso, directory=str(web))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture
def pagina():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context()
        pedidas: list[str] = []

        def ruta(route):
            pedidas.append(route.request.url)
            if es_peticion_clarity(route.request.url):
                route.fulfill(status=200, content_type="text/javascript", body=CLARITY_FALSO)
            elif route.request.url.startswith("http://127.0.0.1"):
                route.continue_()
            else:
                route.abort()

        ctx.route("**/*", ruta)
        page = ctx.new_page()
        page.pedidas = pedidas
        yield page
        b.close()


# La etiqueta de Clarity simulada: apunta cada llamada a ``clarity(...)`` en sessionStorage (sobrevive a la recarga)
# y pone sus cookies como lo haría Clarity.
CLARITY_FALSO = """
window.clarity = function () {
  var l = JSON.parse(sessionStorage.getItem("tf-llamadas") || "[]");
  l.push(Array.prototype.slice.call(arguments));
  sessionStorage.setItem("tf-llamadas", JSON.stringify(l));
};
document.cookie = "_clck=abc; path=/";
document.cookie = "_clsk=def; path=/";
"""


def _clarity(page) -> list[str]:
    return [u for u in page.pedidas if es_peticion_clarity(u)]


def test_sin_aceptar_no_sale_nada(pagina, servidor):
    pagina.goto(servidor, wait_until="load")
    pagina.wait_for_timeout(500)
    assert pagina.is_visible("#tf-consentimiento")
    assert _clarity(pagina) == []


def test_rechazar_no_carga_y_no_vuelve_a_preguntar(pagina, servidor):
    pagina.goto(servidor, wait_until="load")
    pagina.click('[data-tf-consentimiento="no"]')
    pagina.reload(wait_until="load")
    pagina.wait_for_timeout(300)
    assert not pagina.is_visible("#tf-consentimiento")
    assert _clarity(pagina) == []


def test_aceptar_carga_clarity_y_se_recuerda(pagina, servidor):
    pagina.goto(servidor, wait_until="load")
    pagina.click('[data-tf-consentimiento="si"]')
    pagina.wait_for_timeout(300)
    assert _clarity(pagina) == ["https://www.clarity.ms/tag/abcde12345"]
    pagina.reload(wait_until="load")
    pagina.wait_for_timeout(300)
    assert not pagina.is_visible("#tf-consentimiento")
    assert len(_clarity(pagina)) == 2


def test_retirar_el_consentimiento(pagina, servidor):
    pagina.goto(servidor, wait_until="load")
    pagina.click('[data-tf-consentimiento="si"]')
    pagina.click("[data-tf-consentimiento-cambiar]")
    assert pagina.is_visible("#tf-consentimiento")
    with pagina.expect_navigation():
        pagina.click('[data-tf-consentimiento="no"]')
    pagina.wait_for_timeout(300)
    assert len(_clarity(pagina)) == 1  # solo la de antes de retirarlo


def test_retirar_avisa_a_clarity_y_borra_sus_cookies(pagina, servidor):
    """L2: clarity('consent', false) antes de borrar _clck/_clsk; tras la recarga no quedan."""
    pagina.goto(servidor, wait_until="load")
    pagina.click('[data-tf-consentimiento="si"]')
    pagina.wait_for_function("document.cookie.indexOf('_clck=') >= 0")
    pagina.evaluate("""() => {
        const orig = window.clarity;
        window.clarity = function () {
            sessionStorage.setItem("tf-cookies-al-avisar", document.cookie);
            return orig.apply(this, arguments);
        };
    }""")
    pagina.click("[data-tf-consentimiento-cambiar]")
    with pagina.expect_navigation():
        pagina.click('[data-tf-consentimiento="no"]')
    pagina.wait_for_timeout(300)
    llamadas = pagina.evaluate('JSON.parse(sessionStorage.getItem("tf-llamadas") || "[]")')
    assert ["consent", False] in llamadas
    assert "_clck=" in pagina.evaluate('sessionStorage.getItem("tf-cookies-al-avisar") || ""')  # aún no borradas
    cookies = {c["name"] for c in pagina.context.cookies()}
    assert "_clck" not in cookies and "_clsk" not in cookies
