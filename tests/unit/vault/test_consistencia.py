import re

from trovify.vault.andamio import crear_vault
from trovify.vault.frontmatter import leer
from trovify.vault.reglas import consistencia


def test_semilla_es_consistente(tmp_path):
    crear_vault(tmp_path / "v")
    assert consistencia(tmp_path / "v") == []


def test_umbral_sin_regla_se_detecta(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    (v / "wiki/reglas/R-005-corte-de-anuncio.md").unlink()
    problemas = consistencia(v)
    assert any("R-005" in p for p in problemas)


def test_clave_inexistente_se_detecta(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    p = v / "wiki/reglas/R-005-corte-de-anuncio.md"
    p.write_text(p.read_text().replace("corte.anuncio.gasto_usd", "corte.anuncio.inventada", 1))
    problemas = consistencia(v)
    assert any("corte.anuncio.inventada" in x for x in problemas)
    assert any("corte.anuncio.gasto_usd" in x for x in problemas)


def test_claude_md_lista_las_12_reglas_y_17_duras(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    t = (v / "CLAUDE.md").read_text()
    bloque = t.split("<!-- REGLAS:INICIO -->")[1].split("<!-- REGLAS:FIN -->")[0]
    assert len(re.findall(r"^- \[\[R-\d{3}-", bloque, re.MULTILINE)) == 12
    assert len(re.findall(r"^\d+\. \*\*", t, re.MULTILINE)) == 17


def test_paginas_de_wiki_con_frontmatter_y_enlazadas(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    indice = (v / "index.md").read_text()
    for p in (v / "wiki").rglob("*.md"):
        meta, _ = leer(p)
        assert "tipo" in meta and "fecha" in meta and ("fuente" in meta or "fuentes" in meta), p
        assert f"[[{p.relative_to(v).with_suffix('').as_posix()}]]" in indice, p
