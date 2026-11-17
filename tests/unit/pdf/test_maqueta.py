import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.pdf.gates import evaluar
from trovefy.pdf.maqueta import (
    BASE_CSS,
    BrandbookSinTokens,
    FragmentoInvalido,
    ensamblar,
    familias_brandbook,
    generar_ficha_imprimible,
    sanear_fragmento,
    tokens_brandbook,
)
from trovefy.producto.config import ConfigProducto
from trovefy.producto.ficha import Ficha, PiezaFicha
from trovefy.producto.medios import escribir_medio, leer_manifiesto, registrar_medio
from trovefy.producto.rutas import pieza
from trovefy.vault import frontmatter

P = "p-0042-respira"
TESTS = Path(__file__).resolve().parents[2]
RESPIRA = TESTS / "fixtures" / "pdf" / "respira"
BRANDBOOK = TESTS / "fixtures" / "producto" / P / "BRANDBOOK.md"
GOLDEN = TESTS / "golden" / "pdf" / "respira-principal.html"
PNG = b"\x89PNG\r\n\x1a\n" + b"portada-propia-de-prueba"
CFG = ConfigProducto(
    tope_usd=Decimal("2.00"), modelos_imagen=("gpt-image-2",), resolucion="1k", palabras_por_pagina=350,
    paginas_min={"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}, seccion_palabras_min=60,
    puntuacion_min=85,
)
PRINCIPAL = PiezaFicha("principal", "Respira y duerme", "ebook", 4)
FICHA = Ficha(p_id=P, pais="ZZ", idioma="es", slug="respira-lento", unidad_venta="plan de 21 días",
              promesa="Duerme mejor en 21 días", avatar="Adulto que duerme mal", exigencia="sanitario",
              tipo="ebook", piezas=(PRINCIPAL,))
DIARIO = {"id": "diario", "titulo": "Diario de sueño", "instrucciones": "Anota cada mañana.", "tipo": "tabla",
          "columnas": ["Día", "Hora"], "filas": 3}


@pytest.fixture
def pieza_respira(tmp_path):
    """Pieza principal de p-0042-respira con 3 secciones, 1 ficha, aviso, fuentes y portada propia."""
    p = pieza(tmp_path / "v", P, "principal")
    shutil.copytree(RESPIRA / "fuente", p.raiz / "fuente")
    sha = escribir_medio(p.raiz / "medios" / "portada.png", PNG)
    registrar_medio(p.raiz, "portada", "portada.png", sha, "apimart", task_id="t-0001")
    return p


def _ensamblar(p, **cambios):
    texto = BRANDBOOK.read_text(encoding="utf-8")
    meta, _ = frontmatter.leer(BRANDBOOK)
    args = {
        "tokens": tokens_brandbook(texto), "familias": familias_brandbook(meta),
        "secciones": sorted((p.raiz / "fuente" / "secciones").glob("*.html")),
        "fichas": [p.raiz / "fuente" / "fichas" / "diario.yaml"], "manifiesto": leer_manifiesto(p.raiz),
    }
    args.update(cambios)
    return ensamblar(p, FICHA, PRINCIPAL, **args)


# --- fragmentos -------------------------------------------------------------------------------------


def test_fragmento_con_script_rechazado():
    with pytest.raises(FragmentoInvalido, match="script"):
        sanear_fragmento("<h2>Hola</h2><script>alert(1)</script>")


def test_fragmento_con_src_remoto_rechazado():
    with pytest.raises(FragmentoInvalido, match="src"):
        sanear_fragmento('<h2>Hola</h2><img src="https://x.example/a.png" alt="a">')


@pytest.mark.parametrize("html", [
    "<style>p{color:red}</style>",
    '<link rel="stylesheet" href="x.css">',
    '<iframe src="medios/a.png"></iframe>',
    '<p onclick="x()">a</p>',
    '<p style="color:red">a</p>',
    '<a href="https://x.example">a</a>',
    '<a href="javascript:alert(1)">a</a>',
    '<img src="medios/../secreto.png" alt="">',
    '<img src="medios/sub/a.png" alt="">',
    '<img src="/etc/passwd" alt="">',
    '<img src="file:///etc/passwd" alt="">',
    "<section><p>a</p></section>",
    "<nav class='indice'></nav>",
    "<h1>Otro título</h1>",
    '<p data-x="1">a</p>',
    "<!-- comentario --><p>a</p>",
    "<svg><circle/></svg>",
])
def test_fragmento_fuera_de_lista_blanca(html):
    with pytest.raises(FragmentoInvalido):
        sanear_fragmento(html)


def test_fragmento_bueno_pasa_igual():
    html = ('<h2 id="x">Hola</h2>\n<div class="lograr"><p>Uno <strong>dos</strong> <em>tres</em><br>'
            '<a class="fuente" href="#fuente-1">[1]</a><sup>2</sup></p></div>\n'
            '<figure><img src="medios/il-01.png" alt="Dibujo"><figcaption>Pie</figcaption></figure>\n'
            "<table><thead><tr><th>a</th></tr></thead><tbody><tr><td>b</td></tr></tbody></table>\n"
            "<ul><li>a</li></ul><ol><li>b</li></ol><blockquote>c</blockquote><aside><span>d</span></aside>"
            "<h3>e</h3><h4>f</h4>\n")
    assert sanear_fragmento(html) == html.strip()


# --- brandbook --------------------------------------------------------------------------------------


def test_tokens_del_frontmatter():
    tokens = tokens_brandbook(BRANDBOOK.read_text(encoding="utf-8"))
    assert tokens["--color-primario"] == "#1F4E5F"
    assert tokens["--fuente-texto"] == "'DejaVu Sans', sans-serif"


def test_tokens_sin_url():
    texto = "---\ntokens_css:\n  --color-primario: '#000000'\n  --fondo: url(http://x)\n---\n# B\n"
    with pytest.raises(BrandbookSinTokens, match="--fondo"):
        tokens_brandbook(texto)


@pytest.mark.parametrize("valor", ["'#000;} body{x:y'", "'@import x'", "'#000 {'", "'a}'"])
def test_tokens_peligrosos(valor):
    with pytest.raises(BrandbookSinTokens):
        tokens_brandbook(f"---\ntokens_css:\n  --color-primario: {valor}\n---\n")


def test_tokens_clave_rara():
    with pytest.raises(BrandbookSinTokens):
        tokens_brandbook("---\ntokens_css:\n  --Color: '#000000'\n---\n")


def test_sin_tokens():
    with pytest.raises(BrandbookSinTokens):
        tokens_brandbook("---\nnombre_local: X\n---\n```css\n:root{--color-primario:#000}\n```\n")


def test_familias_por_uso():
    meta, _ = frontmatter.leer(BRANDBOOK)
    assert familias_brandbook(meta) == ("DejaVu Serif", "DejaVu Sans")
    meta["tipografias"].reverse()
    assert familias_brandbook(meta) == ("DejaVu Serif", "DejaVu Sans")


@pytest.mark.parametrize("tipografias", [
    None,
    [{"familia": "DejaVu Sans", "uso": "texto"}],
    [{"familia": "A", "uso": "titulos"}, {"familia": "B", "uso": "titulos"}, {"familia": "C", "uso": "texto"}],
    [{"familia": 'Evil"); } body{', "uso": "titulos"}, {"familia": "B", "uso": "texto"}],
])
def test_familias_invalidas(tipografias):
    with pytest.raises(ValueError, match="tipografias"):
        familias_brandbook({"tipografias": tipografias})


# --- fichas imprimibles -----------------------------------------------------------------------------


def test_ficha_lleva_anclas():
    html = generar_ficha_imprimible(DIARIO)
    assert html.startswith('<div class="page ficha">\n<span id="ini-diario"></span>')
    assert html.endswith('<span class="push" id="fin-diario"></span>\n</div>')
    assert 'id="ini-diario"' in html and 'id="fin-diario"' in html
    assert html.count("<tr><td></td><td></td></tr>") == 3


def test_ficha_lineas_y_casillas():
    lineas = generar_ficha_imprimible({**DIARIO, "tipo": "lineas", "filas": 4})
    assert lineas.count('<div class="linea"></div>') == 4
    casillas = generar_ficha_imprimible({**DIARIO, "tipo": "casillas", "filas": ["Agua", "Luz <apagada>"]})
    assert '<li><span class="casilla"></span>Luz &lt;apagada&gt;</li>' in casillas


def test_ficha_escapa_texto():
    html = generar_ficha_imprimible({**DIARIO, "titulo": "<script>x</script>"})
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.parametrize("cambio", [
    {"id": "Diario"}, {"id": "../x"}, {"tipo": "dibujo"}, {"filas": 0}, {"filas": 501}, {"filas": True},
    {"columnas": []}, {"titulo": ""}, {"instrucciones": None},
])
def test_ficha_invalida(cambio):
    with pytest.raises(ValueError):
        generar_ficha_imprimible({**DIARIO, **cambio})


MANIFIESTO_F01 = {"f-01": {"archivo": "f-01.png", "sha256": "0" * 64, "origen": "apimart"}}


def test_ficha_con_imagen_entre_instrucciones_y_tabla():
    html = generar_ficha_imprimible({**DIARIO, "imagen": "f-01"}, MANIFIESTO_F01)
    figura = '<figure class="ficha-img"><img src="medios/f-01.png" alt="Diario de sueño"></figure>'
    assert figura in html
    assert html.index('class="instrucciones"') < html.index(figura) < html.index("<table>")
    lineas = generar_ficha_imprimible({**DIARIO, "tipo": "lineas", "imagen": "f-01"}, MANIFIESTO_F01)
    assert lineas.index(figura) < lineas.index('<div class="lineas">')
    casillas = generar_ficha_imprimible({**DIARIO, "tipo": "casillas", "imagen": "f-01"}, MANIFIESTO_F01)
    assert casillas.index(figura) < casillas.index('<ul class="casillas">')


def test_ficha_con_imagen_escapa_el_alt():
    html = generar_ficha_imprimible({**DIARIO, "titulo": 'Diario "<b>"', "imagen": "f-01"}, MANIFIESTO_F01)
    assert 'alt="Diario &quot;&lt;b&gt;&quot;"' in html


@pytest.mark.parametrize("manifiesto", [None, {}, MANIFIESTO_F01])
def test_ficha_con_imagen_desconocida_falla(manifiesto):
    with pytest.raises(ValueError, match=r"ficha diario: .*f-02"):
        generar_ficha_imprimible({**DIARIO, "imagen": "f-02"}, manifiesto)


@pytest.mark.parametrize("imagen", ["", 3, "../f-01", None])
def test_ficha_con_imagen_mal_escrita_falla(imagen):
    with pytest.raises(ValueError, match="ficha diario"):
        generar_ficha_imprimible({**DIARIO, "imagen": imagen}, MANIFIESTO_F01)


def test_ensamblado_ficha_con_imagen_pasa_gates(pieza_respira):
    sha = escribir_medio(pieza_respira.raiz / "medios" / "f-01.png", PNG)
    registrar_medio(pieza_respira.raiz, "f-01", "f-01.png", sha, "apimart", task_id="t-0002")
    diario = pieza_respira.raiz / "fuente" / "fichas" / "diario.yaml"
    diario.write_text(diario.read_text(encoding="utf-8") + "imagen: f-01\n", encoding="utf-8")
    html = _ensamblar(pieza_respira)
    assert '<figure class="ficha-img"><img src="medios/f-01.png" alt="Diario de sueño"></figure>' in html
    informe = evaluar(html, raiz=pieza_respira.raiz, idioma="es", exigencia="sanitario", tipo_pieza="principal",
                      paginas_objetivo=4, cfg=CFG)
    assert informe.hallazgos == () and informe.pasa


def test_ensamblado_ficha_con_imagen_fuera_del_manifiesto(pieza_respira):
    diario = pieza_respira.raiz / "fuente" / "fichas" / "diario.yaml"
    diario.write_text(diario.read_text(encoding="utf-8") + "imagen: f-07\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"diario.yaml: ficha diario: .*f-07"):
        _ensamblar(pieza_respira)


def test_qg04_ve_la_imagen_de_una_ficha_sin_registrar(pieza_respira):
    html = _ensamblar(pieza_respira).replace(
        '<span class="push" id="fin-diario">',
        '<figure class="ficha-img"><img src="medios/f-09.png" alt="x"></figure><span class="push" id="fin-diario">')
    informe = evaluar(html, raiz=pieza_respira.raiz, idioma="es", exigencia="sanitario", tipo_pieza="principal",
                      paginas_objetivo=4, cfg=CFG)
    assert any(h.gate == "QG-04" and "f-09.png" in h.texto for h in informe.hallazgos)


def test_css_imagen_de_ficha_acotada():
    css = BASE_CSS.read_text(encoding="utf-8")
    regla = re.search(r"\.ficha-img img\{([^}]*)\}", css)
    assert regla, "falta la regla .ficha-img img"
    for decl in ("max-height:115mm", "width:auto", "object-fit:contain", "margin:0 auto"):
        assert decl in regla.group(1)


# --- revisión del primer producto: índice, flujo y fichas que llenan la página ---------------------


def _regla(selector: str) -> str:
    css = BASE_CSS.read_text(encoding="utf-8")
    m = re.search(rf"(?:^|\}}|\n){re.escape(selector)}\{{([^}}]*)\}}", css)
    assert m, f"falta la regla {selector}"
    return m.group(1)


def test_css_enlaces_con_color_de_marca_sin_subrayar():
    regla = _regla("a")
    assert "color:var(--color-primario)" in regla and "text-decoration:none" in regla


def test_css_indice_con_titulo_y_puntos_guia():
    assert "list-style:none" in _regla(".indice ol")
    assert "margin" in _regla(".indice li")
    despues = _regla(".indice a::after")
    assert "leader(" in despues and "target-counter(attr(href url),page)" in despues
    assert "font-size" in _regla(".indice h2")


def test_css_secciones_en_flujo():
    css = BASE_CSS.read_text(encoding="utf-8")
    assert not re.search(r"\.seccion\{[^}]*break-before", css), "las secciones no fuerzan página"
    assert "break-after:avoid" in _regla("h2,h3,h4")
    assert "break-inside:avoid" in _regla("figure,.plantilla,.ejercicio,.recordar,.lograr")
    assert "break-before:page" in _regla(".fuentes")


def test_css_fichas_con_numero_de_pagina():
    css = BASE_CSS.read_text(encoding="utf-8")
    m = re.search(r"@page ficha\{size:A4;margin:0 0 (\d+)mm;@bottom-center\{([^}]*)\}\}", css)
    assert m and "counter(page)" in m.group(2)
    # la página de la ficha + el margen del pie = la página A4: el límite de desborde no cambia
    ficha = _regla(".ficha")
    assert "page:ficha" in ficha and f"height:{296.8 - int(m.group(1)):.1f}mm" in ficha
    assert "padding-bottom:0" in ficha


def test_css_casillas_holgadas_y_notas_que_llenan():
    assert "min-height:12mm" in _regla(".ficha .casillas li")
    assert "flex-grow:1" in _regla(".ficha .notas")
    assert "repeating-linear-gradient" in _regla(".ficha .notas-lineas")


def test_ensamblado_indice_con_titulo(pieza_respira):
    html = _ensamblar(pieza_respira)
    nav = html[html.index('<nav class="indice flujo">'):html.index("</nav>")]
    assert '<h2 class="indice-titulo">Respira y duerme</h2>' in nav


def test_ficha_con_notas():
    html = generar_ficha_imprimible({**DIARIO, "tipo": "casillas", "filas": ["Agua"], "notas": "Notas <mías>"})
    assert ('<div class="notas"><p class="notas-titulo">Notas &lt;mías&gt;</p>'
            '<div class="notas-lineas"></div></div>') in html
    assert html.index("</ul>") < html.index('class="notas"') < html.index('id="fin-diario"')
    assert "notas" not in generar_ficha_imprimible({**DIARIO, "tipo": "casillas", "filas": ["Agua"]})


@pytest.mark.parametrize("notas", ["", "  ", 3, None, ["a"]])
def test_ficha_con_notas_mal_escritas(notas):
    with pytest.raises(ValueError, match="notas"):
        generar_ficha_imprimible({**DIARIO, "notas": notas})


@pytest.mark.parametrize(("filas", "imagen", "clase"), [
    (1, False, "filas-1"), (3, False, "filas-3"), (7, False, "filas-7"), (8, False, "filas-8"),
    (12, False, "filas-12"), (13, False, None), (17, False, None), (7, True, None),
])
def test_tabla_con_pocas_filas_las_hace_mas_altas(filas, imagen, clase):
    spec = {**DIARIO, "filas": filas, **({"imagen": "f-01"} if imagen else {})}
    html = generar_ficha_imprimible(spec, MANIFIESTO_F01)
    assert (f'<table class="{clase}">' if clase else "<table>") in html


def test_css_una_clase_filas_n_por_cada_tabla_que_llena():
    from trovefy.pdf.maqueta import FILAS_LLENAS

    for n in range(1, FILAS_LLENAS + 1):
        assert _regla(f".ficha table.filas-{n} td") == f"height:calc(200mm / {n} - 3.2mm)"
    assert f".ficha table.filas-{FILAS_LLENAS + 1} " not in BASE_CSS.read_text(encoding="utf-8")


# --- ensamblado -------------------------------------------------------------------------------------


def test_ensamblado_golden(pieza_respira):
    assert _ensamblar(pieza_respira) == GOLDEN.read_text(encoding="utf-8")


def test_ensamblado_pasa_gates(pieza_respira):
    informe = evaluar(_ensamblar(pieza_respira), raiz=pieza_respira.raiz, idioma="es", exigencia="sanitario",
                      tipo_pieza="principal", paginas_objetivo=4, cfg=CFG)
    assert informe.hallazgos == ()
    assert informe.pasa


def test_ensamblado_sin_portada_en_manifiesto(pieza_respira):
    html = _ensamblar(pieza_respira, manifiesto={})
    assert "<img" not in html.split("</div>", 1)[0]
    assert 'id="ini-portada"' in html and 'id="fin-portada"' in html


def test_ensamblado_fragmento_malo(pieza_respira):
    malo = pieza_respira.raiz / "fuente" / "secciones" / "04-malo.html"
    malo.write_text("<h2>Malo</h2><script>x()</script>", encoding="utf-8")
    with pytest.raises(FragmentoInvalido, match="04-malo.html"):
        _ensamblar(pieza_respira, secciones=[malo])


def test_ensamblado_seccion_sin_h2(pieza_respira):
    malo = pieza_respira.raiz / "fuente" / "secciones" / "04-malo.html"
    malo.write_text("<p>Sin título</p>", encoding="utf-8")
    with pytest.raises(FragmentoInvalido, match="h2"):
        _ensamblar(pieza_respira, secciones=[malo])


def test_ensamblado_id_repetido(pieza_respira):
    malo = pieza_respira.raiz / "fuente" / "secciones" / "04-malo.html"
    malo.write_text('<h2 id="ini-portada">Choca</h2>', encoding="utf-8")
    with pytest.raises(FragmentoInvalido, match="ini-portada"):
        _ensamblar(pieza_respira, secciones=[malo])


def test_ensamblado_sin_fuentes_ni_aviso(pieza_respira):
    (pieza_respira.raiz / "fuente" / "fuentes.html").unlink()
    (pieza_respira.raiz / "fuente" / "aviso-salud.html").unlink()
    html = _ensamblar(pieza_respira)
    assert 'id="fuentes"' not in html and 'href="#fuentes"' not in html and '<aside' not in html


def test_ensamblado_tokens_inseguros(pieza_respira):
    with pytest.raises(BrandbookSinTokens):
        _ensamblar(pieza_respira, tokens={"--color-primario": "#000;}body{x:y"})


def test_css_sin_overflow_hidden():
    css = BASE_CSS.read_text(encoding="utf-8")
    assert not re.search(r"overflow(?:-x|-y)?\s*:\s*(?:hidden|clip)", css)


def test_css_colores_y_tipos_con_var():
    css = re.sub(r"/\*.*?\*/", "", BASE_CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    for valor in re.findall(r"font-family\s*:\s*([^;}]+)", css):
        assert valor.strip().startswith("var(--")
    for valor in re.findall(r"(?<![-\w])color\s*:\s*([^;}]+)", css):
        assert valor.strip().startswith("var(--")


def test_css_hijos_de_pagina_fija_no_se_encogen():
    """Sin esto, un hijo de ``.page`` (flex) se encoge y su contenido se recorta sin mover ``fin-X``."""
    css = BASE_CSS.read_text(encoding="utf-8")
    assert ".page>*{flex-shrink:0}" in css


# --- revisión: fragmentos truncados (M1) ------------------------------------------------------------


@pytest.mark.parametrize("html", [
    '<h2>x</h2><p>a</p><script src="http://e/x',
    "<h2>x</h2><p>a</p><style",
    "<h2>x</h2><p>a</p><link",
    '<h2>x</h2><img src="medios/a.png" alt="',
    '<h2>x</h2><p class="a>',
    "<h2>x</h2><p>a</p><",
])
def test_fragmento_con_etiqueta_sin_cerrar_rechazado(html):
    with pytest.raises(FragmentoInvalido):
        sanear_fragmento(html)


def test_fragmento_se_reconstruye_desde_los_tokens():
    # el texto se escapa y las etiquetas salen de la lista blanca, nunca se copia la entrada
    assert sanear_fragmento("<h2>a &lt;script&gt; b</h2>") == "<h2>a &lt;script&gt; b</h2>"
    assert sanear_fragmento('<p>a & b</p><img src="medios/a&#46;png" alt=\'x"y\'/>') == (
        '<p>a &amp; b</p><img src="medios/a.png" alt="x&quot;y">')
    assert sanear_fragmento("<P CLASS=nota>Uno&nbsp;dos</P>") == '<p class="nota">Uno\xa0dos</p>'


# --- revisión: familias de los tokens (M2) ----------------------------------------------------------


@pytest.mark.parametrize("cambio", [
    {"--fuente-titulos": "'Lora', serif"},
    {"--fuente-texto": "Arial, 'DejaVu Sans', sans-serif"},
    {"--fuente-mono": "'DejaVu Sans Mono', monospace"},
])
def test_ensamblado_fuente_del_token_distinta_de_tipografias(pieza_respira, cambio):
    tokens = {**tokens_brandbook(BRANDBOOK.read_text(encoding="utf-8")), **cambio}
    with pytest.raises(ValueError, match="--fuente-"):
        _ensamblar(pieza_respira, tokens=tokens)


def test_ensamblado_falta_token_de_fuente(pieza_respira):
    tokens = tokens_brandbook(BRANDBOOK.read_text(encoding="utf-8"))
    del tokens["--fuente-texto"]
    with pytest.raises(ValueError, match="--fuente-texto"):
        _ensamblar(pieza_respira, tokens=tokens)


def test_ensamblado_fuente_del_token_ignora_mayusculas(pieza_respira):
    tokens = {**tokens_brandbook(BRANDBOOK.read_text(encoding="utf-8")),
              "--fuente-titulos": "'dejavu serif', serif", "--fuente-texto": "'DejaVu Sans'"}
    assert "dejavu serif" in _ensamblar(pieza_respira, tokens=tokens)
