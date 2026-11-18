"""Plan 19, Tarea 13: el recorrido de comprador en Chromium real a 390 px, contra una tienda falsa en 127.0.0.1.

Landing con `utm.js` de verdad → botón de compra → checkout que oculta campos y manda una «visita» por POST →
enlace demo de la oferta post-compra. Comprueba que el recorrido llega entero, que nada que no sea GET sale del
navegador y que no se pulsa «pagar».
"""
from __future__ import annotations

import dataclasses
import http.server
import os
import threading
from pathlib import Path

import pytest
from unit.embudo.ejemplos_embudo import PAIS, P, vault_embudo

pytestmark = pytest.mark.integracion

RAIZ = Path(__file__).resolve().parents[2]
FIX = RAIZ / "tests" / "fixtures" / "checkout"
UTM_JS = RAIZ / "templates" / "landing" / "utm.js"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(autouse=True)
def _entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # candado del navegador fuera del HOME real


@pytest.fixture
def tienda():
    pedidas: list[tuple[str, str]] = []
    rutas = {"/": ("landing.html", "text/html"), "/checkout": ("checkout.html", "text/html"),
             "/post-purchase/demo": ("upsell.html", "text/html")}

    class _Tienda(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _responder(self):
            pedidas.append((self.command, self.path))
            ruta = self.path.split("?", 1)[0]
            if ruta == "/assets/utm.js":
                cuerpo, tipo = UTM_JS.read_bytes(), "application/javascript"
            elif ruta == "/foto.png":
                cuerpo, tipo = PNG, "image/png"
            elif ruta in rutas:
                nombre, tipo = rutas[ruta]
                cuerpo = (FIX / nombre).read_bytes()
            else:
                cuerpo, tipo = b"no", "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        do_GET = _responder
        do_POST = _responder

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Tienda)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", pedidas
    srv.shutdown()


def test_demo_local_390px(tienda, tmp_path, monkeypatch):
    from trovefy.checkout import demo, fuera
    from trovefy.embudo.contexto import cargar_contexto, ruta_pais

    base, pedidas = tienda
    monkeypatch.setattr(fuera, "_esperar", lambda host: None)
    v = vault_embudo(tmp_path)
    ctx = dataclasses.replace(cargar_contexto(v, P, PAIS), tienda=base, landing_url=base + "/",
                              checkout_url=base + "/checkout")
    pasos = demo.ejecutar_demo(ctx, ruta_pais(ctx) / "demo", base + "/post-purchase/demo?t=demo-local")
    malos = [(p.clave, p.detalle) for p in pasos if p.estado != "ok"]
    assert malos == []
    assert [p.clave for p in pasos] == [*demo.PASOS_FIJOS, "upsell_u1"]
    assert (ruta_pais(ctx) / "demo" / "demo-checkout.png").stat().st_size > 0
    assert [m for m, _ in pedidas if m != "GET"] == []
    assert not any(r.startswith(("/functions/", "/rest/")) for _, r in pedidas)
    assert not any("fbclid" in r for _, r in pedidas)
    checkout = [r for _, r in pedidas if r.startswith("/checkout")]
    assert checkout and "utm_source=fb" in checkout[0]
