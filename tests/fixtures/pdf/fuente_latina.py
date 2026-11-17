"""Fuente TrueType de prueba sin cirílico (solo ASCII), creada con fontTools."""

from pathlib import Path

FAMILIA_LATINA = "Latin Only"


def crear_fuente_latina(ruta: Path) -> Path:
    """TrueType mínima: solo ASCII imprimible (glifos vacíos). Sirve para probar la cobertura de glifos."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    letras = [chr(c) for c in range(0x20, 0x7F)]
    nombres = [".notdef"] + [f"u{ord(c):04X}" for c in letras]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(nombres)
    fb.setupCharacterMap({ord(c): f"u{ord(c):04X}" for c in letras})
    vacio = TTGlyphPen(None).glyph()
    fb.setupGlyf(dict.fromkeys(nombres, vacio))
    fb.setupHorizontalMetrics(dict.fromkeys(nombres, (500, 0)))
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": FAMILIA_LATINA, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(ruta))
    return ruta
