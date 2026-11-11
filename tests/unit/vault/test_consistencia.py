import re

from trovefy.vault.andamio import crear_vault
from trovefy.vault.frontmatter import leer
from trovefy.vault.reglas import consistencia


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


def test_valores_de_las_reglas_coinciden_con_el_yaml():
    from pathlib import Path

    from trovefy.vault.reglas import valores_citados, valores_desactualizados

    raiz = Path(__file__).resolve().parents[3] / "templates" / "cerebro"
    assert valores_desactualizados(raiz) == []
    assert len(valores_citados(raiz)) >= 10


def test_r005_aplica_a_todo_anuncio_y_cita_esperar():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[3] / "templates" / "cerebro"
    t = (raiz / "wiki/reglas/R-005-corte-de-anuncio.md").read_text(encoding="utf-8")
    assert "No aplica a ofertas con ventas" not in t
    assert "§4.13" in t and "corte.anuncio.impresiones_min" in t
    assert "corte.anuncio.impresiones_min" in (raiz / "config/umbrales.yaml").read_text(encoding="utf-8")


def test_r005_esperar_usa_o_no_ni():
    from pathlib import Path
    raiz =Path(__file__).resolve().parents[3] / "templates" / "cerebro"
    t = (raiz / "wiki/reglas/R-005-corte-de-anuncio.md").read_text(encoding="utf-8")
    regla = t.split("## Regla")[1].split("## ")[0]
    frase = next(f for f in regla.split(". ") if "ESPERAR" in f)
    assert not re.search(r"\bni\b", frase), frase
    partes = re.split(r"`corte\.anuncio\.impresiones_min`", frase)
    assert len(partes) == 2 and "`corte.anuncio.gasto_usd`" in partes[0], frase
    assert re.search(r"\s\*{0,2}o\*{0,2}\s", partes[0]), frase


def test_valores_desactualizados_comparte_implementacion(tmp_path):
    from trovefy.vault.reglas import valores_citados
    crear_vault(tmp_path / "v")
    pares = valores_citados(tmp_path / "v")
    assert len(pares) >= 10 and all(len(x) == 4 for x in pares)
