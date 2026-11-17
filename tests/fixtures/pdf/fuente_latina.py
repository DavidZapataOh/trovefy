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


def crear_coleccion(ruta: Path) -> Path:
    """``.ttc`` con dos fuentes: la 0 solo ASCII y la 1 con ASCII y cirílico (А–я). Sirve para probar que se
    lee la fuente del índice que da ``fc-match`` y no siempre la primera."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.ttCollection import TTCollection

    def fuente(nombre: str, codigos: list[int]) -> TTFont:
        nombres = [".notdef"] + [f"u{c:04X}" for c in codigos]
        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder(nombres)
        fb.setupCharacterMap({c: f"u{c:04X}" for c in codigos})
        vacio = TTGlyphPen(None).glyph()
        fb.setupGlyf(dict.fromkeys(nombres, vacio))
        fb.setupHorizontalMetrics(dict.fromkeys(nombres, (500, 0)))
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupNameTable({"familyName": nombre, "styleName": "Regular"})
        fb.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
        fb.setupPost()
        return fb.font

    ascii_ = list(range(0x20, 0x7F))
    coleccion = TTCollection()
    cirilico = ascii_ + list(range(0x410, 0x450))
    coleccion.fonts = [fuente("Coleccion Latina", ascii_), fuente("Coleccion Cirilica", cirilico)]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    coleccion.save(str(ruta))
    return ruta
