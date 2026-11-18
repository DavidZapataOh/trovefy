"""Plan 19, Tarea 12: el checkout público leído en Chromium real (perfil vacío) contra una página en 127.0.0.1.

Comprueba lo que los unitarios no pueden: que lo oculto por CSS o por JavaScript se marca y no cuenta, y que la
red del comprador no deja salir nada que no sea un GET (visitas, «preparar pago»).
"""
from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.integracion

PAGINA = """<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">
<style>#field-last-name{display:none}.invisible{visibility:hidden}</style></head><body>
<img src="/foto.png" alt="Спокойно тяло">
<h2>Спокойно тяло</h2><p>13,90 €</p>
<p>Получаваш ръководството веднага след плащането, на имейла си. Без абонамент и без скрити такси.</p>
<input type="email" name="email" autocomplete="email">
<input type="text" name="given-name" autocomplete="given-name">
<div id="field-last-name"><input type="text" name="family-name" autocomplete="family-name"></div>
<div id="dir"><input type="text" name="address-line1" autocomplete="address-line1"></div>
<input type="tel" name="phone" autocomplete="tel">
<p class="invisible">Остават само 3 места</p>
<div id="order-bumps-mobile"></div>
<input type="hidden" id="ebook-currency" value="EUR"><input type="hidden" id="ebook-main-price" value="13.9">
<input type="hidden" id="buyer-country" value="ZZ">
<input type="hidden" id="i18n-widget-stock" value="Остават само {count} места">
<script>
  document.getElementById('dir').style.display = 'none';
  fetch('/rest/v1/visits', {method: 'POST', body: '{}'}).catch(() => {});
  fetch('/functions/v1/impulpay-prepare').catch(() => {});
  navigator.sendBeacon && navigator.sendBeacon('/beacon', 'x');
</script>
</body></html>"""
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

    class _Tienda(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _responder(self):
            pedidas.append((self.command, self.path))
            cuerpo, tipo = (PNG, "image/png") if self.path.startswith("/foto") else (PAGINA.encode(), "text/html")
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


def test_checkout_local_solo_lo_visible_y_sin_escrituras(tienda):
    from trovefy.checkout.fuera import abrir_chromium, analizar

    base, pedidas = tienda
    url = base + "/checkout"
    p = analizar(url, abrir_chromium(url))
    assert p.campos_obligatorios == ("email", "nombre", "telefono")
    assert (p.moneda_vista, str(p.precio_visto), p.pais_visto) == ("EUR", "13.90", "ZZ")
    assert p.escasez == ()
    assert p.foto_arriba and not p.bump
    assert [m for m, _ in pedidas if m != "GET"] == []
    assert not any(ruta.startswith(("/functions/", "/beacon", "/rest/")) for _, ruta in pedidas)
