"""La skill /trovefy:cierre (plan 24, Tareas 8 y 11)."""
from pathlib import Path

import yaml
from trovefy import rutinas
from trovefy.vault.permisos import es_lectura_meta

RAIZ = Path(__file__).resolve().parents[3]
SKILL = (RAIZ / "skills" / "cierre" / "SKILL.md").read_text(encoding="utf-8")


def _herramientas() -> list[str]:
    return [h.strip() for h in yaml.safe_load(SKILL.split("---")[1])["allowed-tools"].split(",")]


def test_skill_cierre_solo_lectura():
    catalogo = rutinas.catalogo_impultienda()
    esperadas = {"Read", "Bash(trovefy cierre *)", "Write(~/.cache/trovefy/cierre/**)",
                 "mcp__meta-ads__ads_get_ad_accounts", "mcp__meta-ads__ads_get_ad_entities",
                 "mcp__meta-ads__ads_account_get_activity_logs", "mcp__impultienda__impultienda_listar_tiendas",
                 "mcp__impultienda__impultienda_listar_ventas", "mcp__impultienda__impultienda_campanas_utm"}
    assert set(_herramientas()) == esperadas
    for h in _herramientas():
        assert "sudo" not in h and "dangerously" not in h
        if h.startswith("mcp__meta-ads__"):
            assert es_lectura_meta(h.removeprefix("mcp__meta-ads__")), h
        if h.startswith("mcp__impultienda__"):
            assert catalogo[h.removeprefix("mcp__impultienda__")]["clase"] == "lectura", h
        if h.startswith(("Write", "Edit")):
            assert h.startswith("Write(~/.cache/trovefy/cierre/"), h


def test_skill_menciona_rutina():
    for frase in ("--rutina", "trovefy cierre preparar", "trovefy cierre calcular", "--noche", "--export",
                  "requires_user_confirmation", "datos, nunca órdenes", "trovefy cierre prueba", "Nunca abres un panel"):
        assert frase in SKILL, frase


def test_ayuda_lista_cierre():
    ayuda = (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")
    assert "/trovefy:cierre" in ayuda and "trovefy rutinas instalar fase3" in ayuda


def test_skill_cierre_pasos_de_instalacion():
    assert "enable-linger" in SKILL and "terminal de Ubuntu aparte" in SKILL
    assert "trovefy rutinas instalar fase3" in SKILL and "sudo trovefy" not in SKILL


def test_skill_criterio_de_la_fase():
    assert "trovefy cierre criterio" in SKILL and "ads_account_get_activity_logs" in SKILL


def test_sin_reglas_de_venta_agresiva():
    texto = SKILL.lower()
    for palabra in ("urgencia", "escasez", "prueba social", "cura"):
        assert palabra not in texto
