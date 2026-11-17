"""Paso 2 de ``/producto``: el plan del libro y el contador de 350 palabras por página (§4.7).

Claude escribe ``PLAN.md`` con una tabla ``| sección | palabras | fichas |`` (y, si quiere, una columna
``imágenes`` con las páginas de imagen a toda página). Aquí solo se cuenta: si el plan no llega al
objetivo de páginas de la ficha, se dice cuántas palabras faltan y que se enriquezca, nunca que se rellene.

``contar_palabras`` es el mismo contador que usan los gates (QG-05, QG-06): texto visible, sin el índice
(``nav.indice``), sin las fuentes (``section.fuentes``) y sin los pies de figura; palabras = ``\\w+``
Unicode, así que cuenta igual en latino y en cirílico.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

from trovefy.producto.config import ConfigProducto

PALABRA = re.compile(r"\w+")
# Elementos HTML sin cierre (HTML Living Standard, «void elements»).
VACIAS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                    "wbr"})
# Elementos en línea: su texto se pega al de alrededor («pa<strong>la</strong>bra» es una palabra).
EN_LINEA = frozenset({"a", "abbr", "b", "cite", "code", "em", "i", "mark", "q", "s", "small", "span", "strong",
                       "sub", "sup", "u"})
_NO_VISIBLES = frozenset({"head", "title", "style", "script", "template", "noscript", "figcaption"})
_ENRIQUECER = "enriquece con ejemplos, ejercicios o plantillas; nunca rellenes"
_ENTERO = re.compile(r"\d{1,3}(?:[.  ]\d{3})+|\d+")
_VACIO = frozenset({"", "-", "—", "–"})


def clases(attrs: dict[str, str | None] | list[tuple[str, str | None]]) -> set[str]:
    datos = dict(attrs)
    return set((datos.get("class") or "").split())


def no_cuenta(tag: str, clases_: set[str]) -> bool:
    """True si el texto del elemento no cuenta como palabras del libro."""
    return (tag in _NO_VISIBLES or (tag == "nav" and "indice" in clases_)
            or (tag == "section" and "fuentes" in clases_))


class _Contador(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pila: list[tuple[str, bool]] = []
        self.trozos: list[str] = []

    def _oculto(self) -> bool:
        return any(oculto for _, oculto in self.pila)

    def handle_starttag(self, tag, attrs):
        if tag not in EN_LINEA:
            self.trozos.append(" ")
        if tag not in VACIAS:
            self.pila.append((tag, no_cuenta(tag, clases(attrs))))

    def handle_startendtag(self, tag, attrs):
        if tag not in EN_LINEA:
            self.trozos.append(" ")

    def handle_endtag(self, tag):
        if tag not in EN_LINEA:
            self.trozos.append(" ")
        for i in range(len(self.pila) - 1, -1, -1):
            if self.pila[i][0] == tag:
                del self.pila[i:]
                break

    def handle_data(self, data):
        if not self._oculto():
            self.trozos.append(data)


def contar_palabras(html: str) -> int:
    lector = _Contador()
    lector.feed(html)
    lector.close()
    return len(PALABRA.findall("".join(lector.trozos)))


def paginas_estimadas(palabras: int, fichas: int, paginas_imagen: int, palabras_por_pagina: int) -> int:
    return math.ceil(palabras / palabras_por_pagina) + fichas + paginas_imagen


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@dataclass(frozen=True)
class Cuenta:
    palabras: int
    fichas: int
    paginas_imagen: int
    paginas_estimadas: int
    objetivo: int
    faltan_palabras: int

    @property
    def mensaje(self) -> str:
        if self.faltan_palabras > 0:
            paginas = self.objetivo - self.paginas_estimadas
            return (f"faltan ≈ {_miles(self.faltan_palabras)} palabras ({paginas} "
                    f"{'página' if paginas == 1 else 'páginas'}): {_ENRIQUECER}")
        return f"el plan llega: {self.paginas_estimadas} páginas estimadas para un objetivo de {self.objetivo}"


def cuenta(palabras: int, fichas: int, paginas_imagen: int, objetivo: int, palabras_por_pagina: int) -> Cuenta:
    estimadas = paginas_estimadas(palabras, fichas, paginas_imagen, palabras_por_pagina)
    faltan = max(0, (objetivo - fichas - paginas_imagen) * palabras_por_pagina - palabras)
    return Cuenta(palabras, fichas, paginas_imagen, estimadas, objetivo, faltan)


def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).strip().lower()


def _celdas(linea: str) -> list[str] | None:
    linea = linea.strip()
    if not linea.startswith("|"):
        return None
    return [c.strip() for c in linea.strip("|").split("|")]


def _entero(celda: str, columna: str, obligatoria: bool) -> int:
    if celda in _VACIO and not obligatoria:
        return 0
    if not _ENTERO.fullmatch(celda):
        raise ValueError(f"PLAN.md: «{celda}» no es un número de {columna}")
    return int(re.sub(r"\D", "", celda))


def comprobar_plan(texto_plan: str, objetivo: int, cfg: ConfigProducto) -> Cuenta:
    """Suma la tabla ``| sección | palabras | fichas |`` de ``PLAN.md`` y la compara con el objetivo."""
    lineas = texto_plan.splitlines()
    for i, linea in enumerate(lineas):
        celdas = _celdas(linea)
        if not celdas:
            continue
        nombres = [_normal(c) for c in celdas]
        if not {"seccion", "palabras", "fichas"} <= set(nombres):
            continue
        col = {n: j for j, n in enumerate(nombres)}
        col_img = next((j for j, n in enumerate(nombres) if n.startswith("imagen")), None)
        palabras = fichas = imagenes = 0
        for fila in lineas[i + 2:]:
            datos = _celdas(fila)
            if datos is None:
                break
            if len(datos) < len(nombres):
                raise ValueError(f"PLAN.md: a la fila «{fila.strip()}» le faltan columnas")
            palabras += _entero(datos[col["palabras"]], "palabras", True)
            fichas += _entero(datos[col["fichas"]], "fichas", False)
            if col_img is not None:
                imagenes += _entero(datos[col_img], "imágenes", False)
        return cuenta(palabras, fichas, imagenes, objetivo, cfg.palabras_por_pagina)
    raise ValueError("PLAN.md no tiene la tabla | sección | palabras | fichas |")
