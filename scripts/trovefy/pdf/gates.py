"""Gates deterministas del PDF: QG-01…14 con puntuación por severidad.

Adaptados y traducidos de dp-createur (MIT, ``0cf80efa``): ``references/quality-gates.md`` y
``references/scoring-system.md``. Se leen sobre el HTML ensamblado de una pieza, antes de WeasyPrint,
con ``html.parser`` de la biblioteca estándar: un recorrido que construye un árbol mínimo de elementos
(y anota las etiquetas sin cerrar o mal anidadas para QG-13).

``promesas`` es pública: la reutiliza ``/landing`` (plan 18) para su copy. Sin léxico para el idioma falla
cerrado con un hallazgo crítico «no medido».

Todo texto se normaliza antes de buscar promesas, cifras o contar palabras (``plan.normalizar``: NFC, sin
caracteres de formato, espacio duro como espacio y blancos colapsados). Ningún bloque visible queda fuera
del examen de promesas: el aviso de salud, el índice y las fuentes también pasan; solo las entradas
citadas ``li[id^=fuente-]`` se saltan (el título de un estudio no es una promesa). Un descargo («no
sustituye al médico», «antes de dejar la medicación») se neutraliza por su negación, no por su sitio.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.pdf.plan import (
    EN_LINEA,
    PALABRA,
    VACIAS,
    clases,
    cuenta,
    no_cuenta,
    normalizar,
)
from trovefy.producto.config import ConfigProducto
from trovefy.producto.ficha import EXIGENCIAS
from trovefy.producto.medios import CARPETA, MANIFIESTO, leer_manifiesto

Severidad = Literal["critica", "alta", "media", "baja"]
# dp-createur references/scoring-system.md, adaptado: 100 menos la suma de pesos, mínimo 0.
PESOS: dict[str, int] = {"critica": 25, "alta": 10, "media": 5, "baja": 2}
PLANTILLAS = Path(__file__).resolve().parents[3] / "templates" / "pdf" / "promesas"
CLAVES_LEXICO = ("ingresos", "salud")
TIPOS_PIEZA = ("principal", "ebook", "kit", "bono", "bump", "upsell")
# QG-07: número de h3 por sección (dp-createur: 3–7 subapartados).
H3_POR_SECCION = (3, 7)
# QG-12: largo mínimo (en palabras) de un párrafo repetido que cuenta como relleno.
PALABRAS_RELLENO = 12
# QG-11: palabras mínimas del aside.aviso-salud con exigencia sanitaria. Constante técnica: un aviso de
# menos de una frase («Ojo.», «Consulta a tu médico.») no explica que el libro no es un tratamiento.
AVISO_PALABRAS_MIN = 8
# Promesas: cuántas palabras antes de la coincidencia (en la misma frase, sin puntuación de por medio y solo
# a través de auxiliares) se busca una negación que la convierte en descargo («no sustituye», «не лекува»).
VENTANA_NEGACION = 3

_IDIOMA = re.compile(r"[a-z]{2}")
_MARCADORES = (
    re.compile(r"lorem ipsum", re.IGNORECASE),
    re.compile(r"\b(?:TBD|XXX|PLACEHOLDER)\b"),
    # «TODO» solo como marcador («TODO:», «[TODO …]»); en español «TODO» en mayúsculas es «todo».
    re.compile(r"\bTODO\s*:"),
    re.compile(r"\[\s*TODO\b[^\]]*\]"),
    re.compile(r"\{\{|\}\}"),
    re.compile(r"\[(?:insert|insertar|вмъкни)", re.IGNORECASE),
    re.compile(r"<placeholder", re.IGNORECASE),
)
_COMENTARIO_HTML = re.compile(r"<!--(.*?)-->", re.DOTALL)
_TODO = re.compile(r"\bTODO\b")
_CIFRA = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|por\s?ciento\b|процента?\b|per\s?cent\b|percent\b)"
                    r"|\b\d+ (?:de cada|от всеки|out of) \d+", re.IGNORECASE)
_REMOTO = re.compile(r"^\s*(?:https?:)?//", re.IGNORECASE)
# En CSS: url(…), @import «…» o cualquier cadena (image-set, src…) que empiece por http(s):// o //.
_REMOTO_CSS = re.compile(r"(?:url\(\s*['\"]?|@import\s+['\"]?|['\"])\s*(?:https?:)?//[^\s'\")]*", re.IGNORECASE)
_URL_LOCAL_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_FONT_FACE = re.compile(r"@font-face\s*\{[^{}]*\}", re.IGNORECASE)
_IMPORTANTE = re.compile(r"\s*!\s*important\s*$")
_RECORTA_OVERFLOW = frozenset({"hidden", "clip"})
_RECORTA_CONTAIN = frozenset({"paint", "content", "strict"})
_PROPS_OVERFLOW = ("overflow", "overflow-x", "overflow-y", "overflow-block", "overflow-inline")
_TAMANO_A4 = (frozenset({"a4"}), frozenset({"a4", "portrait"}))
# Promesas: negaciones (es, bg, en) y descargos fijos que neutralizan la coincidencia siguiente.
_NEGACIONES = frozenset({"no", "ni", "nunca", "jamás", "не", "нито", "никога", "not", "never", "nor", "cannot"})
# Entre la negación y la promesa solo caben pronombres átonos y auxiliares («no te curará», «no va a curar»,
# «will not cure», «не ще те излекува»); cualquier otra palabra cambia lo que se niega.
_AUXILIARES = frozenset({
    "te", "se", "lo", "la", "le", "les", "me", "nos", "os", "va", "vas", "van", "vamos", "a", "puede", "pueden",
    "puedes", "debe", "deben", "es", "está", "do", "does", "did", "will", "would", "can", "could", "may", "might",
    "it", "this", "that", "is", "to", "ще", "се", "го", "я", "ги", "ви", "ти", "те", "ни", "ми", "може", "да", "е",
})
_DESCARGOS = re.compile(r"(?:\bantes de|\bbefore(?: you)?|\bпреди да)\s*$", re.IGNORECASE)
_FIN_DE_FRASE = re.compile(r"[.!?;:,¡¿()«»\"“”—]")
_TOKEN = re.compile(r"[\w'’]+")
_IMG_EN_SVG = frozenset({"image", "use", "feimage"})
_COMENTARIO_CSS = re.compile(r"/\*.*?\*/", re.DOTALL)
_ESTILO = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.DOTALL | re.IGNORECASE)
_CERO = re.compile(r"0(?:mm|cm|in|pt|px|pc|q|em|rem)?")
_NO_PALABRA = re.compile(r"[^\w]+")
_NO_PROMESA = ("head", "title", "style", "script", "template", "noscript")


@dataclass(frozen=True)
class Hallazgo:
    gate: str
    severidad: Severidad
    donde: str
    texto: str


@dataclass(frozen=True)
class Informe:
    hallazgos: tuple[Hallazgo, ...]
    puntuacion: int
    pasa: bool
    palabras: int
    paginas_estimadas: int


# --- árbol mínimo -----------------------------------------------------------------------------------


@dataclass
class _Nodo:
    tag: str
    attrs: dict[str, str]
    linea: int
    padre: _Nodo | None = None
    hijos: list[_Nodo | str] = field(default_factory=list)

    @property
    def clases(self) -> set[str]:
        return clases(self.attrs)

    def elementos(self) -> list[_Nodo]:
        return [h for h in self.hijos if isinstance(h, _Nodo)]

    def descendientes(self):
        for h in self.hijos:
            if isinstance(h, _Nodo):
                yield h
                yield from h.descendientes()

    def donde(self) -> str:
        ident = f"#{self.attrs['id']}" if self.attrs.get("id") else ""
        clase = "".join(f".{c}" for c in sorted(self.clases))
        return f"línea {self.linea}: <{self.tag}{ident}{clase}>"


class _Arbol(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.raiz = _Nodo("#documento", {}, 1)
        self.pila = [self.raiz]
        self.errores: list[tuple[int, str]] = []

    def _nuevo(self, tag, attrs) -> _Nodo:
        nodo = _Nodo(tag, {k: v or "" for k, v in attrs}, self.getpos()[0], self.pila[-1])
        self.pila[-1].hijos.append(nodo)
        return nodo

    def handle_starttag(self, tag, attrs):
        nodo = self._nuevo(tag, attrs)
        if tag not in VACIAS:
            self.pila.append(nodo)

    def handle_startendtag(self, tag, attrs):
        self._nuevo(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VACIAS:
            return
        linea = self.getpos()[0]
        if self.pila[-1].tag == tag:
            self.pila.pop()
            return
        abiertas = [n.tag for n in self.pila[1:]]
        if tag in abiertas:
            while self.pila[-1].tag != tag:
                sin_cerrar = self.pila.pop()
                texto = (f"<{sin_cerrar.tag}> (línea {sin_cerrar.linea}) sin cerrar antes de </{tag}>: "
                         "etiquetas mal anidadas")
                self.errores.append((linea, texto))
            self.pila.pop()
        else:
            self.errores.append((linea, f"</{tag}> cierra algo que no está abierto"))

    def handle_data(self, data):
        self.pila[-1].hijos.append(data)

    def cerrar(self) -> None:
        self.close()
        for nodo in self.pila[1:]:
            self.errores.append((nodo.linea, f"<{nodo.tag}> sin cerrar"))


def _arbol(html: str) -> _Arbol:
    arbol = _Arbol()
    arbol.feed(html)
    arbol.cerrar()
    return arbol


def _texto(nodo: _Nodo, omitir) -> str:
    """Texto de ``nodo`` normalizado; un elemento de bloque (también uno omitido, p. ej. ``<br>``) separa."""
    trozos: list[str] = []

    def recorrer(n: _Nodo) -> None:
        for h in n.hijos:
            if isinstance(h, str):
                trozos.append(h)
                continue
            separa = h.tag not in EN_LINEA
            if separa:
                trozos.append(" ")
            if not omitir(h):
                recorrer(h)
                if separa:
                    trozos.append(" ")

    recorrer(nodo)
    return normalizar("".join(trozos))


def _omitir_contar(n: _Nodo) -> bool:
    return no_cuenta(n.tag, n.clases)


def _es_cita(n: _Nodo) -> bool:
    """Una entrada citada de las fuentes (``li[id^=fuente-]`` dentro de ``section.fuentes``): lo único de
    las fuentes que se salta. Fuera de ``section.fuentes`` ese id no esconde nada."""
    if n.tag != "li" or not n.attrs.get("id", "").startswith("fuente-"):
        return False
    padre = n.padre
    while padre is not None:
        if padre.tag == "section" and "fuentes" in padre.clases:
            return True
        padre = padre.padre
    return False


def _omitir_promesas(n: _Nodo) -> bool:
    # El aviso de salud, el índice y el resto de las fuentes sí pasan (Ruling R-T7b y revisión H1/M2).
    return n.tag in _NO_PROMESA or _es_cita(n)


def _palabras(nodo: _Nodo) -> int:
    return len(PALABRA.findall(_texto(nodo, _omitir_contar)))


def _de_clase(raiz: _Nodo, tag: str | None, clase: str) -> list[_Nodo]:
    return [n for n in raiz.descendientes() if clase in n.clases and (tag is None or n.tag == tag)]


# --- léxico de promesas -----------------------------------------------------------------------------


def _leer_lexico(ruta: Path) -> dict[str, list[str]]:
    try:
        datos = cargar_yaml(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{ruta.name}: léxico de promesas ilegible ({exc})") from None
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta.name}: el léxico de promesas no es un mapa")  # noqa: TRY004 - error de datos
    salida: dict[str, list[str]] = {}
    for clave in CLAVES_LEXICO:
        lista = datos.get(clave) or []
        if not isinstance(lista, list) or not all(isinstance(x, str) and x.strip() for x in lista):
            raise ValueError(f"{ruta.name}: «{clave}» debe ser una lista de patrones")
        salida[clave] = list(lista)
    return salida


def cargar_lexico(idioma: str, vault: Path | None) -> dict[str, list[re.Pattern]] | None:
    """Plantilla del repo + ``config/promesas/<idioma>.yaml`` del vault, si existe. None si no hay léxico."""
    if not isinstance(idioma, str) or not _IDIOMA.fullmatch(idioma):
        return None
    rutas = [PLANTILLAS / f"{idioma}.yaml"]
    if vault is not None:
        rutas.append(Path(vault) / "config" / "promesas" / f"{idioma}.yaml")
    patrones: dict[str, list[str]] = {clave: [] for clave in CLAVES_LEXICO}
    for ruta in rutas:
        if ruta.is_file():
            for clave, lista in _leer_lexico(ruta).items():
                patrones[clave] += [p for p in lista if p not in patrones[clave]]
    if not any(patrones.values()):
        return None
    compilados: dict[str, list[re.Pattern]] = {}
    for clave, lista in patrones.items():
        compilados[clave] = []
        for p in lista:
            try:
                compilados[clave].append(re.compile(unicodedata.normalize("NFC", p), re.IGNORECASE | re.UNICODE))
            except re.error as exc:
                raise ValueError(f"léxico de promesas ({idioma}, {clave}): patrón roto «{p}» ({exc})") from None
    return compilados


def _descargo(texto: str, inicio: int) -> bool:
    """True si la coincidencia que empieza en ``inicio`` va negada o tras un descargo fijo, en la misma frase."""
    antes = texto[:inicio]
    cortes = list(_FIN_DE_FRASE.finditer(antes))
    frase = antes[cortes[-1].end():] if cortes else antes
    if _DESCARGOS.search(frase):
        return True
    for n, token in enumerate(reversed([t.lower() for t in _TOKEN.findall(frase)])):
        if token in _NEGACIONES or token.endswith(("n't", "n’t")):
            return True
        if n + 1 >= VENTANA_NEGACION or token not in _AUXILIARES:
            return False  # «¿No quieres ganar…?» niega «quieres», no la promesa
    return False


def promesas(texto: str, idioma: str, exigencia: str, vault: Path | None = None) -> list[Hallazgo]:
    """QG-10 (ingresos) y QG-11 (salud) sobre un texto. Sin léxico: un hallazgo crítico «no medido».

    El texto se normaliza antes (``plan.normalizar``). Una coincidencia negada en su frase (``no``, ``не``,
    ``not``… hasta ``VENTANA_NEGACION`` palabras antes) o tras un descargo fijo («antes de», «before»,
    «преди да») no es una promesa."""
    if exigencia not in EXIGENCIAS:
        raise ValueError(f"exigencia «{exigencia}» no admitida: {', '.join(EXIGENCIAS)}")
    lexico = cargar_lexico(idioma, vault)
    if lexico is None:
        return [Hallazgo("QG-10", "critica", "léxico",
                         f"no medido: sin léxico de promesas para {idioma}")]
    texto = normalizar(texto)
    hallazgos: list[Hallazgo] = []
    for clave, gate in (("ingresos", "QG-10"), ("salud", "QG-11")):
        vistos: set[str] = set()
        for patron in lexico[clave]:
            for m in patron.finditer(texto):
                if _descargo(texto, m.start()):
                    continue
                frase = m.group(0)
                if frase.lower() in vistos:
                    continue
                vistos.add(frase.lower())
                hallazgos.append(Hallazgo(gate, "critica", f"«{frase}»",
                                          f"promesa de {clave}: «{frase}»; quítala o di lo mismo sin prometer"))
    return hallazgos


# --- CSS --------------------------------------------------------------------------------------------


def _declaraciones(texto: str) -> dict[str, str]:
    """Propiedad → valor en minúsculas, con los blancos colapsados y sin ``!important``."""
    salida = {}
    for parte in texto.split(";"):
        if ":" in parte:
            prop, valor = parte.split(":", 1)
            valor = _IMPORTANTE.sub("", " ".join(valor.strip().lower().split()))
            salida[prop.strip().lower()] = valor
    return salida


def _recorte(d: dict[str, str]) -> str | None:
    """La declaración que recorta el contenido (``overflow*: hidden|clip``, también en la sintaxis de dos
    valores, o ``contain: paint|content|strict``), o None."""
    for prop in _PROPS_OVERFLOW:
        if set(d.get(prop, "").split()) & _RECORTA_OVERFLOW:
            return f"{prop}:{d[prop]}"
    if set(d.get("contain", "").split()) & _RECORTA_CONTAIN:
        return f"contain:{d['contain']}"
    return None


def _bloque(texto: str, reglas: list[tuple[str, dict[str, str]]]) -> str:
    """Añade a ``reglas`` las de ``texto`` (anidadas incluidas) y devuelve sus declaraciones sueltas."""
    sueltas, inicio, i, n = [], 0, 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "{":
            preludio = texto[inicio:i]
            profundidad, k = 1, i + 1
            while k < n and profundidad:
                profundidad += {"{": 1, "}": -1}.get(texto[k], 0)
                k += 1
            propias = _bloque(texto[i + 1:k - 1], reglas)
            reglas.append((" ".join(preludio.strip().lower().split()), _declaraciones(propias)))
            inicio = i = k
            continue
        if c == ";":
            sueltas.append(texto[inicio:i + 1])
            inicio = i + 1
        i += 1
    sueltas.append(texto[inicio:])
    return "".join(sueltas)


def _reglas_css(css: str) -> list[tuple[str, dict[str, str]]]:
    reglas: list[tuple[str, dict[str, str]]] = []
    _bloque(_COMENTARIO_CSS.sub("", css), reglas)
    return reglas


# --- gates ------------------------------------------------------------------------------------------


def _sin_estilos(html: str) -> str:
    """El HTML sin el contenido de ``<style>`` (el CSS anidado legítimo cierra con ``}}``); conserva las líneas."""
    return _ESTILO.sub(lambda m: m.group(1) + "\n" * m.group(2).count("\n") + m.group(3), html)


def _qg01(html: str) -> list[Hallazgo]:
    salida = []
    html = _sin_estilos(html)
    for patron in _MARCADORES:
        for m in patron.finditer(html):
            linea = html.count("\n", 0, m.start()) + 1
            salida.append(Hallazgo("QG-01", "critica", f"línea {linea}",
                                   f"marcador sin rellenar: «{m.group(0)}»"))
    for comentario in _COMENTARIO_HTML.finditer(html):
        if _TODO.search(comentario.group(1)):
            linea = html.count("\n", 0, comentario.start()) + 1
            salida.append(Hallazgo("QG-01", "critica", f"línea {linea}",
                                   f"marcador sin rellenar en un comentario: «{comentario.group(0).strip()[:60]}»"))
    return salida


def _qg02(raiz: _Nodo) -> list[Hallazgo]:
    salida = []
    ids = {n.attrs["id"] for n in raiz.descendientes() if n.attrs.get("id")}
    for n in raiz.descendientes():
        href = n.attrs.get("href", "")
        if href.startswith("#") and href[1:] not in ids:
            salida.append(Hallazgo("QG-02", "critica", n.donde(), f"el enlace {href} no lleva a ningún id"))
    indice = _de_clase(raiz, "nav", "indice")
    enlazados = {n.attrs.get("href", "")[1:] for nav in indice for n in nav.descendientes() if n.tag == "a"}
    for seccion in _de_clase(raiz, None, "seccion"):
        for h2 in (n for n in seccion.descendientes() if n.tag == "h2"):
            destinos = {seccion.attrs.get("id"), h2.attrs.get("id")} - {None, ""}
            if not destinos & enlazados:
                titulo = " ".join(_texto(h2, _omitir_contar).split())
                salida.append(Hallazgo("QG-02", "critica", seccion.donde(),
                                       f"el apartado «{titulo}» no está en el índice (nav.indice)"))
    return salida


def _candidatos_srcset(valor: str) -> list[str]:
    return [c.split()[0] for c in valor.split(",") if c.split()]


def _no_es_recurso(n: _Nodo, attr: str) -> bool:
    """``<a href>`` (las fuentes enlazan su web) y ``xmlns`` (un espacio de nombres) no se descargan."""
    return (n.tag == "a" and attr in ("href", "xlink:href")) or attr == "xmlns" or attr.startswith("xmlns:")


def _qg03(raiz: _Nodo, css: str) -> list[Hallazgo]:
    """Ningún recurso remoto: ``http(s)://`` o ``//`` en cualquier atributo salvo ``<a href>`` (``src``,
    cada candidato de ``srcset``, ``data``, ``poster``, ``href`` de SVG, ``url()`` en ``style=``…), ni en el
    CSS. ``<base>`` y ``<link rel=stylesheet>`` están prohibidos (la maqueta incrusta el CSS en ``<style>``)."""
    salida = []
    for n in raiz.descendientes():
        if n.tag == "base":
            salida.append(Hallazgo("QG-03", "critica", n.donde(),
                                   "<base> prohibido: cambia de dónde se cargan todos los recursos"))
        if n.tag == "link" and "stylesheet" in n.attrs.get("rel", "").lower().split():
            salida.append(Hallazgo("QG-03", "critica", n.donde(),
                                   "<link rel=stylesheet> prohibido: el CSS va incrustado en <style>"))
        for attr, valor in n.attrs.items():
            if _no_es_recurso(n, attr):
                continue
            if attr.endswith("srcset"):
                remotos = [c for c in _candidatos_srcset(valor) if _REMOTO.match(c)]
            elif _REMOTO.match(valor):
                remotos = [valor.strip()]
            else:  # url(…) o una cadena remota dentro del valor (style=, sobre todo)
                remotos = [m.group(0) for m in _REMOTO_CSS.finditer(_COMENTARIO_CSS.sub("", valor))]
            for remoto in remotos:
                salida.append(Hallazgo("QG-03", "critica", n.donde(),
                                       f"recurso remoto en {attr}: {remoto}; solo material propio local"))
    for m in _REMOTO_CSS.finditer(_COMENTARIO_CSS.sub("", css)):
        salida.append(Hallazgo("QG-03", "critica", "css", f"recurso remoto en el CSS: «{m.group(0)}»"))
    return salida


def _urls_css(css: str) -> list[str]:
    """Las ``url(…)`` de un CSS, sin comentarios ni bloques ``@font-face`` (las fuentes las mira fuentes.py)."""
    css = _FONT_FACE.sub("", _COMENTARIO_CSS.sub("", css))
    return [m.group(2).strip() for m in _URL_LOCAL_CSS.finditer(css)]


def _imagenes_locales(raiz: _Nodo, css: str) -> list[tuple[str, str]]:
    """(dónde, referencia) de toda imagen que no sea remota (QG-03) ni un fragmento ``#id`` del documento:
    ``src`` de ``img``/``input``/``source``/``embed``, cada candidato de ``srcset``, ``poster``, ``href`` y
    ``xlink:href`` de ``image``/``use``/``feImage`` de SVG, y ``url()`` en ``<style>`` y en ``style=``."""
    refs: list[tuple[str, str]] = []
    for n in raiz.descendientes():
        valores: list[str] = []
        if n.tag in ("img", "input", "source", "embed") and "src" in n.attrs:
            valores.append(n.attrs["src"])
        for attr, valor in n.attrs.items():
            if attr.endswith("srcset"):
                valores += _candidatos_srcset(valor)
            elif attr == "poster" or (n.tag in _IMG_EN_SVG and attr in ("href", "xlink:href")):
                valores.append(valor)
        valores += _urls_css(n.attrs.get("style", ""))
        refs += [(n.donde(), v.strip()) for v in valores]
    refs += [("css", v) for v in _urls_css(css)]
    return [(donde, ref) for donde, ref in refs if not _REMOTO.match(ref) and not ref.startswith("#")]


def _qg04(raiz: _Nodo, css: str, raiz_pieza: Path) -> list[Hallazgo]:
    """Cada imagen local (``_imagenes_locales``) está en ``medios.json``; una ``data:`` incrustada no lo está.
    El manifiesto se lee con ``verificar=True``: origen ``apimart|propio``, sha256 recalculado, sin enlaces y
    en 0640 (Tarea 1); el primer fallo es crítico."""
    refs = _imagenes_locales(raiz, css)
    if not refs:
        return []
    try:
        manifiesto = leer_manifiesto(raiz_pieza, verificar=True)
    except (ValueError, OSError) as exc:
        return [Hallazgo("QG-04", "critica", f"{CARPETA}/{MANIFIESTO}", f"{exc}: solo imágenes propias")]
    archivos = {e["archivo"] for e in manifiesto.values()}
    salida = []
    for donde, ref in refs:
        archivo = ref.removeprefix(f"{CARPETA}/") if ref.startswith(f"{CARPETA}/") else None
        if archivo not in archivos:
            salida.append(Hallazgo("QG-04", "critica", donde,
                                   f"la imagen «{ref[:80]}» no está en {CARPETA}/{MANIFIESTO}: solo imágenes propias"))
    return salida


def _qg06_07_08(secciones: list[_Nodo], cfg: ConfigProducto) -> list[Hallazgo]:
    salida = []
    for s in secciones:
        palabras = _palabras(s)
        if palabras < cfg.seccion_palabras_min:
            salida.append(Hallazgo("QG-06", "alta", s.donde(),
                                   f"la sección tiene {palabras} palabras (mínimo {cfg.seccion_palabras_min}): "
                                   "enriquécela con ejemplos o ejercicios; nunca rellenes"))
        hijos = [h for h in s.elementos() if h.tag != "h2"]
        faltan = []
        if not hijos or "lograr" not in hijos[0].clases:
            faltan.append("«.lograr» al principio")
        h3 = sum(1 for n in s.descendientes() if n.tag == "h3")
        minimo, maximo = H3_POR_SECCION
        if not minimo <= h3 <= maximo:
            faltan.append(f"entre {minimo} y {maximo} h3 (tiene {h3})")
        if not hijos or "recordar" not in hijos[-1].clases:
            faltan.append("«.recordar» al final")
        if faltan:
            salida.append(Hallazgo("QG-07", "alta", s.donde(), "a la sección le falta: " + "; ".join(faltan)))
    practica = [any(c in n.clases for n in s.descendientes() for c in ("plantilla", "ejercicio", "ficha"))
                for s in secciones]
    i = 0
    while i < len(secciones):
        j = i
        while j < len(secciones) and not practica[j]:
            j += 1
        if j - i >= 2:
            ids = ", ".join(secciones[k].attrs.get("id", "?") for k in range(i, j))
            salida.append(Hallazgo("QG-08", "media", secciones[i].donde(),
                                   f"{j - i} secciones seguidas sin práctica ({ids}): añade una plantilla, "
                                   "un ejercicio o una ficha"))
        i = max(j, i + 1)
    return salida


def _en_linea(n: _Nodo):
    """Descendientes en línea de ``n`` sin entrar en sus bloques hijos."""
    for h in n.elementos():
        if h.tag in EN_LINEA:
            yield h
            yield from _en_linea(h)


def _qg09(raiz: _Nodo) -> list[Hallazgo]:
    """Cada bloque (``p``, ``li``, ``td``, ``h3``…) con una cifra en su propio texto (sin sus bloques hijos)
    cita una fuente con un ``a.fuente`` en ese texto. Se saltan lo invisible, el índice (repite los
    títulos) y las entradas citadas ``li[id^=fuente-]``."""
    salida = []
    fuentes = {n.attrs.get("id") for f in _de_clase(raiz, "section", "fuentes") for n in f.descendientes()}

    def propio(h: _Nodo) -> bool:
        return h.tag not in EN_LINEA or _omitir_contar(h)

    def revisar(n: _Nodo) -> None:
        for h in n.elementos():
            if h.tag in _NO_PROMESA or (h.tag == "nav" and "indice" in h.clases) or _es_cita(h):
                continue
            if h.tag not in EN_LINEA:
                cifra = _CIFRA.search(_texto(h, propio))
                if cifra:
                    citas = [a.attrs.get("href", "") for a in _en_linea(h) if a.tag == "a" and "fuente" in a.clases]
                    if not any(c.startswith("#fuente-") and c[1:] in fuentes for c in citas):
                        salida.append(Hallazgo("QG-09", "alta", h.donde(),
                                               f"la cifra «{cifra.group(0)}» no cita una fuente "
                                               "(a.fuente → #fuente-N)"))
            revisar(h)

    revisar(raiz)
    return salida


def _qg12(raiz: _Nodo) -> list[Hallazgo]:
    salida, vistos = [], {}
    for p in (n for n in raiz.descendientes() if n.tag == "p"):
        palabras = PALABRA.findall(_texto(p, _omitir_contar).lower())
        if len(palabras) < PALABRAS_RELLENO:
            continue
        clave = " ".join(palabras)
        if clave in vistos:
            if vistos[clave] is not None:
                salida.append(Hallazgo("QG-12", "alta", p.donde(),
                                       f"párrafo repetido (ya en la línea {vistos[clave]}): «"
                                       f"{' '.join(palabras[:8])}…»; nunca rellenes"))
                vistos[clave] = None
        else:
            vistos[clave] = p.linea
    return salida


def _paginas_vacias(paginas: list[_Nodo]) -> list[Hallazgo]:
    """Una ``.page`` sin texto ni imagen es relleno (QG-12, alta como el resto del gate): no suma páginas."""
    return [Hallazgo("QG-12", "alta", n.donde(), "página vacía (.page sin texto ni imagen): no cuenta como "
                     "página; quítala o dale contenido, nunca rellenes")
            for n in paginas if _vacia(n)]


def _vacia(n: _Nodo) -> bool:
    return (not PALABRA.search(_texto(n, lambda _n: False))
            and not any(d.tag in ("img", "svg") for d in n.descendientes()))


def _qg14(raiz: _Nodo, css: str) -> list[Hallazgo]:
    """``@page{size:A4;margin:0}`` y ``.page{height:296.8mm}``; nada recorta el desborde en ningún selector
    ni en ningún ``style=`` (``overflow*: hidden|clip``, también con ``!important`` o dos valores, y
    ``contain: paint|content|strict``): el desborde se ve y se arregla, no se esconde."""
    salida = []
    reglas = _reglas_css(css)
    pagina = any(pre == "@page" and frozenset(d.get("size", "").split()) in _TAMANO_A4
                 and d.get("margin") and all(_CERO.fullmatch(v) for v in d["margin"].split())
                 for pre, d in reglas)
    if not pagina:
        salida.append(Hallazgo("QG-14", "alta", "css", "falta @page{size:A4;margin:0}"))
    alto = any(".page" in [s.strip() for s in pre.split(",")] and d.get("height") == "296.8mm"
               for pre, d in reglas)
    if not alto:
        salida.append(Hallazgo("QG-14", "alta", "css", "falta .page{height:296.8mm}"))
    for pre, d in reglas:
        recorte = _recorte(d)
        if recorte:
            salida.append(Hallazgo("QG-14", "alta", f"css: {pre}",
                                   f"{recorte} recorta el desborde en vez de mostrarlo (overflow:hidden y "
                                   "parecidos): prohibido"))
    for n in raiz.descendientes():
        recorte = _recorte(_declaraciones(n.attrs.get("style", "")))
        if recorte:
            salida.append(Hallazgo("QG-14", "alta", n.donde(),
                                   f"{recorte} en style= recorta el desborde (overflow:hidden y parecidos): prohibido"))
    return salida


def puntuar(hallazgos: list[Hallazgo] | tuple[Hallazgo, ...], puntuacion_min: int) -> tuple[int, bool]:
    puntuacion = max(0, 100 - sum(PESOS[h.severidad] for h in hallazgos))
    criticos = any(h.severidad == "critica" for h in hallazgos)
    return puntuacion, not criticos and puntuacion >= puntuacion_min


def evaluar(html: str, *, raiz: Path, idioma: str, exigencia: str, tipo_pieza: str, paginas_objetivo: int,
            cfg: ConfigProducto, vault: Path | None = None) -> Informe:
    if exigencia not in EXIGENCIAS:
        raise ValueError(f"exigencia «{exigencia}» no admitida: {', '.join(EXIGENCIAS)}")
    if tipo_pieza not in TIPOS_PIEZA:
        raise ValueError(f"tipo de pieza «{tipo_pieza}» no admitido: {', '.join(TIPOS_PIEZA)}")
    arbol = _arbol(html)
    doc = arbol.raiz
    css = "\n".join(_texto(n, lambda _n: False) for n in doc.descendientes() if n.tag == "style")
    secciones = _de_clase(doc, None, "seccion")

    hallazgos: list[Hallazgo] = []
    hallazgos += _qg01(html)
    hallazgos += _qg02(doc)
    hallazgos += _qg03(doc, css)
    hallazgos += _qg04(doc, css, Path(raiz))

    palabras = _palabras(doc)
    paginas = [n for n in doc.descendientes() if "page" in n.clases]
    llenas = [n for n in paginas if not _vacia(n)]
    fichas = sum(1 for n in llenas if "ficha" in n.clases)
    # Una página de imagen solo cuenta si tiene un <img>; una .page vacía no cuenta y es un hallazgo.
    imagen = sum(1 for n in llenas if "ficha" not in n.clases and any(d.tag == "img" for d in n.descendientes()))
    hallazgos += _paginas_vacias(paginas)
    c = cuenta(palabras, fichas, imagen, paginas_objetivo, cfg.palabras_por_pagina)
    if c.paginas_estimadas < paginas_objetivo:
        hallazgos.append(Hallazgo("QG-05", "critica", "documento",
                                  f"{c.paginas_estimadas} páginas estimadas de {paginas_objetivo}: {c.mensaje}"))

    hallazgos += _qg06_07_08(secciones, cfg)
    hallazgos += _qg09(doc)
    hallazgos += promesas(_texto(doc, _omitir_promesas), idioma, exigencia, vault)
    if exigencia == "sanitario":
        avisos = _de_clase(doc, "aside", "aviso-salud")
        palabras_aviso = sum(_palabras(a) for a in avisos)
        if not avisos:
            hallazgos.append(Hallazgo("QG-11", "critica", "documento",
                                      "exigencia sanitaria sin aside.aviso-salud: añade el aviso de salud"))
        elif palabras_aviso < AVISO_PALABRAS_MIN:
            hallazgos.append(Hallazgo("QG-11", "critica", avisos[0].donde(),
                                      f"el aside.aviso-salud tiene {palabras_aviso} palabras (mínimo "
                                      f"{AVISO_PALABRAS_MIN}): explica que no es un tratamiento y cuándo ir al médico"))
    hallazgos += _qg12(doc)
    hallazgos += [Hallazgo("QG-13", "media", f"línea {linea}", texto) for linea, texto in arbol.errores]
    hallazgos += _qg14(doc, css)

    hallazgos.sort(key=lambda h: h.gate)
    puntuacion, pasa = puntuar(hallazgos, cfg.puntuacion_min)
    return Informe(tuple(hallazgos), puntuacion, pasa, palabras, c.paginas_estimadas)
