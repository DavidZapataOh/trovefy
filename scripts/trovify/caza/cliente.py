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
from trovify.caza.presupuesto import ParadaPorErrores, Presupuesto
from trovify.navegador import NavegadorError, _un_navegador_a_la_vez

TOPE_META = 50_000
_POR_PAGINA = 30  # anuncios de la primera carga (observado en la grabación del 2026-11-10); cada scroll trae otro tramo
_MAX_ERRORES_SEGUIDOS = 3
_LIMITADO = (403, 429)
_MAX_DESPLAZAMIENTOS = 10
_MOTIVO_TOPE = "más de 50.000 (tope de Meta)"
_MOTIVO_ERRORES = "3 búsquedas seguidas con error; se para para no forzar a Meta"
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
    estado_http: int | None = None  # estado HTTP del documento principal; None si no se conoce


class Navegador(Protocol):
    def abrir(self, url: str, desplazar: int) -> PaginaCapturada: ...


# --- navegador real ------------------------------------------------------------------------


@contextmanager
def _lanzar_chromium(**kw):
    """Lanza Chromium y entrega el ``browser``; lo cierra al salir. Punto de inyección de las pruebas."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**kw)
        except Exception as exc:
            raise NavegadorError(
                f"no se pudo iniciar Chromium ({type(exc).__name__}); comprueba que está instalado "
                "(en una terminal de Ubuntu aparte: cd ~/trovefy/trovify && uv run playwright install chromium) "
                "y que tiene sus librerías de sistema"
            ) from exc
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

    def close(self):
        return None

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
                # tope de 40: cuenta todas las respuestas de /api/graphql, no solo las de la búsqueda
                respuestas = escuchar_respuestas(pagina, max_respuestas=40)
                try:
                    respuesta = pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    estado_http = getattr(respuesta, "status", None)
                    pagina.wait_for_timeout(6_000)
                    if not detectar_bloqueo(pagina.url, pagina.content()):
                        for _ in range(desplazar):
                            pagina.mouse.wheel(0, 20_000)
                            pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            pagina.wait_for_timeout(2_500)
                    html = pagina.content()
                    url_final = pagina.url
                except PlaywrightError as exc:
                    raise ErrorDeRed(f"no se pudo cargar la Biblioteca ({type(exc).__name__})") from exc
                try:
                    texto = pagina.evaluate(_JS_ENCABEZADOS) or ""
                except PlaywrightError:
                    texto = ""  # sin encabezados no hay total de texto; no es un fallo de red
                return PaginaCapturada(url_final, html, texto, [r["cuerpo"] for r in respuestas], estado_http)
            finally:
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
        self._errores_seguidos = 0
        self._parada: str | None = None  # motivo de la parada por errores; una vez parada, no se navega más

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
        if self._parada is not None:
            raise ParadaPorErrores(self._parada)
        url = url_biblioteca(pais, q, page_id, estado)
        if self.cache is not None:
            en_cache = self.cache.leer(url, max_anuncios)
            if en_cache is not None:
                # Sin navegar, sin presupuesto, sin pausa; tampoco cuenta en presupuesto.vacios
                # (ese contador es de búsquedas navegadas).
                return en_cache
        self.presupuesto.antes_de_buscar()
        desplazar = min(_MAX_DESPLAZAMIENTOS, max(0, math.ceil(max_anuncios / _POR_PAGINA) - 1))
        try:
            pagina = self._abrir_con_reintentos(url, desplazar)
        except ParadaPorErrores as exc:
            self._parada = str(exc)  # parada persistente: la siguiente búsqueda no vuelve a tocar Meta
            raise
        self.presupuesto.exito()  # la página cargó: se acaba la racha de errores de red
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
                self._errores_seguidos = 0
                if self.cache is not None:
                    self.cache.guardar(url, r, max_anuncios)
            else:
                self._errores_seguidos += 1
                if self._errores_seguidos >= _MAX_ERRORES_SEGUIDOS:
                    self._parada = f"{_MOTIVO_ERRORES} (última: {r.motivo})" if r.motivo else _MOTIVO_ERRORES
                    raise ParadaPorErrores(self._parada)
        return r

    def _abrir_con_reintentos(self, url: str, desplazar: int) -> PaginaCapturada:
        while True:
            try:
                pagina = self.navegador.abrir(url, desplazar)
                if pagina.estado_http is not None and pagina.estado_http >= 500:
                    raise ErrorDeRed(f"HTTP {pagina.estado_http}")
                return pagina
            except ErrorDeRed:
                self.presupuesto.tras_error()  # espera 30 s, luego 90 s; a la tercera, ParadaPorErrores

    def _interpretar(self, url: str, pais: str, p: PaginaCapturada, max_anuncios: int) -> ResultadoBusqueda:
        ahora = datetime.now(UTC)

        def resultado(estado, total=None, anuncios=(), motivo=None, completo=False):
            return ResultadoBusqueda(estado, url, total, list(anuncios), motivo, ahora, completo)

        if p.estado_http in _LIMITADO:
            return resultado("bloqueado", motivo=f"Meta limitó las búsquedas (HTTP {p.estado_http})")
        bloqueo = detectar_bloqueo(p.url_final, p.html)
        if bloqueo:
            return resultado("bloqueado", motivo=f"Meta mostró {bloqueo}; se detiene la sesión")
        try:
            parseo = parsear_detalle(p.cuerpos, pais, p.html)
        except FormatoDesconocido as exc:
            if sin_resultados(p.html):
                return resultado("vacio", total=0, completo=True)
            return resultado("error", motivo=f"formato de la Biblioteca no reconocido: {exc}")
        if not parseo.anuncios:
            if sin_resultados(p.html):
                return resultado("vacio", total=0, completo=True)
            return resultado("error", motivo="la página no trae anuncios ni aviso de «sin resultados»")
        total, motivo_total = parseo.total_json, None
        if total is not None:
            if total > TOPE_META:
                total, motivo_total = TOPE_META, _MOTIVO_TOPE
        else:
            total = total_aproximado(p.texto)
            if total is not None and _cota_en_texto(p.texto):
                if total >= TOPE_META:
                    total, motivo_total = TOPE_META, _MOTIVO_TOPE
                else:
                    motivo_total = f"más de {total:,} (cota inferior)".replace(",", ".")
        motivos = []
        if motivo_total:
            motivos.append(motivo_total)
        elif total is None:
            motivos.append("total no medido: Meta no mostró recuento")
        if parseo.descartados:
            motivos.append(f"{parseo.descartados} anuncios descartados por formato")
        leidos = parseo.anuncios
        anuncios = leidos[:max_anuncios]
        # Completo solo si Meta dice que no hay más (o su count no pasa de lo leído) y no se recortó
        # ni se descartó nada: si no, es una muestra y sus cifras son «≥».
        sin_mas = parseo.hay_mas is False or (parseo.total_json is not None and parseo.total_json <= len(leidos))
        completo = sin_mas and len(anuncios) == len(leidos) and not parseo.descartados
        return resultado("ok", total, anuncios, "; ".join(motivos) or None, completo)
