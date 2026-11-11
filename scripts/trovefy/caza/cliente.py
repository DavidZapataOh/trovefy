"""Cliente de la Biblioteca pública de anuncios de Meta (sin sesión, navegador efímero).

Un cliente = una sesión: comparte un :class:`Presupuesto` y, si Meta bloquea, se detiene
(:class:`SesionBloqueada` en la siguiente búsqueda). Un acierto de caché no navega, no gasta
presupuesto y no hace pausa. Nunca se usa un perfil, ``storage_state`` ni contexto persistente.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from html import unescape
from typing import ClassVar, Literal, Protocol

from trovefy.caza.biblioteca import aviso_de_bloqueo, detectar_bloqueo, url_biblioteca
from trovefy.caza.cache import Cache
from trovefy.caza.captura import escuchar_respuestas
from trovefy.caza.modelo import ResultadoBusqueda
from trovefy.caza.parser import (
    FormatoDesconocido,
    parsear_detalle,
    sin_resultados,
    total_aproximado,
)
from trovefy.caza.presupuesto import ParadaPorErrores, Presupuesto
from trovefy.navegador import NavegadorError, _un_navegador_a_la_vez

TOPE_META = 50_000
_MAX_ERRORES_SEGUIDOS = 3
_LIMITADO = (403, 429)
# Tope técnico de desplazamientos por búsqueda. Se desplaza mientras haya progreso real (ver
# _desplazar); el tope solo evita un bucle si Meta nunca dice que acabó. En la grabación del
# 2026-11-10 cada desplazamiento trajo 10 anuncios: 30 del HTML + 15 × 10 = 180.
_MAX_DESPLAZAMIENTOS = 15
# Tope de respuestas de /api/graphql que se guardan (cuenta todas, no solo las de la búsqueda).
_MAX_RESPUESTAS = 80
# Errores de GraphQL que indican que Meta limita las peticiones: códigos conocidos de la Graph API
# y frases concretas (nunca raíces sueltas como «limitad»: otras consultas de la página las usan).
_CODIGOS_LIMITE = frozenset({4, 17, 32, 368, 613, 1675004})
_FRASES_LIMITE = (
    "has usado esta función demasiado rápido",
    "you're temporarily blocked",
    "temporarily blocked",
    "bloqueado temporalmente",
    "rate limit",
    "too many requests",
)
# Consultas de la búsqueda (primera carga y paginación); el resto de /api/graphql es ajeno.
_CONSULTA_BUSQUEDA = re.compile(r"^AdLibrary\w*(?:Search|Pagination)\w*Query$")
_MARCAS_BUSQUEDA = ("ad_library_main", "search_results_connection")
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
    # estado HTTP de cada respuesta de datos, en el orden de ``cuerpos``; vacío si no se conoce
    estados_datos: list[int] = field(default_factory=list)
    # nombre de la consulta GraphQL de cada respuesta (fb_api_req_friendly_name); None si no se sabe
    consultas: list[str | None] = field(default_factory=list)


class Navegador(Protocol):
    def abrir(self, url: str, max_anuncios: int) -> PaginaCapturada: ...


# --- respuestas de datos y desplazamiento ----------------------------------------------------


def _json_de(cuerpo: str):
    t = (cuerpo or "").strip()
    t = t.removeprefix("for (;;);")
    for candidato in (t, t.split("\n", 1)[0]):
        try:
            return json.loads(candidato)
        except (ValueError, TypeError):
            continue
    return None


def es_de_busqueda(cuerpo: str, consulta: str | None) -> bool:
    """¿Es una respuesta de la búsqueda (no otra consulta de la página)? Por el nombre de la
    consulta o porque el cuerpo trae ``ad_library_main``/``search_results_connection``."""
    if consulta and _CONSULTA_BUSQUEDA.match(consulta):
        return True
    return any(marca in (cuerpo or "") for marca in _MARCAS_BUSQUEDA)


def _error_de_limite(e) -> bool:
    if not isinstance(e, dict):
        return False
    texto = " ".join(str(e.get(k, "")) for k in ("message", "summary", "description"))
    texto = texto.replace("\u2019", "'").casefold()
    return e.get("code") in _CODIGOS_LIMITE or any(f in texto for f in _FRASES_LIMITE)


def fallo_de_datos(
    estado: int | None, cuerpo: str, consulta: str | None = None
) -> tuple[Literal["limitado", "error"], str] | None:
    """¿Falló una respuesta de datos?

    - HTTP 403/429 en cualquier ``/api/graphql/``: ``("limitado", "HTTP N")``.
    - Solo en respuestas de la búsqueda (:func:`es_de_busqueda`): un error de GraphQL de límite
      (código o frase conocida) es ``("limitado", …)``; otro estado no 2xx es ``("error", …)``.
    - Las demás consultas de la página se ignoran: sus errores no dicen nada de la búsqueda.
    Una página de resultados fallida sin estos signos ya deja ``has_next_page`` en true, así que
    el resultado no sale ``completo``.
    """
    if estado in _LIMITADO:
        return "limitado", f"HTTP {estado}"
    if not es_de_busqueda(cuerpo, consulta):
        return None
    if estado is not None and not 200 <= estado < 300:
        return "error", f"HTTP {estado}"
    doc = _json_de(cuerpo)
    errores = doc.get("errors") if isinstance(doc, dict) else None
    if isinstance(errores, list) and any(_error_de_limite(e) for e in errores):
        return "limitado", f"HTTP {estado or 200}"
    return None


def _fallos(respuestas: list[dict]):
    return [f for f in (fallo_de_datos(r.get("estado"), r.get("cuerpo", ""), r.get("consulta"))
                        for r in respuestas) if f]


def _como_respuestas(p: PaginaCapturada) -> list[dict]:
    n = len(p.cuerpos)
    estados = list(p.estados_datos) + [None] * (n - len(p.estados_datos))
    consultas = list(p.consultas) + [None] * (n - len(p.consultas))
    return [{"estado": e, "cuerpo": c, "consulta": q} for e, c, q in zip(estados, p.cuerpos, consultas, strict=False)]


def _progreso(respuestas: list[dict], html: str) -> tuple[int, bool | None]:
    """Anuncios distintos leídos hasta ahora y el último ``has_next_page``."""
    try:
        p = parsear_detalle([r["cuerpo"] for r in respuestas], "ALL", html)
    except FormatoDesconocido:
        return 0, None
    return len(p.anuncios), p.hay_mas


def _fallo_desde(respuestas: list[dict], antes: int) -> bool:
    return bool(_fallos(respuestas[antes:]))


def _desplazar(pagina, respuestas: list[dict], html: str, max_anuncios: int) -> None:
    """Desplaza la página mientras haya progreso real, sin suponer cuántos anuncios trae cada tramo.

    Para cuando: ya hay ``max_anuncios``; Meta dice ``has_next_page`` false; un desplazamiento no
    trae ningún anuncio nuevo; llega una respuesta de datos fallida (el cliente decide si es
    bloqueo o lectura parcial; no se insiste); o se alcanza ``_MAX_DESPLAZAMIENTOS``. Sin anuncios
    en la primera página no hay nada que paginar.
    """
    n, hay_mas = _progreso(respuestas, html)
    if n == 0:
        return
    for _ in range(_MAX_DESPLAZAMIENTOS):
        if n >= max_anuncios or hay_mas is False:
            return
        antes = len(respuestas)
        pagina.mouse.wheel(0, 20_000)
        pagina.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        pagina.wait_for_timeout(2_500)
        nuevo, hay_mas = _progreso(respuestas, html)
        if nuevo <= n and not _fallo_desde(respuestas, antes):
            pagina.wait_for_timeout(2_500)  # la respuesta puede tardar: se espera una vez más
            nuevo, hay_mas = _progreso(respuestas, html)
        if _fallo_desde(respuestas, antes) or nuevo <= n:
            return
        n = nuevo


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
                "(en una terminal de Ubuntu aparte: cd ~/trovefy/trovefy && uv run playwright install chromium) "
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


def _encabezados(pagina) -> str:
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pagina.evaluate(_JS_ENCABEZADOS) or ""
    except PlaywrightError:
        return ""  # sin encabezados no hay total de texto; no es un fallo de red


def _se_puede_desplazar(estado_http: int | None, url_final: str, html: str, texto: str, respuestas) -> bool:
    """Nunca se desplaza sobre un documento limitado, fallido o bloqueado, ni tras un límite en datos."""
    if estado_http in _LIMITADO or (estado_http is not None and estado_http >= 500):
        return False
    if detectar_bloqueo(url_final, html) or aviso_de_bloqueo(texto):
        return False
    fallos = _fallos(respuestas)
    return not any(tipo == "limitado" for tipo, _ in fallos)


class NavegadorEfimero:
    """Chromium sin interfaz con contexto nuevo en cada apertura; se cierra todo al terminar."""

    def abrir(self, url: str, max_anuncios: int) -> PaginaCapturada:
        from playwright.sync_api import Error as PlaywrightError

        with _un_navegador_a_la_vez(), _lanzar_chromium(headless=True, chromium_sandbox=True) as navegador:
            ctx = navegador.new_context()  # efímero: sin storage_state ni user_data_dir
            try:
                pagina = ctx.new_page()
                respuestas = escuchar_respuestas(pagina, max_respuestas=_MAX_RESPUESTAS)
                try:
                    respuesta = pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    estado_http = getattr(respuesta, "status", None)
                    pagina.wait_for_timeout(6_000)
                    html = pagina.content()
                    texto = _encabezados(pagina)
                    if _se_puede_desplazar(estado_http, pagina.url, html, texto, respuestas):
                        _desplazar(pagina, respuestas, html, max_anuncios)
                        html = pagina.content()
                        texto = _encabezados(pagina)
                    url_final = pagina.url
                except PlaywrightError as exc:
                    raise ErrorDeRed(f"no se pudo cargar la Biblioteca ({type(exc).__name__})") from exc
                return PaginaCapturada(
                    url_final, html, texto, [r["cuerpo"] for r in respuestas], estado_http,
                    [r["estado"] for r in respuestas], [r.get("consulta") for r in respuestas],
                )
            finally:
                ctx.close()


# --- cliente -------------------------------------------------------------------------------


def _cota_en_texto(texto: str) -> bool:
    return any(_MAYOR_QUE.search(unescape(s)) for s in _SEGMENTOS.split(texto or ""))


class ClienteBibliotecaPublica:
    def __init__(
        self,
        presupuesto: Presupuesto,
        navegador: Navegador | None = None,
        cache: Cache | None = None,
        firecrawl: Navegador | None = None,
    ):
        """``navegador`` es la vía Playwright (lecturas completas y respaldo). ``firecrawl`` es la
        vía principal [D-11b]; si no se pasa ni ``navegador`` ni ``firecrawl`` (uso real), sale de
        ``FIRECRAWL_API_KEY`` en ``claude.env`` si existe. Con un ``navegador`` inyectado y sin
        ``firecrawl`` no hay Firecrawl (las pruebas no tocan el HOME real)."""
        self.presupuesto = presupuesto
        if firecrawl is None and navegador is None:
            from trovefy.caza.firecrawl import NavegadorFirecrawl, clave_firecrawl

            clave = clave_firecrawl()
            firecrawl = NavegadorFirecrawl(clave) if clave else None
        self.navegador = navegador or NavegadorEfimero()
        self.firecrawl = firecrawl
        self._firecrawl_caido = False
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
        completa: bool = False,
    ) -> ResultadoBusqueda:
        """``completa=True`` usa Playwright (desplazamiento, ``completo`` real); si no, la primera
        página se pide por Firecrawl si hay clave y sigue disponible, si no por Playwright."""
        if self._bloqueada:
            raise SesionBloqueada("Meta bloqueó la sesión: se detiene la caza; no se fuerza ni se reintenta.")
        if self._parada is not None:
            raise ParadaPorErrores(self._parada)
        url = url_biblioteca(pais, q, page_id, estado)
        if self.cache is not None:
            en_cache = (not completa and self.cache.leer(url, max_anuncios, primera=True)) or self.cache.leer(
                url, max_anuncios
            )
            if en_cache:
                # Sin navegar, sin presupuesto, sin pausa; tampoco cuenta en presupuesto.vacios
                # (ese contador es de búsquedas navegadas).
                if len(en_cache.anuncios) > max_anuncios:
                    en_cache = replace(en_cache, anuncios=en_cache.anuncios[:max_anuncios], completo=False)
                return en_cache
        self.presupuesto.antes_de_buscar()
        via: Literal["firecrawl", "playwright"] = "playwright"
        aviso: str | None = None
        rechazo: str | None = None
        pagina: PaginaCapturada | None = None
        try:
            if not completa and self.firecrawl is not None and not self._firecrawl_caido:
                from trovefy.caza.firecrawl import (
                    FirecrawlNoDisponible,
                    FirecrawlRechazo,
                )

                try:
                    pagina = self._abrir_con_reintentos(url, max_anuncios, self.firecrawl)
                    via = "firecrawl"
                except FirecrawlRechazo as exc:
                    via, rechazo = "firecrawl", str(exc)  # solo esta búsqueda; sin reintento ni cambio de vía
                except FirecrawlNoDisponible as exc:
                    self._firecrawl_caido = True  # el resto de la sesión, Playwright; el aviso sale una vez
                    aviso = f"{exc}; se usa Playwright"
                    pagina = self._abrir_con_reintentos(url, max_anuncios)
            else:
                pagina = self._abrir_con_reintentos(url, max_anuncios)
        except ParadaPorErrores as exc:
            # Solo este proceso: la siguiente búsqueda suya no vuelve a tocar Meta. No se guarda en
            # el archivo del día (una caída de red o de Firecrawl no es Meta pidiendo parar).
            self._parada = str(exc)
            raise
        try:
            if pagina is None:
                r = ResultadoBusqueda("error", url, None, [], rechazo, datetime.now(UTC))
            else:
                self.presupuesto.exito()  # la página cargó: se acaba la racha de errores de red
                r = self._interpretar(url, pais, pagina, max_anuncios)
        finally:
            self.presupuesto.pausa()
        r.via = via
        if via == "firecrawl":
            r.creditos = getattr(self.firecrawl, "creditos", None)
            r.proxy = getattr(self.firecrawl, "proxy", None)
        if r.estado == "bloqueado":
            self.presupuesto.bloqueos += 1
            self._bloqueada = True
            self._guardar_parada(f"bloqueo de Meta: {r.motivo or 'acceso bloqueado'}")
        else:
            if r.estado == "vacio":
                self.presupuesto.vacios += 1
            if r.estado in ("ok", "vacio"):
                self._errores_seguidos = 0
                if self.cache is not None:
                    # sin el aviso de la sesión; la primera página sirve a cualquier lectura no completa
                    self.cache.guardar(url, r, max_anuncios)
                    if len(r.anuncios) < max_anuncios:  # sin recortar: vale para cualquier tope
                        self.cache.guardar(url, r, max_anuncios, primera=True)
            else:
                self._errores_seguidos += 1
                if self._errores_seguidos >= _MAX_ERRORES_SEGUIDOS:
                    self._parada = f"{_MOTIVO_ERRORES} (última: {r.motivo})" if r.motivo else _MOTIVO_ERRORES
                    raise ParadaPorErrores(self._parada)  # solo este proceso, como arriba
        if aviso:
            r.motivo = f"{r.motivo}; {aviso}" if r.motivo else aviso
        return r

    def _guardar_parada(self, motivo: str) -> None:
        """Un bloqueo de Meta vale para el día entero y para todos los procesos (archivo del presupuesto)."""
        guardar = getattr(self.presupuesto, "registrar_parada", None)
        if guardar is not None:
            guardar(motivo)

    def _abrir_con_reintentos(self, url: str, max_anuncios: int, navegador: Navegador | None = None) -> PaginaCapturada:
        navegador = navegador or self.navegador
        while True:
            try:
                pagina = navegador.abrir(url, max_anuncios)
                if pagina.estado_http is not None and pagina.estado_http >= 500:
                    raise ErrorDeRed(f"HTTP {pagina.estado_http}")
                return pagina
            except ErrorDeRed:
                self.presupuesto.tras_error()  # espera 30 s, luego 90 s; a la tercera, ParadaPorErrores

    def _interpretar(self, url: str, pais: str, p: PaginaCapturada, max_anuncios: int) -> ResultadoBusqueda:
        ahora = datetime.now(UTC)

        def resultado(estado, total=None, anuncios=(), motivo=None, completo=False, exacto=False):
            return ResultadoBusqueda(estado, url, total, list(anuncios), motivo, ahora, completo, total_exacto=exacto)

        if p.estado_http in _LIMITADO:
            return resultado("bloqueado", motivo=f"Meta limitó las búsquedas (HTTP {p.estado_http})")
        bloqueo = detectar_bloqueo(p.url_final, p.html)
        if bloqueo:
            return resultado("bloqueado", motivo=f"Meta mostró {bloqueo}; se detiene la sesión")
        if aviso_de_bloqueo(p.texto):
            return resultado("bloqueado", motivo="Meta mostró un aviso de bloqueo temporal; se detiene la sesión")
        fallos = _fallos(_como_respuestas(p))
        limite = next((d for tipo, d in fallos if tipo == "limitado"), None)
        if limite:
            return resultado("bloqueado", motivo=f"Meta limitó las búsquedas durante el desplazamiento ({limite})")
        parcial = (
            f"lectura parcial: Meta respondió {', '.join(d for _, d in fallos)} al desplazar" if fallos else None
        )
        try:
            parseo = parsear_detalle(p.cuerpos, pais, p.html)
        except FormatoDesconocido as exc:
            if sin_resultados(p.html):
                return resultado("vacio", total=0, completo=True, exacto=True)
            return resultado("error", motivo=f"formato de la Biblioteca no reconocido: {exc}")
        if not parseo.anuncios:
            if sin_resultados(p.html):
                return resultado("vacio", total=0, completo=True, exacto=True)
            motivo = "la página no trae anuncios ni aviso de «sin resultados»"
            return resultado("error", motivo=f"{motivo}; {parcial}" if parcial else motivo)
        total, motivo_total = parseo.total_json, None
        exacto = total is not None and total <= TOPE_META
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
        if parcial:
            motivos.append(parcial)
        leidos = parseo.anuncios
        anuncios = leidos[:max_anuncios]
        # Completo solo si Meta dice que no hay más (o su count no pasa de lo leído) y no se recortó
        # ni se descartó nada: si no, es una muestra y sus cifras son «≥».
        sin_mas = parseo.hay_mas is False or (parseo.total_json is not None and parseo.total_json <= len(leidos))
        completo = sin_mas and len(anuncios) == len(leidos) and not parseo.descartados and not parcial
        return resultado("ok", total, anuncios, "; ".join(motivos) or None, completo, exacto)
