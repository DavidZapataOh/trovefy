import pathlib
from datetime import date

from trovify.cerebro.ingesta import html_a_texto, ingerir
from trovify.vault import frontmatter

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures/cerebro/mini_playbook.html"


def test_html_a_texto_limpio_con_minutos():
    texto = html_a_texto(FIX.read_text())
    assert "# Playbook potenciado" in texto
    assert "T3 6:50" in texto
    assert "function(" not in texto and "{display:" not in texto
    assert "Índice" not in texto
    assert "Copiar" not in texto
    assert "https://" not in texto


def test_html_a_texto_estructura():
    texto = html_a_texto(FIX.read_text())
    assert "## Capítulo A" in texto
    assert "escala & " not in texto and "funciona & escala" in texto
    assert "- Primer paso\n- Segundo paso" in texto
    assert "Métrica | Valor" in texto and "CPA | 5" in texto
    assert "\n\n\n" not in texto


def test_reingesta_no_duplica(tmp_path):
    fuente = tmp_path / "nota.md"
    fuente.write_text("# Nota\nC1 10:55: 15+ anuncios")
    v = tmp_path / "v"
    r1, c1 = ingerir(v, fuente, date(2026, 11, 10))
    r2, c2 = ingerir(v, fuente, date(2026, 11, 11))
    assert c1 is True and c2 is False and r1 == r2
    assert len(list((v / "raw").rglob("*.md"))) == 1


def test_frontmatter_y_ruta(tmp_path):
    fuente = tmp_path / "Mi Nota Única.md"
    fuente.write_text("hola")
    r, _ = ingerir(tmp_path / "v", fuente, date(2026, 11, 10))
    assert r == tmp_path / "v/raw/2026-11-10/mi-nota-unica.md"
    meta, cuerpo = frontmatter.leer(r)
    assert meta["tipo"] == "fuente" and meta["origen"] == str(fuente.resolve())
    assert len(meta["sha256"]) == 64 and str(meta["fecha_ingesta"]) == "2026-11-10"
    assert cuerpo.strip() == "hola"


def test_mismo_slug_otro_contenido_sufijo(tmp_path):
    a = tmp_path / "a" / "nota.md"
    b = tmp_path / "b" / "nota.md"
    a.parent.mkdir(); b.parent.mkdir()
    a.write_text("uno"); b.write_text("dos")
    v = tmp_path / "v"
    ra, _ = ingerir(v, a, date(2026, 11, 10))
    rb, cb = ingerir(v, b, date(2026, 11, 10))
    assert cb and rb.name == "nota-2.md" and ra.name == "nota.md"


def test_html_se_convierte(tmp_path):
    r, c = ingerir(tmp_path / "v", FIX, date(2026, 11, 10))
    assert c and "# Playbook potenciado" in r.read_text()
    assert "<script" not in r.read_text()


def test_cli_ingerir(tmp_path, capsys):
    from trovify.cli import main
    f = tmp_path / "n.md"
    f.write_text("x")
    v = tmp_path / "v"
    assert main(["cerebro", "ingerir", "--vault", str(v), str(f)]) == 0
    assert main(["cerebro", "ingerir", "--vault", str(v), str(f), str(tmp_path / "no.md")]) == 2
    out = capsys.readouterr().out
    assert f"nuevo: {f}" in out and f"ya estaba: {f}" in out
    assert (v / "log.md").read_text().count("ingerir") == 2
