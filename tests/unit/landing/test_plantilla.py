"""Tarea 3 del plan 18: esqueleto propio, script UTM, `preparar` y `guardar`."""

import re
import stat
from pathlib import Path

import pytest
import yaml
from trovefy import cli, landing_cli
from trovefy.landing.entrada import EntradaInvalida, cargar_datos, ruta_landing
from trovefy.landing.plantilla import (
    UTM_JS,
    checkout_url,
    guardar,
    preparar,
    version_de,
)

from .conftest import TIENDA, P, vault_demo

SECRETO = "EAAB" + "x7Kq2" * 8  # forma de token de Meta: «EAAB» + 40 alfanuméricos (ficticio)


@pytest.fixture
def vd(tmp_path):
    v = vault_demo(tmp_path)
    return v, cargar_datos(v, P, "ZZ")


def test_preparar_una_seccion_por_entrada(tmp_path, vd):
    v, d = vd
    ruta = preparar(v, d, "impultienda", tmp_path / "borrador")
    html = (ruta / "index.html").read_text(encoding="utf-8")
    assert html.count("data-tf-seccion=") == 15 and 'lang="bg"' in html and 'href="/checkout"' in html
    assert html.count("data-tf-checkout") == 3  # las tres secciones con cta
    assert html.count("data-tf-hito") == 15 and "<!-- texto propio -->" in html
    assert 'data-tf-tipo="vista_previa"' in html and 'data-tf-tipo="prueba_social"' not in html
    assert '<script src="assets/utm.js" defer></script>' in html
    assert 'data-tf-version=""' in html and "14,90" in html and "€" in html
    css = (ruta / "assets" / "estilo.css").read_text(encoding="utf-8")
    assert "--color-primario: #1F4E5F;" in css
    assert (ruta / "assets" / "utm.js").read_bytes() == UTM_JS.read_bytes()


def test_preparar_escribe_wireframe_y_landing_yaml(tmp_path, vd):
    v, d = vd
    preparar(v, d, "cloudflare", tmp_path / "borrador")
    raiz = ruta_landing(v, P, "ZZ")
    w = yaml.safe_load((raiz / "wireframe.yaml").read_text(encoding="utf-8"))
    assert [s["tipo"] for s in w["secciones"]][6] == "vista_previa" and len(w["secciones"]) == 15
    ly = yaml.safe_load((raiz / "landing.yaml").read_text(encoding="utf-8"))
    assert ly == {"p_id": P, "pais": "ZZ", "idioma": "bg", "moneda": "EUR", "precio": "14.90",
                  "angulo": d.angulo, "promesa_h1": d.promesa_h1, "hosting": "cloudflare",
                  "checkout_url": f"{TIENDA}/checkout", "version": None, "url": None, "publicada": None}
    log = (v / "log.md").read_text(encoding="utf-8")
    assert "preparar" in log


def test_preparar_con_vistas_las_pone(tmp_path, vd):
    v, d = vd
    assets = ruta_landing(v, P, "ZZ") / "assets"
    assets.mkdir(parents=True)
    (assets / "vistas.json").write_text('{"pdf": "x.pdf", "sha256": "0", "paginas": [1, 3]}', encoding="utf-8")
    html = (preparar(v, d, "impultienda", tmp_path / "b") / "index.html").read_text(encoding="utf-8")
    assert html.count("data-tf-vista") == 2
    assert 'srcset="assets/vista-p3-480.webp 480w, assets/vista-p3-960.webp 960w"' in html


def test_preparar_conserva_url_publicada(tmp_path, vd):
    v, d = vd
    preparar(v, d, "impultienda", tmp_path / "b")
    ruta = ruta_landing(v, P, "ZZ") / "landing.yaml"
    ly = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    ly.update(url="https://ejemplo-demo.test/", publicada="2026-11-16", version="abc123abc123")
    ruta.write_text(yaml.safe_dump(ly), encoding="utf-8")
    preparar(v, d, "impultienda", tmp_path / "b2")
    ly = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert (ly["url"], ly["publicada"], ly["version"]) == ("https://ejemplo-demo.test/", "2026-11-16", "abc123abc123")


def test_checkout_url_cloudflare_absoluta():
    assert checkout_url("cloudflare", "https://tienda.demo.test") == "https://tienda.demo.test/checkout"
    assert checkout_url("cloudflare", "https://tienda.demo.test/") == "https://tienda.demo.test/checkout"
    assert checkout_url("impultienda", None) == "/checkout"


@pytest.mark.parametrize("tienda", [None, "http://tienda.demo.test", "tienda.demo.test", "https://a.test/x?y"])
def test_checkout_url_cloudflare_sin_tienda_https(tienda):
    with pytest.raises(EntradaInvalida, match="tienda"):
        checkout_url("cloudflare", tienda)


def test_checkout_url_hosting_desconocido():
    with pytest.raises(EntradaInvalida, match="hosting"):
        checkout_url("netlify", None)


def test_version_estable():
    h = '<html><main id="tf-landing" data-tf-version="">hola</main></html>'
    assert version_de(h) == version_de(h.replace('data-tf-version=""', 'data-tf-version="abc"'))
    assert re.fullmatch(r"[0-9a-f]{12}", version_de(h))
    assert version_de(h) != version_de(h.replace("hola", "adiós"))


def _borrador(tmp_path, vd):
    v, d = vd
    return v, d, preparar(v, d, "impultienda", tmp_path / "borrador")


def test_guardar_copia_y_fija_version(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    version = guardar(v, d, b)
    raiz = ruta_landing(v, P, "ZZ")
    html = (raiz / "index.html").read_text(encoding="utf-8")
    assert f'data-tf-version="{version}"' in html and version_de(html) == version
    assert yaml.safe_load((raiz / "landing.yaml").read_text(encoding="utf-8"))["version"] == version
    for nombre in ("estilo.css", "utm.js"):
        assert stat.S_IMODE((raiz / "assets" / nombre).stat().st_mode) == 0o640
    assert "guardar" in (v / "log.md").read_text(encoding="utf-8")


def test_guardar_rechaza_secreto(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    html = (b / "index.html").read_text(encoding="utf-8").replace("<!-- texto propio -->", SECRETO, 1)
    (b / "index.html").write_text(html, encoding="utf-8")
    with pytest.raises(EntradaInvalida, match="secreto"):
        guardar(v, d, b)
    raiz = ruta_landing(v, P, "ZZ")
    assert not (raiz / "index.html").exists() and not (raiz / "assets" / "estilo.css").exists()


def test_guardar_rechaza_secreto_en_css(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    with (b / "assets" / "estilo.css").open("a", encoding="utf-8") as f:
        f.write(f"/* {SECRETO} */\n")
    with pytest.raises(EntradaInvalida, match="secreto"):
        guardar(v, d, b)


def test_guardar_usa_utm_del_repo(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    (b / "assets" / "utm.js").write_text("fetch('https://otro.test/x')\n", encoding="utf-8")
    guardar(v, d, b)
    assert (ruta_landing(v, P, "ZZ") / "assets" / "utm.js").read_bytes() == UTM_JS.read_bytes()


def test_guardar_sin_index_falla(tmp_path, vd):
    v, d = vd
    (tmp_path / "vacio").mkdir()
    with pytest.raises(EntradaInvalida, match="index.html"):
        guardar(v, d, tmp_path / "vacio")


def test_utm_js_estatico():
    js = UTM_JS.read_text(encoding="utf-8")
    assert UTM_JS == Path(__file__).resolve().parents[3] / "templates" / "landing" / "utm.js"
    assert len([linea for linea in js.splitlines() if linea.strip()]) <= 25
    assert not re.search(r"fetch|XMLHttpRequest|sendBeacon|eval|setTimeout|setInterval|cookie|localStorage", js)
    assert "URLSearchParams" in js and "fbclid" in js and "utm_" in js


def test_cli_preparar_y_guardar(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    assert cli.main(["landing", "preparar", "--producto", P, "--pais", "ZZ", "--hosting", "impultienda"]) == 0
    out = capsys.readouterr().out
    borrador = tmp_path / "cache" / "landing" / P / "ZZ"
    assert str(borrador) in out and (borrador / "index.html").is_file()
    assert cli.main(["landing", "guardar", "--producto", P, "--pais", "ZZ"]) == 0
    assert (ruta_landing(entorno, P, "ZZ") / "index.html").is_file()


def test_cli_preparar_sin_hosting_avisa_cloudflare(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    assert cli.main(["landing", "preparar", "--producto", P, "--pais", "ZZ"]) == 0
    assert "cloudflare" in capsys.readouterr().out
    ly = yaml.safe_load((ruta_landing(entorno, P, "ZZ") / "landing.yaml").read_text(encoding="utf-8"))
    assert ly["hosting"] == "cloudflare"


def test_cli_guardar_con_secreto_sale_2(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    cli.main(["landing", "preparar", "--producto", P, "--pais", "ZZ", "--hosting", "impultienda"])
    b = tmp_path / "cache" / "landing" / P / "ZZ" / "index.html"
    b.write_text(b.read_text(encoding="utf-8") + SECRETO, encoding="utf-8")
    assert cli.main(["landing", "guardar", "--producto", P, "--pais", "ZZ"]) == 2
    assert SECRETO not in capsys.readouterr().err
