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
import time
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


class _Registro(http.server.BaseHTTPRequestHandler):
    """Servidor que solo anota lo que le llega (método y ruta): la QA no debe tocarlo nunca."""

    hits: list[str]

    def _anotar(self):
        self.hits.append(f"{self.command} {self.path}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html>checkout</html>")

    do_GET = do_POST = do_HEAD = _anotar

    def log_message(self, *a):
        pass


class _LandingConRegistro(_Silencioso):
    """La landing de siempre, pero anota cada petición (GET incluidos) y acepta POST con un 204."""

    hits: list[str]

    def do_GET(self):
        self.hits.append(f"GET {self.path}")
        super().do_GET()

    def do_POST(self):
        self.hits.append(f"POST {self.path}")
        self.send_response(204)
        self.end_headers()

    do_PUT = do_POST


@pytest.fixture
def registro():
    """Un segundo servidor en 127.0.0.1; se le llama por `localhost` (otro host para la QA)."""
    hits: list[str] = []
    handler = type("R", (_Registro,), {"hits": hits})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}", hits
    srv.shutdown()


@pytest.fixture
def servir_anotando():
    servidores = []

    def _servir(web: Path) -> tuple[str, list[str], int]:
        hits: list[str] = []
        handler = functools.partial(type("L", (_LandingConRegistro,), {"hits": hits}), directory=str(web))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servidores.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/index.html", hits, srv.server_address[1]

    yield _servir
    for srv in servidores:
        srv.shutdown()


def _cambiar(web: Path, viejo: str, nuevo: str) -> None:
    html = (web / "index.html").read_text(encoding="utf-8")
    assert viejo in html
    (web / "index.html").write_text(html.replace(viejo, nuevo), encoding="utf-8")


def test_clic_a_checkout_absoluto_no_sale_a_la_red(tmp_path, servir, registro):
    """T2: el checkout absoluto se intercepta con un 204: el servidor del checkout no recibe nada."""
    from trovefy.landing.qa import probar_clic, utm_intactos

    base, hits = registro
    web = _web(tmp_path / "web")
    _cambiar(web, 'href="/checkout"', f'href="{base}/checkout"')
    url = servir(web)
    c = probar_clic(url, f"{base}/checkout")
    assert c.url_pedida is not None and c.url_pedida.startswith(f"{base}/checkout?")
    assert utm_intactos(c.url_pedida, f"{base}/checkout", url)
    time.sleep(1)
    assert hits == []


def test_clic_sin_boton_no_toca_otro_host(tmp_path, servir, registro):
    """T2: sin a[data-tf-checkout] no hay medida, y lo que la página pida a otro host se aborta."""
    from trovefy.landing.qa import probar_clic

    base, hits = registro
    web = _web(tmp_path / "web", f'<img src="{base}/pixel.gif" alt="">')
    _cambiar(web, "data-tf-checkout ", "")
    c = probar_clic(servir(web), f"{base}/checkout")
    assert c.url_pedida is None and "a[data-tf-checkout]" in c.motivo
    time.sleep(1)
    assert hits == []


@pytest.mark.parametrize("target", ['target="_blank"', 'target="otra"', 'target="_blank" rel="opener"'])
def test_clic_con_target_no_abre_ventana_ni_sale_a_la_red(tmp_path, servir, registro, target):
    """I1 (sonda popup.py de la revisión): la ventana nueva que abre el botón se cierra y su navegación se aborta;
    el segundo servidor en 127.0.0.1 no recibe ni una petición."""
    from trovefy.landing.qa import probar_clic

    base, hits = registro
    web = _web(tmp_path / "web")
    _cambiar(web, 'href="/checkout"', f'{target} href="{base}/checkout"')
    c = probar_clic(servir(web), f"{base}/checkout")
    time.sleep(1.5)
    assert hits == []
    assert c.url_pedida is None  # no navegó la página: la QA no lo da por bueno (y validar rechaza target)


_CSS_DESBORDE = ["", "html,body{overflow-x:hidden}", "html,body{overflow-x:clip}", "body{overflow-x:hidden}",
                 "html{overflow:hidden}"]


@pytest.mark.parametrize("css", _CSS_DESBORDE)
def test_desborde_oculto_se_detecta(tmp_path, servir, rapido, css):
    """I3 (sonda desborde.py de la revisión): con overflow oculto en html/body el scrollWidth no crece, pero la
    tabla de 900 px sigue saliendo de los 390 px: FALLA."""
    from trovefy.landing.qa import Clic, evaluar, medir
    from trovefy.landing.validar import Resultado

    tabla = '<table class="comparativa" style="width:900px;min-width:900px"><tr><td>a</td></tr></table>'
    web = _web(tmp_path / "web", tabla)
    (web / "assets" / "estilo.css").write_text((web / "assets" / "estilo.css").read_text("utf-8") + "\n" + css,
                                               encoding="utf-8")
    m = medir(servir(web), "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    assert m.desborde_selector == "table.comparativa", (css, m.ancho_scroll)
    r = evaluar(Resultado(True, (), ()), [m], Clic(None, "sin clic"), [], None, "", False)
    fila = next(f for f in r.filas if f[0] == "Desborde (movil)")
    assert fila[1] == "FALLA" and "table.comparativa" in fila[2]


def test_tabla_en_contenedor_con_scroll_no_es_desborde(tmp_path, servir, rapido):
    from trovefy.landing.qa import medir

    tabla = ('<div class="tabla" style="overflow-x:auto"><table class="comparativa" '
             'style="width:900px;min-width:900px"><tr><td>a</td></tr></table></div>')
    m = medir(servir(_web(tmp_path / "web", tabla)), "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    assert m.desborde_selector is None and m.ancho_scroll <= 390


def test_medir_bloquea_service_workers(tmp_path, servir_anotando, rapido):
    """I5: el contexto de la QA no registra service workers (nada de lo medido sale de una caché propia)."""
    from trovefy.landing.qa import medir

    web = _web(tmp_path / "web", "<script>navigator.serviceWorker && "
                                 "navigator.serviceWorker.register('/sw.js')</script>")
    (web / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    url, hits, _ = servir_anotando(web)
    m = medir(url, "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    assert m.motivo is None
    assert not any(h.endswith("/sw.js") for h in hits), hits


def test_medir_movil_como_un_movil(tmp_path, servir, rapido):
    """M1: 390 px con is_mobile, táctil y DPR 2."""
    from PIL import Image
    from trovefy.landing.qa import medir

    m = medir(servir(_web(tmp_path / "web")), "movil", tmp_path / "m.png", ("127.0.0.1",), red_4g=False)
    with Image.open(m.captura) as im:
        assert im.width == 780  # 390 px × DPR 2


def test_clic_aborta_beacons_posts_y_websockets(tmp_path, servir_anotando):
    """I5: tras la carga, nada que no sea un GET de navegación sale (beacon, fetch POST); los WebSocket tampoco."""
    from trovefy.landing.qa import probar_clic

    web = _web(tmp_path / "web")
    url, hits, puerto = servir_anotando(web)
    _cambiar(web, "</main>", "</main><script>"
             f"const ws = new WebSocket('ws://127.0.0.1:{puerto}/ws');"
             "document.addEventListener('click', () => {"
             "  navigator.sendBeacon('/beacon', 'x');"
             "  fetch('/f', {method: 'POST', body: 'x', keepalive: true}).catch(() => {});"
             f"  try {{ new WebSocket('ws://127.0.0.1:{puerto}/ws2'); }} catch (e) {{}}"
             "}, true);</script>")
    c = probar_clic(url, "/checkout")
    time.sleep(1)
    assert c.url_pedida is not None, c.motivo
    assert not any(h.startswith(("POST", "PUT")) for h in hits), hits
    assert not any("/ws" in h for h in hits), hits


def test_lcp_con_red_4g_es_mayor(tmp_path, servir, rapido):
    """T1: con 4G simulado el LCP sube al menos una latencia (la del documento)."""
    from trovefy.landing.constantes import LATENCIA_MS
    from trovefy.landing.qa import medir

    url = servir(_web(tmp_path / "web"))
    rapida = medir(url, "movil", tmp_path / "a.png", ("127.0.0.1",), red_4g=False)
    lenta = medir(url, "movil", tmp_path / "b.png", ("127.0.0.1",), red_4g=True)
    assert rapida.lcp_ms and lenta.lcp_ms
    assert statistics.median(lenta.lcp_ms) >= statistics.median(rapida.lcp_ms) + LATENCIA_MS


def test_ejecutar_qa_local_de_punta_a_punta(tmp_path, monkeypatch, rapido):
    """`ejecutar_qa` sirve la landing guardada del vault demo en 127.0.0.1 y escribe `QA.md`."""
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.qa import ejecutar_qa
    from trovefy.vault import frontmatter
    from unit.landing.conftest import P, cargar
    from unit.landing.test_validar import montar

    v = montar(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))  # T3: ni el vault ni el HOME reales (HOME en _entorno)
    r = ejecutar_qa(v, cargar(v))
    filas = {f[0]: f for f in r.filas}
    assert filas["Clic al checkout con UTM"][1] == "OK", r.filas
    assert filas["Peticiones externas (movil)"][1] == "OK"
    assert filas["Hitos (movil)"][1] in ("OK", "AVISO"), filas["Hitos (movil)"]
    assert filas["Idioma (nativo)"][1] == "NO MEDIDO"
    meta, _ = frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA.md")
    assert meta["ok"] is False and meta["movil_390"]["http"] == 200
