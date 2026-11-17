"""Plan 18, Tarea 3: `templates/landing/utm.js` en Chromium real, contra una página en 127.0.0.1."""

import functools
import http.server
import os
import shutil
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.integracion

UTM_JS = Path(__file__).resolve().parents[2] / "templates" / "landing" / "utm.js"
# Plantilla de §4.9 rellenada con datos ficticios: «|», espacios y una «А» cirílica.
QUERY = ("?utm_source=fb&utm_medium=paid&utm_campaign=Demo%20ZZ%7C120000000000000001"
         "&utm_term=Conjunto%201%7C120000000000000002&utm_content=Anuncio%20%D0%90%7C120000000000000003"
         "&fbclid=IwDemo&gclid=x&otro=1")
PAGINA = """<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">
<script src="assets/utm.js" defer></script></head><body>
<a id="a1" data-tf-checkout href="/checkout">1</a>
<a id="a2" data-tf-checkout href="/checkout?p=1">2</a>
<a id="a3" data-tf-checkout href="/checkout#pagar">3</a>
<a id="a4" data-tf-checkout href="/checkout?p=a%20b&amp;q=x+y">4</a>
<a id="a5" data-tf-checkout href="https://tienda.demo.test/checkout?p=1">5</a>
<a id="otro" href="/otro">x</a>
</body></html>"""


@pytest.fixture(autouse=True)
def _navegadores_reales(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # sin ruido en la salida de los tests
        pass


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    web = tmp_path_factory.mktemp("web")
    (web / "assets").mkdir()
    shutil.copyfile(UTM_JS, web / "assets" / "utm.js")
    (web / "index.html").write_text(PAGINA, encoding="utf-8")
    handler = functools.partial(_Silencioso, directory=str(web))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def navegador():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def _hrefs(navegador, url: str) -> dict[str, str]:
    pagina = navegador.new_page()
    externas = []

    def solo_local(route):
        if urlsplit(route.request.url).hostname == "127.0.0.1":
            route.continue_()
        else:
            externas.append(route.request.url)
            route.abort()

    pagina.route("**/*", solo_local)
    pagina.goto(url, wait_until="load")
    hrefs = {i: pagina.get_attribute(f"#{i}", "href") for i in ("a1", "a2", "a3", "a4", "a5", "otro")}
    pagina.close()
    assert not externas
    return hrefs


def _query(href: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(href).query, keep_blank_values=True)


def test_utm_pasa_todos_y_fbclid(servidor, navegador):
    q = _query(_hrefs(navegador, servidor + "/index.html" + QUERY)["a1"])
    assert set(q) == {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"}
    assert q["fbclid"] == ["IwDemo"] and q["utm_source"] == ["fb"]


def test_utm_valores_codificados_ida_y_vuelta(servidor, navegador):
    h = _hrefs(navegador, servidor + "/index.html" + QUERY)
    q = _query(h["a1"])
    assert q["utm_content"] == ["Anuncio А|120000000000000003"]
    assert q["utm_campaign"] == ["Demo ZZ|120000000000000001"] and q["utm_term"] == ["Conjunto 1|120000000000000002"]
    assert h["a1"].startswith("/checkout?")  # sigue siendo relativa (ruta Impultienda)


def test_utm_no_pisa_parametros_del_enlace(servidor, navegador):
    h = _hrefs(navegador, servidor + "/index.html" + QUERY)
    assert _query(h["a2"])["p"] == ["1"] and "utm_source" in _query(h["a2"])
    h = _hrefs(navegador, servidor + "/index.html?p=9&utm_source=fb")
    assert _query(h["a2"]) == {"p": ["1"], "utm_source": ["fb"]}


def test_utm_conserva_fragmento(servidor, navegador):
    h = _hrefs(navegador, servidor + "/index.html" + QUERY)
    assert h["a3"].endswith("#pagar") and "utm_medium=paid" in h["a3"]
    assert h["otro"] == "/otro"


def test_utm_sin_parametros_no_toca(servidor, navegador):
    h = _hrefs(navegador, servidor + "/index.html?gclid=x")
    assert h == {"a1": "/checkout", "a2": "/checkout?p=1", "a3": "/checkout#pagar", "a4": "/checkout?p=a%20b&q=x+y",
                 "a5": "https://tienda.demo.test/checkout?p=1", "otro": "/otro"}
    assert _hrefs(navegador, servidor + "/index.html") == h


def test_utm_conserva_la_codificacion_del_enlace(servidor, navegador):
    """El query que ya trae el botón no se recodifica («%20» sigue «%20» y «+» sigue «+»)."""
    h = _hrefs(navegador, servidor + "/index.html" + QUERY)
    assert h["a4"].startswith("/checkout?p=a%20b&q=x+y&utm_source=fb&")
    assert _query(h["a4"])["utm_content"] == ["Anuncio А|120000000000000003"]


def test_utm_href_absoluto(servidor, navegador):
    """Ruta Cloudflare: el checkout absoluto de la tienda sigue absoluto y recibe los parámetros."""
    h = _hrefs(navegador, servidor + "/index.html" + QUERY)
    assert h["a5"].startswith("https://tienda.demo.test/checkout?p=1&")
    q = _query(h["a5"])
    assert q["p"] == ["1"] and q["fbclid"] == ["IwDemo"] and q["utm_campaign"] == ["Demo ZZ|120000000000000001"]
