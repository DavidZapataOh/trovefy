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
    confirmada = {"capturado": "2026-11-20"}  # R-1: cada pantalla con controles lleva su propio `capturado`
    return {
        "capturado": "2026-11-20",
        "fuente": "páginas de prueba propias",
        "hosts": ["127.0.0.1"],
        "pantallas": {
            "producto": {"url": base + "/producto.html", "firma": ["Editar producto"], "controles": controles, **confirmada},
            "cambiada": {"url": base + "/producto-cambiada.html", "firma": ["Editar producto"], "controles": controles,
                         **confirmada},
            "redirige": {"url": base + "/guardar-y-redirige.html", "firma": ["Editar producto"], **confirmada,
                         "controles": {"precio": {"etiqueta": "Precio", "tipo": "precio"},
                                       "guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"}}},
            "login": {"url": base + "/login.html", "firma": ["Iniciar sesión"]},
            # segunda revisión
            "spa": {"url": base + "/spa-cambia.html", "firma": ["Editar producto"], **confirmada,
                    "controles": {"precio": {"etiqueta": "Precio", "tipo": "precio"},
                                  "guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"}}},
            "ventana": {"url": base + "/ventana.html", "firma": ["Editar producto"], **confirmada,
                        "controles": {"guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"}}},
            "configuraciones": {"url": base + "/configuraciones.html", "firma": ["Pasarelas de pago"]},  # sin marca
            "con_marco": {"url": base + "/con-marco.html", "firma": ["Editar producto"]},
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
        cajas = {sel: page.locator(sel).bounding_box() for sel in ("#token", "#precio", "h1")}
    _cubierta(captura, cajas["#token"])  # el secreto, tapado
    _cubierta(captura, cajas["#precio"])  # y, por defecto, cualquier campo
    assert not _es_mascara(captura, cajas["h1"])  # el resto de la pantalla se ve


MAGENTA = (255, 0, 255)  # color por defecto de las máscaras de Playwright


def _pixeles(captura: Path, caja: dict, margen: int = 2) -> list[tuple[int, int, int]]:
    from PIL import Image

    with Image.open(captura) as img:
        rgb = img.convert("RGB")
        x0, y0 = int(caja["x"]) + margen, int(caja["y"]) + margen
        x1, y1 = int(caja["x"] + caja["width"]) - margen, int(caja["y"] + caja["height"]) - margen
        assert x1 > x0 and y1 > y0
        return [rgb.getpixel((x, y)) for x in range(x0, x1) for y in range(y0, y1)]


def _cubierta(captura: Path, caja: dict) -> None:
    pixeles = _pixeles(captura, caja)
    assert pixeles and all(px == MAGENTA for px in pixeles), "la región del campo no está tapada en la captura"


def _es_mascara(captura: Path, caja: dict) -> bool:
    return all(px == MAGENTA for px in _pixeles(captura, caja))


def test_guardar_que_redirige_no_escribe_en_la_otra_pantalla(servidor_local):
    # H-1 (repro de la revisión con Chromium real): «Guardar» desactiva el campo y lleva a otra pantalla con un
    # campo de la misma etiqueta. Antes, `poner` comprobaba en A y `fill` reintentaba hasta escribir en B.
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import Parada

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("redirige")
        c.pulsar("redirige", "guardar")
        with pytest.raises(Parada):
            c.poner("redirige", "precio", "99.00")
        page.wait_for_url("**/otra-pantalla.html", timeout=10_000)
        page.wait_for_load_state("load")
        assert page.inner_text("h1") == "Otra pantalla"
        assert page.locator("#precio").input_value() == "B-original"
        with pytest.raises(Parada):  # y nada más hasta volver a ir()
            c.poner("redirige", "precio", "99.00")
        assert page.locator("#precio").input_value() == "B-original"


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


# --- Segunda revisión: casos de probe.py / probe2.py con Chromium real -------------------------------------------


def test_spa_que_cambia_la_pantalla_bajo_el_campo_para(servidor_local):
    # L-a: el campo (el mismo nodo) acaba en una pantalla «Cuenta para cobrar» con URL inocente (/cuenta)
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import FirmaNoCasa, Parada

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("spa")
        with pytest.raises(FirmaNoCasa, match="sí se hizo"):
            c.poner("spa", "precio", "99")
        assert page.inner_text("h1") == "Cuenta para cobrar"
        with pytest.raises(Parada):  # y nada más hasta volver a ir()
            c.poner("spa", "precio", "77")
        assert page.locator("#precio").input_value() == "99"
        c.ir("spa")
        with pytest.raises(FirmaNoCasa, match="sí se hizo"):
            c.pulsar("spa", "guardar")


def test_archivo_en_un_campo_sustituido_es_incierto(servidor_local, tmp_path, monkeypatch):
    # L-b (probe.py, caso 3): la página sustituye el campo de archivo justo después de fijarlo
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import AccionIncierta, Conductor

    original = Conductor._recomprobar

    def y_sustituye(self, pantalla, zona):
        original(self, pantalla, zona)
        self.page.evaluate("""() => { const o = document.getElementById('entrega'); const n = document.createElement('input');
            n.type = 'file'; n.id = 'entrega2'; n.setAttribute('aria-label', 'Entregable'); o.replaceWith(n); }""")

    monkeypatch.setattr(Conductor, "_recomprobar", y_sustituye)
    pdf = tmp_path / "e.pdf"
    pdf.write_bytes(b"%PDF-1.4 prueba")
    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("producto")
        with pytest.raises(AccionIncierta, match="archivo"):
            c.poner("producto", "entrega", pdf)
        assert page.evaluate("document.getElementById('entrega2').files.length") == 0


def test_pulsar_que_abre_una_ventana_la_cierra_y_para(servidor_local):
    # popups (probe.py, caso 9): la ventana nueva se cierra y el conductor para
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import Parada

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("ventana")
        with pytest.raises(Parada, match="se abrió otra ventana; la cerré y paro"):
            c.pulsar("ventana", "guardar")
        page.wait_for_timeout(500)
        assert [p.url for p in page.context.pages] == [page.url]
        with pytest.raises(Parada):
            c.pulsar("ventana", "guardar")


def test_no_captura_una_pantalla_de_pagos_sin_marca(servidor_local, tmp_path):
    # M-a (probe2.py): «Pasarelas de pago» sin `prohibida: true` ni controles; el token está en texto plano
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import ZonaProhibida

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("configuraciones")
        with pytest.raises(ZonaProhibida):
            c.capturar(tmp_path / "pagos.png")
    assert list(tmp_path.glob("*.png")) == []


def test_no_captura_una_pagina_con_marcos(servidor_local, tmp_path):
    # M-b (probe2.py): el token está dentro de un iframe, donde las máscaras no llegan
    from trovefy.navegador import sesion
    from trovefy.tienda.conductor import Parada

    with sesion("prueba", visible=False) as page:
        c = _conductor(page, servidor_local)
        c.ir("con_marco")
        page.wait_for_function("document.querySelector('iframe').contentDocument?.readyState === 'complete'")
        with pytest.raises(Parada, match="marcos"):
            c.capturar(tmp_path / "marco.png")
    assert list(tmp_path.glob("*.png")) == []
