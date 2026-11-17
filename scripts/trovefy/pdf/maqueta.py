"""Maquetación A4: fragmentos saneados, tokens del brandbook, fichas imprimibles y ensamblado.

Claude escribe el texto (D-27) como fragmentos HTML en ``<pieza>/fuente/``: ``secciones/NN-*.html``
(cada uno con su ``h2``), ``fichas/*.yaml`` (kits), ``fuentes.html`` (con su ``h2`` y la lista
``li#fuente-N``) y, si la pieza lo necesita, ``aviso-salud.html``. Aquí solo se comprueba y se maqueta:
cada fragmento pasa una lista blanca estricta (nada de scripts, estilos ni recursos remotos) y el
documento se arma con ``templates/pdf/base.css`` + los tokens del brandbook.

Tokens y tipografías (resolución 7): la fuente es ``tokens_css`` del frontmatter de ``BRANDBOOK.md``
(el bloque ```` ```css ```` es copia para leer) y ``tipografias`` es una lista con ``uso: titulos`` y
``uso: texto``.
"""

from __future__ import annotations

import html as html_mod
import re
from html.parser import HTMLParser
from pathlib import Path

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.modelar.esquema import token_css_inseguro
from trovefy.producto.ficha import Ficha, PiezaFicha
from trovefy.producto.medios import CARPETA
from trovefy.producto.rutas import Pieza

BASE_CSS = Path(__file__).resolve().parents[3] / "templates" / "pdf" / "base.css"
ETIQUETAS = frozenset([
    "h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "blockquote", "table", "thead", "tbody", "tr", "th",
    "td", "figure", "figcaption", "img", "a", "aside", "div", "span", "br", "sup",
])
ATRIBUTOS = frozenset(("class", "id", "href", "src", "alt"))
TIPOS_FICHA = ("tabla", "lineas", "casillas")
FILAS_MAX = 500  # una ficha de más de una página se detecta por anclas; esto solo corta lo absurdo
PORTADA = "portada.png"

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_CLASE = re.compile(r"[A-Za-z0-9_-]+(?:\s+[A-Za-z0-9_-]+)*")
_HREF = re.compile(r"#[A-Za-z][A-Za-z0-9_-]*")
_SRC = re.compile(rf"{CARPETA}/[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
_ID_FICHA = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
_CLAVE_TOKEN = re.compile(r"--[a-z0-9-]+")
_TOKEN_PROHIBIDO = re.compile(r"url\(|@|;|\{|\}", re.IGNORECASE)
_FAMILIA = re.compile(r"[^\W_][\w \-]*")
_IDIOMA = re.compile(r"[a-z]{2}")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


class FragmentoInvalido(ValueError):
    """Un fragmento HTML de Claude se sale de la lista blanca."""


class BrandbookSinTokens(ValueError):
    """``BRANDBOOK.md`` no trae ``tokens_css`` válidos."""


# --- fragmentos -------------------------------------------------------------------------------------


class _Saneador(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.h2: str | None = None
        self._en_h2 = False
        self._texto_h2: list[str] = []

    def _mal(self, motivo: str):
        linea = self.getpos()[0]
        raise FragmentoInvalido(f"línea {linea}: {motivo}")

    def handle_starttag(self, tag, attrs):
        if tag not in ETIQUETAS:
            self._mal(f"<{tag}> no está permitido (solo {', '.join(sorted(ETIQUETAS))})")
        for nombre, valor in attrs:
            valor = valor or ""
            if nombre.startswith("on"):
                self._mal(f"atributo {nombre} prohibido en <{tag}>")
            if nombre not in ATRIBUTOS:
                self._mal(f"atributo {nombre} no permitido en <{tag}> (solo {', '.join(sorted(ATRIBUTOS))})")
            if nombre == "id":
                if not _ID.fullmatch(valor):
                    self._mal(f"id mal escrito: «{valor}»")
                self.ids.append(valor)
            elif nombre == "class" and not _CLASE.fullmatch(valor.strip()):
                self._mal(f"class mal escrita: «{valor}»")
            elif nombre == "href" and not _HREF.fullmatch(valor):
                self._mal(f"href solo a un ancla del propio libro (#…): «{valor}»")
            elif nombre == "src" and (tag != "img" or not _SRC.fullmatch(valor) or ".." in valor):
                self._mal(f"src solo en <img> y a {CARPETA}/<archivo>: «{valor}»")
        if tag == "h2" and self.h2 is None:
            self._en_h2 = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in ETIQUETAS:
            self._mal(f"</{tag}> no está permitido")
        if tag == "h2" and self._en_h2:
            self._en_h2 = False
            self.h2 = " ".join("".join(self._texto_h2).split())

    def handle_data(self, data):
        if self._en_h2:
            self._texto_h2.append(data)

    def handle_comment(self, data):
        self._mal("comentarios HTML no permitidos")

    def handle_decl(self, decl):
        self._mal(f"declaración <!{decl}> no permitida")

    def handle_pi(self, data):
        self._mal("instrucción de proceso no permitida")

    def unknown_decl(self, data):
        self._mal("declaración no permitida")


def _sanear(html: str) -> tuple[str, _Saneador]:
    if not isinstance(html, str):
        raise FragmentoInvalido("el fragmento no es texto")
    s = _Saneador()
    s.feed(html)
    s.close()
    return html.strip(), s


def sanear_fragmento(html: str) -> str:
    """Devuelve el fragmento (sin espacios en los extremos) si cumple la lista blanca; si no,
    ``FragmentoInvalido``. Nunca lo «arregla»: un fragmento malo lo rehace Claude."""
    return _sanear(html)[0]


# --- brandbook --------------------------------------------------------------------------------------


def _meta(texto: str) -> dict:
    m = _FRONTMATTER.match(texto or "")
    if not m:
        return {}
    try:
        meta = cargar_yaml(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise BrandbookSinTokens(f"BRANDBOOK.md: frontmatter ilegible ({exc})") from None
    return meta if isinstance(meta, dict) else {}


def _validar_tokens(tokens: object) -> dict[str, str]:
    if not isinstance(tokens, dict) or not tokens:
        raise BrandbookSinTokens("BRANDBOOK.md no trae tokens_css: rehaz el brandbook en /modelar")
    salida: dict[str, str] = {}
    for clave, valor in tokens.items():
        if not isinstance(clave, str) or not _CLAVE_TOKEN.fullmatch(clave):
            raise BrandbookSinTokens(f"tokens_css: clave «{clave}» mal escrita (--minusculas-numeros-y-guiones)")
        if not isinstance(valor, str) or _TOKEN_PROHIBIDO.search(valor):
            raise BrandbookSinTokens(f"tokens_css.{clave}: «{valor}» no puede llevar url( @ ; {{ ni }}")
        motivo = token_css_inseguro(clave, valor)
        if motivo:
            raise BrandbookSinTokens(f"tokens_css.{clave}: {motivo}")
        salida[clave] = valor
    return salida


def tokens_brandbook(texto: str) -> dict[str, str]:
    """Tokens ``--…`` de ``tokens_css`` en el frontmatter de ``BRANDBOOK.md`` (texto completo)."""
    return _validar_tokens(_meta(texto).get("tokens_css"))


def familias_brandbook(meta: dict) -> tuple[str, str]:
    """(familia de títulos, familia de texto) de ``tipografias`` por ``uso`` (resolución 7)."""
    lista = meta.get("tipografias") if isinstance(meta, dict) else None
    if not isinstance(lista, list):
        raise ValueError("BRANDBOOK.md: tipografias no es una lista: /modelar")  # noqa: TRY004 - error de datos
    por_uso: dict[str, list[str]] = {"titulos": [], "texto": []}
    for t in lista:
        if isinstance(t, dict) and t.get("uso") in por_uso:
            por_uso[t["uso"]].append(t.get("familia"))
    familias = []
    for uso, encontradas in por_uso.items():
        if len(encontradas) != 1:
            raise ValueError(f"BRANDBOOK.md: tipografias necesita exactamente una con uso: {uso}: /modelar")
        familia = encontradas[0]
        if not isinstance(familia, str) or not _FAMILIA.fullmatch(familia.strip()):
            raise ValueError(f"BRANDBOOK.md: tipografias ({uso}) trae una familia mal escrita: «{familia}»")
        familias.append(familia.strip())
    return familias[0], familias[1]


# --- fichas imprimibles -----------------------------------------------------------------------------


def _e(texto: str) -> str:
    return html_mod.escape(texto, quote=True)


def _texto(spec: dict, clave: str) -> str:
    valor = spec.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"ficha: falta «{clave}» (texto)")
    return valor.strip()


def generar_ficha_imprimible(spec: dict) -> str:
    """``div.page.ficha`` con anclas ``ini-<id>``/``fin-<id>`` desde un ``fuente/fichas/*.yaml``:
    ``{id, titulo, instrucciones, tipo: tabla|lineas|casillas, columnas?, filas}``. ``filas`` es un entero
    (filas vacías); en ``casillas`` también puede ser la lista de textos de cada casilla."""
    if not isinstance(spec, dict):
        raise ValueError("ficha: el yaml no es un mapa")  # noqa: TRY004 - error de datos
    ident = spec.get("id")
    if not isinstance(ident, str) or not _ID_FICHA.fullmatch(ident):
        raise ValueError(f"ficha: id mal escrito «{ident}» (minúsculas, cifras y guiones)")
    titulo, instrucciones = _texto(spec, "titulo"), _texto(spec, "instrucciones")
    tipo = spec.get("tipo")
    if tipo not in TIPOS_FICHA:
        raise ValueError(f"ficha {ident}: tipo «{tipo}» no admitido ({', '.join(TIPOS_FICHA)})")
    filas = spec.get("filas")
    etiquetas: list[str] = []
    if tipo == "casillas" and isinstance(filas, list):
        if not filas or not all(isinstance(x, str) and x.strip() for x in filas):
            raise ValueError(f"ficha {ident}: filas debe ser un entero o una lista de textos")
        etiquetas = [x.strip() for x in filas]
        filas = len(etiquetas)
    if isinstance(filas, bool) or not isinstance(filas, int) or not 1 <= filas <= FILAS_MAX:
        raise ValueError(f"ficha {ident}: filas debe ser un entero entre 1 y {FILAS_MAX}")

    lineas = ['<div class="page ficha">', f'<span id="ini-{ident}"></span>', f"<h2>{_e(titulo)}</h2>",
              f'<p class="instrucciones">{_e(instrucciones)}</p>']
    if tipo == "tabla":
        columnas = spec.get("columnas")
        if not isinstance(columnas, list) or not columnas or not all(isinstance(c, str) for c in columnas):
            raise ValueError(f"ficha {ident}: una tabla necesita columnas (lista de textos)")
        cabecera = "".join(f"<th>{_e(c)}</th>" for c in columnas)
        vacia = "<tr>" + "<td></td>" * len(columnas) + "</tr>"
        lineas += ["<table>", f"<thead><tr>{cabecera}</tr></thead>", "<tbody>", *[vacia] * filas,
                   "</tbody>", "</table>"]
    elif tipo == "lineas":
        lineas += ['<div class="lineas">', *['<div class="linea"></div>'] * filas, "</div>"]
    else:
        textos = etiquetas or [""] * filas
        lineas += ['<ul class="casillas">', *[f'<li><span class="casilla"></span>{_e(t)}</li>' for t in textos],
                   "</ul>"]
    lineas += [f'<span class="push" id="fin-{ident}"></span>', "</div>"]
    return "\n".join(lineas)


# --- ensamblado -------------------------------------------------------------------------------------


def _leer_fragmento(ruta: Path, *, con_h2: bool) -> tuple[str, _Saneador]:
    try:
        texto, s = _sanear(Path(ruta).read_text(encoding="utf-8"))
    except FragmentoInvalido as exc:
        raise FragmentoInvalido(f"{Path(ruta).name}: {exc}") from None
    if con_h2 and not s.h2:
        raise FragmentoInvalido(f"{Path(ruta).name}: le falta su <h2> (el título del apartado)")
    return texto, s


def _ficha_yaml(ruta: Path) -> str:
    try:
        spec = cargar_yaml(Path(ruta).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{Path(ruta).name}: yaml ilegible ({exc})") from None
    try:
        return generar_ficha_imprimible(spec)
    except ValueError as exc:
        raise ValueError(f"{Path(ruta).name}: {exc}") from None


def ensamblar(pieza: Pieza, ficha: Ficha, pieza_ficha: PiezaFicha, tokens: dict[str, str],
              familias: tuple[str, str], secciones: list[Path], fichas: list[Path], manifiesto: dict) -> str:
    """Documento A4 completo de una pieza, listo para los gates y WeasyPrint.

    Orden: portada (``div.page.portada``, con ``medios/portada.png`` si está en el manifiesto) →
    ``nav.indice`` → ``aside.aviso-salud`` (si existe ``fuente/aviso-salud.html``) → una
    ``section.seccion.flujo#s-NN`` por fragmento, en el orden dado → fichas → ``section.fuentes#fuentes``
    (si existe ``fuente/fuentes.html``). ``FragmentoInvalido`` si un fragmento se sale de la lista blanca,
    no trae su ``h2`` o repite un id.
    """
    tokens = _validar_tokens(tokens)
    if not isinstance(ficha.idioma, str) or not _IDIOMA.fullmatch(ficha.idioma):
        raise ValueError(f"idioma mal escrito en FICHA.md: «{ficha.idioma}»")
    for familia in familias:
        if not isinstance(familia, str) or not _FAMILIA.fullmatch(familia):
            raise ValueError(f"familia de fuente mal escrita: «{familia}»")
    fuente = Path(pieza.raiz) / "fuente"
    titulo = _e(pieza_ficha.titulo)
    ids = ["ini-portada", "fin-portada", "fuentes"]

    bloques_secciones, indice = [], []
    for n, ruta in enumerate(secciones, 1):
        texto, s = _leer_fragmento(ruta, con_h2=True)
        ancla = f"s-{n:02d}"
        ids += [ancla, *s.ids]
        indice.append(f'<li><a href="#{ancla}">{_e(s.h2)}</a></li>')
        bloques_secciones.append(f'<section class="seccion flujo" id="{ancla}">\n{texto}\n</section>')

    bloques_fichas = []
    for ruta in fichas:
        html_ficha = _ficha_yaml(ruta)
        ids += _sanear(html_ficha)[1].ids
        bloques_fichas.append(html_ficha)

    aviso = None
    if (fuente / "aviso-salud.html").is_file():
        texto, s = _leer_fragmento(fuente / "aviso-salud.html", con_h2=False)
        ids += s.ids
        aviso = f'<aside class="aviso-salud flujo">\n{texto}\n</aside>'
    fuentes = None
    if (fuente / "fuentes.html").is_file():
        texto, s = _leer_fragmento(fuente / "fuentes.html", con_h2=True)
        ids += s.ids
        indice.append(f'<li><a href="#fuentes">{_e(s.h2)}</a></li>')
        fuentes = f'<section class="fuentes flujo" id="fuentes">\n{texto}\n</section>'

    vistos: set[str] = set()
    for i in ids:
        if i in vistos:
            raise FragmentoInvalido(f"id repetido en el documento: «{i}» (cada id una vez; ini-/fin-/s-NN "
                                    "y fuentes los pone la maqueta)")
        vistos.add(i)

    root = ";".join(f"{k}:{v}" for k, v in tokens.items())
    caras = [f'@font-face{{font-family:"{f}";src:local("{f}")}}' for f in dict.fromkeys(familias)]
    css = BASE_CSS.read_text(encoding="utf-8").rstrip("\n")
    portada = ['<div class="page portada">', '<span id="ini-portada"></span>', f"<h1>{titulo}</h1>"]
    if any(isinstance(e, dict) and e.get("archivo") == PORTADA for e in (manifiesto or {}).values()):
        portada.append(f'<img src="{CARPETA}/{PORTADA}" alt="{titulo}">')
    portada += ['<span class="push" id="fin-portada"></span>', "</div>"]

    partes = [
        "<!DOCTYPE html>", f'<html lang="{_e(ficha.idioma)}">', "<head>", '<meta charset="utf-8">',
        f"<title>{titulo}</title>", "<style>", css, f":root{{{root}}}", *caras, "</style>", "</head>", "<body>",
        *portada, '<nav class="indice flujo">', "<ol>", *indice, "</ol>", "</nav>",
    ]
    if aviso:
        partes.append(aviso)
    partes += bloques_secciones + bloques_fichas
    if fuentes:
        partes.append(fuentes)
    partes += ["</body>", "</html>"]
    return "\n".join(partes) + "\n"
