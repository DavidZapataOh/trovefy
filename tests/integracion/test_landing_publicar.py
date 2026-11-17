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
                                   dormir=lambda _s: None, ahora=AHORA).url
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
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
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


def test_publicar_con_el_campo_rellenado_tarde_respalda_y_restaura_lo_real(tmp_path):
    """I3: con el campo rellenado tarde (fetch + setTimeout), el respaldo es el contenido real y, tras un
    recorte, se restaura ese contenido (no un campo vacío)."""
    from integracion.impultienda_falsa import Estado
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.publicar import HtmlRecortado
    from unit.landing.conftest import P

    estado = Estado(tarde=True, recorte=50_000)
    original = estado.contenido
    with pytest.raises(HtmlRecortado, match="--hosting cloudflare"):
        _publicar(tmp_path, estado, engordar=True)
    respaldo = ruta_landing(tmp_path / "v", P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    assert respaldo.read_text(encoding="utf-8") == original
    assert estado.contenido == original and estado.posts[-1] == original


def test_publicar_firma_ausente_no_toca(tmp_path):
    from integracion.impultienda_falsa import Estado
    from trovefy.tienda.conductor import FirmaNoCasa

    estado = Estado(firma=False)
    with pytest.raises(FirmaNoCasa):
        _publicar(tmp_path, estado)
    assert estado.posts == []


def test_publicar_con_guardado_que_navega(tmp_path):
    """T: el guardado es un formulario (POST + 303): se relee igual tras la navegación."""
    from integracion.impultienda_falsa import Estado
    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.hosting import empaquetar_en_linea
    from unit.landing.conftest import P

    estado = Estado(formulario=True)
    v, _ = _publicar(tmp_path, estado)
    assert estado.contenido == empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    assert len(estado.posts) == 1


# --- T: el `_abrir_seguro` real contra 127.0.0.1 (https con un certificado propio) ------------------


@pytest.fixture
def https_local(tmp_path):
    """Servidor https en 127.0.0.1 con un certificado autofirmado: `/` sirve la landing, `/redirige` → 302."""
    import http.server
    import shutil
    import ssl
    import subprocess
    import threading

    if shutil.which("openssl") is None:
        pytest.skip("sin openssl para el certificado de prueba")
    cert, clave = tmp_path / "cert.pem", tmp_path / "clave.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(clave), "-out", str(cert)],
                   check=True, capture_output=True, timeout=60)
    cuerpo = {"html": b""}

    class Manejador(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):
            if self.path == "/redirige":
                self.send_response(302)
                self.send_header("Location", "https://otro.test/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo["html"])))
            self.end_headers()
            self.wfile.write(cuerpo["html"])

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    servidor = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    servidor.load_cert_chain(cert, clave)
    srv.socket = servidor.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cliente = ssl.create_default_context(cafile=str(cert))
    try:
        yield f"https://127.0.0.1:{srv.server_address[1]}", cliente, cuerpo
    finally:
        srv.shutdown()


def test_abrir_seguro_real_no_sigue_redirecciones(tmp_path, https_local):
    import functools
    import urllib.error

    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.publicar import _abrir_seguro, verificar_cloudflare
    from unit.landing.conftest import P
    from unit.landing.test_hosting import montar

    base, contexto, cuerpo = https_local
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    cuerpo["html"] = (raiz / "index.html").read_bytes()
    abrir = functools.partial(_abrir_seguro, contexto=contexto)
    with abrir(base + "/", timeout=5) as r:
        assert r.read() == cuerpo["html"]
    with pytest.raises(urllib.error.HTTPError) as e:
        abrir(base + "/redirige", timeout=5)
    assert e.value.code == 302  # no la sigue: se queda en el 302
    assert verificar_cloudflare(base + "/", raiz, abrir=abrir) is True
    assert verificar_cloudflare(base + "/redirige", raiz, abrir=abrir) is False
    with pytest.raises(ValueError, match="https"):
        _abrir_seguro(base.replace("https", "http") + "/", contexto=contexto)
    assert verificar_cloudflare(base + "/", raiz) is False  # sin el certificado de prueba: el sistema no lo cree


# --- Plan 18b: pegado manual (la QA publicada prueba que la tienda guardó el script) -----------------


def _pagina_tienda(v, sin_script: bool = False) -> bytes:
    """La tienda con el paquete pegado dentro, como la serviría Impultienda (con o sin el `<script>`)."""
    import re

    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.hosting import empaquetar_en_linea
    from unit.landing.conftest import P

    paquete = empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    if sin_script:
        paquete = re.sub(r"<script>.*?</script>", "", paquete, flags=re.DOTALL)
        assert "<script" not in paquete
    return (f"<!doctype html><html lang=bg><head><meta charset=utf-8><title>Tienda</title></head>"
            f"<body><header>Tienda demo</header>{paquete}</body></html>").encode()


@pytest.fixture
def tienda_http():
    """La «tienda» en http://127.0.0.1 (el clic de la QA no sale de ahí: el checkout se intercepta con un 204)."""
    import http.server
    import threading

    cuerpo = {"html": b""}

    class Manejador(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo["html"])))
            self.end_headers()
            self.wfile.write(cuerpo["html"])

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/", cuerpo
    finally:
        srv.shutdown()


@pytest.mark.parametrize("sin_script", [False, True])
def test_pegado_manual_sin_utm_js_la_qa_publicada_sale_en_rojo(tmp_path, tienda_http, sin_script):
    """Sin evidencia de la sonda, el clic de la QA publicada es lo que prueba que la tienda guardó `utm.js`: si
    Impultienda lo quitó, el botón va al checkout sin los UTM y la QA sale en rojo."""
    from trovefy.landing.qa import UTM_PUBLICADA, evaluar, probar_clic
    from trovefy.landing.validar import Resultado
    from unit.landing.test_hosting import montar

    v = montar(tmp_path)
    url, cuerpo = tienda_http
    cuerpo["html"] = _pagina_tienda(v, sin_script)
    c = probar_clic(url, "/checkout", utm=UTM_PUBLICADA)
    assert c.url_pedida is not None, c.motivo
    r = evaluar(Resultado(True, (), ()), [], c, [], ("ok", "x"), "x", publicada=True)
    clic = next(f for f in r.filas if f[0] == "Clic al checkout con UTM")
    if sin_script:
        assert c.intactos is False and clic[1] == "FALLA" and r.ok is False
    else:
        assert c.intactos is True and clic[1] == "OK"


def test_pegado_manual_verifica_la_version_servida_por_https(tmp_path, https_local):
    """La verificación del pegado manual con el `_abrir_seguro` real: la tienda sirve el paquete con la versión
    actual (sí) o una anterior (no)."""
    import functools

    from trovefy.landing.entrada import ruta_landing
    from trovefy.landing.plantilla import leer_landing_yaml
    from trovefy.landing.publicar import _abrir_seguro, verificar_cloudflare
    from unit.landing.conftest import P
    from unit.landing.test_hosting import montar

    base, contexto, cuerpo = https_local
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    abrir = functools.partial(_abrir_seguro, contexto=contexto)
    cuerpo["html"] = _pagina_tienda(v)
    assert verificar_cloudflare(base + "/", raiz, abrir=abrir) is True
    version = leer_landing_yaml(v, P, "ZZ")["version"]
    cuerpo["html"] = _pagina_tienda(v).replace(version.encode(), b"0123456789ab")
    assert verificar_cloudflare(base + "/", raiz, abrir=abrir) is False
