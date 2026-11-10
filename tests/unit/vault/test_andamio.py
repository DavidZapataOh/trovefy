from trovify.vault.andamio import crear_vault

CARPETAS = ["config", "raw", "wiki/metodo", "wiki/reglas", "wiki/caza", "wiki/ofertas", "wiki/competidores",
            "wiki/mercados", "wiki/nichos", "wiki/angulos", "wiki/banco-de-ideas", "wiki/analisis/partes",
            "wiki/analisis/cierres", "wiki/analisis/semanas", "productos", "propuestas", "ledger/ventas",
            "ledger/gasto", "ledger/caja", "ledger/auditoria", "data/caza", "data/cache", "rutinas/log",
            "sesiones", ".trovify"]


def test_init_crea_el_andamio(tmp_path):
    v = tmp_path / "cerebro"
    crear_vault(v)
    for c in CARPETAS:
        assert (v / c).is_dir(), c
    for f in ["CLAUDE.md", "index.md", "log.md", "config/umbrales.yaml", "config/mercados.yaml",
              "wiki/caza/exclusiones.md", "wiki/entidades.md"]:
        assert (v / f).is_file(), f
    assert "<!-- REGLAS:INICIO -->" in (v / "CLAUDE.md").read_text()
    assert len(list((v / "wiki/reglas").glob("R-*.md"))) == 12
    assert not list(v.rglob(".gitkeep"))


def test_init_no_sobrescribe(tmp_path):
    v = tmp_path / "cerebro"
    crear_vault(v)
    (v / "CLAUDE.md").write_text("editado")
    (v / "config/umbrales.yaml").write_text("editado: true")
    assert crear_vault(v) == []
    assert (v / "CLAUDE.md").read_text() == "editado"
    assert (v / "config/umbrales.yaml").read_text() == "editado: true"


def test_devuelve_solo_lo_creado(tmp_path):
    v = tmp_path / "cerebro"
    crear_vault(v)
    (v / "log.md").unlink()
    assert crear_vault(v) == [v / "log.md"]


def test_cli_init(tmp_path, capsys):
    from trovify.cli import main
    v = tmp_path / "cerebro"
    assert main(["cerebro", "init", "--vault", str(v)]) == 0
    assert (v / "CLAUDE.md").is_file()
