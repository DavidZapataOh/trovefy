"""Firecrawl como vía principal para pedir la página de la Biblioteca [D-11b].

Firecrawl entrega el HTML sin procesar y lo lee el mismo *parser* que usa Playwright. La clave
vive solo en ``~/.config/trovefy/claude.env`` (``FIRECRAWL_API_KEY``); nunca se imprime, se guarda
ni aparece en un mensaje de error.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

from trovefy.caza.cliente import ErrorDeRed, PaginaCapturada
from trovefy.secretos import RUTA_CLAUDE_ENV, EnvNoSeguro, PermisosInseguros, leer_env

URL_API = "https://api.firecrawl.dev/v2/scrape"
_TIMEOUT_S = 90
_VARIABLE = "FIRECRAWL_API_KEY"

Http = Callable[[str, dict, dict], "tuple[int, str]"]


class FirecrawlNoDisponible(RuntimeError):
    """La clave no vale o no hay créditos: el resto de la sesión usa Playwright."""


class FirecrawlRechazo(RuntimeError):
    """Firecrawl rechazó esta petición (4xx inesperado, ``success: false``): esa búsqueda acaba en
    ``error``; no se reintenta ni se cambia de vía."""


def clave_firecrawl(ruta: Path = RUTA_CLAUDE_ENV) -> str | None:
    """``FIRECRAWL_API_KEY`` de ``claude.env``, o None si falta el archivo, la variable o los permisos."""
    try:
        valor = leer_env(Path(ruta)).get(_VARIABLE, "").strip()
    except (OSError, PermisosInseguros, EnvNoSeguro, UnicodeDecodeError):
        return None
    return valor or None


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirección no permitida", headers, fp)


def _http_real(url: str, cuerpo: dict, cabeceras: dict) -> tuple[int, str]:
    if not url.startswith("https://"):
        raise ErrorDeRed("Firecrawl solo se llama por https")
    peticion = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode("utf-8"), headers=cabeceras, method="POST"
    )
    try:
        with urllib.request.build_opener(_SinRedireccion).open(peticion, timeout=_TIMEOUT_S) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise ErrorDeRed(f"no se pudo llamar a Firecrawl ({type(exc).__name__})") from None


class _Encabezados(HTMLParser):
    _VACIOS = frozenset({"br", "img", "hr", "input", "meta", "link", "wbr", "source", "area", "col"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.textos: list[str] = []
        self._pila: list[str] = []  # etiquetas abiertas dentro de un encabezado
        self._actual: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self._pila:
            if tag not in self._VACIOS:
                self._pila.append(tag)
        elif ("role", "heading") in attrs and tag not in self._VACIOS:
            self._pila = [tag]
            self._actual = []

    def handle_endtag(self, tag):
        if self._pila and tag == self._pila[-1]:
            self._pila.pop()
            if not self._pila:
                texto = " ".join("".join(self._actual).split())
                if texto:
                    self.textos.append(texto)

    def handle_data(self, data):
        if self._pila:
            self._actual.append(data)


def _texto_de_encabezados(html: str) -> str:
    p = _Encabezados()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001, S110 (HTML roto: sin encabezados, no es un fallo)
        pass
    return "\n".join(p.textos)


class NavegadorFirecrawl:
    """Pide la página por Firecrawl (``rawHtml``). Cumple ``Navegador``.

    Solo devuelve la primera página: ``max_anuncios`` (el «desplazar») se ignora; para lecturas
    completas se usa Playwright. ``creditos`` guarda ``metadata.creditsUsed`` de la última llamada.
    """

    def __init__(self, api_key: str, http: Http | None = None):
        self._api_key = api_key
        self._http = http or _http_real
        self.creditos: int | None = None
        self.proxy: str | None = None

    def __repr__(self) -> str:
        return "NavegadorFirecrawl()"

    def abrir(self, url: str, max_anuncios: int) -> PaginaCapturada:
        self.creditos = None
        self.proxy = None
        if not self._api_key.isascii() or not self._api_key.isprintable() or any(c.isspace() for c in self._api_key):
            raise FirecrawlNoDisponible("la clave de Firecrawl tiene caracteres raros; vuelve a pegarla")
        cuerpo = {"url": url, "formats": ["rawHtml"], "proxy": "auto", "maxAge": 0,
                  "waitFor": 3000, "onlyMainContent": False}
        cabeceras = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            codigo, texto = self._http(URL_API, cuerpo, cabeceras)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise ErrorDeRed(f"no se pudo llamar a Firecrawl ({type(exc).__name__})") from None
        if codigo in (401, 403):
            raise FirecrawlNoDisponible("la clave de Firecrawl no vale")
        if codigo == 402:
            raise FirecrawlNoDisponible("sin créditos de Firecrawl")
        if codigo in (408, 429) or codigo >= 500:
            raise ErrorDeRed(f"Firecrawl respondió HTTP {codigo}")
        if not 200 <= codigo < 300:
            raise FirecrawlRechazo(f"Firecrawl rechazó la petición (HTTP {codigo})")
        try:
            datos = json.loads(texto)
        except (ValueError, TypeError):
            raise ErrorDeRed("Firecrawl devolvió una respuesta ilegible") from None
        if not isinstance(datos, dict):
            raise ErrorDeRed("Firecrawl devolvió una respuesta ilegible")
        if datos.get("success") is False:
            detalle = " ".join(str(datos.get("error") or "").split()).replace(self._api_key, "[clave]")[:120]
            raise FirecrawlRechazo(
                f"Firecrawl rechazó la petición (success:false{': ' + detalle if detalle else ''})"
            )
        cuerpo_datos = datos.get("data") if isinstance(datos.get("data"), dict) else datos
        meta = cuerpo_datos.get("metadata")
        meta = meta if isinstance(meta, dict) else {}
        html = cuerpo_datos.get("rawHtml")
        if not isinstance(html, str):
            raise ErrorDeRed("Firecrawl no devolvió el HTML")
        estado = meta.get("statusCode")
        creditos = meta.get("creditsUsed")
        self.creditos = creditos if isinstance(creditos, int) and not isinstance(creditos, bool) else None
        proxy = meta.get("proxyUsed")
        self.proxy = proxy if isinstance(proxy, str) else None
        return PaginaCapturada(
            str(meta.get("url") or url), html, _texto_de_encabezados(html), [],
            estado if isinstance(estado, int) else None,
        )
