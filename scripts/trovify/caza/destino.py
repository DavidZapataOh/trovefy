"""Destino de un anuncio: landing, pasarela de pago, precio y clave de oferta (§4.7).

Nunca se abre ``facebook.com``/``l.facebook.com``: el salto ``l.php?u=`` se desenvuelve en local
(Meta limita las peticiones de esta máquina). Las landings son sitios de terceros.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import parse_qs, urlparse

from trovify.caza.huellas import GATEWAYS, TRACKERS_POR_NOMBRE
from trovify.navegador import NavegadorError, _un_navegador_a_la_vez, sesion_caducada

_DOMINIOS_COMPARTIDOS = ("netlify.app", "vercel.app", "pages.dev", "github.io")
# Segmentos genéricos que no identifican la oferta (whop.com/checkout/<plan>, gumroad /l/<slug>).
_GENERICOS = {"checkout", "l", "buy", "b", "c", "pay", "p"}
_SEGUNDO_NIVEL = {"com", "co", "org", "net", "gov", "edu", "ac"}
_RED_SOCIAL = (
    "facebook.com", "fb.com", "fb.me", "fb.watch", "messenger.com", "m.me", "instagram.com", "ig.me",
    "wa.me", "whatsapp.com", "api.whatsapp.com", "play.google.com", "apps.apple.com", "itunes.apple.com",
    "onelink.me", "t.me", "facebook.net",
)
_MOVIL_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_UA_ROBOT = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
_URL = re.compile(r"""https?://[^\s"'<>\\)]+""")


# --- URLs -----------------------------------------------------------------------------------


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def deshacer_redireccion_fb(url: str) -> str:
    """Saca ``u=`` de ``l.facebook.com/l.php`` (y ``lm.``/``www.facebook.com/l.php``). No abre nada."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if (host.endswith("facebook.com") and p.path.rstrip("/") == "/l.php") or (
        host == "l.instagram.com"
    ):
        destino = parse_qs(p.query).get("u")
        if destino:
            return destino[0]
    return url


def url_valida(url: str) -> bool:
    """Solo http/https con un nombre de host público: nada de localhost, IP privadas, ``file:`` ni ``data:``."""
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    return "." in host and not host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa"))


def _en_dominio(host: str, dominio: str) -> bool:
    return host == dominio or host.endswith("." + dominio)


def es_red_social(url: str) -> bool:
    host = _host(url)
    return any(_en_dominio(host, d) for d in _RED_SOCIAL)


def _coincide(url: str, patron: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    ruta = p.path or "/"
    h, _, pref = patron.partition("/")
    if h.startswith("*."):
        ok = host.endswith(h[1:]) and host != h[2:]
    else:
        ok = host == h or host == "www." + h
    if not ok:
        return False
    return ruta.startswith("/" + pref) if pref else True


_EXT_RECURSO = (".js", ".mjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2")


def _es_recurso(url: str) -> bool:
    """Rutas de SDK o de recursos estáticos (``/js``, ``/sdk``, ``*.js``...): no son un checkout."""
    ruta = (urlparse(url).path or "/").lower()
    primero = ruta.strip("/").split("/")[0]
    return primero in ("js", "sdk") or ruta.endswith(_EXT_RECURSO)


def detectar_gateway(urls: list[str]) -> tuple[str, str] | None:
    """``(plataforma, url_checkout)`` de la primera URL que coincide, en el orden dado.

    Quien llama pasa las URLs en el orden de confianza de §4.7: cadena de redirecciones, peticiones
    de red, marcadores del HTML. Quien llama solo pasa navegaciones (cadena, documentos de primer nivel)
    y enlaces/acciones de formulario; nunca scripts, imágenes ni XHR. Las rutas de SDK se ignoran.
    """
    for url in urls:
        if _es_recurso(url):
            continue
        for plataforma, patrones in GATEWAYS.items():
            if any(_coincide(url, pat) for pat in patrones):
                return plataforma, url
    return None


def detectar_tracker(urls: list[str]) -> str | None:
    for url in urls:
        host = _host(url)
        for nombre, hosts in TRACKERS_POR_NOMBRE.items():
            if any((host.endswith(h[1:]) if h.startswith("*.") else _en_dominio(host, h)) for h in hosts):
                return nombre
    return None


def urls_en_html(html: str) -> list[str]:
    """URLs absolutas que aparecen en el HTML (enlaces, iframes, scripts), sin repetir."""
    vistas: dict[str, None] = {}
    for m in _URL.findall(html or ""):
        vistas.setdefault(m.rstrip(".,;"), None)
    return list(vistas)


_ENLACE = re.compile(r"""\b(?:href|action)\s*=\s*["']?(https?://[^\s"'<>]+)""", re.IGNORECASE)


def enlaces_en_html(html: str) -> list[str]:
    """URLs de ``<a href>`` y ``<form action>`` (no scripts, imágenes ni hojas de estilo), sin repetir."""
    return list(dict.fromkeys(m.rstrip(".,;") for m in _ENLACE.findall(html or "")))


# --- clave de oferta ------------------------------------------------------------------------


def _registrable(host: str) -> str:
    host = host.removeprefix("www.")
    partes = host.split(".")
    if len(partes) >= 3 and len(partes[-1]) == 2 and partes[-2] in _SEGUNDO_NIVEL:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:]) if len(partes) >= 2 else host


def _segmentos(url: str) -> list[str]:
    return [s for s in urlparse(url).path.split("/") if s]


def _id_producto(segs: list[str]) -> str | None:
    """Primer segmento no genérico (se saltan TODOS los genéricos iniciales)."""
    for seg in segs:
        if seg not in _GENERICOS:
            return seg
    return None


def clave_oferta(url_final: str, checkout: str | None) -> str:
    """Clave de oferta por producto: ``<plataforma>:<id>`` si hay checkout estable.

    Hotmart: código de producto (igual en pay./go.hotmart.com y hotm.art); Kiwify: código del checkout;
    Whop: ``plan_…`` si está, si no la empresa; Stripe: ``buy.stripe.com/<enlace>`` (las sesiones
    ``checkout.stripe.com/c/pay/cs_…`` son efímeras y caen al dominio de la landing); Impultienda: el
    subdominio de la tienda; el resto: ``<plataforma>:<host>/<primer segmento no genérico>``. Sin checkout:
    ``host/seg1/seg2`` en dominios compartidos (netlify.app...) o el dominio registrable.

    hotm.art/<corto> usa el código corto (no es el de pay.hotmart.com; el resolver lo
    sustituye si la cadena llega a pay.hotmart.com). Limitación: Whop ``whop.com/<empresa>/…`` (clave por empresa, junta planes) y
    ``whop.com/checkout/plan_…`` (clave por plan) nunca coinciden entre sí.
    """
    if checkout:
        det = detectar_gateway([checkout])
        plataforma = det[0] if det else "checkout"
        host = _host(checkout)
        segs = _segmentos(checkout)
        id_ = _id_producto(segs)
        if plataforma in ("hotmart", "kiwify") and id_:
            return f"{plataforma}:{id_}"
        if plataforma == "whop":
            plan = next((x for x in segs if x.startswith("plan_")), None)
            if plan or id_:
                return f"whop:{plan or id_}"
        elif plataforma == "impultienda":
            return f"impultienda:{host.removeprefix('www.').split('.')[0]}"
        elif plataforma == "stripe":
            if host == "buy.stripe.com" and id_:
                return f"stripe:{id_}"
            # sesión efímera: se usa la landing
        elif plataforma != "checkout":
            return f"{plataforma}:{host}" + (f"/{id_}" if id_ else "")
    host = _host(url_final).removeprefix("www.")
    if any(_en_dominio(host, d) for d in _DOMINIOS_COMPARTIDOS):
        return "/".join([host, *_segmentos(url_final)[:2]])
    return _registrable(host)


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")


def oferta_id(clave: str) -> str:
    return "o-" + _slug(clave)[:40] + "-" + hashlib.sha1(clave.encode()).hexdigest()[:6]


# --- precio ---------------------------------------------------------------------------------

# ``$`` suelto es ambiguo (USD, MXN, ARS, COP, CLP...): no se asigna moneda. USD solo con señal explícita.
_MONEDAS = {
    "us$": "USD", "usd": "USD", "dólares": "USD", "dolares": "USD", "dólar": "USD", "dolar": "USD", "dollars": "USD",
    "dollar": "USD", "r$": "BRL", "brl": "BRL", "€": "EUR", "eur": "EUR", "lei": "RON", "ron": "RON",
    "kč": "CZK", "czk": "CZK", "zł": "PLN", "pln": "PLN", "mxn": "MXN", "ars": "ARS", "cop": "COP",
    "clp": "CLP", "pen": "PEN", "uyu": "UYU", "$": None,
}
_CODIGOS = "USD|BRL|EUR|RON|CZK|PLN|MXN|ARS|COP|CLP|PEN|UYU|lei|d[óo]lar(?:es)?|dollars?"
_CUR = rf"(?:US\$|R\$|\$|€|(?<![A-Za-z])(?:{_CODIGOS})(?![A-Za-z])|Kč|zł)"
_NUM = r"\d[\d.,]*\d|\d"
_PRECIO = re.compile(rf"(?:(?P<c1>{_CUR})\s*(?P<n1>{_NUM})|(?P<n2>{_NUM})\s*(?P<c2>{_CUR}))", re.IGNORECASE)
_P = rf"(?:{_CUR}\s*(?:{_NUM})|(?:{_NUM})\s*{_CUR})"
_PARCELA = re.compile(
    rf"\b\d{{1,2}}\s*(?:[x×]|cuotas?|parcelas?|pagos?|installments?|payments?|rate|plăți)\s*(?:de|of|à|a)?\s*{_P}",
    re.IGNORECASE,
)
# gastos de envío y descuentos no son el precio del producto
_NO_PRECIO = re.compile(
    rf"(?:env[ií]o|frete|shipping|livrare|doprava|dostawa|wysyłka|ahorras?|desconto|descuento|discount|save|"
    rf"economiza|poupa)\b[^\d€$]{{0,15}}{_P}",
    re.IGNORECASE,
)


def _numero(s: str) -> float | None:
    ult = max(s.rfind("."), s.rfind(","))
    if ult != -1 and len(s) - ult - 1 in (1, 2):
        ent, dec = s[:ult], s[ult + 1:]
    else:
        ent, dec = s, ""
    ent = re.sub(r"[.,]", "", ent)
    try:
        return float(f"{ent}.{dec}" if dec else ent)
    except ValueError:
        return None


_CODIGO_ANTES = re.compile(rf"(?<![A-Za-z])({_CODIGOS})\s*\$", re.IGNORECASE)
_CODIGO_DESPUES = re.compile(rf"\$\s*({_NUM})\s*({_CODIGOS})(?![A-Za-z])", re.IGNORECASE)


def extraer_precio(texto: str) -> tuple[float, str | None] | None:
    """Precio al contado y moneda: ignora parcelas («12x de», «3 cuotas de»), envíos y descuentos, y
    devuelve el menor (el ancla es el mayor).

    La moneda es ``None`` cuando solo hay un ``$`` suelto (ambiguo: USD, MXN, ARS, COP...): el importe
    se conserva y quien llama anota «no medido: símbolo $ ambiguo». USD solo con ``US$``, ``USD`` o
    «dólares»; un código cercano (``MXN $499``, ``$499 ARS``) manda sobre el ``$``."""
    texto = _CODIGO_DESPUES.sub(r"\1 \2", _CODIGO_ANTES.sub(r"\1 ", texto or ""))
    limpio = _NO_PRECIO.sub(" ", _PARCELA.sub(" ", texto))
    precios = []
    for m in _PRECIO.finditer(limpio):
        cur = m.group("c1") or m.group("c2")
        valor = _numero(m.group("n1") or m.group("n2"))
        if valor and valor > 0:
            precios.append((valor, _MONEDAS[cur.lower()]))
    return min(precios, key=lambda p: p[0]) if precios else None


# --- destino --------------------------------------------------------------------------------


@dataclass
class Destino:
    url_anuncio: str
    url_final: str | None
    gateway: str | None
    checkout: str | None
    precio: float | None
    moneda: str | None
    tracker: str | None
    cloaker: bool | None
    red_social: bool
    estado: Literal["ok", "no_medido"]
    motivo: str | None
    vsl: bool = False


def motivo_dudoso(d: Destino) -> str | None:
    """Por qué una landing no es modelable (None si lo es)."""
    if d.estado == "no_medido":
        return f"no medido: {d.motivo}" if d.motivo else "no medido"
    if not d.checkout:
        return "sin checkout detectado"
    if d.precio is None:
        return "sin precio visible en la landing ni en el checkout"
    return None


def veredicto_landing(d: Destino) -> Literal["modelable", "dudoso"]:
    """Modelable = checkout detectado y precio visible; una oferta dudosa nunca llega a A."""
    return "dudoso" if motivo_dudoso(d) else "modelable"


@dataclass
class PaginaLanding:
    url_final: str
    html: str
    texto: str
    titulo: str
    estado_http: int | None
    cadena: list[str] = field(default_factory=list)  # redirecciones del documento, en orden
    peticiones: list[str] = field(default_factory=list)  # todas las URLs pedidas (sirve para rastreadores)
    documentos: list[str] = field(default_factory=list)  # solo documentos de primer nivel (navegaciones)
    reproductor: bool = False  # hay un reproductor de vídeo renderizado y visible


class NavegadorLanding(Protocol):
    def abrir_landing(self, url: str, espera_s: float = 3.5) -> PaginaLanding: ...


_JS_REPRODUCTOR = """() => {
  const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 50 && r.height > 50 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const sel = 'video, vturb-smartplayer, iframe[src*="youtube"], iframe[src*="vimeo"], iframe[src*="vturb"], '
    + 'iframe[src*="wistia"], iframe[src*="player"], iframe[src*="panda"]';
  return Array.from(document.querySelectorAll(sel)).some(visible);
}"""


def _filtrar_ruta(ruta) -> None:
    """Aborta lo de Meta y todo lo que no sea una URL pública (o ``data:``/``blob:``/``about:``)."""
    u = ruta.request.url
    if es_red_social(u) or not (url_valida(u) or u.startswith(("data:", "blob:", "about:"))):
        ruta.abort()
    else:
        ruta.continue_()


class NavegadorLandingEfimero:
    """Chromium móvil efímero (sin sesión) para landings de terceros; nunca carga recursos de Meta."""

    def abrir_landing(self, url: str, espera_s: float = 3.5) -> PaginaLanding:
        from playwright.sync_api import Error as PlaywrightError

        from trovify.caza.cliente import _lanzar_chromium

        with _un_navegador_a_la_vez(), _lanzar_chromium(headless=True, chromium_sandbox=True) as navegador:
            ctx = navegador.new_context(
                viewport={"width": 390, "height": 844}, user_agent=_MOVIL_UA, is_mobile=True, has_touch=True
            )
            try:
                pagina = ctx.new_page()
                peticiones: list[str] = []
                documentos: list[str] = []

                def al_pedir(r):
                    peticiones.append(r.url)
                    if r.resource_type == "document":
                        documentos.append(r.url)

                pagina.on("request", al_pedir)
                pagina.route("**/*", _filtrar_ruta)
                try:
                    resp = pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    pagina.wait_for_timeout(int(espera_s * 1000))
                    cadena, req = [], getattr(resp, "request", None)
                    while req is not None:
                        cadena.insert(0, req.url)
                        req = req.redirected_from
                    texto = pagina.evaluate("() => document.body ? document.body.innerText : ''") or ""
                    return PaginaLanding(
                        pagina.url, pagina.content(), texto, pagina.title(), getattr(resp, "status", None),
                        cadena, peticiones, documentos, bool(pagina.evaluate(_JS_REPRODUCTOR)),
                    )
                except PlaywrightError as exc:
                    raise NavegadorError(f"no se pudo abrir la landing ({type(exc).__name__})") from exc
            finally:
                ctx.close()


def pedir_como_robot_http(url: str) -> tuple[str, str]:
    """Pide la URL con el UA del robot de Meta (``facebookexternalhit/1.1``); devuelve ``(url_final, texto)``."""
    import urllib.request

    if not url_valida(url):
        raise ValueError("enlace no válido")
    req = urllib.request.Request(url, headers={"User-Agent": _UA_ROBOT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")


_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ETIQUETAS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_GEO = ("not available in your country", "no disponible en tu país", "indisponível no seu país", "geo-block")


def _titulo(s: str) -> str:
    m = _TITULO.search(s or "")
    return re.sub(r"\s+", " ", m.group(1)).strip().lower() if m else ""


def _texto_visible(s: str) -> str:
    return re.sub(r"\s+", " ", _ETIQUETAS.sub(" ", s or "")).strip()


def _sin_www(host: str) -> str:
    return host.removeprefix("www.")


_MOTIVO_JS = "no medido: la landing se arma con JavaScript"


def _cloaker(
    url_movil: str, pagina: PaginaLanding, pedir_como_robot: Callable[[str], tuple[str, str]], url: str
) -> tuple[bool | None, str | None]:
    """``(cloaker, motivo)``. True solo si difieren el host final o el título entre robot y móvil.

    Si el texto visible del robot es < 20 % del móvil (ambos sin etiquetas ni scripts) con mismo host y
    título, la página es un cascarón de JavaScript: no se puede decidir (None con motivo)."""
    try:
        url_robot, bruto = pedir_como_robot(url)
    except Exception:  # noqa: BLE001 - cualquier fallo del robot = no medido
        return None, "no medido: el robot no pudo pedir la landing"
    if _sin_www(_host(url_robot)) != _sin_www(_host(url_movil)):
        return True, None
    t_robot, t_movil = _titulo(bruto), (pagina.titulo or _titulo(pagina.html)).strip().lower()
    if t_robot and t_movil and t_robot != t_movil:
        return True, None
    texto_movil = re.sub(r"\s+", " ", pagina.texto).strip()
    if texto_movil and len(_texto_visible(bruto)) < 0.2 * len(texto_movil):
        return None, _MOTIVO_JS
    return False, None


def resolver_destino(
    url: str, navegador: NavegadorLanding, pedir_como_robot: Callable[[str], tuple[str, str]]
) -> Destino:
    """Abre la landing (vista móvil), la compara con lo que ve el robot de Meta y detecta checkout y precio."""
    destino = Destino(url, None, None, None, None, None, None, None, False, "ok", None)
    real = deshacer_redireccion_fb(url)

    def no_medido(motivo: str) -> Destino:
        destino.estado, destino.motivo = "no_medido", motivo
        return destino

    if es_red_social(real) and url_valida(real):
        destino.url_final, destino.red_social = real, True
        return destino
    if not url_valida(real):
        return no_medido("enlace no válido")

    try:
        p = navegador.abrir_landing(real)
    except Exception as exc:  # noqa: BLE001 - la landing no abre por cualquier causa
        return no_medido(f"la landing no abre ({type(exc).__name__})")
    destino.url_final = p.url_final
    if es_red_social(p.url_final):
        destino.red_social = True
        return destino
    if p.estado_http == 451 or any(g in p.texto.lower() for g in _GEO):
        return no_medido("landing geobloqueada")
    if p.estado_http is not None and p.estado_http >= 400:
        return no_medido(f"la landing responde HTTP {p.estado_http}")
    if sesion_caducada(p.url_final):
        return no_medido("la landing pide login")

    chk = (
        detectar_gateway([*p.cadena, p.url_final])
        or detectar_gateway(p.documentos)
        or detectar_gateway(enlaces_en_html(p.html))
    )
    if chk:
        destino.gateway, destino.checkout = chk
        if chk[0] == "hotmart":
            # un enlace corto hotm.art/<corto> no lleva el código de producto: si la cadena llega a
            # pay.hotmart.com se usa ese; si no, queda el código corto (la oferta puede partirse)
            pay = next((u for u in [*p.cadena, p.url_final] if _host(u) == "pay.hotmart.com"), None)
            if pay:
                destino.checkout = pay
    destino.tracker = detectar_tracker([*p.cadena, *p.peticiones, *urls_en_html(p.html)])
    destino.vsl = p.reproductor
    destino.cloaker, destino.motivo = _cloaker(p.url_final, p, pedir_como_robot, real)

    precio = extraer_precio(p.texto)
    if precio is None and destino.checkout and not es_red_social(destino.checkout) and destino.checkout != p.url_final:
        try:
            precio = extraer_precio(navegador.abrir_landing(destino.checkout).texto)
        except Exception:  # noqa: BLE001 - sin precio del checkout: queda «dudoso»
            precio = None
    if precio:
        destino.precio, destino.moneda = precio
        if destino.moneda is None:
            destino.motivo = "; ".join(m for m in (destino.motivo, "no medido: símbolo $ ambiguo") if m)
    return destino
