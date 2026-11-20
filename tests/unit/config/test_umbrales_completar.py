"""`completar`: añade al vault las claves nuevas de la plantilla sin tocar las que ya tiene (plan 23, Tarea 4)."""
import re

from trovefy.config.umbrales import cargar, completar
from trovefy.vault.andamio import crear_vault
from trovefy.vault.reglas import consistencia


def _vault_viejo(tmp_path):
    """Un vault de antes del plan 23: sin pi_visitas_min, sin diagnostico.* ni R-014, y con corte a 4."""
    v = tmp_path / "v"
    crear_vault(v)
    u = v / "config/umbrales.yaml"
    t = u.read_text(encoding="utf-8")
    t = re.sub(r"^(corte\.anuncio\.pi_visitas_min|diagnostico\.[a-z_]+):\n(?:  .*\n)+\n?", "", t, flags=re.MULTILINE)
    t = t.replace("corte.anuncio.gasto_usd:\n  valor: 3", "corte.anuncio.gasto_usd:\n  valor: 4")
    u.write_text(t, encoding="utf-8")
    (v / "wiki/reglas/R-014-diagnostico-por-etapa.md").unlink()
    for nombre in ("CLAUDE.md", "index.md"):
        f = v / nombre
        f.write_text("".join(x for x in f.read_text(encoding="utf-8").splitlines(True) if "R-014" not in x),
                     encoding="utf-8")
    return v


def test_completar_anade_sin_tocar(tmp_path):
    v = _vault_viejo(tmp_path)
    lineas = completar(v)
    u = cargar(v / "config/umbrales.yaml")
    assert u["corte.anuncio.gasto_usd"].valor == 4  # el valor del usuario no se pisa
    assert u["corte.anuncio.pi_visitas_min"].valor == 0.15 and u["diagnostico.ctr_min"].valor == 0.015
    assert any("R-014-diagnostico-por-etapa.md" in x for x in lineas)
    assert "R-014-diagnostico-por-etapa" in (v / "CLAUDE.md").read_text(encoding="utf-8")
    assert consistencia(v) == []


def test_completar_idempotente(tmp_path):
    v = _vault_viejo(tmp_path)
    completar(v)
    antes = (v / "config/umbrales.yaml").read_bytes()
    assert completar(v) == []
    assert (v / "config/umbrales.yaml").read_bytes() == antes


def test_completar_con_r014_ocupada_no_anade_sus_claves(tmp_path):
    v = _vault_viejo(tmp_path)
    (v / "wiki/reglas/R-014-otra.md").write_text(
        "---\ntipo: regla\nid: R-014\ntitulo: Otra\nfecha: 2026-11-10\nfuente: x\numbrales: []\nestado: vigente\n"
        "---\n\n# R-014\n", encoding="utf-8")
    lineas = completar(v)
    u = cargar(v / "config/umbrales.yaml")
    assert "diagnostico.ctr_min" not in u and "corte.anuncio.pi_visitas_min" in u
    assert any(x.startswith("pendiente: diagnostico.ctr_min") for x in lineas)
