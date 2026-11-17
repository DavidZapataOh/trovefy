"""Impultienda falsa en 127.0.0.1 para la sonda y la publicación del plan 18 (Tareas 8 y 9).

`/panel` sirve `tests/fixtures/landing/impultienda-contenido.html` con lo guardado en el `<textarea>`;
«Guardar cambios» hace `POST /guardar`; `/tienda` sirve lo guardado como la tienda pública. Opciones para
simular las manías posibles de Impultienda: recortar a N caracteres, quitar `<script>`, envolver con cabecera y
pie propios, cambiar la pantalla (sin «HTML completo de la tienda») o rellenar el campo tarde (`fetch` a
`/contenido` + `setTimeout`).
"""

from __future__ import annotations

import html
import http.server
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "landing" / "impultienda-contenido.html"
FIRMA = ["Diseño de tienda", "HTML completo de la tienda", "Guardar cambios"]


@dataclass
class Estado:
    contenido: str = "<h1>Mi tienda</h1>\n<p>Contenido del usuario, con tildes y «comillas».</p>"
    recorte: int | None = None
    sin_script: bool = False
    marco: bool = False
    firma: bool = True
    formulario: bool = False  # «Guardar cambios» envía un <form> (POST + 303 a /panel): el guardado navega
    tarde: bool = False  # el <textarea> llega vacío y lo rellena un fetch lento + setTimeout (I3)
    posts: list[str] = field(default_factory=list)


# Con `tarde`: el panel llega con el campo vacío y lo rellena después, como un panel que carga por API.
_RELLENO_TARDE = """<script>
fetch("/contenido").then(function (r) { return r.text(); }).then(function (t) {
  setTimeout(function () { document.getElementById("html").value = t; }, 200);
});
</script>
</body>"""
ESPERA_CONTENIDO_S = 0.6  # lo que tarda /contenido en responder


# El mismo panel con un formulario de verdad: guardar es una navegación (POST /guardar → 303 → GET /panel).
_FORMULARIO = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Panel de prueba</title></head>
<body>
<h1>Diseño de tienda</h1>
<h2>Contenido</h2>
<form method="post" action="/guardar">
<label for="html">{{etiqueta}}</label>
<textarea id="html" name="html" rows="10" cols="80">{{contenido}}</textarea>
<button type="submit" id="guardar">Guardar cambios</button>
</form>
</body>
</html>
"""


def _manejador(estado: Estado):
    class Manejador(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def _responder(self, codigo: int, cuerpo: str = "", tipo: str = "text/html; charset=utf-8") -> None:
            datos = cuerpo.encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            ruta = self.path.split("?", 1)[0]
            if ruta == "/panel":
                etiqueta = "HTML completo de la tienda" if estado.firma else "Código de la portada"
                plantilla = _FORMULARIO if estado.formulario else FIXTURE.read_text(encoding="utf-8")
                pagina = plantilla.replace("{{etiqueta}}", etiqueta)
                if estado.tarde:
                    pagina = pagina.replace("{{contenido}}", "").replace("</body>", _RELLENO_TARDE, 1)
                self._responder(200, pagina.replace("{{contenido}}", html.escape(estado.contenido, quote=False)))
            elif ruta == "/contenido":
                time.sleep(ESPERA_CONTENIDO_S)
                self._responder(200, estado.contenido, "text/plain; charset=utf-8")
            elif ruta in ("/tienda", "/tienda/"):
                cuerpo = estado.contenido
                if estado.marco:
                    cuerpo = ("<header>Tienda de prueba · Inicio · Productos · Contacto · Envíos gratis</header>"
                              + cuerpo + "<footer>Hecho con una plataforma de tiendas · Términos</footer>")
                self._responder(200, cuerpo)
            else:
                self._responder(404, "no")

        def do_POST(self):
            if self.path != "/guardar":
                self._responder(404, "no")
                return
            largo = int(self.headers.get("Content-Length") or 0)
            texto = self.rfile.read(largo).decode("utf-8")
            if estado.formulario:  # application/x-www-form-urlencoded; el navegador manda los saltos como CRLF
                texto = parse_qs(texto, keep_blank_values=True).get("html", [""])[0].replace("\r\n", "\n")
            estado.posts.append(texto)
            if estado.sin_script:
                texto = re.sub(r"<script\b.*?</script>", "", texto, flags=re.DOTALL | re.IGNORECASE)
            if estado.recorte:
                texto = texto[: estado.recorte]
            estado.contenido = texto
            if estado.formulario:
                self.send_response(303)
                self.send_header("Location", "/panel")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._responder(204)

    return Manejador


@contextmanager
def impultienda_falsa(estado: Estado):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _manejador(estado))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def mapa_local(base: str, capturado: str | None = "2026-11-17") -> dict:
    """El mapa de `diseno_contenido` (mismos controles que el del repo) apuntando al panel falso.

    http:// solo aquí: es un mapa en memoria contra 127.0.0.1 (`cargar()` exige https)."""
    pantalla = {"url": base + "/panel", "firma": list(FIRMA),
                "controles": {"html": {"css": "textarea", "tipo": "area"},
                              "guardar": {"etiqueta": "Guardar cambios", "rol": "button", "tipo": "boton"}}}
    if capturado is not None:
        pantalla["capturado"] = capturado
    return {"capturado": None, "fuente": "panel de prueba propio", "hosts": ["127.0.0.1"],
            "pantallas": {"diseno_contenido": pantalla}}
