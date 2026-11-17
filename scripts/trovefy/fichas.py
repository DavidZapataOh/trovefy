"""Palabras comparables de un texto (solo biblioteca estándar: la usan también los hooks con el python3 del sistema).

`fichas` vino de `trovefy.mapa` (que la reexporta como `_fichas`): %-decodifica, quita acentos, pasa homoglifos
cirílicos y griegos a latín, quita invisibles, pasa a minúsculas y parte por cualquier separador. Con
``camel=True`` además parte el camelCase («metaPixelId» → meta, pixel, id; «APIKey» → api, key).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

# Letras cirílicas y griegas que se confunden con latinas (mayúsculas y minúsculas por separado: la «ν» griega
# minúscula parece una «v», la «Ν» mayúscula una «N»).
HOMOGLIFOS = str.maketrans({
    # cirílico
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J", "Ү": "Y", "Ԛ": "Q", "Ԝ": "W",
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w", "ӏ": "l",
    "ү": "y", "ɡ": "g",
    # griego
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ω": "w", "ϲ": "c",
})
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def fichas(texto: str, *, camel: bool = False) -> list[str]:
    """Las palabras de `texto`, comparables: %-decodificado (hasta 3 veces), sin acentos (NFKD), homoglifos
    cirílicos y griegos pasados a latín, en minúsculas, sin caracteres invisibles (ancho cero, guion blando) y
    partido por cualquier separador (espacios, guiones, puntos, barras, «_»…); con `camel`, también por camelCase.
    """
    t = str(texto)
    for _ in range(3):
        decodificado = unquote(t)
        if decodificado == t:
            break
        t = decodificado
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = t.translate(HOMOGLIFOS)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    if camel:
        t = _CAMEL.sub(" ", t)
    return [f for f in re.split(r"[\W_]+", t.casefold()) if f]
