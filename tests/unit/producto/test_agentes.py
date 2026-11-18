from pathlib import Path

import pytest

AGENTES = Path(__file__).resolve().parents[3] / "agents"


def _salida(nombre: str) -> str:
    texto = (AGENTES / f"{nombre}.md").read_text(encoding="utf-8")
    return texto.split("## Salida", 1)[1]


@pytest.mark.parametrize("nombre", ["revisor", "nativo"])
def test_veredicto_sin_bloque_de_codigo(nombre):
    salida = _salida(nombre)
    lineas = salida.splitlines()
    for veredicto in ("VEREDICTO: ok", "VEREDICTO: corregir"):
        assert veredicto in lineas, veredicto
        i = lineas.index(veredicto)
        assert not lineas[i - 1].startswith("```") and not lineas[i + 1].startswith("```")
    assert "sin comillas, sin negritas, sin bloque de código" in salida


def test_nativo_precios_en_numero_y_palabras():
    texto = (AGENTES / "nativo.md").read_text(encoding="utf-8")
    assert "cuando toca" not in texto
    assert "en número y en palabras" in texto


def test_revisor_ultima_pagina_de_texto_puede_quedar_a_medias():
    texto = (AGENTES / "revisor.md").read_text(encoding="utf-8")
    que_buscas = texto.split("## Qué buscas", 1)[1].split("\n## ", 1)[0]
    vacio = que_buscas.split("- **vacío**", 1)[1].split("\n- **", 1)[0]
    for lugar in ("antes de las fichas", "antes de las fuentes", "al final del documento"):
        assert lugar in vacio, lugar
    assert "no es un «vacío»" in vacio


@pytest.mark.parametrize("nombre", ["revisor", "nativo"])
def test_sugerencias_no_bloquean(nombre):
    salida = _salida(nombre)
    assert "~ " in salida
    assert "`VEREDICTO: ok` también con líneas `~ `" in salida
    assert "nunca obligan a `VEREDICTO: corregir`" in salida


def test_nativo_separa_errores_de_preferencias():
    texto = (AGENTES / "nativo.md").read_text(encoding="utf-8")
    assert "~ <s-NN|portada|ficha-id> · «cita breve» · <mejora>" in texto
    assert "- <s-NN|portada|ficha-id> · «cita breve» · <corrección>" in texto
    assert "¿lo notaría un comprador nativo como un error?" in texto
    for error in ("concordancia", "ти", "Вие", "letras latinas", "comillas", "calcos"):
        assert error in texto, error
    for nit in ("по-добре от нищо", "Няма нищо лошо в това"):
        assert nit in texto, nit


def test_revisor_vacio_bloquea_solo_si_pasa_de_un_tercio():
    texto = (AGENTES / "revisor.md").read_text(encoding="utf-8")
    que_buscas = texto.split("## Qué buscas", 1)[1].split("\n## ", 1)[0]
    vacio = que_buscas.split("- **vacío**", 1)[1].split("\n- **", 1)[0]
    assert "más de un tercio de la página" in vacio
    assert "`~ `" in vacio
    assert "~ p<N> · <desborde|vacío|imagen|tipografía|contraste|en blanco|ajeno> · <mejora>" in texto
