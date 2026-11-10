"""Cliente de la Biblioteca pública de anuncios de Meta (sin sesión, navegador efímero).

Un cliente = una sesión: comparte un :class:`Presupuesto` y, si Meta bloquea, se detiene
(:class:`SesionBloqueada` en la siguiente búsqueda). Un acierto de caché no navega, no gasta
presupuesto y no hace pausa. Nunca se usa un perfil, ``storage_state`` ni contexto persistente.
"""

from __future__ import annotations

import math
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from typing import ClassVar, Literal, Protocol

from trovify.caza.biblioteca import detectar_bloqueo, url_biblioteca
from trovify.caza.cache import Cache
from trovify.caza.captura import escuchar_respuestas
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.parser import (
    FormatoDesconocido,
    parsear_detalle,
    sin_resultados,
    total_aproximado,
)
from trovify.caza.presupuesto import Presupuesto
from trovify.navegador import _un_navegador_a_la_vez

TOPE_META = 50_000
_POR_PAGINA = 30  # anuncios que trae la primera carga; cada desplazamiento trae otro tramo
_MAX_DESPLAZAMIENTOS = 10
_MOTIVO_TOPE = "más de 50.000 (tope de Meta)"
_MAYOR_QUE = re.compile(r">\s*\d[\d.,]*\s*(?:results?|resultados?)", re.IGNORECASE)
_SEGMENTOS = re.compile(r"<[^>]*>|\n")
_JS_ENCABEZADOS = "() => Array.from(document.querySelectorAll('[role=heading]')).map(e => e.innerText).join('\\n')"


class SesionBloqueada(RuntimeError):
    """Meta mostró un bloqueo: la sesión queda detenida; no se reintenta."""


class ErrorDeRed(Exception):
    """Fallo de red o de carga al abrir la página (se reintenta con esperas)."""


@dataclass
class PaginaCapturada:
    url_final: str
    html: str
    texto: str  # texto de los encabezados (role="heading"), donde Meta muestra el total
    cuerpos: list[str]


class Navegador(Protocol):
    def abrir(self, url: str, desplazar: int) -> PaginaCapturada: ...


# --- navegador real ------------------------------------------------------------------------


@contextmanager
def _lanzar_chromium(**kw):
    """Lanza Chromium y entrega el ``browser``; lo cierra al salir. Punto de inyección de las pruebas."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(**kw)
        try:
            yield browser
        finally:
            browser.close()


class _ChromiumFalso:
    """Chromium de pega para probar el lanzamiento sin abrir nada."""

    nuevos_contextos: ClassVar[list[dict]] = []

    def __enter__(self):
        _ChromiumFalso.nuevos_contextos = []
        return self

    def __exit__(self, *_):
        return None

    def new_context(self, **kw):
        _ChromiumFalso.nuevos_contextos.append(kw)
        return self

    def new_page(self):
        return self

    url = "https://www.facebook.com/ads/library/"
    mouse = None

    def on(self, *_a):
        return None

    def goto(self, *_a, **_k):
        return None

    def wait_for_timeout(self, *_a):
        return None

    def content(self):
        return "<html></html>"

    def evaluate(self, *_a):
        return ""


class NavegadorEfimero:
    """Chromium sin interfaz con contexto nuevo en cada apertura; se cierra todo al terminar."""

    def abrir(self, url: str, desplazar: int) -> PaginaCapturada:
        from playwright.sync_api import Error as PlaywrightError

        with _un_navegador_a_la_vez(), _lanzar_chromium(headless=True, chromium_sandbox=True) as navegador:
            ctx = navegador.new_context()  # efímero: sin storage_state ni user_data_dir
            try:
                pagina = ctx.new_page()
                respuestas = escuchar_respuestas(pagina, max_respuestas=40)
                try:
                    pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    pagina.wait_for_timeout(6_000)
                    if not detectar_bloqueo(pagina.url, pagina.content()):
                        for _ in range(desplazar):
                            pagina.mouse.wheel(0, 20_000)
                            pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            pagina.wait_for_timeout(2_500)
                    html = pagina.content()
                    texto = pagina.evaluate(_JS_ENCABEZADOS) or ""
                    url_final = pagina.url
                except PlaywrightError as exc:
                    raise ErrorDeRed(f"no se pudo cargar la Biblioteca ({type(exc).__name__})") from exc
                return PaginaCapturada(url_final, html, texto, [r["cuerpo"] for r in respuestas])
            finally:
                if hasattr(ctx, "close"):
                    ctx.close()


# --- cliente -------------------------------------------------------------------------------


def _cota_en_texto(texto: str) -> bool:
    return any(_MAYOR_QUE.search(unescape(s)) for s in _SEGMENTOS.split(texto or ""))


class ClienteBibliotecaPublica:
    def __init__(
        self, presupuesto: Presupuesto, navegador: Navegador | None = None, cache: Cache | None = None
    ):
        self.presupuesto = presupuesto
        self.navegador = navegador or NavegadorEfimero()
        self.cache = cache
        self._bloqueada = False

    def buscar(
        self,
        pais: str,
        q: str | None = None,
        page_id: str | None = None,
        estado: Literal["active", "all"] = "active",
        max_anuncios: int = 60,
    ) -> ResultadoBusqueda:
        if self._bloqueada:
            raise SesionBloqueada("Meta bloqueó la sesión: se detiene la caza; no se fuerza ni se reintenta.")
        url = url_biblioteca(pais, q, page_id, estado)
        if self.cache is not None:
            en_cache = self.cache.leer(url)
            if en_cache is not None:
                return en_cache  # sin navegar, sin presupuesto, sin pausa
        self.presupuesto.antes_de_buscar()
        desplazar = min(_MAX_DESPLAZAMIENTOS, max(0, math.ceil(max_anuncios / _POR_PAGINA) - 1))
        pagina = self._abrir_con_reintentos(url, desplazar)
        try:
            r = self._interpretar(url, pais, pagina, max_anuncios)
        finally:
            self.presupuesto.pausa()
        if r.estado == "bloqueado":
            self.presupuesto.bloqueos += 1
            self._bloqueada = True
        else:
            if r.estado == "vacio":
                self.presupuesto.vacios += 1
            if r.estado in ("ok", "vacio"):
                self.presupuesto.exito()
                if self.cache is not None:
                    self.cache.guardar(url, r)
        return r

    def _abrir_con_reintentos(self, url: str, desplazar: int) -> PaginaCapturada:
        while True:
            try:
                return self.navegador.abrir(url, desplazar)
            except ErrorDeRed:
                self.presupuesto.tras_error()  # espera 30 s, luego 90 s; a la tercera, ParadaPorErrores

    def _interpretar(self, url: str, pais: str, p: PaginaCapturada, max_anuncios: int) -> ResultadoBusqueda:
        ahora = datetime.now(UTC)

        def resultado(estado, total=None, anuncios=(), motivo=None):
            return ResultadoBusqueda(estado, url, total, list(anuncios), motivo, ahora)

        bloqueo = detectar_bloqueo(p.url_final, p.html)
        if bloqueo:
            return resultado("bloqueado", motivo=f"Meta mostró {bloqueo}; se detiene la sesión")
        try:
            parseo = parsear_detalle(p.cuerpos, pais, p.html)
        except FormatoDesconocido as exc:
            if sin_resultados(p.html):
                return resultado("vacio", total=0)
            return resultado("error", motivo=f"formato de la Biblioteca no reconocido: {exc}")
        if not parseo.anuncios:
            if sin_resultados(p.html):
                return resultado("vacio", total=0)
            return resultado("error", motivo="la página no trae anuncios ni aviso de «sin resultados»")
        total, cota = parseo.total_json, False
        if total is not None:
            cota = total > TOPE_META
        else:
            total = total_aproximado(p.texto)
            cota = total is not None and _cota_en_texto(p.texto)
        if cota:
            total = TOPE_META
        motivos = []
        if cota:
            motivos.append(_MOTIVO_TOPE)
        if parseo.descartados:
            motivos.append(f"{parseo.descartados} anuncios descartados por formato")
        return resultado("ok", total, parseo.anuncios[:max_anuncios], "; ".join(motivos) or None)
