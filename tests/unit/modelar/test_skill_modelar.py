"""La skill /modelar dice lo que el plan exige (aprobación tácita, citas literales, material ajeno)."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3] / "skills"
SKILL = (RAIZ / "modelar" / "SKILL.md").read_text() if (RAIZ / "modelar" / "SKILL.md").is_file() else ""


def test_aprobacion_tacita():
    assert "queda aprobada" in SKILL
    assert "No pidas confirmación" in SKILL


def test_cita_literal_entrecomillada():
    assert "--cita '<sus palabras literales>'" in SKILL
    assert "'\\''" in SKILL


def test_aviso_be_bajo_tal_cual():
    assert "precio bajo = BE chico = ningún anuncio es rentable" in SKILL


def test_material_ajeno():
    assert "nunca el texto ni el diseño" in SKILL
    assert "sin pulsar nada" in SKILL


def test_excepcion_solo_con_respuesta_explicita():
    assert "trovefy modelar excepcion" in SKILL
    assert "Solo con su respuesta explícita" in SKILL


def test_nunca_cifras_de_memoria():
    assert "de memoria" in SKILL


def test_cerrar_marca_la_aprobacion_tacita():
    assert "trovefy modelar cerrar" in (RAIZ / "cerrar/SKILL.md").read_text()


def test_ayuda_lista_modelar():
    assert "/trovefy:modelar" in (RAIZ / "ayuda/SKILL.md").read_text()


def test_allowed_tools_del_plan():
    meta = yaml.safe_load(SKILL.split("---")[1])
    assert meta["allowed-tools"] == (
        "Read, Write(productos/*/modelar.yaml), Bash(trovefy modelar *), Bash(trovefy economia *), "
        "mcp__firecrawl__firecrawl_scrape"
    )
