import pytest
from trovefy.cerebro.destilado import CITA, pendientes, validar_pagina
from trovefy.vault.andamio import crear_vault

RAW = "raw/2026-11-10/playbook-videos-cerebro.md"


def _vault(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    f = v / RAW
    f.parent.mkdir(parents=True)
    f.write_text("---\ntipo: fuente\n---\nC1 10:55 quince anuncios")
    return v, f


def _pagina(v, nombre, cuerpo, fuentes=f"[{RAW}]", extra="tipo: metodo\nfecha: 2026-11-10\n"):
    p = v / "wiki/metodo" / nombre
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{extra}fuentes: {fuentes}\n---\n{cuerpo}")
    return p


def test_pendientes_hasta_que_se_cita(tmp_path):
    v, f = _vault(tmp_path)
    assert pendientes(v) == [f]
    p = _pagina(v, "caza.md", "## Vara\n15+ anuncios (C1 10:55)\n")
    assert pendientes(v) == [] and validar_pagina(v, p) == []


def test_pagina_sin_cita_valida_se_rechaza(tmp_path):
    v, _ = _vault(tmp_path)
    p = _pagina(v, "x.md", "## Vara\nquince anuncios\n", fuentes="[raw/2026-11-10/no-existe.md]")
    problemas = validar_pagina(v, p)
    assert any("no-existe.md" in x for x in problemas)
    assert any("Vara" in x for x in problemas)


@pytest.mark.parametrize("texto", [
    "T3 1:02:03", "S2 0:10", "C1 10:55", "L2 5:00", "V1 0:10:55", "§4.1", "§12", "raw/2026-11-10/a.md",
])
def test_cita_reconoce(texto):
    assert CITA.search(f"dato ({texto})")


@pytest.mark.parametrize("texto", ["T4 1:02", "C1 sin minuto", "S3 0:10", "§", "quince anuncios"])
def test_cita_rechaza(texto):
    assert not CITA.search(texto)


def test_frontmatter_incompleto(tmp_path):
    v, _ = _vault(tmp_path)
    p = v / "wiki/metodo/y.md"
    p.write_text("---\ntipo: regla\n---\n## A\n§1\n")
    m = " ".join(validar_pagina(v, p))
    assert "tipo: metodo" in m and "fecha" in m and "fuentes" in m


def test_texto_antes_de_primera_seccion_no_se_comprueba(tmp_path):
    v, _ = _vault(tmp_path)
    p = _pagina(v, "z.md", "Introducción sin cita\n\n## A\ndato (S1 2:00)\n")
    assert validar_pagina(v, p) == []


def test_seccion_con_solo_subtitulos_cuenta_su_contenido(tmp_path):
    v, _ = _vault(tmp_path)
    p = _pagina(v, "z.md", "## A\n### a1\ndato (C2 3:10)\n## B\n### b1\nsin cita\n")
    problemas = validar_pagina(v, p)
    assert len(problemas) == 1 and "B" in problemas[0] and "z.md" in problemas[0]


def test_fuentes_normaliza_y_pendientes_exacto(tmp_path):
    v, _ = _vault(tmp_path)
    _pagina(v, "z.md", "## A\n§1\n", fuentes=f"[./{RAW}]")
    assert pendientes(v) == []
    assert validar_pagina(v, v / "wiki/metodo/z.md") == []


def test_fuente_fuera_del_vault_o_basename_no_cuenta(tmp_path):
    v, f = _vault(tmp_path)
    p = _pagina(v, "z.md", "## A\n§1\n", fuentes="[playbook-videos-cerebro.md, ../../etc/passwd]")
    assert pendientes(v) == [f]
    assert len([x for x in validar_pagina(v, p) if "passwd" in x or "playbook" in x]) == 2


def test_cli_destilar(tmp_path, capsys):
    from trovefy.cli import main
    v, _ = _vault(tmp_path)
    assert main(["cerebro", "destilar", "--pendientes", "--vault", str(v)]) == 0
    assert RAW in capsys.readouterr().out
    _pagina(v, "a/b.md", "## A\nsin cita\n")
    assert main(["cerebro", "destilar", "--validar", "--vault", str(v)]) == 1
    assert "a/b.md" in capsys.readouterr().out


def test_cita_raw_anclada():
    assert not CITA.search("https://x/raw/foo.md")
    assert not CITA.search("myraw/a.md")
    assert CITA.search("(raw/2026/a.md)") and CITA.search("`raw/a.md`") and CITA.search("ver raw/a.md.")


def test_cita_raw_inexistente_se_reporta(tmp_path):
    v, _ = _vault(tmp_path)
    p = _pagina(v, "z.md", "## A\ndato (raw/2026-11-10/nada.md)\n")
    assert any("nada.md" in x for x in validar_pagina(v, p))
    ok = _pagina(v, "w.md", f"## A\ndato ({RAW})\n")
    assert validar_pagina(v, ok) == []


def test_validar_sin_metodo(tmp_path, capsys):
    from trovefy.cli import main
    v, _ = _vault(tmp_path)
    assert main(["cerebro", "destilar", "--validar", "--vault", str(v)]) == 0
    assert "No hay páginas del método" in capsys.readouterr().out


def test_cli_log(tmp_path, capsys):
    from trovefy.cli import main
    v, _ = _vault(tmp_path)
    assert main(["cerebro", "log", "--skill", "destilar", "--que", "a\nb", "--archivo", "x.md",
                 "--archivo", "y.md", "--tokens", "1200", "--vault", str(v)]) == 0
    linea = (v / "log.md").read_text().splitlines()[-1]
    assert "destilar · a b · x.md, y.md · ~1200 tokens" in linea
    assert main(["cerebro", "log", "--skill", "s", "--que", "q", "--vault", str(v)]) == 0
    assert (v / "log.md").read_text().splitlines()[-1].endswith("· — · — tokens")
    assert main(["cerebro", "log", "--skill", " ", "--que", "q", "--vault", str(v)]) == 2
    assert main(["cerebro", "log", "--skill", "s", "--que", "q", "--tokens", "-1", "--vault", str(v)]) == 2
