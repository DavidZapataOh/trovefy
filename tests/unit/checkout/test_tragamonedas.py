"""Página de downsell con tragamonedas calcada del vídeo, con el premio que sortea la plataforma."""
import yaml
from trovefy.checkout import tragamonedas
from trovefy.checkout.operaciones import pagina_html
from trovefy.checkout.receta import validar_pagina_upsell

DATOS = {
    "plantilla": "tragamonedas", "premios": [40, 60], "etiqueta": "Още едно нещо", "saludo": "Чакай{nombre}.",
    "titular": "Заглавие.", "parrafos": ["Едно.", "**Две**."],
    "maquina": {"rotulo": "Машината", "titulo": "ТИХА ВЪЛНА", "subtitulo": "Един опит: днес", "premio": "Награда · №",
                "boton": "ДРЪПНИ ЛОСТА", "girando": "ПРОБВАМ…", "pie": "Един опит."},
    "posibles": "Възможни награди: 40 % или 60 % отстъпка.", "resultado": {"sufijo": "OFF", "texto": "Важи тук."},
    "producto": "Тяло без напрежение", "ahorro": "Спестяваш",
    "aceptar": {"titulo": "Искам го", "subtitulo": "С {n} % отстъпка"}, "lista": ["Едно", "Две"],
    "contador": {"minutos": 10, "texto": "Цената остава още", "vencido": "Времето изтече."},
    "rechazar": "Не, благодаря",
}


def _md(datos: dict) -> str:
    return "---\n" + yaml.safe_dump(datos, allow_unicode=True) + "---\n"


def test_datos_y_validacion():
    assert tragamonedas.datos_de(_md(DATOS)) == DATOS
    assert tragamonedas.datos_de("# Обикновена страница\n") is None
    assert validar_pagina_upsell(_md(DATOS)) == []
    malos = {**DATOS, "premios": [40], "posibles": "Награди: 40 %.", "lista": []}
    problemas = validar_pagina_upsell(_md(malos))
    assert any("premios" in p for p in problemas) and any("lista" in p for p in problemas)
    assert any("posibles" in p for p in validar_pagina_upsell(_md({**DATOS, "posibles": "Награди: 40 %."})))
    sin = {**DATOS, "maquina": {**DATOS["maquina"], "boton": ""}}
    assert any("maquina.boton" in p for p in validar_pagina_upsell(_md(sin)))
    assert any("contador.minutos" in p for p in validar_pagina_upsell(
        _md({**DATOS, "contador": {**DATOS["contador"], "minutos": 0}})))


def test_html_calcado_con_tokens_de_la_plataforma():
    html = pagina_html(_md(DATOS))
    assert 'data-ts="40,60"' in html and "<span data-ts-sorteo hidden>{discount}</span>" in html
    for token in ("{compare}", "{price}", "{savings}", "{product-image}", "{first-name}"):
        assert token in html, token
    assert "data-pp-accept" in html and "data-pp-decline" in html
    assert "ДРЪПНИ ЛОСТА" in html and 'data-ts-girando="ПРОБВАМ…"' in html and "<strong>Две</strong>" in html
    assert 'data-ts-reloj="600"' in html and "Възможни награди: 40 % или 60 % отстъпка." in html
    assert "Math.random()*10" in html  # solo la animación de los rodillos
    assert "{nombre}" not in html and "{n}" not in html and "onerror" not in html
    assert html.count("<div") == html.count("</div>")
    assert pagina_html(_md({**DATOS, "premios": [40]})) is None


def test_html_escapa_el_texto():
    html = pagina_html(_md({**DATOS, "titular": "<script>x</script>"}))
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
