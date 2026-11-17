from decimal import Decimal

import pytest
from trovefy.pdf.plan import Cuenta, comprobar_plan, contar_palabras, paginas_estimadas
from trovefy.producto.config import ConfigProducto

CFG = ConfigProducto(
    tope_usd=Decimal("2.00"), modelos_imagen=("gpt-image-2",), resolucion="1k", palabras_por_pagina=350,
    paginas_min={"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}, seccion_palabras_min=300,
    puntuacion_min=85,
)


def _plan(filas: list[tuple[str, int, int]], cabecera="| sección | palabras | fichas |") -> str:
    lineas = ["# Plan · principal", "", "Notas libres.", "", cabecera, "|---|---|---|"]
    lineas += [f"| {s} | {p} | {f} |" for s, p, f in filas]
    return "\n".join(lineas) + "\n"


def test_350_palabras_por_pagina():
    assert paginas_estimadas(7000, 2, 1, 350) == 23
    assert paginas_estimadas(7001, 0, 0, 350) == 21
    assert paginas_estimadas(0, 0, 0, 350) == 0


def test_plan_corto_pide_enriquecer():
    texto = _plan([("01 Por qué no duermes", 2000, 0), ("02 La respiración lenta", 1950, 0),
                   ("03 El plan de 21 días", 2000, 0)])
    cuenta = comprobar_plan(texto, 20, CFG)
    assert cuenta == Cuenta(palabras=5950, fichas=0, paginas_imagen=0, paginas_estimadas=17, objetivo=20,
                            faltan_palabras=1050)
    assert cuenta.mensaje == ("faltan ≈ 1.050 palabras (3 páginas): enriquece con ejemplos, ejercicios o "
                              "plantillas; nunca rellenes")
    assert "nunca rellenes" in cuenta.mensaje


def test_plan_que_llega():
    texto = _plan([("01", 3000, 2), ("02", 3000, 1)])
    cuenta = comprobar_plan(texto, 20, CFG)
    assert (cuenta.palabras, cuenta.fichas, cuenta.paginas_estimadas, cuenta.faltan_palabras) == (6000, 3, 21, 0)
    assert "nunca rellenes" not in cuenta.mensaje
    assert "21" in cuenta.mensaje and "20" in cuenta.mensaje


def test_plan_fichas_cuentan_como_pagina():
    texto = _plan([("01", 5950, 3)])
    cuenta = comprobar_plan(texto, 20, CFG)
    assert cuenta.paginas_estimadas == 20 and cuenta.faltan_palabras == 0


def test_plan_con_columna_de_imagenes():
    texto = ("| Sección | Palabras | Fichas | Imágenes |\n|---|---|---|---|\n"
             "| 01 | 5600 | 1 | 2 |\n")
    cuenta = comprobar_plan(texto, 20, CFG)
    assert (cuenta.paginas_imagen, cuenta.paginas_estimadas) == (2, 19)
    assert cuenta.faltan_palabras == 350


def test_plan_acepta_miles_con_punto():
    texto = _plan([("01", 0, 0)]).replace("| 01 | 0 | 0 |", "| 01 | 1.200 | 0 |")
    assert comprobar_plan(texto, 4, CFG).palabras == 1200


def test_plan_sin_tabla_falla():
    with pytest.raises(ValueError, match="sección | palabras | fichas"):
        comprobar_plan("# Plan\n\nSin tabla.\n", 20, CFG)


def test_plan_con_celda_ilegible_falla():
    texto = _plan([("01", 0, 0)]).replace("| 01 | 0 | 0 |", "| 01 | muchas | 0 |")
    with pytest.raises(ValueError, match="muchas"):
        comprobar_plan(texto, 20, CFG)


def test_contar_palabras_cirilico():
    assert contar_palabras("<p>Дишай бавно и спокойно</p>") == 4


def test_contar_palabras_sin_indice_fuentes_ni_pies():
    html = """<html><head><title>Título fuera</title><style>.a{color:red}</style></head><body>
    <nav class="indice"><a href="#s-01">uno dos tres</a></nav>
    <section class="seccion flujo" id="s-01"><h2>Hola mundo</h2>
    <p>Una <strong>frase</strong> corta.</p>
    <figure><img src="medios/a.png" alt="nada"><figcaption>pie de figura largo</figcaption></figure>
    <ul><li>uno</li><li>dos</li></ul></section>
    <section class="fuentes" id="fuentes"><ol><li id="fuente-1">Fuente con muchas palabras</li></ol></section>
    </body></html>"""
    # Hola mundo (2) + Una frase corta (3) + uno dos (2)
    assert contar_palabras(html) == 7


def test_contar_palabras_no_pega_bloques():
    assert contar_palabras("<p>uno</p><p>dos</p>") == 2
    assert contar_palabras("<p>pa<strong>la</strong>bra</p>") == 1
