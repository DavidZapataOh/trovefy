from trovify.vault.andamio import crear_vault
from trovify.vault.lint import lint


def _pagina(ruta, cuerpo, meta="tipo: mercado\nfecha: 2026-11-10\nfuente: x\n"):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(f"---\n{meta}---\n{cuerpo}\n")


def test_vault_recien_creado_esta_limpio(tmp_path):
    crear_vault(tmp_path / "v")
    assert lint(tmp_path / "v") == []


def test_detecta_roto_huerfana_y_frontmatter(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    (v / "wiki/mercados/ro.md").write_text(
        "---\ntipo: mercado\nfecha: 2026-11-10\n---\nVer [[wiki/mercados/no-existe]]\n"
    )
    tipos = {p.tipo for p in lint(v)}
    assert tipos == {"enlace_roto", "huerfana", "frontmatter"}


def test_formas_de_enlace_validas(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    _pagina(v / "wiki/mercados/a.md", "[[wiki/mercados/b#sec]] [[wiki/mercados/c.md|alias]] [web](https://x.org/y.md)")
    _pagina(v / "wiki/mercados/b.md", "[a](a.md) [c](../mercados/c.md#h)")
    _pagina(v / "wiki/mercados/c.md", "x")
    (v / "index.md").write_text((v / "index.md").read_text() + "\n- [[wiki/mercados/a]]\n")
    assert lint(v) == []


def test_enlace_roto_markdown_y_enlaces_en_codigo_no_cuentan(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    _pagina(v / "wiki/mercados/a.md", "[x](nada.md) y `[[ejemplo]]`")
    (v / "index.md").write_text((v / "index.md").read_text() + "\n- [[wiki/mercados/a]]\n")
    rotos = [p for p in lint(v) if p.tipo == "enlace_roto"]
    assert len(rotos) == 1 and "nada.md" in rotos[0].detalle


def test_productos_exigen_frontmatter_y_sesiones_raw_se_ignoran(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    (v / "productos/p-0001").mkdir(parents=True)
    (v / "productos/p-0001/PRODUCTO.md").write_text("sin frontmatter\n")
    (v / "sesiones/2026-11-10-0900.md").write_text("[[no-existe-pero-sesion]]\n")
    (v / "raw/nota.md").write_text("huérfana en raw\n")
    ps = lint(v)
    assert [(p.tipo, p.ruta) for p in ps if p.tipo == "frontmatter"] == [("frontmatter", "productos/p-0001/PRODUCTO.md")]
    assert not any(p.tipo == "huerfana" for p in ps)
