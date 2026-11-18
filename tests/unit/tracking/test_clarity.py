"""Clarity solo tras el consentimiento (plan 19, cabecera punto 7; Tarea 7): el aviso de cookies propio de la
landing, su comprobación estática y la de la QA (ninguna petición a Clarity sin aceptar)."""

import re

import pytest
from trovefy.landing.constantes import HOSTS_META
from trovefy.landing.qa import clasificar_peticion
from trovefy.tracking.clarity import (
    CONSENTIMIENTO_JS,
    bloque_consentimiento,
    es_peticion_clarity,
    peticiones_sin_consentimiento,
    validar_consentimiento,
)

TEXTOS = {"texto": "Използваме бисквитки за анализ само ако се съгласите.", "aceptar": "Приемам",
          "rechazar": "Отказвам"}


def _bloque(proyecto: str = "abcde12345") -> str:
    return bloque_consentimiento(proyecto, **TEXTOS)


def test_bloque_oculto_hasta_que_el_script_decide():
    html = _bloque()
    assert 'id="tf-consentimiento"' in html and 'data-tf-clarity="abcde12345"' in html and " hidden" in html
    assert 'data-tf-consentimiento="si"' in html and 'data-tf-consentimiento="no"' in html
    assert "clarity.ms" not in html  # el bloque no carga nada: solo el script, tras aceptar


def test_bloque_mismo_peso_para_aceptar_y_rechazar():
    botones = re.findall(r"<button[^>]*>", _bloque())
    assert len(botones) == 2
    assert {re.sub(r'data-tf-consentimiento="(si|no)"', "", b) for b in botones} == {botones[0].replace(
        'data-tf-consentimiento="si"', "")}


def test_bloque_escapa_los_textos():
    html = bloque_consentimiento("abcde12345", texto="<script>x</script>", aceptar="Sí & ya", rechazar="No")
    assert "<script>x" not in html and "&lt;script&gt;" in html and "Sí &amp; ya" in html


@pytest.mark.parametrize("malo", ["", "ABC", "abc de", "a" * 30, "x/../y", '"><script>'])
def test_bloque_rechaza_proyecto_mal_escrito(malo):
    with pytest.raises(ValueError, match="Clarity"):
        bloque_consentimiento(malo, **TEXTOS)


def test_bloque_sin_textos():
    with pytest.raises(ValueError):
        bloque_consentimiento("abcde12345", texto=" ", aceptar="Sí", rechazar="No")


def _pagina(cuerpo: str) -> str:
    return f'<main id="tf-landing">{cuerpo}</main><script src="assets/consentimiento.js" defer></script>'


def test_validar_bien():
    assert validar_consentimiento(_pagina(_bloque())) == []


def test_validar_clarity_fuera_del_script():
    html = _pagina(_bloque() + '<script async src="https://www.clarity.ms/tag/abcde12345"></script>')
    assert any("clarity.ms" in p for p in validar_consentimiento(html))


def test_validar_falta_rechazar_o_el_script():
    sin_no = _bloque().replace('data-tf-consentimiento="no"', 'data-x="no"')
    assert any("rechazar" in p for p in validar_consentimiento(_pagina(sin_no)))
    assert any("consentimiento.js" in p for p in validar_consentimiento(f"<main>{_bloque()}</main>"))
    assert any("una sola vez" in p for p in validar_consentimiento(_pagina(_bloque() + _bloque())))


def test_validar_aviso_visible_de_entrada():
    # Si el aviso no sale oculto, sin JS se quedaría tapando la página sin poder cerrarse: el script lo muestra.
    visible = _bloque().replace(" hidden", "")
    assert any("hidden" in p for p in validar_consentimiento(_pagina(visible)))


def test_sin_aviso_no_hay_nada_que_validar():
    assert validar_consentimiento('<main id="tf-landing">hola</main>') == []


def test_plantilla_js_solo_carga_clarity_al_aceptar():
    js = CONSENTIMIENTO_JS.read_text(encoding="utf-8")
    assert js.count("clarity.ms") == 1
    cargar = js[js.index("function cargar"):js.index("function borrarCookies")]
    assert "clarity.ms" in cargar
    # `cargar()` solo se llama tras «si» (al elegir o porque ya lo había elegido antes).
    llamadas = [m.start() for m in re.finditer(r"(?<!function )cargar\(\)", js)]
    assert len(llamadas) == 2
    for pos in llamadas:
        assert '"si"' in js[max(0, pos - 40):pos]
    for prohibido in ("fetch(", "XMLHttpRequest", "sendBeacon", "setTimeout", "setInterval", "eval("):
        assert prohibido not in js


def test_es_peticion_clarity():
    assert es_peticion_clarity("https://www.clarity.ms/tag/abcde12345")
    assert es_peticion_clarity("https://k.clarity.ms/collect")
    assert not es_peticion_clarity("https://clarity.ms.example/x")
    assert not es_peticion_clarity("https://prueba.impultienda.example/")


def test_qa_sin_aceptar_ninguna_peticion_a_clarity():
    antes = ["https://prueba.impultienda.example/", "https://www.clarity.ms/tag/abcde12345"]
    assert peticiones_sin_consentimiento(antes) == ["https://www.clarity.ms/tag/abcde12345"]
    assert peticiones_sin_consentimiento(antes[:1]) == []


def test_qa_de_la_landing_ya_la_cuenta_como_externa():
    # La QA del 18 nunca pulsa «aceptar»: una petición a Clarity sería un tercero y la QA saldría en rojo.
    propios = (".impultienda.example",)
    clase = clasificar_peticion("https://www.clarity.ms/tag/abcde12345", ("prueba.impultienda.example",),
                                tuple(HOSTS_META), propios)
    assert clase == "externa"
