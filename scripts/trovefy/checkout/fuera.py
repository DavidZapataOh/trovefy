"""El checkout público visto desde fuera (plan 19, Tarea 12).

Qué hacen los vídeos: comprobar el precio «como Italia» o con una compra de prueba, porque desde Argentina la tienda
sale en USD (V1 0:31:50, A6.5; V1 1:14:15). Aquí, sin sesión en ningún panel (resolución 38):

- **Leer** (`leer_checkout_publico`, `leer_ver_como`): el checkout se pinta con JavaScript (oculta campos, redirige a
  la portada si el producto no tiene precio, añade la barra de «N personas comprando»), así que se abre en Chromium
  con un contexto efímero, sin perfil (``navegador.sesion("comprador", perfil_persistente=False)``), a 390 px. La red
  pasa por `politica_red`: Meta y Clarity silenciados (ningún evento llega al dataset del usuario), pasarelas de pago
  abortadas, nada que no sea GET (ni visitas, ni carritos, ni «preparar pago») y nunca ``fbclid``. Tras la carga se
  marca con ``data-tf-oculto`` lo que no se ve y se guarda el DOM; no se escribe en el formulario ni se pulsa nada.
- **«Ver como <país>»**: el checkout público acepta ``?edit=1&preview_country=<PAIS>`` (la vista previa de la propia
  tienda, sin sesión; comprobado el 2026-11-17): la tienda pinta el precio, la moneda y el idioma del comprador de
  ese país y lo dice en ``buyer-country``. Si la tienda no lo confirma, el precio queda «no medido» y se pide la
  captura de «Ver como Bulgaria» (nunca se adivina).
- **Analizar** (`analizar`, puro): texto visible, campos que se piden, precio y moneda, país visto, idioma,
  order bump, foto arriba. Las cadenas de traducción ocultas de la plataforma y los scripts no cuentan: solo lo
  visible.
- **Comprobar** (`comprobar_fuera`, puro): un `EstadoFuera` por comprobación.
- **Escribir** (`escribir_comprobacion`): ``checkout/<PAIS>/COMPROBACION.md``.

Ojo: la CAPI de Impultienda corre en su servidor y puede emitir eventos por cualquier visita (la skill lo avisa).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from trovefy import navegador
from trovefy.checkout.receta import VERDE, Ajuste
from trovefy.embudo.contexto import ruta_pais
from trovefy.idioma import detectar
from trovefy.landing.constantes import HOSTS_META, casa_host
from trovefy.landing.publicar import AGENTE_NAVEGADOR
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

Estado = Literal["ok", "falla", "no_medido", "parado", "captura", "dicho"]
Fuente = Literal["fuera", "captura", "dicho"]

SERVICIO = "comprador"
VIEWPORT = (390, 844)
TIEMPO_CARGA_MS = 45_000
ESPERA_JS_MS = 3_000
CITA_VER_COMO = "V1 0:31:50"
ARCHIVO = "COMPROBACION.md"
NOMBRES_PAIS = {"BG": "Bulgaria", "RO": "Rumanía", "IT": "Italia", "GR": "Grecia", "HR": "Croacia", "ZZ": "ZZ"}

# --- red del navegador ---------------------------------------------------------------------------------------

SILENCIADOS = (*HOSTS_META, ".clarity.ms")
PASARELAS = ("whop", "stripe", "paypal", "mercadopago", "mercadolibre", "mercadolivre", "dlocal", "impulpay",
             "hotmart", "adyen", "braintree", "klarna", "pagseguro", "checkout.com")
RUTAS_PAGO = ("/functions/v1/",)


def politica_red(url: str, metodo: str) -> Literal["seguir", "abortar"]:
    """Qué hace el navegador del comprador con una petición: ``seguir`` solo un GET que no va a Meta, a Clarity ni a
    una pasarela, que no llama a las funciones de pago de la tienda (``/functions/v1/…``) y que no lleva ``fbclid``.
    Todo lo demás (POST de visitas, carritos, «preparar pago», beacons) se aborta."""
    partes = urlsplit(url)
    if partes.scheme in ("data", "blob"):
        return "seguir"
    host = (partes.hostname or "").lower().rstrip(".")
    if casa_host(host, SILENCIADOS) or any(p in host for p in PASARELAS):
        return "abortar"
    if (metodo or "").upper() != "GET":
        return "abortar"
    if any(r in partes.path for r in RUTAS_PAGO) or "fbclid" in parse_qs(partes.query):
        return "abortar"
    return "seguir"


def proteger(page, abortadas: list[str] | None = None) -> None:
    """La política de red en el **contexto** (también ventanas nuevas, que se cierran) y sin WebSockets."""
    from trovefy.landing.qa import _blindar

    def ruta(route):
        req = route.request
        try:
            de_otra = req.frame.page is not page
        except Exception:  # noqa: BLE001 - sin frame (service worker): fuera
            de_otra = True
        if de_otra or politica_red(req.url, req.method) == "abortar":
            if abortadas is not None:
                abortadas.append(f"{req.method} {req.url.split('?', 1)[0]}")
            route.abort()
            return
        route.continue_()

    _blindar(page)
    page.context.route("**/*", ruta)


MARCAR_OCULTOS = """() => {
  if (!document.body) return 0;
  let n = 0;
  for (const el of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse' ||
        (cs.display !== 'contents' && el.getClientRects().length === 0)) {
      el.setAttribute('data-tf-oculto', '1'); n++;
    }
  }
  return n;
}"""
CONTEXTO = {"service_workers": "block", "is_mobile": True, "has_touch": True, "user_agent": AGENTE_NAVEGADOR}


@dataclass(frozen=True)
class Vista:
    """Lo que devuelve el navegador: la URL final, el código HTTP y el DOM ya pintado y marcado."""

    url_final: str
    http: int | None
    html: str


def _esperar(host: str) -> None:
    navegador.esperar_entre_navegaciones(host)


def abrir_chromium(url: str) -> Vista:
    """Abre `url` como un comprador nuevo (perfil vacío, 390 px, red protegida), espera a que pinte y devuelve el DOM
    con lo oculto marcado. No escribe ni pulsa nada. ``ValueError`` si el navegador falla."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        with navegador.sesion(SERVICIO, visible=False, perfil_persistente=False, viewport=VIEWPORT,
                              _contexto=dict(CONTEXTO)) as page:
            proteger(page)
            resp = page.goto(url, wait_until="load", timeout=TIEMPO_CARGA_MS)
            page.wait_for_timeout(ESPERA_JS_MS)
            page.wait_for_load_state("load", timeout=TIEMPO_CARGA_MS)
            page.evaluate(MARCAR_OCULTOS)
            return Vista(page.url, getattr(resp, "status", None), page.content())
    except (PlaywrightError, navegador.NavegadorError) as exc:
        raise ValueError(f"el navegador no pudo abrir {url.split('?', 1)[0]} ({type(exc).__name__})") from None


# --- analizar (puro) -----------------------------------------------------------------------------------------

_VACIOS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                     "wbr"})
_SIN_TEXTO = frozenset({"script", "style", "template", "noscript", "head", "title"})
_NO_CAMPO = frozenset({"hidden", "radio", "checkbox", "submit", "button", "image", "reset"})
_OCULTOS_UTILES = ("store-name", "store-language", "ebook-title", "ebook-main-price", "ebook-main-override-price",
                   "ebook-currency", "buyer-country", "live-country", "pay-button-color", "market-id")
_GUION = re.compile(r"guion:\s*([a-z_]+)")


@dataclass(frozen=True)
class Imagen:
    src: str
    alt: str
    orden: int


@dataclass(frozen=True)
class PaginaPublica:
    url_final: str
    http: int | None
    texto: str
    campos_obligatorios: tuple[str, ...]
    moneda_vista: str | None
    precio_visto: Decimal | None
    imagenes: tuple[Imagen, ...]
    pedida: str = ""
    pais_visto: str | None = None
    idioma_tienda: str | None = None
    bump: bool = False
    foto_arriba: bool = False
    guion: tuple[str, ...] = ()
    ocultos: dict[str, str] = field(default_factory=dict)
    motivo: str | None = None


def _campo(attrs: dict[str, str]) -> str:
    tipo = (attrs.get("type") or "text").lower()
    claves = " ".join((attrs.get(k) or "").lower() for k in ("autocomplete", "name", "id"))
    reglas = (
        (tipo == "email" or "email" in claves, "email"),
        (tipo == "tel" or bool(re.search(r"\btel\b|phone|telefono", claves)), "telefono"),
        (bool(re.search(r"family-name|last|apellido|surname", claves)), "apellido"),
        (bool(re.search(r"given-name|first|nombre|\bname\b", claves)), "nombre"),
        (bool(re.search(r"country|pais", claves)), "pais"),
        (bool(re.search(r"postal|zip", claves)), "codigo_postal"),
        (bool(re.search(r"address-level2|city|ciudad", claves)), "ciudad"),
        (bool(re.search(r"address-level1|state|provincia", claves)), "provincia"),
        (bool(re.search(r"address|direccion", claves)), "direccion"),
        (bool(re.search(r"cupon|coupon", claves)), "cupon"),
    )
    return next((nombre for cumple, nombre in reglas if cumple), (attrs.get("name") or attrs.get("id") or tipo))


class _Lector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pila: list[tuple[str, bool, bool, bool]] = []  # (etiqueta, oculto, sin_texto, bump)
        self.textos: list[str] = []
        self.campos: list[tuple[int, str]] = []
        self.imagenes: list[Imagen] = []
        self.ocultos: dict[str, str] = {}
        self.guion: list[str] = []
        self.lang: str | None = None
        self.bump = False
        self.orden = 0

    def _estado(self) -> tuple[bool, bool, bool]:
        return (any(f[1] for f in self.pila), any(f[2] for f in self.pila), any(f[3] for f in self.pila))

    def handle_starttag(self, tag, attrs_lista):
        attrs = {k: (v or "") for k, v in attrs_lista}
        self.orden += 1
        oculto_padre, sin_texto_padre, bump_padre = self._estado()
        oculto = oculto_padre or "data-tf-oculto" in attrs or "hidden" in attrs
        marca = f"{attrs.get('id', '')} {attrs.get('class', '')}".lower()
        bump = bump_padre or (not oculto and "bump" in marca)
        if tag == "html":
            self.lang = attrs.get("lang") or None
        if tag == "input" and (attrs.get("type") or "").lower() == "hidden":
            if attrs.get("id") in _OCULTOS_UTILES:
                self.ocultos[attrs["id"]] = attrs.get("value", "").strip()
        elif tag in ("input", "select", "textarea") and not oculto:
            tipo = (attrs.get("type") or "text").lower()
            if bump and tipo == "checkbox":
                self.bump = True
            if tag != "input" or tipo not in _NO_CAMPO:
                self.campos.append((self.orden, _campo(attrs)))
        elif (tag == "img" and not oculto and attrs.get("src")
              and not urlsplit(attrs["src"]).path.lower().endswith(".svg")):
            self.imagenes.append(Imagen(attrs["src"], attrs.get("alt", ""), self.orden))
        if tag not in _VACIOS:
            self.pila.append((tag, oculto, sin_texto_padre or tag in _SIN_TEXTO, bump))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VACIOS and self.pila and self.pila[-1][0] == tag:
            self.pila.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.pila) - 1, -1, -1):
            if self.pila[i][0] == tag:
                del self.pila[i:]
                return

    def handle_data(self, data):
        oculto, sin_texto, bump = self._estado()
        if oculto or sin_texto or not data.strip():
            return
        self.textos.append(data)
        if bump:
            self.bump = True

    def handle_comment(self, data):
        self.guion += _GUION.findall(data)


# Precios: «13,90 €», «EUR 13.9», «US$ 15,29», «1.234,50 €», «0 €».
_NUM = r"\d{1,3}(?:[.,\u00a0\u202f ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEDAS = (("COP", r"CO\$|COP"), ("USD", r"US\$|USD"), ("EUR", r"€|EUR"), ("BGN", r"лв\.?|BGN"),
            ("RON", r"lei|RON"))
_MONEDA = "|".join(f"(?:{p})" for _, p in _MONEDAS)
_PRECIO_MONEDA = re.compile(rf"(?:({_MONEDA})\s?({_NUM}))|(?:({_NUM})\s?({_MONEDA}))", re.IGNORECASE)
_SOLO_NUM = re.compile(rf"(?<![\d.,])({_NUM})(?![\d])")


def _numero(texto: str) -> Decimal | None:
    s = re.sub(r"[\u00a0\u202f ]", "", texto)
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        if re.fullmatch(rf"\d{{1,3}}(?:{re.escape(sep)}\d{{3}})+", s):
            s = s.replace(sep, "")
        else:
            s = s.replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _moneda(texto: str) -> str | None:
    return next((codigo for codigo, patron in _MONEDAS if re.fullmatch(patron, texto, re.IGNORECASE)), None)


def leer_precio(texto: str | None) -> tuple[Decimal | None, str | None]:
    """El primer importe con su moneda («13,90 €» → (13.90, EUR)); sin moneda al lado, el primer número suelto."""
    texto = texto or ""
    m = _PRECIO_MONEDA.search(texto)
    if m:
        moneda, numero = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return _numero(numero), _moneda(moneda)
    m = _SOLO_NUM.search(texto)
    return (_numero(m.group(1)), None) if m else (None, None)


def _vacia(pedida: str, motivo: str) -> PaginaPublica:
    return PaginaPublica(url_final="", http=None, texto="", campos_obligatorios=(), moneda_vista=None,
                         precio_visto=None, imagenes=(), pedida=pedida, motivo=motivo)


def analizar(url_pedida: str, vista: Vista) -> PaginaPublica:
    """La página tal como la ve el comprador, desde el DOM pintado y marcado (puro)."""
    lector = _Lector()
    lector.feed(vista.html or "")
    lector.close()
    texto = re.sub(r"\s+", " ", " ".join(t.strip() for t in lector.textos)).strip()
    oc = lector.ocultos
    moneda = (oc.get("ebook-currency") or "").upper() or None
    bruto = oc.get("ebook-main-override-price") or oc.get("ebook-main-price") or ""
    precio = _numero(bruto) if bruto else None
    if precio is None or moneda is None:
        visto, moneda_texto = leer_precio(texto) if _PRECIO_MONEDA.search(texto) else (None, None)
        precio = precio if precio is not None else visto
        moneda = moneda or moneda_texto
    campos = tuple(dict.fromkeys(c for _, c in lector.campos))
    primer_campo = min((o for o, _ in lector.campos), default=None)
    foto = any(primer_campo is None or i.orden < primer_campo for i in lector.imagenes)
    pais = (oc.get("buyer-country") or oc.get("live-country") or "").upper() or None
    return PaginaPublica(
        url_final=vista.url_final, http=vista.http, texto=texto, campos_obligatorios=campos, moneda_vista=moneda,
        precio_visto=precio, imagenes=tuple(lector.imagenes), pedida=url_pedida, pais_visto=pais,
        idioma_tienda=oc.get("store-language") or lector.lang,
        bump=lector.bump,
        foto_arriba=foto and bool(lector.imagenes), guion=tuple(lector.guion), ocultos=dict(oc),
    )


def ver_como_url(checkout_url: str, pais: str) -> str:
    """La vista pública del checkout como un comprador de `pais` (``?edit=1&preview_country=<PAIS>``)."""
    base = checkout_url.split("#", 1)[0]
    return f"{base}{'&' if '?' in base else '?'}edit=1&preview_country={pais}"


def _leer(url: str, abrir) -> PaginaPublica:
    abrir = abrir or abrir_chromium
    _esperar(urlsplit(url).hostname or "")
    try:
        return analizar(url, abrir(url))
    except (ValueError, OSError) as exc:
        return _vacia(url, f"no medido: {exc}")


def leer_checkout_publico(ctx, abrir=None) -> PaginaPublica:
    """El checkout público (``ctx.checkout_url``) como lo ve un comprador nuevo desde aquí."""
    if not ctx.checkout_url:
        return _vacia("", "no medido: falta checkout_url (landing.yaml o la tienda en config/mercados.yaml)")
    return _leer(ctx.checkout_url, abrir)


def leer_ver_como(ctx, abrir=None) -> PaginaPublica:
    """El checkout público como un comprador de ``ctx.pais`` (`ver_como_url`)."""
    if not ctx.checkout_url:
        return _vacia("", "no medido: falta checkout_url")
    return _leer(ver_como_url(ctx.checkout_url, ctx.pais), abrir)


# --- comprobar (puro) ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EstadoFuera:
    clave: str
    estado: Estado
    esperado: str
    visto: str | None
    detalle: str
    fuente: Fuente | None = None
    evidencia: str | None = None


def nombre_pais(pais: str) -> str:
    return NOMBRES_PAIS.get(pais, pais)


def hosts_de_la_tienda(ctx) -> set[str]:
    """Los hosts que sirven la tienda: el de ``tienda``/``checkout_url`` y, si la landing la sirve Impultienda, el
    de su dominio propio (con y sin ``www.``)."""
    hosts = {urlsplit(u).hostname for u in (getattr(ctx, "tienda", None), ctx.checkout_url) if u}
    if getattr(ctx, "landing_hosting", None) == "impultienda" and getattr(ctx, "landing_url", None):
        h = urlsplit(ctx.landing_url).hostname
        if h:
            hosts |= {h, h.removeprefix("www."), "www." + h.removeprefix("www.")}
    return {h for h in hosts if h}


def _es_checkout(p: PaginaPublica | None, ctx) -> bool:
    if p is None or p.motivo or not p.url_final or not ctx.checkout_url:
        return False
    a, b = urlsplit(p.url_final), urlsplit(ctx.checkout_url)
    return a.hostname in hosts_de_la_tienda(ctx) and a.path.rstrip("/") == b.path.rstrip("/")


def _precio_txt(precio: Decimal | None, moneda: str | None) -> str | None:
    if precio is None:
        return None
    return f"{str(precio).replace('.', ',')} {moneda or '¿?'}"


def _relectura_ok(relecturas, claves: tuple[str, ...]) -> bool:
    for r in relecturas or ():
        ajuste = getattr(r, "ajuste", None)
        clave = getattr(ajuste, "clave", ajuste)
        if clave in claves and getattr(r, "estado", None) == "ok":
            return True
    return False


def _ultima(indice: dict, clave: str, tipos: tuple[str, ...]):
    return next((p for p in reversed(indice.get(clave, [])) if p.tipo in tipos), None)


def _precio_por_captura(ctx, esperado: Decimal, indice: dict, relecturas, base: str) -> EstadoFuera:
    clave, esperado_txt = "producto.front.precio", _precio_txt(esperado, ctx.moneda)
    cap = _ultima(indice, "ver-como", ("captura",))
    if cap is None or not cap.valores.get("precio"):
        return EstadoFuera(clave, "no_medido", esperado_txt, None, base)
    visto, moneda = leer_precio(cap.valores["precio"])
    moneda = (cap.valores.get("moneda") or moneda or "").upper() or None
    visto_txt = _precio_txt(visto, moneda)
    if visto != esperado or (moneda and moneda != ctx.moneda):
        return EstadoFuera(clave, "falla", esperado_txt, visto_txt,
                           f"la captura de «Ver como {nombre_pais(ctx.pais)}» muestra {visto_txt}", "captura", cap.ruta)
    if not _relectura_ok(relecturas, (clave, f"market.{ctx.pais}.precio_front")):
        return EstadoFuera(clave, "no_medido", esperado_txt, visto_txt,
                           f"la captura cuadra; falta la relectura del MCP del precio del mercado {ctx.pais} "
                           "(trovefy checkout releer)", None, cap.ruta)
    return EstadoFuera(clave, "captura", esperado_txt, visto_txt,
                       f"captura de «Ver como {nombre_pais(ctx.pais)}» y relectura del MCP", "captura", cap.ruta)


def _precio(ctx, ajuste: Ajuste, base: PaginaPublica | None, del_pais: bool, plano: PaginaPublica,
            indice: dict, relecturas, motivo: str | None = None) -> EstadoFuera:
    clave = "producto.front.precio"
    try:
        esperado = Decimal(str(ajuste.valor)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return EstadoFuera(clave, "no_medido", str(ajuste.valor), None, "no medido: precio de la receta ilegible")
    esperado_txt = _precio_txt(esperado, ctx.moneda)
    if base is not None and del_pais and base.moneda_vista == ctx.moneda:
        visto_txt = _precio_txt(base.precio_visto, base.moneda_vista)
        if base.precio_visto == esperado:
            return EstadoFuera(clave, "ok", esperado_txt, visto_txt, "precio y moneda del país", "fuera",
                               base.url_final)
        return EstadoFuera(clave, "falla", esperado_txt, visto_txt, f"el checkout cobra {visto_txt}", "fuera",
                           base.url_final)
    moneda = (base or plano).moneda_vista
    motivo = motivo or (f"no medido: la tienda te muestra {moneda or 'otra moneda'} desde tu IP: pega la captura de "
              f"«Ver como {nombre_pais(ctx.pais)}» ({CITA_VER_COMO}) con trovefy checkout evidencia --clave ver-como "
              "--valor precio=…")
    return _precio_por_captura(ctx, esperado, indice, relecturas, motivo)


def _campos(ajuste: Ajuste, base: PaginaPublica) -> EstadoFuera:
    esperados = [c.strip() for c in str(ajuste.valor).split(",") if c.strip()]
    vistos = list(base.campos_obligatorios)
    de_mas = [c for c in vistos if c not in esperados]
    faltan = [c for c in esperados if c not in vistos]
    problemas = ([f"pide de más: {', '.join(de_mas)}"] if de_mas else []) + (
        [f"no pide: {', '.join(faltan)}"] if faltan else [])
    return EstadoFuera("checkout.campos", "falla" if problemas else "ok", ",".join(esperados), ",".join(vistos),
                       "; ".join(problemas) or "solo los datos de la receta", "fuera", base.url_final)


def _idioma(ctx, base: PaginaPublica | None, del_pais: bool, plano: PaginaPublica) -> EstadoFuera:
    clave = "checkout.idioma"
    if base is None or not del_pais:
        visto = (base or plano).idioma_tienda
        return EstadoFuera(clave, "no_medido", ctx.idioma, visto,
                           f"no medido: desde tu IP la tienda sale en «{visto or '¿?'}» (se traduce según el país "
                           f"del comprador): se mira con «Ver como {nombre_pais(ctx.pais)}»")
    detectado = detectar(base.texto, [ctx.idioma, "es", "en"])
    tienda = (base.idioma_tienda or "").split("-")[0].lower() or None
    if detectado == ctx.idioma or (detectado is None and tienda == ctx.idioma):
        detalle = "el texto visible" if detectado else "el idioma de la tienda (texto corto)"
        return EstadoFuera(clave, "ok", ctx.idioma, detectado or tienda, detalle, "fuera", base.url_final)
    if detectado is None and tienda is None:
        return EstadoFuera(clave, "no_medido", ctx.idioma, None, "no medido: el texto no basta para saber el idioma")
    return EstadoFuera(clave, "falla", ctx.idioma, detectado or tienda, "el checkout sale en otro idioma", "fuera",
                       base.url_final)


def comprobar_fuera(ctx, ajustes: list[Ajuste], pagina: PaginaPublica, indice: dict, *,
                    ver_como: PaginaPublica | None = None, relecturas=None) -> list[EstadoFuera]:
    """Lo que se ve en el checkout público frente a la receta: precio y moneda (regla de la moneda: desde otro país
    es «no medido» salvo que la vista pública como ``ctx.pais`` lo confirme o haya captura de «Ver como …» más la
    relectura del MCP), idioma, campos (los de más fallan, el teléfono se pide), order bump (no), foto arriba,
    título, nombre de la tienda y color del botón."""
    por_clave = {a.clave: a for a in ajustes}
    plano_ok = _es_checkout(pagina, ctx)
    vc_ok = _es_checkout(ver_como, ctx) and ver_como.pais_visto == ctx.pais
    base = ver_como if vc_ok else (pagina if plano_ok else None)
    del_pais = vc_ok or (plano_ok and pagina.pais_visto in (None, ctx.pais))

    if base is None:
        if pagina.motivo:
            motivo = pagina.motivo
        else:
            final = urlsplit(pagina.url_final or "").path or "?"
            motivo = (f"no medido: el checkout redirige a «{final}» (¿el producto no tiene precio todavía?): "
                      "vuelve tras aplicar el plan del MCP")
        claves = ["producto.front.precio", "checkout.idioma", "checkout.campos", "checkout.bump",
                  *(c for c in ("checkout.foto", "producto.front.titulo", "tienda.nombre", "checkout.boton")
                    if c in por_clave)]
        precio = por_clave.get("producto.front.precio")
        salida = [EstadoFuera(c, "no_medido", "", None, motivo) for c in claves if c != "producto.front.precio"]
        if precio is not None:
            salida.insert(0, _precio(ctx, precio, None, False, pagina, indice, relecturas,
                                     f"{motivo}; o pega la captura de «Ver como {nombre_pais(ctx.pais)}» "
                                     f"({CITA_VER_COMO})"))
        return salida

    estados: list[EstadoFuera] = []
    if "producto.front.precio" in por_clave:
        estados.append(_precio(ctx, por_clave["producto.front.precio"], base, del_pais, pagina, indice, relecturas))
    estados.append(_idioma(ctx, base, del_pais, pagina))
    if "checkout.campos" in por_clave:
        # «Ver como <país>» (?edit=1) es la vista del editor y enseña todos los campos aunque estén apagados:
        # los campos se miden en el checkout tal cual, si se pudo leer.
        estados.append(_campos(por_clave["checkout.campos"], pagina if plano_ok else base))
    estados.append(EstadoFuera("checkout.bump", "falla" if base.bump else "ok", "sin order bump",
                               "hay order bump" if base.bump else None,
                               "el checkout ofrece un order bump (los vídeos no lo ponen, V1 0:38:35)" if base.bump
                               else "sin order bump", "fuera", base.url_final))
    if "checkout.foto" in por_clave:
        estados.append(EstadoFuera("checkout.foto", "ok" if base.foto_arriba else "falla", "foto arriba",
                                   base.imagenes[0].src.split("?", 1)[0] if base.imagenes else None,
                                   "foto antes de los datos" if base.foto_arriba else "no hay foto antes de los datos",
                                   "fuera", base.url_final))
    titulo = por_clave.get("producto.front.titulo")
    if titulo is not None:
        esta = str(titulo.valor).casefold() in base.texto.casefold()
        estados.append(EstadoFuera("producto.front.titulo", "ok" if esta else "falla", str(titulo.valor),
                                   base.ocultos.get("ebook-title"),
                                   "el título se ve" if esta else "el título del producto no aparece", "fuera",
                                   base.url_final))
    for clave, oculto, normal in (("tienda.nombre", "store-name", str.casefold),
                                  ("checkout.boton", "pay-button-color", str.casefold)):
        ajuste = por_clave.get(clave)
        if ajuste is None:
            continue
        esperado = VERDE if clave == "checkout.boton" else str(ajuste.valor)
        visto = base.ocultos.get(oculto)
        if not visto:
            estados.append(EstadoFuera(clave, "no_medido", esperado, None, f"no medido: la página no dice {oculto}"))
            continue
        igual = normal(visto) == normal(esperado)
        estados.append(EstadoFuera(clave, "ok" if igual else "falla", esperado, visto,
                                   "igual" if igual else "distinto", "fuera", base.url_final))
    return estados


def estado_global(estados: list[EstadoFuera]) -> Literal["completo", "a_medias", "parado"]:
    if any(e.estado == "parado" for e in estados):
        return "parado"
    if estados and all(e.estado in ("ok", "captura", "dicho") for e in estados):
        return "completo"
    return "a_medias"


# --- escribir --------------------------------------------------------------------------------------------------


def _celda(texto: object) -> str:
    return str(texto if texto not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def escribir_comprobacion(vault: Path, ctx, estados: list[EstadoFuera], manuales: list[EstadoFuera],
                          ahora: datetime) -> Path:
    """``checkout/<PAIS>/COMPROBACION.md``: frontmatter (``estado`` completo|a_medias|parado, fecha, url del checkout
    sin query, estados) y la tabla «ajuste · pedido · visto · estado · fuente · evidencia», con «A medias» y «A mano».
    ``ValueError`` (sin escribir) si algo tiene forma de secreto."""
    todos = [*estados, *manuales]
    estado = estado_global(todos)
    fecha = ahora.astimezone(ZONA_NEGOCIO).isoformat(timespec="seconds")
    url = (ctx.checkout_url or "").split("?", 1)[0] or None
    meta = {"tipo": "comprobacion_checkout", "producto": ctx.producto, "pais": ctx.pais, "estado": estado,
            "fecha": fecha, "url": url,
            "estados": [*({**asdict(e), "origen": "fuera"} for e in estados),
                        *({**asdict(e), "origen": "manual"} for e in manuales)]}
    filas = ["| ajuste | pedido | visto | estado | fuente | evidencia |", "|---|---|---|---|---|---|"]
    filas += [f"| {_celda(e.clave)} | {_celda(e.esperado)} | {_celda(e.visto)} | {e.estado} | {_celda(e.fuente)} | "
              f"{_celda(e.evidencia)} |" for e in todos]
    medias = [f"- {e.clave}: {e.detalle}" for e in estados if e.estado not in ("ok", "captura", "dicho")]
    mano = [f"- {e.clave} ({e.estado}): {e.detalle}" for e in manuales]
    cuerpo = "\n".join([f"# Checkout {ctx.pais} visto desde fuera", "", f"Estado: **{estado}**.", "", *filas, "",
                        "## A medias", "", *(medias or ["- nada"]), "", "## A mano", "", *(mano or ["- nada"]), ""])
    texto = frontmatter.renderizar(meta, cuerpo)
    patron = buscar_secreto(texto)
    if patron:
        raise ValueError(f"la comprobación lleva algo con forma de secreto ({patron}): no se guarda")
    ruta = ruta_pais(ctx) / ARCHIVO
    escribir_atomico(ruta, texto)
    anadir_log(Path(vault), "checkout", f"{ctx.producto} {ctx.pais}: checkout comprobado desde fuera ({estado})",
               [ruta.relative_to(Path(vault)).as_posix()], ahora=ahora)
    return ruta
