import json
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.pdf.gates import (
    PESOS,
    Hallazgo,
    Informe,
    evaluar,
    puntuar,
)
from trovefy.producto.config import ConfigProducto
from trovefy.producto.medios import escribir_medio, registrar_medio

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
# Mínimo de palabras por sección rebajado para que las fixtures sean cortas; el resto, el de la plantilla.
CFG = ConfigProducto(
    tope_usd=Decimal("2.00"), modelos_imagen=("gpt-image-2",), resolucion="1k", palabras_por_pagina=350,
    paginas_min={"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}, seccion_palabras_min=60,
    puntuacion_min=85,
)
# bueno.html: ~446 palabras (2 páginas) + 1 ficha + 1 portada = 4 páginas estimadas.
OBJETIVO = 4
PNG = b"\x89PNG\r\n\x1a\n" + b"portada-propia-de-prueba"


@pytest.fixture
def raiz(tmp_path):
    """Raíz de la pieza con ``medios/portada.png`` propia y registrada en ``medios.json``."""
    r = tmp_path / "entregable"
    sha = escribir_medio(r / "medios" / "portada.png", PNG)
    registrar_medio(r, "portada", "portada.png", sha, "apimart", task_id="t-0001")
    return r


def _html(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def _evaluar(html: str, raiz: Path, *, idioma="es", exigencia="sanitario", objetivo=OBJETIVO, vault=None,
             cfg=CFG) -> Informe:
    return evaluar(html, raiz=raiz, idioma=idioma, exigencia=exigencia, tipo_pieza="principal",
                   paginas_objetivo=objetivo, cfg=cfg, vault=vault)


def _gates(informe: Informe) -> set[str]:
    return {h.gate for h in informe.hallazgos}


def test_bueno_pasa(raiz):
    informe = _evaluar(_html("bueno.html"), raiz)
    assert informe.hallazgos == ()
    assert informe.puntuacion == 100
    assert informe.pasa is True
    assert informe.paginas_estimadas == OBJETIVO
    assert 351 <= informe.palabras <= 700


@pytest.mark.parametrize(("archivo", "gate", "severidad"), [
    ("malo-qg01.html", "QG-01", "critica"),
    ("malo-qg02.html", "QG-02", "critica"),
    ("malo-qg03.html", "QG-03", "critica"),
    ("malo-qg04.html", "QG-04", "critica"),
    ("malo-qg05.html", "QG-05", "critica"),
    ("malo-qg06.html", "QG-06", "alta"),
    ("malo-qg07.html", "QG-07", "alta"),
    ("malo-qg08.html", "QG-08", "media"),
    ("malo-qg09.html", "QG-09", "alta"),
    ("malo-qg12.html", "QG-12", "alta"),
    ("malo-qg13.html", "QG-13", "media"),
    ("malo-qg14.html", "QG-14", "alta"),
])
def test_cada_malo_falla_solo_su_gate(raiz, archivo, gate, severidad):
    informe = _evaluar(_html(archivo), raiz)
    assert _gates(informe) == {gate}
    assert {h.severidad for h in informe.hallazgos} == {severidad}
    if severidad == "critica":
        assert informe.pasa is False


def test_qg01_marcador_todo(raiz):
    informe = _evaluar(_html("malo-qg01.html"), raiz)
    [h] = informe.hallazgos
    assert (h.gate, h.severidad) == ("QG-01", "critica")
    assert "TODO" in h.texto
    assert informe.pasa is False


@pytest.mark.parametrize("marcador", ["lorem ipsum", "TBD", "XXX", "{{nombre}}", "[insertar dato]",
                                      "[вмъкни текст]", "[insert here]", "PLACEHOLDER"])
def test_qg01_otros_marcadores(raiz, marcador):
    html = _html("bueno.html").replace("Recuerda: poco cada día", f"Recuerda: {marcador} poco cada día")
    assert "QG-01" in _gates(_evaluar(html, raiz))


def test_qg01_no_mira_el_css_anidado(raiz):
    # «}}» del @page anidado de bueno.html no es un marcador.
    assert "}}" in _html("bueno.html")
    assert "QG-01" not in _gates(_evaluar(_html("bueno.html"), raiz))


def test_qg02_enlace_indice_roto(raiz):
    informe = _evaluar(_html("malo-qg02.html"), raiz)
    textos = " ".join(h.texto for h in informe.hallazgos)
    assert "#s-30" in textos
    assert "Tu plan de 21 días" in textos
    assert informe.pasa is False


def test_qg03_imagen_remota(raiz):
    informe = _evaluar(_html("malo-qg03.html"), raiz)
    [h] = informe.hallazgos
    assert (h.gate, h.severidad) == ("QG-03", "critica")
    assert "https://imagenes.example.test" in h.texto


@pytest.mark.parametrize("trozo", [
    '<link rel="stylesheet" href="https://cdn.example.test/a.css">',
    '<link rel="stylesheet" href="//cdn.example.test/a.css">',
    "<style>@import url('https://fonts.example.test/x.css');</style>",
    "<style>.x{background:url(//cdn.example.test/f.png)}</style>",
])
def test_qg03_otros_recursos_remotos(raiz, trozo):
    html = _html("bueno.html").replace("</head>", f"{trozo}\n</head>")
    assert "QG-03" in _gates(_evaluar(html, raiz))


def test_qg04_imagen_fuera_de_manifiesto(raiz):
    informe = _evaluar(_html("malo-qg04.html"), raiz)
    [h] = informe.hallazgos
    assert (h.gate, h.severidad) == ("QG-04", "critica")
    assert "foto-ajena.png" in h.texto
    assert informe.pasa is False


def test_qg04_sha_que_no_cuadra(raiz):
    (raiz / "medios" / "portada.png").write_bytes(PNG + b"cambiada")
    assert _gates(_evaluar(_html("bueno.html"), raiz)) == {"QG-04"}


def test_qg04_origen_ajeno(raiz):
    manifiesto = raiz / "medios" / "medios.json"
    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    datos["portada"]["origen"] = "pinterest"
    manifiesto.write_text(json.dumps(datos), encoding="utf-8")
    informe = _evaluar(_html("bueno.html"), raiz)
    assert _gates(informe) == {"QG-04"}
    assert "pinterest" in informe.hallazgos[0].texto


def test_qg04_medio_fuera_de_0640(raiz):
    (raiz / "medios" / "portada.png").chmod(0o644)
    informe = _evaluar(_html("bueno.html"), raiz)
    assert _gates(informe) == {"QG-04"}
    assert "640" in informe.hallazgos[0].texto


def test_qg04_sin_manifiesto(tmp_path):
    assert _gates(_evaluar(_html("bueno.html"), tmp_path)) == {"QG-04"}


def test_qg05_corto_pide_enriquecer(raiz):
    informe = _evaluar(_html("malo-qg05.html"), raiz)
    [h] = informe.hallazgos
    assert (h.gate, h.severidad) == ("QG-05", "critica")
    assert "faltan ≈" in h.texto and "nunca rellenes" in h.texto and "enriquece" in h.texto
    assert informe.paginas_estimadas == OBJETIVO - 1
    assert informe.pasa is False


def test_qg05_objetivo_alto(raiz):
    informe = _evaluar(_html("bueno.html"), raiz, objetivo=20)
    assert _gates(informe) == {"QG-05"}
    assert "faltan ≈ 5.854 palabras (16 páginas)" in informe.hallazgos[0].texto


def test_qg06_seccion_corta(raiz):
    informe = _evaluar(_html("malo-qg06.html"), raiz)
    [h] = informe.hallazgos
    assert "s-03" in h.donde and "mínimo 60" in h.texto
    assert informe.puntuacion == 90 and informe.pasa is True


def test_qg07_sin_recordar(raiz):
    [h] = _evaluar(_html("malo-qg07.html"), raiz).hallazgos
    assert "s-02" in h.donde and "recordar" in h.texto


def test_qg07_pocos_h3(raiz):
    html = _html("bueno.html").replace("<h3>Semana dos</h3>", "<h4>Semana dos</h4>")
    informe = _evaluar(html, raiz)
    assert _gates(informe) == {"QG-07"}
    assert "tiene 2" in informe.hallazgos[0].texto


def test_qg07_sin_lograr_al_principio(raiz):
    html = _html("bueno.html").replace('<div class="lograr"><p>Al terminar este capítulo tendrás',
                                       '<div class="intro"><p>Al terminar este capítulo tendrás')
    informe = _evaluar(html, raiz)
    assert _gates(informe) == {"QG-07"}
    assert "lograr" in informe.hallazgos[0].texto


def test_qg08_dos_secciones_sin_practica(raiz):
    [h] = _evaluar(_html("malo-qg08.html"), raiz).hallazgos
    assert "s-02, s-03" in h.texto


def test_qg09_cifra_sin_fuente(raiz):
    [h] = _evaluar(_html("malo-qg09.html"), raiz).hallazgos
    assert "40 %" in h.texto


def test_qg09_fuente_que_no_existe(raiz):
    html = _html("bueno.html").replace('href="#fuente-1">[1]', 'href="#fuente-9">[9]')
    # Además del enlace roto (QG-02), la cifra se queda sin fuente válida.
    assert {"QG-02", "QG-09"} <= _gates(_evaluar(html, raiz))


@pytest.mark.parametrize("frase", ["3 out of 4 people", "3 от всеки 4 души", "un 12,5% menos"])
def test_qg09_otras_cifras(raiz, frase):
    html = _html("bueno.html").replace("<h3>Semana tres</h3>\n", f"<h3>Semana tres</h3>\n<p>{frase}.</p>\n")
    assert "QG-09" in _gates(_evaluar(html, raiz))


def test_qg12_parrafo_repetido(raiz):
    [h] = _evaluar(_html("malo-qg12.html"), raiz).hallazgos
    assert "mantén el aire" in h.texto


def test_qg13_mal_anidado(raiz):
    informe = _evaluar(_html("malo-qg13.html"), raiz)
    assert informe.hallazgos and all(h.gate == "QG-13" for h in informe.hallazgos)
    assert any("mal anidadas" in h.texto for h in informe.hallazgos)


def test_qg13_sin_cerrar(raiz):
    html = _html("bueno.html").replace("</body>\n</html>\n", "")
    textos = [h.texto for h in _evaluar(html, raiz).hallazgos if h.gate == "QG-13"]
    assert "<body> sin cerrar" in textos and "<html> sin cerrar" in textos


def test_qg14_overflow_hidden_prohibido(raiz):
    informe = _evaluar(_html("malo-qg14.html"), raiz)
    [h] = informe.hallazgos
    assert (h.gate, h.severidad) == ("QG-14", "alta")
    assert "overflow:hidden" in h.texto


def test_qg14_overflow_hidden_en_variante_y_en_style(raiz):
    html = _html("bueno.html").replace(".push{margin-top:auto}", ".push{margin-top:auto}\n.page.ficha{overflow: clip}")
    assert _gates(_evaluar(html, raiz)) == {"QG-14"}
    html = _html("bueno.html").replace('<div class="page ficha">', '<div class="page ficha" style="overflow:hidden">')
    assert _gates(_evaluar(html, raiz)) == {"QG-14"}


@pytest.mark.parametrize(("viejo", "nuevo", "falta"), [
    ("@page{size:A4;margin:0}", "@page{size:A4;margin:10mm}", "@page"),
    ("height:296.8mm;", "height:297mm;", "296.8mm"),
])
def test_qg14_falta_maqueta(raiz, viejo, nuevo, falta):
    informe = _evaluar(_html("bueno.html").replace(viejo, nuevo), raiz)
    assert _gates(informe) == {"QG-14"}
    assert falta in informe.hallazgos[0].texto


# --- puntuación -------------------------------------------------------------------------------------


def test_pesos():
    assert PESOS == {"critica": 25, "alta": 10, "media": 5, "baja": 2}


def test_puntuacion_por_severidad():
    hallazgos = [Hallazgo("QG-06", "alta", "s-01", "corta"), Hallazgo("QG-08", "media", "s-02", "sin práctica"),
                 Hallazgo("QG-13", "media", "línea 3", "mal anidada")]
    assert puntuar(hallazgos, 85) == (80, False)
    assert puntuar(hallazgos, 80) == (80, True)


def test_puntuacion_por_severidad_en_evaluar(raiz):
    # 1 alta (QG-06) + 2 medias (QG-13: mal anidada y cierre sin abrir) → 80 < 85.
    html = _html("malo-qg06.html").replace(
        "<p>Recuerda: la salida del aire más larga que la entrada.</p>",
        "<p>Recuerda: la salida del aire <strong>más larga</p></strong> que la entrada.")
    informe = _evaluar(html, raiz)
    assert sorted(h.severidad for h in informe.hallazgos) == ["alta", "media", "media"]
    assert informe.puntuacion == 80
    assert informe.pasa is False


def test_puntuacion_no_baja_de_cero():
    assert puntuar([Hallazgo("QG-01", "critica", "x", "y")] * 5, 85) == (0, False)


def test_una_critica_no_pasa_aunque_puntue():
    assert puntuar([Hallazgo("QG-05", "critica", "x", "y")], 70) == (75, False)


def test_valores_no_admitidos(raiz):
    with pytest.raises(ValueError):
        _evaluar(_html("bueno.html"), raiz, exigencia="alta")
    with pytest.raises(ValueError):
        evaluar("", raiz=raiz, idioma="es", exigencia="normal", tipo_pieza="folleto", paginas_objetivo=1, cfg=CFG)


# --- ronda de revisión de las tareas 6–7 ------------------------------------------------------------

ANCLA = '<div class="ejercicio"><p>Esta noche'
AVISO = ("<p>Este libro es una guía de hábitos. No es un tratamiento: si duermes mal desde hace semanas, "
         "habla con tu médico.</p>")


def _con(trozo: str, ancla: str = ANCLA) -> str:
    html = _html("bueno.html")
    assert ancla in html
    return html.replace(ancla, trozo + ancla, 1)


# H2: normalización del texto.


def test_h2_cifra_partida_por_salto_de_linea(raiz):
    assert "QG-09" in _gates(_evaluar(_con("<p>Casi 1 de\ncada 3 adultos.</p>"), raiz))
    assert "QG-09" in _gates(_evaluar(_con("<p>El 40&nbsp;% de la gente.</p>"), raiz))


# H3: QG-03 caza cualquier recurso remoto.


@pytest.mark.parametrize("cambio", [
    ("ancla", '<p style="background:url(https://x.test/a.png)">texto</p>'),
    ("ancla", "<p style=\"background:url('//x.test/a.png')\">texto</p>"),
    ("img", '<img src="medios/portada.png" srcset="medios/portada.png 1x, https://x.test/b.png 2x"'),
    ("head", '<base href="https://x.test/">'),
    ("head", '<base href="medios/">'),
    ("ancla", '<svg><image href="https://x.test/a.png"/></svg>'),
    ("ancla", '<svg><image xlink:href="//x.test/a.png"/></svg>'),
    ("ancla", '<object data="https://x.test/a.pdf"></object>'),
    ("ancla", '<video poster="https://x.test/p.png"></video>'),
    ("ancla", '<iframe src="about:blank" data-x="1"></iframe><embed src="https://x.test/e.swf">'),
    ("head", '<link rel="stylesheet" href="extra.css">'),
    ("head", "<style>.x{background:image-set('https://x.test/a.png' 1x)}</style>"),
])
def test_h3_qg03_todo_recurso_remoto(raiz, cambio):
    donde, trozo = cambio
    html = _html("bueno.html")
    if donde == "ancla":
        html = _con(trozo)
    elif donde == "img":
        html = html.replace('<img src="medios/portada.png"', trozo)
    else:
        html = html.replace("</head>", f"{trozo}\n</head>")
    informe = _evaluar(html, raiz)
    assert "QG-03" in _gates(informe)
    assert informe.pasa is False


def test_h3_enlace_a_fuente_y_xmlns_no_son_recursos(raiz):
    html = _html("bueno.html").replace(
        "(dato de prueba).</li>", '(dato de prueba). <a href="https://datos.example.test/encuesta">enlace</a></li>')
    html = html.replace(ANCLA, '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>' + ANCLA, 1)
    assert _evaluar(html, raiz).hallazgos == ()


# H4: QG-14 caza cualquier recorte.


@pytest.mark.parametrize(("viejo", "nuevo"), [
    (".push{", ".ficha{overflow:hidden}\n.push{"),
    ("break-after:page}", "break-after:page;overflow:hidden !important}"),
    ("break-after:page}", "break-after:page;overflow:hidden auto}"),
    ("break-after:page}", "break-after:page;overflow: visible clip}"),
    ("break-after:page}", "break-after:page;OVERFLOW-Y:Clip}"),
    ("break-after:page}", "break-after:page;contain:paint}"),
    ("break-after:page}", "break-after:page;contain: content}"),
    ("break-after:page}", "break-after:page;contain:strict}"),
    (".push{", "@media print{.seccion p{overflow:hidden}}\n.push{"),
    ('<div class="lograr"><p>Al terminar este capítulo sabrás qué',
     '<div class="lograr" style="overflow-x: hidden"><p>Al terminar este capítulo sabrás qué'),
])
def test_h4_qg14_cualquier_recorte(raiz, viejo, nuevo):
    html = _html("bueno.html")
    assert viejo in html
    informe = _evaluar(html.replace(viejo, nuevo, 1), raiz)
    assert _gates(informe) == {"QG-14"}


@pytest.mark.parametrize(("viejo", "nuevo"), [
    ("@page{size:A4;margin:0}", "@page{size:A4 portrait;margin:0}"),
    ("@page{size:A4;margin:0}", "@page{size:a4;margin:0 0 0 0}"),
    ("@page{size:A4;margin:0}", "@page{size:A4;margin:0mm 0}"),
    ("height:296.8mm;", "height:296.8mm !important;"),
    ("break-after:page}", "break-after:page;overflow:visible;contain:layout}"),
])
def test_h4_qg14_sin_falsos_positivos(raiz, viejo, nuevo):
    html = _html("bueno.html")
    assert viejo in html
    assert _evaluar(html.replace(viejo, nuevo, 1), raiz).hallazgos == ()


def test_h4_qg14_a4_apaisado_no_vale(raiz):
    html = _html("bueno.html").replace("@page{size:A4;margin:0}", "@page{size:A4 landscape;margin:0}")
    assert _gates(_evaluar(html, raiz)) == {"QG-14"}


# M1: una página de imagen solo cuenta si tiene imagen; una .page vacía es un hallazgo.


def test_m1_paginas_vacias_no_rellenan(raiz):
    html = _html("bueno.html").replace('<section class="fuentes"',
                                       '<div class="page"></div>' * 6 + '<section class="fuentes"')
    informe = _evaluar(html, raiz, objetivo=10)
    assert informe.paginas_estimadas == OBJETIVO
    assert {"QG-05", "QG-12"} <= _gates(informe)
    assert informe.pasa is False


def test_m1_pagina_vacia_es_hallazgo(raiz):
    html = _html("bueno.html").replace('<section class="fuentes"', '<div class="page"> </div><section class="fuentes"')
    informe = _evaluar(html, raiz)
    assert _gates(informe) == {"QG-12"}
    [h] = informe.hallazgos
    assert h.severidad == "alta" and "vacía" in h.texto


def test_m1_pagina_sin_imagen_no_es_de_imagen(raiz):
    # La portada sin <img> (con su título) ya no cuenta como página de imagen.
    html = _html("bueno.html").replace('<img src="medios/portada.png" alt="Portada de Respira Lento">', "")
    informe = _evaluar(html, raiz)
    assert informe.paginas_estimadas == OBJETIVO - 1
    assert _gates(informe) == {"QG-05"}


# M2: fuentes e índice no esconden texto.


def test_m2_cita_de_fuente_no_se_revisa(raiz):
    html = _html("bueno.html").replace(
        "Encuesta ficticia de hábitos de sueño, 2025 (dato de prueba).",
        "Estudio ficticio: la respiración lenta cura el insomnio leve en el 40 % de los casos, 2025.")
    assert _evaluar(html, raiz).hallazgos == ()


def test_m2_cifra_en_fuentes_fuera_de_las_citas(raiz):
    html = _html("bueno.html").replace("<h2>Fuentes</h2>", "<h2>Fuentes</h2><p>El 40 % no duerme.</p>")
    assert "QG-09" in _gates(_evaluar(html, raiz))


# M3: falsos positivos.


@pytest.mark.parametrize("texto", ["TODO EMPIEZA AQUÍ", "Lo TODO en mayúsculas", "Todo cambia"])
def test_m3_todo_en_espanol_no_es_marcador(raiz, texto):
    html = _html("bueno.html").replace("<h2>Tu plan de 21 días</h2>", f"<h2>{texto}</h2>")
    assert "QG-01" not in _gates(_evaluar(html, raiz))


@pytest.mark.parametrize("marcador", ["TODO: revisar", "TODO : revisar", "[ TODO ]", "[TODO revisar]",
                                      "<!-- TODO revisar -->"])
def test_m3_todo_como_marcador(raiz, marcador):
    html = _html("bueno.html").replace("Recuerda: poco cada día", f"Recuerda: {marcador} poco cada día")
    assert "QG-01" in _gates(_evaluar(html, raiz))


def test_m3_bueno_bg_pasa(raiz):
    informe = _evaluar(_html("bueno-bg.html"), raiz, idioma="bg")
    assert informe.hallazgos == ()
    assert informe.pasa is True
    assert informe.paginas_estimadas == OBJETIVO


# M4: QG-04 revisa toda referencia local a imagen.


@pytest.mark.parametrize(("donde", "trozo"), [
    ("css", ".portada{background:url(medios/ajena.png)}"),
    ("css", ".portada{background:url('medios/ajena.png')}"),
    ("ancla", '<p style="background:url(medios/ajena.png)">texto</p>'),
    ("img", '<img src="medios/portada.png" srcset="medios/portada.png 1x, medios/ajena.png 2x"'),
    ("ancla", '<svg><image href="medios/ajena.png"/></svg>'),
    ("ancla", '<svg><image xlink:href="otra/ajena.png"/></svg>'),
    ("ancla", '<video poster="medios/ajena.png"></video>'),
    ("ancla", '<p><img src="data:image/png;base64,iVBORw0KGgo=" alt="x"></p>'),
])
def test_m4_qg04_toda_referencia_local(raiz, donde, trozo):
    html = _html("bueno.html")
    if donde == "css":
        html = html.replace(".push{", trozo + "\n.push{")
    elif donde == "img":
        html = html.replace('<img src="medios/portada.png"', trozo)
    else:
        html = _con(trozo)
    informe = _evaluar(html, raiz)
    assert _gates(informe) == {"QG-04"}
    assert informe.pasa is False


def test_m4_referencias_propias_pasan(raiz):
    html = _html("bueno.html").replace(".push{", ".portada{background:url(medios/portada.png)}\n.push{")
    html = html.replace('<img src="medios/portada.png"',
                        '<img src="medios/portada.png" srcset="medios/portada.png 1x, medios/portada.png 2x"')
    html = html.replace(ANCLA, '<svg><defs><linearGradient id="g"/></defs><use href="#g"/></svg>'
                        '<p style="fill:url(#g)">x</p>' + ANCLA, 1)
    assert _evaluar(html, raiz).hallazgos == ()


def test_m4_fuentes_de_font_face_no_son_imagenes(raiz):
    html = _html("bueno.html").replace(
        ".push{", "@font-face{font-family:'X';src:url(fuentes/x.ttf) format('truetype')}\n.push{")
    assert _evaluar(html, raiz).hallazgos == ()


# Bajos.


@pytest.mark.parametrize("frase", ["El 40 por ciento de la gente", "70 процента от хората", "40 percent of people",
                                   "40 per cent of people"])
def test_bajo_qg09_porcentaje_en_palabras(raiz, frase):
    assert "QG-09" in _gates(_evaluar(_con(f"<p>{frase}.</p>"), raiz))


@pytest.mark.parametrize("trozo", ["<ul><li>El 40% de la gente<ul><li>sub</li></ul></li></ul>",
                                   "<table><tr><td>El 40% de la gente</td></tr></table>",
                                   "<h3>El 40% de la gente</h3>"])
def test_bajo_qg09_cifra_en_otros_bloques(raiz, trozo):
    assert "QG-09" in _gates(_evaluar(_con(trozo), raiz))


