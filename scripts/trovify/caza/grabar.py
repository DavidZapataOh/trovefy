"""Herramienta de desarrollo: graba *fixtures* reales de la Biblioteca pública de anuncios.

Abre la URL en un Chromium sin interfaz con un contexto EFÍMERO (sin perfil, sin sesión, sin
cookies previas), guarda la URL final, el HTML final y las respuestas de datos (``/api/graphql/``)
y nada más: ni cabeceras ni cookies. Antes de escribir, redacta los tokens de sesión y
anti-CSRF y sustituye las URLs de medios por ``<media>``; si después de redactar el texto aún
tiene algo con forma de secreto, no escribe nada.

Idea tomada (reescrita, no copiada) de un repo de referencia y de
un repo de referencia (MIT; ver avisos privados): escuchar las
respuestas de ``/api/graphql/`` que traen ``ad_archive_id`` y leer además los bloques
``<script type="application/json">`` del HTML, donde llega la primera página de resultados.

Uso::

    uv run python -m trovify.caza.grabar URL SALIDA.json [--crudo CRUDO.json]
    uv run python -m trovify.caza.grabar --desde-crudo CRUDO.json SALIDA.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from trovify.caza.captura import es_respuesta_de_datos, escuchar_respuestas  # noqa: F401 (reexporta)
from trovify.secretos import buscar_secreto
from trovify.vault.escritura import escribir_atomico

REDACTADO = "<redactado>"
MEDIA = "<media>"
MAX_BYTES = 1_000_000
MIN_ANUNCIOS = 20

# Nombres de campos de sesión / anti-CSRF; además, cualquier campo cuyo nombre contenga «token».
# Por prudencia, también el id de sesión de la página y el cursor de paginación (opacos y ligados a la sesión).
_NOMBRES = (
    r"lsd|fb_dtsg|jazoest|__spin_[rtb]|spin_[rtb]|__hsi|hsi|__dyn|__csr|__rev|_?_?js_datr|datr"
    r"|session_?id|haste_session|end_cursor"
)
_CLAVE = rf"(?:{_NOMBRES}|[A-Za-z0-9_]*token[A-Za-z0-9_]*)"

# "clave": "valor" | número   (JSON normal)
_JSON_PLANO = re.compile(
    rf'(?i)("{_CLAVE}"\s*:\s*)(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?)'
)
# \"clave\": \"valor\" | número   (JSON escapado dentro de una cadena)
_JSON_ESCAPADO = re.compile(
    rf'(?i)(\\"{_CLAVE}\\"\s*:\s*)(?:\\"(?:[^"\\]|\\[^"])*?\\"|-?\d+(?:\.\d+)?)'
)
# ["_js_datr","valor",...]
_ARRAY_DATR = re.compile(r'(?i)("_?_?js_datr"|"datr")(\s*,\s*)"(?:[^"\\]|\\.)*"')
# ?lsd=valor&...  (también &amp; y &)
_PARAM_URL = re.compile(rf"(?i)((?:[?&;]|\\u0026)(?:{_NOMBRES})=)[^&\"'\s<>\\]*")
# <input name="lsd" value="...">
_INPUT = re.compile(rf'(?i)(name="(?:{_NOMBRES})"[^>]*?value=")[^"]*(")')
# Cualquier URL (también con barras escapadas \/ o \u00XX); se decide por el host.
_URL = re.compile(r"https?:(?:\\/|/){2}(?:\\/|\\u[0-9a-fA-F]{4}|[^\"'\s<>\\])*")
_HOST = re.compile(r"https?:(?:\\/|/){2}([^/\\:?#]*)")

_ANUNCIO = re.compile(r'\\?"ad_archive_id\\?"\s*:\s*\\?"?(\d+)')


class SecretoEnCaptura(Exception):
    """La captura aún contiene algo con forma de secreto después de redactar: no se guarda."""


class BloqueoBiblioteca(Exception):
    """Meta mostró captcha, login o comprobación de seguridad."""

    def __init__(self, mensaje: str, captura: dict | None = None) -> None:
        super().__init__(mensaje)
        self.captura = captura  # ya redactada; solo para diagnóstico con --crudo


def _es_media(url: str) -> bool:
    m = _HOST.match(url)
    host = (m.group(1) if m else "").lower()
    return host.startswith("scontent") or "fbcdn" in host


def redactar(texto: str) -> str:
    """Quita tokens de sesión / anti-CSRF y URLs de medios. Idempotente."""
    texto = _JSON_PLANO.sub(lambda m: m.group(1) + f'"{REDACTADO}"', texto)
    texto = _JSON_ESCAPADO.sub(lambda m: m.group(1) + f'\\"{REDACTADO}\\"', texto)
    texto = _ARRAY_DATR.sub(lambda m: m.group(1) + m.group(2) + f'"{REDACTADO}"', texto)
    texto = _PARAM_URL.sub(lambda m: m.group(1) + REDACTADO, texto)
    texto = _INPUT.sub(lambda m: m.group(1) + REDACTADO + m.group(2), texto)
    return _URL.sub(lambda m: MEDIA if _es_media(m.group(0)) else m.group(0), texto)


def contar_anuncios(texto: str) -> int:
    """Número de ``ad_archive_id`` distintos en el texto."""
    return len(set(_ANUNCIO.findall(texto)))


# --- recorte del HTML ---------------------------------------------------------------------

# Total («~230 resultados», «>50.000 resultados», «~1,700 results») o aviso de «sin resultados».
_MARCADOR = re.compile(
    r"(?i)^\s*(?:~|>|aproximadamente\s+|about\s+)?\s*[\d.,]+\s+(?:results?|resultados?)\s*$"
    r"|\bno ads\b|ningún anuncio|no hay anuncios|no se encontraron"
)
_SCRIPT_JSON = re.compile(r'<script\b[^>]*type="application/json"[^>]*>.*?</script>', re.DOTALL | re.IGNORECASE)
_VACIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Marcadores(HTMLParser):
    """Localiza el elemento más interno cuyo texto propio es el total o «sin resultados»."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self._lineas = [0]
        for linea in html.splitlines(keepends=True):
            self._lineas.append(self._lineas[-1] + len(linea))
        self._pila: list[tuple[str, int, bool]] = []
        self.trozos: list[tuple[int, int]] = []

    def _offset(self) -> int:
        linea, col = self.getpos()
        return self._lineas[linea - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag not in _VACIOS:
            self._pila.append((tag, self._offset(), False))

    def handle_endtag(self, tag):
        for i in range(len(self._pila) - 1, -1, -1):
            if self._pila[i][0] == tag:
                _, ini, marcado = self._pila[i]
                del self._pila[i:]
                if marcado:
                    texto_fin = self.rawdata.find(">", self._offset())
                    self.trozos.append((ini, texto_fin + 1))
                return

    def handle_data(self, data):
        if not self._pila or self._pila[-1][0] in ("script", "style"):
            return
        if len(data.strip()) <= 200 and _MARCADOR.search(data):
            tag, ini, _ = self._pila[-1]
            self._pila[-1] = (tag, ini, True)


def recortar_html(html: str) -> str:
    """Deja solo los ``<script type="application/json">`` con anuncios y los elementos con el
    total de resultados o el aviso de «sin resultados» (en ese orden)."""
    scripts = [s for s in _SCRIPT_JSON.findall(html) if "ad_archive_id" in s or "search_results_connection" in s]
    p = _Marcadores(html)
    p.feed(html)
    p.close()
    marcas = [html[a:b] for a, b in p.trozos]
    return "<html><body>\n" + "\n".join(marcas + scripts) + "\n</body></html>"


# --- recorte de la captura ----------------------------------------------------------------


def _tamano(datos: dict) -> int:
    return len(json.dumps(datos, ensure_ascii=False, indent=1).encode("utf-8"))


def recortar(captura: dict, max_bytes: int = MAX_BYTES, min_anuncios: int = MIN_ANUNCIOS) -> dict:
    """Recorta la captura a ``max_bytes`` conservando al menos ``min_anuncios`` (o todos los que haya).

    Conserva solo respuestas con anuncios; si ninguna los trae, las de la búsqueda
    (``ad_library_main``). Lanza ValueError si no cabe sin bajar del mínimo.
    """
    resp = [r for r in captura["respuestas"] if "ad_archive_id" in r["cuerpo"]]
    if not resp:
        resp = [r for r in captura["respuestas"] if "ad_library_main" in r["cuerpo"]]
    datos = {**captura, "html_final": recortar_html(captura["html_final"]), "respuestas": resp}
    total = contar_anuncios("".join(r["cuerpo"] for r in resp))
    objetivo = min(min_anuncios, total)
    while _tamano(datos) > max_bytes and len(datos["respuestas"]) > 1:
        menos = datos["respuestas"][:-1]
        if contar_anuncios("".join(r["cuerpo"] for r in menos)) < objetivo:
            break
        datos["respuestas"] = menos
    if _tamano(datos) > max_bytes:
        raise ValueError(f"la captura no cabe en {max_bytes} bytes conservando {objetivo} anuncios")
    return datos


# --- composición y escritura segura -------------------------------------------------------


def componer(url: str, url_final: str, html: str, respuestas: list[dict], capturado_en: str | None = None) -> dict:
    """Arma el dict de la fixture, ya redactado. Solo url, estado y cuerpo de cada respuesta."""
    return {
        "url": redactar(url),
        "url_final": redactar(url_final),
        "capturado_en": capturado_en or datetime.now(UTC).isoformat(timespec="seconds"),
        "html_final": redactar(html),
        "respuestas": [
            {"url": redactar(r["url"]), "estado": int(r["estado"]), "cuerpo": redactar(r["cuerpo"])} for r in respuestas
        ],
    }


def guardar(datos: dict, salida: Path) -> None:
    """Escribe la fixture de forma atómica si el texto completo pasa la revisión de secretos."""
    texto = json.dumps(datos, ensure_ascii=False, indent=1) + "\n"
    patron = buscar_secreto(texto)
    if patron:
        raise SecretoEnCaptura(f"la captura aún contiene un posible secreto ({patron}); no se guarda")
    escribir_atomico(Path(salida), texto)


# --- grabación en vivo (no se ejecuta en la suite por defecto) -----------------------------


def _capturar(url: str, max_respuestas: int, desplazamientos: int = 4) -> dict:
    from playwright.sync_api import sync_playwright

    from trovify.caza.biblioteca import detectar_bloqueo
    from trovify.navegador import _un_navegador_a_la_vez

    with _un_navegador_a_la_vez(), sync_playwright() as p:
        navegador = p.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            ctx = navegador.new_context()  # efímero: sin user_data_dir ni storage_state
            pagina = ctx.new_page()
            respuestas = escuchar_respuestas(pagina, max_respuestas)
            pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
            pagina.wait_for_timeout(6_000)
            html = pagina.content()
            bloqueo = detectar_bloqueo(pagina.url, html)
            if bloqueo:
                raise BloqueoBiblioteca(f"Meta mostró {bloqueo} en {pagina.url}; no se fuerza",
                                        componer(url, pagina.url, html, respuestas))
            for _ in range(desplazamientos):
                if len(respuestas) >= max_respuestas:
                    break
                pagina.mouse.wheel(0, 20_000)
                pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                pagina.wait_for_timeout(2_500)
            html = pagina.content()
            bloqueo = detectar_bloqueo(pagina.url, html)
            if bloqueo:
                raise BloqueoBiblioteca(f"Meta mostró {bloqueo} en {pagina.url}; no se fuerza",
                                        componer(url, pagina.url, html, respuestas))
            return componer(url, pagina.url, html, respuestas)
        finally:
            navegador.close()


def grabar(url: str, salida: Path, max_respuestas: int = 20, crudo: Path | None = None) -> None:
    """Graba la URL (contexto efímero, sin sesión) y guarda la fixture redactada y recortada."""
    try:
        captura = _capturar(url, max_respuestas)
    except BloqueoBiblioteca as exc:
        if crudo is not None and exc.captura is not None:
            guardar(exc.captura, Path(crudo))  # diagnóstico; nunca se guarda como fixture
        raise
    if crudo is not None:
        guardar(captura, Path(crudo))
    guardar(recortar(captura), Path(salida))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trovify.caza.grabar", description="Graba una fixture de la Biblioteca.")
    ap.add_argument("url_o_crudo", help="URL de la Biblioteca (o la captura cruda con --desde-crudo)")
    ap.add_argument("salida", type=Path)
    ap.add_argument("--max-respuestas", type=int, default=20)
    ap.add_argument("--crudo", type=Path, help="guarda también la captura redactada sin recortar")
    ap.add_argument("--desde-crudo", action="store_true", help="recorta una captura cruda ya guardada, sin red")
    a = ap.parse_args(argv)
    try:
        if a.desde_crudo:
            datos = json.loads(Path(a.url_o_crudo).read_text(encoding="utf-8"))
            guardar(recortar(componer(datos["url"], datos["url_final"], datos["html_final"],
                                      datos["respuestas"], datos["capturado_en"])), a.salida)
        else:
            grabar(a.url_o_crudo, a.salida, a.max_respuestas, a.crudo)
    except (BloqueoBiblioteca, SecretoEnCaptura, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
