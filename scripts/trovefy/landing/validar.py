"""Validación estática de ``landing/<PAIS>/`` (``html.parser``): estructura, botones, idioma, prueba social y
origen de todo. Cada fallo es una frase que dice qué y dónde; los avisos no bloquean.

Modelo positivo (lista blanca): solo pasan las etiquetas de :data:`ETIQUETAS` y, en cada una, los atributos
de :data:`ATRIBUTOS_GLOBALES` y :data:`ATRIBUTOS`. Todo lo demás (``<base>``, ``<noscript>``, ``<svg>``,
``ping``, ``background``, ``imagesrcset``…) falla sin tener que conocerlo de antemano. Los únicos atributos
con URL son ``href``, ``src`` y ``srcset``, y cada valor se revisa como lo leería un navegador (sin
espacios ni saltos, ``\\`` como ``/``): lo que lleva esquema o empieza por ``//`` solo vale si es https al
dominio propio o a la tienda, el checkout o un ``mailto:`` (R3); un recurso que se carga va siempre en
``assets/``. El CSS (``assets/estilo.css``, ``<style>`` y ``style=``) se lee sin comentarios y con los
escapes resueltos, y no puede nombrar ``http:``, ``https:`` ni ``//``.

Prueba social solo real (D-01): una reseña entra solo desde ``resenas.yaml`` con :func:`anadir_resena`
(fecha, país y fuente: el pedido o el email de origen). Fuera de ``data-tf-resena`` no hay testimonios
(``blockquote``, ``q``, ``cite``) ni contadores (``meter``, ``progress``); en ningún texto (título,
descripción, texto visible, ``alt``, ``aria-label`` y ``content:`` del CSS) hay estrellas, notas «4,9/5»,
cupos, compradores, cuentas atrás ni importes que no sean el precio real (:func:`prueba_social_falsa`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from trovefy.landing.constantes import SECCIONES_MAX, SECCIONES_MIN
from trovefy.landing.diacriticos import revisar_texto
from trovefy.landing.entrada import (
    DatosLanding,
    EntradaInvalida,
    leer_resenas,
    resena_completa,
    ruta_landing,
)
from trovefy.landing.medios import FIJOS, MANIFIESTO, ORIGENES, VISTAS
from trovefy.landing.plantilla import (
    UTM_JS,
    host_tienda,
    leer_landing_yaml,
    pixel_js,
    precio_texto,
    version_de,
)
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import secreto_en

PERMITIDAS_FIJAS = frozenset({"PDF", "A4"})
# Marcas de pago que una landing nombra tal cual (no cuentan contra la escritura del idioma).
MARCAS_PAGO = ("Visa", "Mastercard", "Maestro", "PayPal", "Apple Pay", "Google Pay", "Impul Pay", "Stripe",
               "Revolut")
DESCRIPCION_MAX = 160  # caracteres que muestran los buscadores
LARGO_MIN, LARGO_MAX = 0.5, 2.0  # fracción de las palabras de la referencia (aviso)
PIXEL_JS = "pixel.js"  # resolución 23: solo en la ruta Cloudflare
HOSTS_PIXEL = frozenset({"connect.facebook.net", "www.facebook.com"})  # los que contacta pixel.js; en el HTML no

# --- lista blanca -----------------------------------------------------------------------------------------
ETIQUETAS = frozenset({
    "html", "head", "body", "title", "meta", "link", "script", "style",
    "main", "header", "footer", "nav", "section", "article", "aside", "div", "span",
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "ul", "ol", "li", "dl", "dt", "dd",
    "strong", "em", "b", "i", "u", "small", "mark", "sub", "sup", "abbr", "time",
    "img", "picture", "source", "figure", "figcaption", "a",
    "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td", "colgroup", "col", "details", "summary",
    "blockquote", "q", "cite", "meter", "progress",  # solo dentro de data-tf-resena (D-01)
})
ATRIBUTOS_GLOBALES = frozenset({
    "id", "class", "style", "role", "aria-label", "aria-hidden", "aria-labelledby", "aria-describedby",
    "data-tf-hito", "data-tf-precio", "data-tf-formato", "data-tf-garantia", "data-tf-resena", "data-tf-nota",
})
ATRIBUTOS: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in {
    "html": {"lang"},
    "meta": {"charset", "name", "content", "http-equiv"},
    "link": {"rel", "href"},
    "script": {"src", "defer"},
    "main": {"data-tf-version"},
    "section": {"data-tf-seccion", "data-tf-tipo"},
    "a": {"href", "data-tf-checkout", "rel", "target"},
    "img": {"src", "srcset", "sizes", "alt", "width", "height", "loading", "decoding", "fetchpriority",
            "data-tf-vista"},
    "source": {"srcset", "sizes", "media", "type", "width", "height"},
    "ol": {"start", "reversed"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "time": {"datetime"},
    "details": {"open"},
    "meter": {"value", "min", "max", "low", "high", "optimum"},
    "progress": {"value", "max"},
}.items()}
_ATRIBUTOS_URL = frozenset({"href", "src", "srcset"})
_META_NOMBRES = frozenset({"description", "viewport", "robots", "theme-color"})
_SOLO_EN_RESENA = frozenset({"blockquote", "q", "cite", "meter", "progress"})
_VACIOS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                     "wbr"})
# Su contenido no se ve (o es texto crudo para el parser: con scripting=True, también <noscript>).
_INVISIBLES = frozenset({"head", "title", "script", "style", "noscript", "template", "xmp", "noembed", "noframes",
                         "iframe", "textarea", "plaintext"})
_ESPACIO_URL = "".join(chr(i) for i in range(0x21))  # lo que un navegador quita de los extremos de una URL

# --- CSS ----------------------------------------------------------------------------------------------------
_COMENTARIO_CSS = re.compile(r"/\*.*?\*/", re.DOTALL)
_ESCAPE_CSS = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|(\r\n|[\n\r\f])|(.))", re.DOTALL)
_REMOTO_CSS = re.compile(r"https?:|//", re.IGNORECASE)
_PELIGRO_CSS = re.compile(r"@import|expression\s*\(|behavior\s*:|-moz-binding|javascript:", re.IGNORECASE)
_URL_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_IMAGE_SET = re.compile(r"image-set\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
_CADENA_CSS = re.compile(r"(['\"])(.*?)\1", re.DOTALL)
_CONTENT_CSS = re.compile(r"(?<![\w-])content\s*:\s*([^;}]*)", re.IGNORECASE)
_REGLA_CSS = re.compile(r"([^{}]*)\{([^{}]*)\}")
_OVERFLOW_CSS = re.compile(r"(?<![\w-])overflow(-x)?\s*:\s*([^;}]*)", re.IGNORECASE)
_SUJETO_RAIZ = re.compile(r"(?:html|body|\*|:root)(?![\w-])", re.IGNORECASE)
_COMBINADOR = re.compile(r"\s*[>+~]\s*|\s+")
_MENSAJE_OVERFLOW = ("overflow oculto en html/body esconde los desbordes (la QA no los vería): quítalo y mete lo ancho "
                     "en un contenedor con overflow-x:auto")

# --- prueba social (D-01) -----------------------------------------------------------------------------------
_ESTRELLAS = re.compile("[★☆✩✪✫✬✭✮✯✰⋆⭑⭒⭐\U0001f31f]+")
_NOTA = re.compile(r"(?<!\d)\d[,.]\d\s*/\s*5(?!\d)")
_TEMPORIZADOR = re.compile(r"(?<!\d)\d{1,2}:\d{2}:\d{2}(?!\d)")
_NUM = r"\d{1,3}(?:[   .]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEDA_TRAS = r"€|\$|£|eur\b|euro\b|евро\b|лв\b\.?|лева\b|bgn\b|lei\b|leu\b|ron\b|usd\b|gbp\b"
_MONEDA_ANTES = r"€|\$|£|eur\b|bgn\b|ron\b|usd\b|gbp\b"
_IMPORTE = re.compile(rf"(?<![\w.,])(?:({_NUM})\s*(?:{_MONEDA_TRAS})|(?:{_MONEDA_ANTES})\s*({_NUM})(?!\d))",
                      re.IGNORECASE)
_CEDILLA = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})
# Cupos, escasez, compradores y prisa, por idioma (en minúsculas; se comparan sin mayúsculas).
PRESION_POR_IDIOMA: dict[str, tuple[str, ...]] = {
    "bg": (
        r"остава(?:т)?\s+(?:само|още|последни)", r"\bброя\b", r"\bбройки\b", r"последн\w+\s+\d+",
        r"ограничен\w*\s+(?:брой|количеств\w*|наличност\w*|оферт\w*|тираж\w*)", r"изчерпва",
        r"души\s+(?:\w+\s+)?купиха", r"купувач\w*", r"\d[\d  .,]*\s+(?:души|клиенти|човека)\b",
        r"продаден\w*|продадоха", r"изтича", r"само\s+днес", r"до\s+полунощ",
    ),
    "ro": (
        r"au\s+mai\s+rămas", r"rămas\w*\s+doar", r"\bbucăți\b", r"stoc\s+limitat", r"ofert\w+\s+limitat\w*",
        r"ultimel?e\s+\d+", r"\d[\d  .,]*\s+(?:de\s+)?(?:persoane|clienți|cumpărători)\b", r"cumpărători",
        r"au\s+cumpărat", r"vândut\w*", r"expiră", r"doar\s+(?:azi|astăzi)", r"miezul\s+nopții",
    ),
}
_PRESION = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in PRESION_POR_IDIOMA.items()}

_PAGINAS = re.compile(r"(\d+)\s*(?:страниц|pagin|págin|page)", re.IGNORECASE)
_EVENTO_PIXEL = re.compile(r"fbq\(\s*['\"](?:track|trackCustom|trackSingle)['\"]\s*,\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class Resultado:
    ok: bool
    fallos: tuple[str, ...]
    avisos: tuple[str, ...]


@dataclass(eq=False)  # se compara por identidad: dos secciones iguales siguen siendo dos
class _Seccion:
    orden: str
    tipo: str
    hitos: int = 0
    botones: list[str] = field(default_factory=list)
    texto: list[str] = field(default_factory=list)
    vistas: int = 0


@dataclass
class _Abierta:
    tag: str
    capturas: list[str]
    seccion: _Seccion | None
    resena: bool


def _importe(texto: str) -> Decimal | None:
    t = re.sub(r"[   ]", "", texto)
    m = re.search(r"[.,](\d{1,2})$", t)
    entero, dec = (t[:m.start()], m.group(1)) if m else (t, "0")
    try:
        return Decimal(re.sub(r"[.,]", "", entero) + "." + dec)
    except InvalidOperation:
        return None


def prueba_social_falsa(texto: str, idioma: str, precio: Decimal) -> list[str]:
    """Lo que en ``texto`` parece prueba social o presión inventada (D-01): estrellas, notas «4,9/5», cuentas
    atrás, cupos y compradores (patrones de :data:`PRESION_POR_IDIOMA`) e importes con moneda que no son
    ``precio``. Cada entrada dice qué y lo cita; ``[]`` si no hay nada."""
    texto = " ".join((texto or "").translate(_CEDILLA).split())
    hallazgos = [f"estrellas «{m.group(0)}»" for m in _ESTRELLAS.finditer(texto)]
    hallazgos += [f"nota «{m.group(0)}»" for m in _NOTA.finditer(texto)]
    hallazgos += [f"cuenta atrás «{m.group(0)}»" for m in _TEMPORIZADOR.finditer(texto)]
    for patron in _PRESION.get(idioma, ()):
        hallazgos += [f"«{m.group(0)}»" for m in patron.finditer(texto)]
    for m in _IMPORTE.finditer(texto):
        valor = _importe(m.group(1) or m.group(2))
        if valor is None or valor != precio:
            hallazgos.append(f"importe «{m.group(0).strip()}» que no es el precio "
                             f"({f'{precio:.2f}'.replace('.', ',')})")
    return list(dict.fromkeys(hallazgos))


def _url_normal(url: str) -> str:
    """La URL como la lee un navegador: sin espacios ni controles en los extremos, sin tabuladores ni saltos
    dentro y con ``\\`` como ``/``."""
    return re.sub(r"[\t\n\r]", "", url.strip(_ESPACIO_URL)).replace("\\", "/")


def _en_assets(url: str) -> str | None:
    """Nombre del archivo si ``url`` es ``assets/<archivo>`` relativo; si no, ``None``."""
    sp = urlsplit(_url_normal(url))
    ruta = unquote(sp.path)
    if sp.scheme or sp.netloc or not ruta.startswith("assets/"):
        return None
    nombre = ruta[len("assets/"):]
    return nombre if nombre and "/" not in nombre and nombre not in (".", "..") else None


class _Lector(HTMLParser):
    """Recorre el HTML una vez: anota lo que se sale de la lista blanca y guarda lo que comprueban las reglas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True, scripting=True)
        self.pila: list[_Abierta] = []
        self.lang: str | None = None
        self.titulo: list[str] | None = None
        self.descripcion: str | None = None
        self.versiones: list[str] = []
        self.secciones: list[_Seccion] = []
        self.botones: list[tuple[int | None, str]] = []  # (índice de sección, href)
        self.capturas: dict[str, list[list[str]]] = {"precio": [], "formato": [], "garantia": [], "resena": [], "nota": []}
        self.resenas: list[str] = []
        self.urls: list[tuple[str, str, bool]] = []  # (dónde, url, es recurso que se carga)
        self.vistas_urls: list[str] = []  # src y srcset de img[data-tf-vista]
        self.scripts: list[tuple[str | None, bool]] = []  # (src, lleva código en línea)
        self.fuera: list[str] = []  # lo que se sale de la lista blanca
        self.d01: list[str] = []  # testimonios o contadores fuera de data-tf-resena
        self.estilos: list[tuple[str, str]] = []  # (dónde, CSS)
        self.visible: list[str] = []
        self.visible_libre: list[str] = []  # visible fuera de las reseñas reales
        self.visible_resena: list[str] = []
        self.aria: list[str] = []

    # -- utilidades
    def _seccion(self) -> _Seccion | None:
        return next((a.seccion for a in reversed(self.pila) if a.seccion is not None), None)

    def _dentro(self, *tags: str) -> bool:
        return any(a.tag in tags for a in self.pila)

    def _en_resena(self) -> bool:
        return any(a.resena for a in self.pila)

    def _atributos(self, tag: str, attrs) -> dict[str, str]:
        a: dict[str, str] = {}
        permitidos = ATRIBUTOS_GLOBALES | ATRIBUTOS.get(tag, frozenset())
        for k, val in attrs:
            if k in a:
                self.fuera.append(f"atributo {k} repetido en <{tag}>")
                continue
            a[k] = val or ""
            if k.startswith("on"):
                self.fuera.append(f"manejador {k} en <{tag}>: no va en la landing (sin JS en línea)")
            elif tag in ETIQUETAS and k not in permitidos:
                self.fuera.append(f"atributo {k} en <{tag}>: fuera de la lista blanca de la landing")
        return a

    def _reglas_de_etiqueta(self, tag: str, a: dict[str, str]) -> None:
        if tag not in ETIQUETAS:
            self.fuera.append(f"<{tag}>: no va en la landing (fuera de la lista blanca)")
            return
        if tag == "meta":
            equiv, nombre = a.get("http-equiv"), a.get("name")
            if equiv is not None and equiv.strip().lower() != "content-type":
                self.fuera.append(f'<meta http-equiv="{equiv}">: solo http-equiv="content-type"')
            if nombre is not None and nombre.strip().lower() not in _META_NOMBRES:
                self.fuera.append(f'<meta name="{nombre}">: solo {", ".join(sorted(_META_NOMBRES))}')
            if "charset" not in a and nombre is None and equiv is None:
                self.fuera.append("<meta> sin charset, name ni http-equiv")
        if tag == "link" and a.get("rel", "").strip().lower() != "stylesheet":
            self.fuera.append(f'<link rel="{a.get("rel", "")}">: solo rel="stylesheet" (a assets/)')
        if tag in _SOLO_EN_RESENA and not ("data-tf-resena" in a or "data-tf-nota" in a or self._en_resena()):
            self.d01.append(f"<{tag}> fuera de data-tf-resena: testimonios y contadores solo de reseñas reales (D-01)")

    def handle_starttag(self, tag, attrs):
        a = self._atributos(tag, attrs)
        self._reglas_de_etiqueta(tag, a)
        if "style" in a:
            self.estilos.append(("estilo en línea", a["style"]))
            if tag in ("html", "body") and (decl := overflow_oculto(
                    _desescapar_css(_COMENTARIO_CSS.sub(" ", a["style"])))) is not None:
                self.fuera.append(f"<{tag}> con style «{decl}»: {_MENSAJE_OVERFLOW}")
        if "aria-label" in a:
            self.aria.append(a["aria-label"])
        if tag == "html" and "lang" in a:
            self.lang = a["lang"]
        if tag == "title":
            self.titulo = []
        if tag == "meta" and a.get("name", "").strip().lower() == "description":
            self.descripcion = a.get("content", "")
        if tag == "main" and a.get("id") == "tf-landing" and "data-tf-version" in a:
            self.versiones.append(a["data-tf-version"])
        if tag == "script":
            self.scripts.append((a.get("src"), False))
        seccion_nueva = None
        if tag == "section" and "data-tf-seccion" in a:
            seccion_nueva = _Seccion(a["data-tf-seccion"], a.get("data-tf-tipo", ""))
            self.secciones.append(seccion_nueva)
        actual = seccion_nueva or self._seccion()
        if "data-tf-hito" in a and actual is not None:
            actual.hitos += 1
        if tag == "a" and "data-tf-checkout" in a:
            if "target" in a and a["target"].strip().lower() != "_self":
                self.fuera.append(f'target="{a["target"]}" en a[data-tf-checkout]: el botón de compra abre en la '
                                  "misma pestaña (sin target, o _self)")
            href = a.get("href", "")
            idx = next((i for i, s in enumerate(self.secciones) if s is actual), None)
            self.botones.append((idx, href))
            if actual is not None:
                actual.botones.append(href)
        resena = "data-tf-resena" in a or "data-tf-nota" in a or self._en_resena()
        if tag == "img" and "data-tf-vista" in a and actual is not None:
            actual.vistas += 1
        if tag == "img" and a.get("alt"):
            if actual is not None:
                actual.texto.append(a["alt"])
            self.visible.append(a["alt"])
            (self.visible_resena if resena else self.visible_libre).append(a["alt"])
        for k in _ATRIBUTOS_URL & a.keys():
            carga = not (tag == "a" and k == "href")
            partes = [p.strip().split()[0] for p in a[k].split(",") if p.strip()] if k == "srcset" else [a[k]]
            for url in partes:
                self.urls.append((f"{k} de <{tag}>", url, carga))
                if tag == "img" and "data-tf-vista" in a:
                    self.vistas_urls.append(url)
        if "data-tf-resena" in a:
            self.resenas.append(a["data-tf-resena"])
        capturas = []
        for clave in ("precio", "formato", "garantia", "resena", "nota"):
            if f"data-tf-{clave}" in a:
                self.capturas[clave].append([a[f"data-tf-{clave}"]] if clave == "resena" else [])
                capturas.append(clave)
        if tag not in _VACIOS:
            self.pila.append(_Abierta(tag, capturas, seccion_nueva, "data-tf-resena" in a or "data-tf-nota" in a))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VACIOS and self.pila and self.pila[-1].tag == tag:
            self.pila.pop()

    def handle_endtag(self, tag):
        if not self._dentro(tag):
            return
        while self.pila:
            if self.pila.pop().tag == tag:
                break

    def handle_data(self, data):
        if self.titulo is not None and self._dentro("title"):
            self.titulo.append(data)
        if self._dentro("script") and data.strip() and self.scripts:
            src, _ = self.scripts[-1]
            self.scripts[-1] = (src, True)
        if self._dentro("style"):
            self.estilos.append(("<style>", data))
        if any(a.tag in _INVISIBLES for a in self.pila):
            return
        self.visible.append(data)
        (self.visible_resena if self._en_resena() else self.visible_libre).append(data)
        s = self._seccion()
        if s is not None:
            s.texto.append(data)
        for a in self.pila:
            for clave in a.capturas:
                self.capturas[clave][-1].append(data)

    def handle_decl(self, decl):
        if " ".join(decl.split()).lower() != "doctype html":
            self.fuera.append(f"<!{decl}>: solo <!DOCTYPE html>")

    def handle_pi(self, data):
        self.fuera.append(f"<?{data[:40]}>: instrucción de proceso: no va en la landing")

    def unknown_decl(self, data):
        self.fuera.append(f"<![{data[:40]}]>: no va en la landing")


def _palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto))


def _limpio(partes: list[str]) -> str:
    return " ".join(" ".join(partes).split())


def _leer_yaml(ruta: Path) -> dict | None:
    if ruta.is_symlink() or not ruta.is_file():
        return None
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return datos if isinstance(datos, dict) else None


def _leer_json(ruta: Path) -> dict | None:
    if ruta.is_symlink():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


class _Origen:
    """Qué URL puede aparecer: relativa (lo que se carga, solo bajo ``assets/``), ``#…``, el checkout, https al
    dominio propio o a la tienda (si es válida, M10) y ``mailto:`` (R3). Nada más con esquema o ``//``."""

    def __init__(self, checkout: str, dominio: str | None, tienda: str | None) -> None:
        self.checkout = checkout
        self.hosts = {h.lower() for h in (dominio, f"www.{dominio}" if dominio else None, host_tienda(tienda)) if h}

    def motivo(self, url: str, carga: bool) -> str | None:
        u = _url_normal(url)
        if not carga and (u.startswith("#") or (u and u == self.checkout)):
            return None
        if not u:
            return "vacía: un recurso propio va dentro de assets/" if carga else None
        try:
            sp = urlsplit(u)
            puerto = sp.port
        except ValueError:
            return "URL mal escrita"
        if sp.scheme or sp.netloc or u.startswith("//"):
            if carga:
                return "un recurso propio va dentro de assets/ (relativo), nunca de otro origen"
            if sp.scheme == "mailto" and not sp.netloc and "@" in sp.path:
                return None
            if (sp.scheme == "https" and sp.hostname in self.hosts and sp.username is None and sp.password is None
                    and puerto in (None, 443)):
                return None
            return "origen no permitido (solo relativo, el dominio propio, la tienda, el checkout o mailto:)"
        if carga and _en_assets(u) is None:
            return "un recurso propio va dentro de assets/ (relativo, sin .. ni subcarpetas)"
        return None


def _desescapar_css(css: str) -> str:
    def cambio(m: re.Match) -> str:
        if m.group(1):
            n = int(m.group(1), 16)
            return chr(n) if 0 < n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else "�"
        return "" if m.group(2) else m.group(3)

    return _ESCAPE_CSS.sub(cambio, css)


def _contexto(texto: str, m: re.Match) -> str:
    return " ".join(texto[max(0, m.start() - 25):m.end() + 35].split())


def _url_css_mala(u: str) -> str | None:
    u = u.strip()
    if not u:
        return None
    if u.lower().startswith("data:"):
        return f"«{u[:40]}…»: sin data: en el CSS"
    partes = u.replace("\\", "/").split("/")
    if ":" in partes[0] or u.startswith("/") or ".." in partes:
        return f"«{u}»: en el CSS solo rutas relativas dentro de assets/"
    return None


def overflow_oculto(declaraciones: str) -> str | None:
    """La declaración ``overflow-x: hidden|clip`` u ``overflow: … hidden|clip …`` de un bloque (ya sin
    comentarios ni escapes), o ``None``."""
    for m in _OVERFLOW_CSS.finditer(declaraciones):
        valores = m.group(2).lower().replace("!important", " ").split()
        if any(v in ("hidden", "clip") for v in valores):
            return " ".join(m.group(0).split())
    return None


def _overflow_en_raiz(donde: str, limpio: str, fallos: list[str]) -> None:
    """I3: ``overflow-x: hidden|clip`` (o ``overflow``) en ``html``, ``body``, ``:root`` o ``*`` esconde los
    desbordes horizontales en vez de arreglarlos."""
    for regla in _REGLA_CSS.finditer(limpio):
        selectores = [s.strip() for s in regla.group(1).split(",") if s.strip()]
        sujetos = [s for s in selectores if _SUJETO_RAIZ.match(_COMBINADOR.split(s)[-1])]
        if sujetos and (decl := overflow_oculto(regla.group(2))) is not None:
            fallos.append(f"{donde}: «{', '.join(sujetos)} {{{decl}}}»: {_MENSAJE_OVERFLOW}")


def textos_content_css(css: str) -> list[str]:
    """Las cadenas de ``content:`` de un CSS (sin comentarios y con los escapes resueltos): texto que el
    comprador lee aunque no esté en el HTML."""
    limpio = _desescapar_css(_COMENTARIO_CSS.sub(" ", css))
    textos = []
    for m in _CONTENT_CSS.finditer(limpio):
        cadenas = [c.group(2) for c in _CADENA_CSS.finditer(m.group(1)) if c.group(2).strip()]
        if cadenas:
            textos.append(" ".join(cadenas))
    return textos


def _revisar_css(donde: str, css: str, fallos: list[str]) -> list[str]:
    """Revisa un CSS ya sin comentarios y con los escapes resueltos; devuelve los textos de ``content:``."""
    limpio = _desescapar_css(_COMENTARIO_CSS.sub(" ", css))
    _overflow_en_raiz(donde, limpio, fallos)
    remotos = list(_REMOTO_CSS.finditer(limpio))
    if remotos:
        mas = f" (y {len(remotos) - 1} más)" if len(remotos) > 1 else ""
        fallos.append(f"{donde}: «{_contexto(limpio, remotos[0])}»{mas}: el CSS no carga nada de fuera "
                      "(sin http:, https: ni //)")
    for m in _PELIGRO_CSS.finditer(limpio):
        fallos.append(f"{donde}: «{m.group(0)}»: no va en el CSS de la landing")
    for m in _URL_CSS.finditer(limpio):
        if (motivo := _url_css_mala(m.group(2))) is not None:
            fallos.append(f"{donde}: {motivo}")
    for m in _IMAGE_SET.finditer(limpio):
        for cadena in _CADENA_CSS.finditer(m.group(1)):
            if (motivo := _url_css_mala(cadena.group(2))) is not None:
                fallos.append(f"{donde}: image-set {motivo}")
    contenidos = []
    for m in _CONTENT_CSS.finditer(limpio):
        cadenas = [c.group(2) for c in _CADENA_CSS.finditer(m.group(1))]
        contenidos.append(" ".join(cadenas) if cadenas else m.group(1))
    return contenidos


def _r_estructura(lec: _Lector, wf: list[dict], fallos: list[str]) -> None:
    n = len(lec.secciones)
    if not SECCIONES_MIN <= n <= SECCIONES_MAX:
        fallos.append(f"la landing tiene {n} secciones; hacen falta {SECCIONES_MIN}–{SECCIONES_MAX}")
    for i, s in enumerate(lec.secciones, 1):
        if s.orden != str(i):
            fallos.append(f"sección {i}: data-tf-seccion=\"{s.orden}\" (van de 1 a N en orden)")
    esperados = [str(x.get("tipo")) for x in wf]
    reales = [s.tipo for s in lec.secciones]
    if reales != esperados:
        for i, (r, e) in enumerate(zip(reales, esperados, strict=False), 1):
            if r != e:
                fallos.append(f"sección {i}: es «{r}» y el wireframe pide «{e}» en ese orden")
        if len(reales) != len(esperados):
            fallos.append(f"el wireframe tiene {len(esperados)} secciones y la landing {len(reales)}")
    for i, s in enumerate(lec.secciones, 1):
        if s.hitos != 1:
            fallos.append(f"sección {i} ({s.tipo}): tiene {s.hitos} data-tf-hito; va uno (su titular)")


def _r_botones(lec: _Lector, wf: list[dict], checkout: str, fallos: list[str]) -> None:
    for i, (s, ref) in enumerate(zip(lec.secciones, wf, strict=False), 1):
        if ref.get("cta") and not s.botones:
            fallos.append(f"sección {i} ({s.tipo}): la referencia lleva botón aquí y falta a[data-tf-checkout]")
    primera_cta = next((i for i, ref in enumerate(wf) if ref.get("cta")), None)
    if lec.botones and primera_cta is not None and lec.botones[0][0] != primera_cta:
        donde = "fuera de las secciones" if lec.botones[0][0] is None else f"en la sección {lec.botones[0][0] + 1}"
        fallos.append(f"el botón principal está {donde}: va donde lo tenía la referencia (sección {primera_cta + 1})")
    if not lec.botones:
        fallos.append("no hay ningún botón a[data-tf-checkout]")
    for _, href in lec.botones:
        if href != checkout:
            fallos.append(f"a[data-tf-checkout] con href «{href}»; landing.yaml dice «{checkout}»")


def _permitidas(datos: DatosLanding) -> frozenset[str]:
    """Palabras que no cuentan contra la escritura: la marca, «PDF»/«A4», el dominio, la tienda y los medios
    de pago (M4)."""
    palabras = set(PERMITIDAS_FIJAS)
    for texto in (datos.marca, datos.dominio or "", host_tienda(datos.tienda) or "", *MARCAS_PAGO):
        palabras |= {texto, *re.findall(r"\w+", texto)}
    return frozenset(p for p in palabras if p)


def _r_idioma(lec: _Lector, datos: DatosLanding, fallos: list[str]) -> None:
    permitidas = _permitidas(datos)
    titulo = _limpio(lec.titulo or [])
    if not titulo:
        fallos.append("falta <title>")
    if lec.descripcion is None or not lec.descripcion.strip():
        fallos.append('falta <meta name="description">')
    if lec.lang != datos.idioma:
        fallos.append(f"<html lang=\"{lec.lang or ''}\">; el país habla «{datos.idioma}»")
    for nombre, texto in (("título", titulo), ("descripción", lec.descripcion or ""),
                          ("texto visible", _limpio(lec.visible))):
        for h in revisar_texto(texto, datos.idioma, permitidas):
            if h.bloquea:
                fallos.append(f"{nombre}: {h.regla}: {h.detalle}")


def _r_datos(lec: _Lector, datos: DatosLanding, fallos: list[str]) -> None:
    formatos = [_limpio(x) for x in lec.capturas["formato"]]
    if not formatos:
        fallos.append("falta data-tf-formato (PDF y su número de páginas)")
    for f in formatos:
        numeros = re.findall(r"\d+", f)
        falsas = [n for n in _PAGINAS.findall(f) if int(n) != datos.pdf_paginas]
        if "PDF" not in f or str(datos.pdf_paginas) not in numeros or falsas:
            fallos.append(f"data-tf-formato «{f}»: debe decir PDF y {datos.pdf_paginas} páginas (las del PDF vigente)")
    garantias = [_limpio(x) for x in lec.capturas["garantia"]]
    if not garantias:
        fallos.append("falta data-tf-garantia")
    for g in garantias:
        if str(datos.garantia_dias) not in re.findall(r"\d+", g):
            fallos.append(f"data-tf-garantia «{g}»: no dice los {datos.garantia_dias} días de OFERTA.md")
    importe, simbolo = precio_texto(datos.precio, datos.moneda, datos.idioma).split(" ", 1)
    exacto = re.compile(rf"(?<![\d.,]){re.escape(importe)}(?!\d)")  # M2: «114,90» o «14,905» no valen
    precios = [_limpio(x) for x in lec.capturas["precio"]]
    if not precios:
        fallos.append("falta data-tf-precio")
    for p in precios:
        if not exacto.search(p) or simbolo not in p:
            fallos.append(f"data-tf-precio «{p}»: debe decir {importe} y {simbolo}")


def _r_prueba_social(lec: _Lector, datos: DatosLanding, vault: Path, contenidos_css: list[tuple[str, str]],
                     fallos: list[str]) -> None:
    try:
        resenas = leer_resenas(vault, datos.p_id, datos.pais)
    except EntradaInvalida as exc:
        fallos.append(str(exc))
        resenas = []
    reales = {}
    for r in resenas:
        if not resena_completa(r):
            ident = r.get("id") if isinstance(r, dict) else None
            fallos.append(f"resenas.yaml: la reseña «{ident}» está incompleta (id, texto, fecha, pais, fuente)")
        elif r["pais"] != datos.pais:
            fallos.append(f"resenas.yaml: la reseña {r['id']} es de {r['pais']}, no de {datos.pais}")
        else:
            reales[r["id"]] = r
    textos = {}
    for captura in lec.capturas["resena"]:
        textos.setdefault(captura[0], []).append(_limpio(captura[1:]))
    for rid in lec.resenas:
        if rid not in reales:
            fallos.append(f"data-tf-resena=\"{rid}\" no está en resenas.yaml: solo reseñas reales (D-01)")
            continue
        real = " ".join(reales[rid]["texto"].split())
        trozos = fragmentos(reales[rid]) or [real]
        if any(any(f not in t for f in trozos) for t in textos.get(rid, [])):
            fallos.append(f"data-tf-resena=\"{rid}\": el texto no es el de resenas.yaml")
        estrellas = reales[rid].get("estrellas")
        for t in textos.get(rid, []):
            llenas, vacias = t.count("★"), t.count("☆")
            otras = bool(_ESTRELLAS.search(t.replace("★", "").replace("☆", "")))
            if (llenas or vacias or otras) and (not _estrellas_validas(estrellas) or otras
                                                or (llenas, vacias) != (estrellas, 5 - estrellas)):
                fallos.append(f"data-tf-resena=\"{rid}\": las estrellas no son las {estrellas} que dio "
                              "(★ llenas y ☆ vacías hasta 5) (D-01)")
    for captura in lec.capturas["nota"]:
        con = [r for r in reales.values() if _estrellas_validas(r.get("estrellas"))]
        texto_nota = _limpio(captura)
        if not con or len(con) != len(reales):
            fallos.append("data-tf-nota: la nota media necesita las estrellas de todas las reseñas reales (D-01)")
            continue
        media = f"{Decimal(sum(r['estrellas'] for r in con)) / len(con):.1f}".replace(".", ",")
        if media not in texto_nota or not re.search(rf"(?<!\d){len(con)}(?!\d)", texto_nota):
            fallos.append(f"data-tf-nota: debe decir la media real {media} y cuántas reseñas ({len(con)}) (D-01)")
    fuentes = [("título", _limpio(lec.titulo or [])), ("descripción", lec.descripcion or ""),
               ("texto visible", _limpio(lec.visible_libre)), *(("aria-label", t) for t in lec.aria),
               *contenidos_css]
    for donde, texto in fuentes:
        for hallazgo in prueba_social_falsa(texto, datos.idioma, datos.precio):
            fallos.append(f"{donde}: {hallazgo}: sin estrellas, notas, cupos, compradores, cuentas atrás ni "
                          "precios de referencia inventados (D-01)")
    fallos.extend(lec.d01)
    tipos = [s.tipo for s in lec.secciones]
    if not reales:
        if "prueba_social" in tipos:
            fallos.append("sección prueba_social sin reseñas reales: va vista previa + garantía (D-01)")
        vistas = [s for s in lec.secciones if s.tipo == "vista_previa"]
        if not vistas or max(s.vistas for s in vistas) < 2:
            fallos.append("sin reseñas reales falta la vista previa: una sección vista_previa con ≥ 2 "
                          "img[data-tf-vista]")
        if "garantia" not in tipos:
            fallos.append("sin reseñas reales falta la sección garantia")


def _r_assets(raiz: Path, datos: DatosLanding, lec: _Lector, pixel: bool, fallos: list[str]) -> None:
    assets = raiz / "assets"
    vistas = _leer_json(assets / VISTAS)
    if vistas is None:
        fallos.append(f"falta assets/{VISTAS}: trovefy landing medios")
    elif vistas.get("sha256") != datos.pdf_sha256:
        fallos.append(f"la vista previa es de {vistas.get('pdf')}: rehaz los medios con `trovefy landing medios` "
                      f"(el PDF vigente es {datos.pdf.name})")
    manifiesto = _leer_json(assets / MANIFIESTO)
    medios = {}
    if manifiesto is None or not isinstance(manifiesto.get("medios"), list):
        fallos.append(f"falta assets/{MANIFIESTO} (el origen de cada medio): trovefy landing medios")
    else:
        for m in manifiesto["medios"]:
            if isinstance(m, dict) and m.get("origen") in ORIGENES and isinstance(m.get("archivo"), str):
                medios[m["archivo"]] = m
            else:
                fallos.append(f"assets/{MANIFIESTO}: entrada sin origen válido: {m!r:.80}")
    fijos = set(FIJOS) | ({PIXEL_JS} if pixel else set())
    presentes = set()
    if assets.is_symlink():
        fallos.append("assets/ es un enlace simbólico")
    elif assets.is_dir():
        for p in sorted(assets.iterdir()):
            presentes.add(p.name)
            if p.is_symlink() or not p.is_file():
                fallos.append(f"assets/{p.name} no es un archivo normal")
            elif p.name in fijos:
                continue
            elif p.name not in medios:
                fallos.append(f"assets/{p.name} no tiene origen en {MANIFIESTO}: material sin origen no va (contrato 4)")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != medios[p.name].get("sha256"):
                fallos.append(f"assets/{p.name}: su sha256 no es el de {MANIFIESTO} (rehaz los medios)")
    for _, url, carga in lec.urls:
        nombre = _en_assets(url) if carga else None
        if nombre is not None and nombre not in presentes:
            fallos.append(f"el HTML usa assets/{nombre} y no existe")
    for url in lec.vistas_urls:  # M1: la vista previa es del PDF, no otra imagen
        nombre = _en_assets(url)
        if nombre is None or medios.get(nombre, {}).get("origen") != "vista_pdf":
            fallos.append(f"img[data-tf-vista] «{url}»: no es una vista previa del PDF ({MANIFIESTO}, "
                          "origen vista_pdf)")


def _r_scripts(raiz: Path, lec: _Lector, pixel: bool, fallos: list[str]) -> None:
    validos = {"assets/utm.js"} | ({f"assets/{PIXEL_JS}"} if pixel else set())
    for src, en_linea in lec.scripts:
        if en_linea or src not in validos:
            fallos.append(f"<script{f' src={src!r}' if src else ''}>: el único script es assets/utm.js"
                          + (" (y assets/pixel.js en Cloudflare)" if pixel else ""))
    utm = raiz / "assets" / "utm.js"
    if utm.is_symlink() or not utm.is_file() or utm.read_bytes() != UTM_JS.read_bytes():
        fallos.append("assets/utm.js no es el de templates/landing/: vuelve a trovefy landing guardar")
    archivo = raiz / "assets" / PIXEL_JS
    if pixel and archivo.is_file() and not archivo.is_symlink():
        eventos = set(_EVENTO_PIXEL.findall(archivo.read_text(encoding="utf-8")))
        if eventos - {"PageView", "ViewContent"}:
            fallos.append(f"assets/{PIXEL_JS}: solo PageView y ViewContent (lleva {', '.join(sorted(eventos))})")
    fallos.extend(dict.fromkeys(lec.fuera))


def aviso_sin_pixel(pais: str) -> str:
    """Ruling B: en Cloudflare sin ``TRACKING.md`` se publica sin píxel; el 19 y /listo lo exigen antes de
    anunciar."""
    return (f"sin píxel: falta checkout/{pais}/TRACKING.md con dataset_id (trovefy tracking preparar); se "
            "publica sin píxel y landing.yaml queda con pixel: pendiente (hace falta antes de anunciar)")


def _r_pixel(vault: Path, raiz: Path, datos: DatosLanding, lec: _Lector, fallos: list[str],
             avisos: list[str]) -> None:
    """R1: en Cloudflare, ``assets/pixel.js`` es byte a byte la plantilla con el dataset de ``TRACKING.md`` y el
    HTML lo carga; sin ``TRACKING.md`` no va (aviso: se publica sin píxel, ruling B)."""
    try:
        esperado = pixel_js(vault, datos)
    except EntradaInvalida as e:
        fallos.append(str(e))
        return
    archivo = raiz / "assets" / PIXEL_JS
    hay = archivo.is_file() and not archivo.is_symlink()
    carga = any(src == f"assets/{PIXEL_JS}" for src, _ in lec.scripts)
    if esperado is None:
        if hay:
            fallos.append(f"assets/{PIXEL_JS} sin checkout/{datos.pais}/TRACKING.md: sobra (vuelve a trovefy "
                          "landing preparar y guardar)")
        avisos.append(aviso_sin_pixel(datos.pais))
        return
    if not hay or archivo.read_bytes() != esperado:
        fallos.append(f"assets/{PIXEL_JS} no es el de la plantilla con el dataset de TRACKING.md: vuelve a "
                      "trovefy landing guardar")
    if not carga:
        fallos.append(f'index.html no carga assets/{PIXEL_JS} (<script src="assets/{PIXEL_JS}" defer>)')


def _leer_texto(ruta: Path, fallos: list[str], nombre: str) -> str:
    if ruta.is_symlink():
        fallos.append(f"{nombre} es un enlace simbólico")
        return ""
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else ""


def validar(vault: Path, datos: DatosLanding) -> Resultado:
    """Comprueba ``landing/<PAIS>/`` contra el wireframe, la oferta, el PDF vigente y sus manifiestos.

    ``EntradaInvalida`` si ``landing.yaml`` está roto o enlazado (no hay nada que validar contra él)."""
    vault = Path(vault)
    raiz = ruta_landing(vault, datos.p_id, datos.pais)
    landing = leer_landing_yaml(vault, datos.p_id, datos.pais)
    fallos: list[str] = []
    avisos: list[str] = []
    indice = raiz / "index.html"
    html = _leer_texto(indice, fallos, "index.html")
    if not html:
        return Resultado(False, (*fallos, f"falta landing/{datos.pais}/index.html: trovefy landing guardar"), ())
    css = _leer_texto(raiz / "assets" / "estilo.css", fallos, "assets/estilo.css")
    if not css:
        fallos.append("falta assets/estilo.css")
    wf_yaml = _leer_yaml(raiz / "wireframe.yaml")
    wf = wf_yaml.get("secciones") if wf_yaml else None
    if not isinstance(wf, list):
        fallos.append("falta wireframe.yaml: trovefy landing preparar")
        wf = []
    checkout = landing.get("checkout_url")
    if not isinstance(checkout, str) or not checkout:
        fallos.append("landing.yaml no trae checkout_url: trovefy landing preparar")
        checkout = ""
    pixel = landing.get("hosting") == "cloudflare"

    lec = _Lector()
    lec.feed(html)
    if "<" in lec.rawdata:  # lo que queda sin entender tras feed es una etiqueta sin cerrar al final
        lec.fuera.append(f"etiqueta sin cerrar al final: «{lec.rawdata.strip()[:40]}»")
    lec.close()

    contenidos_css: list[tuple[str, str]] = []
    for donde, texto in [*lec.estilos, ("assets/estilo.css", css)]:
        contenidos_css += [(f"{donde} (content)", t) for t in _revisar_css(donde, texto, fallos)]
    _r_estructura(lec, wf, fallos)
    _r_botones(lec, wf, checkout, fallos)
    _r_idioma(lec, datos, fallos)
    _r_datos(lec, datos, fallos)
    _r_prueba_social(lec, datos, vault, contenidos_css, fallos)
    _r_assets(raiz, datos, lec, pixel, fallos)
    origen = _Origen(checkout, datos.dominio, datos.tienda)
    for donde, url, carga in lec.urls:
        if (motivo := origen.motivo(url, carga)) is not None:
            fallos.append(f"{donde}: «{url}»: {motivo}")
    _r_scripts(raiz, lec, pixel, fallos)
    if pixel:
        _r_pixel(vault, raiz, datos, lec, fallos, avisos)
    if len(lec.versiones) != 1:
        fallos.append('falta <main id="tf-landing" data-tf-version="…"> (uno solo)')
    elif lec.versiones[0] != version_de(html):
        fallos.append("data-tf-version no cuadra con el HTML (¿editado a mano tras guardar?): vuelve a "
                      "trovefy landing guardar")
    for nombre, texto in (("index.html", html), ("assets/estilo.css", css)):
        patron = buscar_secreto(texto)
        if patron:
            fallos.append(f"{nombre}: aparece algo con forma de secreto ({patron})")

    refs = {str(s.orden): s for s in datos.secciones}
    for s in lec.secciones:
        ref = refs.get(s.orden)
        if ref is None:
            continue
        n = _palabras(_limpio(s.texto))
        if not LARGO_MIN * ref.palabras <= n <= LARGO_MAX * ref.palabras:
            avisos.append(f"sección {s.orden} ({s.tipo}): {n} palabras; la referencia tiene {ref.palabras}")
    if lec.descripcion and len(lec.descripcion) > DESCRIPCION_MAX:
        avisos.append(f"la meta description tiene {len(lec.descripcion)} caracteres (más de {DESCRIPCION_MAX})")
    fallos = list(dict.fromkeys(fallos))
    return Resultado(not fallos, tuple(fallos), tuple(avisos))


def _estrellas_validas(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and 1 <= valor <= 5


SEPARADOR_EXTRACTO = "[…]"


def fragmentos(r: dict) -> list[str]:
    """Los trozos literales de ``extracto`` (separados por ``[…]``); ``[]`` sin extracto."""
    extracto = r.get("extracto") if isinstance(r, dict) else None
    if not isinstance(extracto, str) or not extracto.strip():
        return []
    return [" ".join(t.split()) for t in extracto.split(SEPARADOR_EXTRACTO) if t.strip()]


def completar_resena(vault: Path, p_id: str, pais: str, rid: str, *, nombre: str | None = None,
                     estrellas: int | None = None, extracto: str | None = None) -> None:
    """Añade a una reseña ya guardada lo que el autor autorizó mostrar: ``nombre`` (como lo dio, p. ej.
    «Мария К., София»), ``estrellas`` (1–5, las que dio) y ``extracto`` (trozos LITERALES de su texto, separados
    por ``[…]``). ``ValueError`` si algo no cuadra con el texto original."""
    vault = Path(vault)
    pais = pais.strip().upper()
    try:
        previas = leer_resenas(vault, p_id, pais)
    except EntradaInvalida as exc:
        raise ValueError(str(exc)) from None
    r = next((x for x in previas if isinstance(x, dict) and x.get("id") == rid), None)
    if r is None:
        raise ValueError(f"no hay ninguna reseña {rid} en landing/{pais}/resenas.yaml")
    if estrellas is not None:
        if not _estrellas_validas(estrellas):
            raise ValueError("las estrellas van de 1 a 5")
        r["estrellas"] = estrellas
    if nombre is not None:
        if not nombre.strip():
            raise ValueError("el nombre no puede ir vacío")
        r["nombre"] = " ".join(nombre.split())
    if extracto is not None:
        trozos = fragmentos({"extracto": extracto})
        real = " ".join(str(r.get("texto", "")).split())
        if not trozos or any(t not in real for t in trozos):
            raise ValueError("el extracto tiene que ser trozos literales del texto de la reseña, separados por […]")
        r["extracto"] = f" {SEPARADOR_EXTRACTO} ".join(trozos)
    datos = {"resenas": previas}
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False)
    if secreto_en(datos) or buscar_secreto(contenido):
        raise ValueError("la reseña trae algo con forma de secreto; no se guarda")
    ruta = ruta_landing(vault, p_id, pais) / "resenas.yaml"
    escribir_atomico(ruta, contenido)
    anadir_log(vault, "landing", f"{p_id} {pais}: reseña {rid} completada (nombre, estrellas o extracto)",
               [ruta.relative_to(vault).as_posix()])


def anadir_resena(vault: Path, p_id: str, pais: str, texto: str, fecha: date, fuente: str) -> str:
    """Añade una reseña real a ``landing/<PAIS>/resenas.yaml`` con id ``r-<AAAAMMDD>-<n>``; devuelve el id.

    ``ValueError`` si falta el texto o la fuente (el pedido o el email de origen) o si algo parece un secreto.
    """
    vault = Path(vault)
    pais = pais.strip().upper()
    if not isinstance(fuente, str) or not fuente.strip():
        raise ValueError("una reseña sin fuente (el pedido o el email de origen) no entra")
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("la reseña no trae texto")
    if not isinstance(fecha, date):
        raise ValueError("fecha de la reseña mal escrita (AAAA-MM-DD)")  # noqa: TRY004 - error de uso
    raiz = ruta_landing(vault, p_id, pais)
    try:
        previas = leer_resenas(vault, p_id, pais)
    except EntradaInvalida as exc:
        raise ValueError(str(exc)) from None
    prefijo = f"r-{fecha:%Y%m%d}-"
    usados = {r.get("id") for r in previas if isinstance(r, dict)}
    n = 1
    while f"{prefijo}{n}" in usados:
        n += 1
    rid = f"{prefijo}{n}"
    nueva = {"id": rid, "texto": " ".join(texto.split()), "fecha": fecha.isoformat(), "pais": pais,
             "fuente": fuente.strip()}
    datos = {"resenas": [*previas, nueva]}
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False)
    if secreto_en(datos) or buscar_secreto(contenido):
        raise ValueError("la reseña trae algo con forma de secreto; no se guarda")
    ruta = raiz / "resenas.yaml"
    escribir_atomico(ruta, contenido)
    anadir_log(vault, "landing", f"{p_id} {pais}: reseña real {rid} (fuente: {nueva['fuente']})",
               [ruta.relative_to(vault).as_posix()])
    return rid
