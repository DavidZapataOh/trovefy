import pathlib
from datetime import date

import pytest
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


def test_no_sobrescribe_existente_ni_enlace_roto(tmp_path):
    v = tmp_path / "v"
    carpeta = v / "raw/2026-11-10"
    carpeta.mkdir(parents=True)
    (carpeta / "nota.md").write_text("previo")
    (carpeta / "nota-2.md").symlink_to(tmp_path / "no-existe")
    f = tmp_path / "nota.md"
    f.write_text("nuevo")
    r, c = ingerir(v, f, date(2026, 11, 10))
    assert c and r.name == "nota-3.md"
    assert (carpeta / "nota.md").read_text() == "previo"
    assert not list(carpeta.glob(".*.tmp"))


def test_carrera_entre_escaneo_y_escritura(tmp_path, monkeypatch):
    from trovify.cerebro import ingesta
    v = tmp_path / "v"
    f = tmp_path / "nota.md"
    f.write_text("x")
    real = ingesta._buscar_por_sha

    def con_carrera(raw, sha):
        res = real(raw, sha)
        d = raw / "2026-11-10"
        d.mkdir(parents=True, exist_ok=True)
        (d / "nota.md").write_text("otro proceso")
        return res

    monkeypatch.setattr(ingesta, "_buscar_por_sha", con_carrera)
    r, c = ingerir(v, f, date(2026, 11, 10))
    assert c and r.name == "nota-2.md"
    assert (v / "raw/2026-11-10/nota.md").read_text() == "otro proceso"


def test_html_sin_cierres_no_pierde_contenido():
    h = ("<html><head><title>T</title><body><aside>Menu<h1>Titulo</h1><main><p>Cuerpo</p>"
         "<table><tr><td>a<td>b</tr><tr><td>c<td>d</table>"
         "<table><tr><td><ul><li>uno<li>dos</ul><td>z</table>"
         "<table><tr><td>ext<table><tr><td>int</td></tr></table></td><td>fin</td></tr></table>")
    t = html_a_texto(h)
    assert "Cuerpo" in t and "Menu" not in t and "T\n" not in t
    assert "a | b" in t and "c | d" in t
    assert "- uno - dos | z" in t
    assert "ext int | fin" in t


def test_head_sin_cierre_conserva_cuerpo():
    t = html_a_texto("<html><head><meta charset=x><title>Tit</title><body><p>Hola</p>")
    assert "Hola" in t and "Tit" not in t


def _tokens():
    return {
        "token de Meta": "EA" + "A" + "x1" * 15,
        "token de bot de Telegram": "123456789" + ":" + "Ab_" * 12,
        "clave sk-": "sk" + "-" + "q" * 24,
    }


@pytest.mark.parametrize("patron", ["token de Meta", "token de bot de Telegram", "clave sk-"])
def test_ingesta_rechaza_secretos(tmp_path, patron):
    f = tmp_path / "s.md"
    f.write_text("texto " + _tokens()[patron] + " fin")
    v = tmp_path / "v"
    with pytest.raises(ValueError, match=f"contiene un posible {patron}; no se ingiere"):
        ingerir(v, f)
    assert not list((v / "raw").rglob("*.md"))


def test_ingesta_acepta_mencion_de_access_token(tmp_path):
    f = tmp_path / "m.md"
    f.write_text("la URL lleva access" + "_token" + "= pero sin valor")
    assert ingerir(tmp_path / "v", f)[1] is True


def test_cli_ingerir_secreto_sale_2(tmp_path, capsys):
    from trovify.cli import main
    f = tmp_path / "s.md"
    f.write_text(_tokens()["clave sk-"])
    v = tmp_path / "v"
    assert main(["cerebro", "ingerir", "--vault", str(v), str(f)]) == 2
    assert "no se ingiere" in capsys.readouterr().err
    assert not list((v / "raw").rglob("*.md"))
