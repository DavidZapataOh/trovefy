"""Plan 18, Tarea 6: medición de la landing en Chromium real, contra la fixture buena servida en 127.0.0.1.

Toda petición a otro host la aborta `medir` (y la anota); el checkout lo intercepta `probar_clic` con un 204.
"""

import functools
import http.server
import io
import os
import shutil
import statistics
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.integracion

RAIZ = Path(__file__).resolve().parents[2]
BUENA = RAIZ / "tests" / "fixtures" / "landing" / "buena-zz.html"
PLANTILLAS = RAIZ / "templates" / "landing"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # candado del navegador fuera del HOME real


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _webp(ancho: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (ancho, int(ancho * 1.41)), (240, 236, 228)).save(buf, format="WEBP")
    return buf.getvalue()


def _web(destino: Path, extra: str = "") -> Path:
    (destino / "assets").mkdir(parents=True)
    html = BUENA.read_text(encoding="utf-8")
    if extra:
        html = html.replace("</main>", extra + "</main>")
    (destino / "index.html").write_text(html, encoding="utf-8")
    shutil.copyfile(PLANTILLAS / "utm.js", destino / "assets" / "utm.js")
    css = ":root{--color-primario:#1F4E5F;--color-fondo:#FAF7F2}\n" + (PLANTILLAS / "base.css").read_text("utf-8")
    (destino / "assets" / "estilo.css").write_text(css, encoding="utf-8")
    for n in (1, 2, 3):
        for w in (480, 960):
            (destino / "assets" / f"vista-p{n}-{w}.webp").write_bytes(_webp(w))
    return destino


@pytest.fixture
def servir():
    servidores = []

    def _servir(web: Path) -> str:
        handler = functools.partial(_Silencioso, directory=str(web))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servidores.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/index.html"

    yield _servir
    for srv in servidores:
        srv.shutdown()


@pytest.fixture
def rapido(monkeypatch):
    """La espera tras `load` (3 s en producción) a 0,5 s: aquí no se mide un LCP de verdad."""
    from trovefy.landing import qa

    monkeypatch.setattr(qa, "ESPERA_TRAS_LOAD_MS", 500)


def test_medir_local_390_y_1280(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    url = servir(_web(tmp_path / "web"))
    capturas = tmp_path / "qa"
    for vista, ancho in (("movil", 390), ("escritorio", 1280)):
        m = medir(url, vista, capturas / f"{vista}-x.png", ("127.0.0.1",), red_4g=False)
        assert m.motivo is None, m.motivo
        assert m.peso_bytes and m.peso_bytes > 0
        assert m.peticiones_externas == ()
        assert m.ancho_scroll <= ancho and m.desborde_selector is None
        assert m.lcp_ms is not None and len(m.lcp_ms) == 3 and all(x > 0 for x in m.lcp_ms)
        assert sorted(m.hitos) == list(range(1, 16))
        valores = [m.hitos[i] for i in range(1, 16)]
        assert valores == sorted(valores) and len(set(valores)) == 15
        assert m.http == 200 and m.version_servida == ""
        assert m.captura == capturas / f"{vista}-x.png"
        assert m.captura.read_bytes().startswith(b"\x89PNG")
        assert m.captura.stat().st_mode & 0o777 == 0o640


def test_medir_aborta_externa(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    url = servir(_web(tmp_path / "web", '<img src="https://externo.test/a.webp" alt="">'))
    m = medir(url, "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    assert m.peticiones_externas == ("https://externo.test/a.webp",)


def test_medir_silencia_sin_anotar(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    url = servir(_web(tmp_path / "web", '<img src="https://www.facebook.com/tr?id=0" alt="">'))
    m = medir(url, "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False, silenciar=("www.facebook.com",))
    assert m.peticiones_externas == ()


def test_medir_desborde_con_selector(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    tabla = '<table class="comparativa" style="width:900px;min-width:900px"><tr><td>a</td></tr></table>'
    url = servir(_web(tmp_path / "web", tabla))
    m = medir(url, "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    assert m.ancho_scroll > 390 and m.desborde_selector == "table.comparativa"


def test_clic_lleva_utm(tmp_path, servir):
    from trovefy.landing.qa import probar_clic, utm_intactos

    url = servir(_web(tmp_path / "web"))
    c = probar_clic(url, "/checkout")
    assert c.motivo is None and c.url_pedida is not None, c.motivo
    assert utm_intactos(c.url_pedida, "/checkout", url)
    assert c.intactos is True


def test_clic_a_checkout_absoluto_no_sale_a_la_red(tmp_path, servir):
    from trovefy.landing.qa import probar_clic, utm_intactos

    web = _web(tmp_path / "web")
    html = (web / "index.html").read_text(encoding="utf-8")
    (web / "index.html").write_text(html.replace('href="/checkout"', 'href="https://tienda.demo.test/checkout"'),
                                    encoding="utf-8")
    url = servir(web)
    c = probar_clic(url, "https://tienda.demo.test/checkout")
    assert c.url_pedida is not None and c.url_pedida.startswith("https://tienda.demo.test/checkout?")
    assert utm_intactos(c.url_pedida, "https://tienda.demo.test/checkout", url)


def test_lcp_con_red_4g_es_mayor(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    url = servir(_web(tmp_path / "web"))
    rapida = medir(url, "movil", tmp_path / "a.png", ("127.0.0.1",), red_4g=False)
    lenta = medir(url, "movil", tmp_path / "b.png", ("127.0.0.1",), red_4g=True)
    assert rapida.lcp_ms and lenta.lcp_ms
    assert statistics.median(lenta.lcp_ms) >= statistics.median(rapida.lcp_ms)


def test_ejecutar_qa_local_de_punta_a_punta(tmp_path, rapido):
    """`ejecutar_qa` sirve la landing guardada del vault demo en 127.0.0.1 y escribe `QA.md`."""
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.qa import ejecutar_qa
    from trovefy.vault import frontmatter
    from unit.landing.conftest import P, cargar
    from unit.landing.test_validar import montar

    v = montar(tmp_path)
    r = ejecutar_qa(v, cargar(v))
    filas = {f[0]: f for f in r.filas}
    assert filas["Clic al checkout con UTM"][1] == "OK", r.filas
    assert filas["Peticiones externas (movil)"][1] == "OK"
    assert filas["Hitos (movil)"][1] in ("OK", "AVISO"), filas["Hitos (movil)"]
    assert filas["Idioma (nativo)"][1] == "NO MEDIDO"
    meta, _ = frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA.md")
    assert meta["ok"] is False and meta["movil_390"]["http"] == 200
