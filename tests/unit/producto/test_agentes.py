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


def test_nativo_promesa_obliga_a_corregir():
    texto = (AGENTES / "nativo.md").read_text(encoding="utf-8")
    assert "cuando toca" not in texto
    assert "en número y en palabras" in texto
    promesas = texto.split("**Promesas de salud o de ingresos**", 1)[1].split("\n- **", 1)[0]
    assert "- <s-NN> · «…» · …" in promesas
    assert "VEREDICTO: corregir" in promesas


def test_revisor_ultima_pagina_de_texto_puede_quedar_a_medias():
    texto = (AGENTES / "revisor.md").read_text(encoding="utf-8")
    que_buscas = texto.split("## Qué buscas", 1)[1].split("\n## ", 1)[0]
    vacio = que_buscas.split("- **vacío**", 1)[1].split("\n- **", 1)[0]
    for lugar in ("antes de las fichas", "antes de las fuentes", "al final del documento"):
        assert lugar in vacio, lugar
    assert "no es un «vacío»" in vacio
