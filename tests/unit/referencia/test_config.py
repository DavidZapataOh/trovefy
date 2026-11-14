import os

import pytest
from trovefy.config.umbrales import UmbralFaltante, cargar
from trovefy.referencia.config import (
    CLAVES,
    UmbralesReferencia,
    cargar_umbrales_referencia,
    preparar_vault,
)
from trovefy.vault.andamio import crear_vault
from trovefy.vault.reglas import consistencia


def _vault_antiguo(destino):
    """Vault con R-001…R-012: la plantilla sin los bloques referencia.* ni R-013."""
    crear_vault(destino)
    u = destino / "config/umbrales.yaml"
    texto = u.read_text(encoding="utf-8")
    i = texto.index("referencia.")
    u.write_text(texto[:i].rstrip("\n") + "\n", encoding="utf-8")
    for p in (destino / "wiki/reglas").glob("R-013-*.md"):
        p.unlink()
    for nombre in ("CLAUDE.md", "index.md"):
        f = destino / nombre
        f.write_text("".join(ln for ln in f.read_text(encoding="utf-8").splitlines(True)
                             if "R-013" not in ln), encoding="utf-8")
    return destino


def test_plantilla_tiene_umbrales_referencia(tmp_path):
    crear_vault(tmp_path / "v")
    assert cargar_umbrales_referencia(tmp_path / "v") == UmbralesReferencia(7, 30, 2, 3, 10, 30)


def test_consistencia_plantilla(tmp_path):
    crear_vault(tmp_path / "v")
    assert consistencia(tmp_path / "v") == []


def test_falta_umbral_mensaje(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    u = v / "config/umbrales.yaml"
    t = u.read_text(encoding="utf-8")
    ini = t.index("referencia.top:")
    fin = t.index("\n\n", ini) + 2
    u.write_text(t[:ini] + t[fin:], encoding="utf-8")
    with pytest.raises(UmbralFaltante, match="trovefy ver-anuncios preparar"):
        cargar_umbrales_referencia(v)


def test_preparar_vault_antiguo(tmp_path):
    v = _vault_antiguo(tmp_path / "v")
    antes = (v / "config/umbrales.yaml").read_bytes()
    lineas = preparar_vault(v)
    assert lineas
    assert len(list((v / "wiki/reglas").glob("R-013-*.md"))) == 1
    umbrales = cargar(v / "config/umbrales.yaml")
    assert all(umbrales[c].regla == "R-013" for c in CLAVES) and len(CLAVES) == 6
    assert consistencia(v) == []
    assert (v / "config/umbrales.yaml").read_bytes().startswith(antes)
    assert cargar_umbrales_referencia(v) == UmbralesReferencia(7, 30, 2, 3, 10, 30)


def test_preparar_idempotente(tmp_path):
    v = _vault_antiguo(tmp_path / "v")
    preparar_vault(v)
    u = v / "config/umbrales.yaml"
    os.utime(u, (1_000_000, 1_000_000))
    assert preparar_vault(v) == []
    assert u.stat().st_mtime == 1_000_000


def test_preparar_con_r013_ocupada(tmp_path):
    v = _vault_antiguo(tmp_path / "v")
    ajena = v / "wiki/reglas/R-013-otra-cosa.md"
    ajena.write_text(
        "---\ntipo: regla\nid: R-013\ntitulo: Otra cosa\nfecha: 2026-11-10\nfuente: x\n"
        "umbrales: []\nestado: vigente\n---\n\n# R-013\n", encoding="utf-8")
    preparar_vault(v)
    assert len(list((v / "wiki/reglas").glob("R-014-*.md"))) == 1
    umbrales = cargar(v / "config/umbrales.yaml")
    assert all(umbrales[c].regla == "R-014" for c in CLAVES)
