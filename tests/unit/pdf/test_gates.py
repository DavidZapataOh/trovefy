import json
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.pdf.gates import (
    PESOS,
    Hallazgo,
    Informe,
    cargar_lexico,
    evaluar,
    promesas,
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
    ("malo-qg10.html", "QG-10", "critica"),
    ("malo-qg11.html", "QG-11", "critica"),
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


def test_qg10_promesa_de_ingresos(raiz):
    [h] = _evaluar(_html("malo-qg10.html"), raiz).hallazgos
    assert "ganar 500" in h.texto


def test_qg11_promesa_de_salud(raiz):
    [h] = _evaluar(_html("malo-qg11.html"), raiz).hallazgos
    assert "sanar" in h.texto


def test_qg11_sanitario_sin_aviso(raiz):
    html = _html("bueno.html").replace('<aside class="aviso-salud">', '<aside class="nota">')
    informe = _evaluar(html, raiz)
    assert _gates(informe) == {"QG-11"}
    assert "aviso-salud" in informe.hallazgos[0].texto
    assert informe.pasa is False
    # Con exigencia normal, el aviso no es obligatorio.
    assert _evaluar(html, raiz, exigencia="normal").pasa is True


def test_aviso_de_salud_no_es_promesa(raiz):
    html = _html("bueno.html").replace("habla con tu médico.", "habla con tu médico: no sustituye al médico.")
    assert _evaluar(html, raiz).pasa is True


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


# --- promesas ---------------------------------------------------------------------------------------


def test_sanar_el_trauma_es_promesa():
    [h] = promesas("Este método va a sanar tu trauma", "es", "normal")
    assert (h.gate, h.severidad) == ("QG-11", "critica")


def test_garantia_de_reembolso_no_es_promesa():
    assert promesas("гаранция за връщане на парите 14 дни", "bg", "sanitario") == []


def test_lexico_bg_detecta_lekuva():
    hallazgos = promesas("Тази техника лекува безсънието", "bg", "sanitario")
    assert [h.gate for h in hallazgos] == ["QG-11"]
    assert [h.gate for h in promesas("Ще го излекуваме", "bg", "normal")] == ["QG-11"]
    assert [h.gate for h in promesas("Създай пасивен доход", "bg", "normal")] == ["QG-10"]


def test_lexico_en():
    assert [h.gate for h in promesas("This program cures insomnia", "en", "normal")] == ["QG-11"]
    assert promesas("30-day money-back guarantee", "en", "normal") == []


def test_cura_dentro_de_otra_palabra_no_cuenta():
    assert promesas("Procura dormir a la misma hora", "es", "normal") == []


def test_sin_lexico_falla_cerrado(raiz):
    [h] = promesas("Texto cualquiera", "xx", "normal")
    assert h.severidad == "critica"
    assert h.texto == "no medido: sin léxico de promesas para xx"
    informe = _evaluar(_html("bueno.html"), raiz, idioma="xx")
    assert informe.pasa is False


def test_lexico_del_vault_se_suma(tmp_path, raiz):
    vault = tmp_path / "v"
    (vault / "config" / "promesas").mkdir(parents=True)
    (vault / "config" / "promesas" / "es.yaml").write_text(
        "salud:\n  - '\\bsin efectos secundarios'\ningresos: []\n", encoding="utf-8")
    lexico = cargar_lexico("es", vault)
    assert len(lexico["salud"]) == len(cargar_lexico("es", None)["salud"]) + 1
    texto = "Respira sin efectos secundarios y deja tu medicación"
    assert len(promesas(texto, "es", "normal", vault)) == 2
    assert len(promesas(texto, "es", "normal")) == 1


def test_lexico_solo_en_el_vault(tmp_path):
    vault = tmp_path / "v"
    (vault / "config" / "promesas").mkdir(parents=True)
    (vault / "config" / "promesas" / "ro.yaml").write_text("salud:\n  - '\\bvindecă'\n", encoding="utf-8")
    assert [h.gate for h in promesas("Metoda vindecă anxietatea", "ro", "normal", vault)] == ["QG-11"]


def test_lexico_del_vault_roto(tmp_path):
    vault = tmp_path / "v"
    (vault / "config" / "promesas").mkdir(parents=True)
    (vault / "config" / "promesas" / "es.yaml").write_text("salud:\n  - '(sin cerrar'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="patrón roto"):
        cargar_lexico("es", vault)


def test_idioma_raro_sin_lexico():
    assert cargar_lexico("../es", None) is None


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
    assert puntuar([Hallazgo("QG-10", "critica", "x", "y")], 70) == (75, False)


def test_valores_no_admitidos(raiz):
    with pytest.raises(ValueError):
        _evaluar(_html("bueno.html"), raiz, exigencia="alta")
    with pytest.raises(ValueError):
        evaluar("", raiz=raiz, idioma="es", exigencia="normal", tipo_pieza="folleto", paginas_objetivo=1, cfg=CFG)
