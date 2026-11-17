"""Tarea 3 del plan 18: esqueleto propio, script UTM, `preparar` y `guardar`."""

import os
import re
import stat
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from trovefy import cli, landing_cli
from trovefy.landing.entrada import EntradaInvalida, ruta_landing
from trovefy.landing.plantilla import (
    UTM_JS,
    checkout_url,
    guardar,
    precio_texto,
    preparar,
    version_de,
)

from .conftest import TIENDA, P, cargar, vault_demo

SECRETO = "EAAB" + "x7Kq2" * 8  # forma de token de Meta: «EAAB» + 40 alfanuméricos (ficticio)


@pytest.fixture
def vd(tmp_path):
    v = vault_demo(tmp_path)
    return v, cargar(v)


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


# --- Ronda de revisión T1–5 --------------------------------------------------------------------------------


def test_precio_texto_por_idioma():
    """R5: en rumano el leu se escribe «lei»; el resto, símbolo o código ISO."""
    assert precio_texto(Decimal(79), "RON", "ro") == "79,00 lei"
    assert precio_texto(Decimal("14.9"), "EUR", "bg") == "14,90 €"
    assert precio_texto(Decimal("14.9"), "EUR", "ro") == "14,90 €"
    assert precio_texto(Decimal(30), "PLN", "pl") == "30,00 PLN"


def test_preparar_no_pisa_index_sin_rehacer(tmp_path, vd):
    """I4: el index.html del borrador es el trabajo de Claude; solo `rehacer` lo vuelve a escribir."""
    v, d = vd
    b = preparar(v, d, "impultienda", tmp_path / "b")
    (b / "index.html").write_text("<p>trabajo de Claude</p>", encoding="utf-8")
    preparar(v, d, "impultienda", tmp_path / "b")
    assert (b / "index.html").read_text(encoding="utf-8") == "<p>trabajo de Claude</p>"
    preparar(v, d, "impultienda", tmp_path / "b", rehacer=True)
    assert "data-tf-seccion" in (b / "index.html").read_text(encoding="utf-8")


def test_cli_preparar_avisa_que_no_pisa(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    args = ["landing", "preparar", "--producto", P, "--pais", "ZZ", "--hosting", "impultienda"]
    assert cli.main(args) == 0
    assert "no se ha tocado" not in capsys.readouterr().out
    indice = tmp_path / "cache" / "landing" / P / "ZZ" / "index.html"
    indice.write_text("<p>trabajo de Claude</p>", encoding="utf-8")
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "no se ha tocado" in out and "--rehacer" in out
    assert indice.read_text(encoding="utf-8") == "<p>trabajo de Claude</p>"
    assert cli.main([*args, "--rehacer"]) == 0
    assert "no se ha tocado" not in capsys.readouterr().out
    assert "data-tf-seccion" in indice.read_text(encoding="utf-8")


def test_preparar_no_pisa_css_propio_sin_rehacer(tmp_path, vd):
    """M6: cada archivo se decide aparte; un estilo.css retocado sigue aunque falte el index.html."""
    v, d = vd
    b = preparar(v, d, "impultienda", tmp_path / "b")
    (b / "assets" / "estilo.css").write_text("body{color:red}\n", encoding="utf-8")
    (b / "index.html").unlink()
    preparar(v, d, "impultienda", tmp_path / "b")
    assert (b / "index.html").is_file()
    assert (b / "assets" / "estilo.css").read_text(encoding="utf-8") == "body{color:red}\n"
    preparar(v, d, "impultienda", tmp_path / "b", rehacer=True)
    assert "--color-primario" in (b / "assets" / "estilo.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", ["index.html", "assets/estilo.css", "assets/utm.js"])
def test_preparar_rechaza_enlaces_incluso_colgantes(tmp_path, vd, rel):
    v, d = vd
    b = tmp_path / "b"
    (b / "assets").mkdir(parents=True)
    fuera = tmp_path / "fuera.txt"
    (b / rel).symlink_to(fuera)  # colgante: el destino no existe
    with pytest.raises(EntradaInvalida, match="enlace"):
        preparar(v, d, "impultienda", b, rehacer=True)
    assert not fuera.exists()


def test_preparar_rechaza_carpeta_assets_enlazada(tmp_path, vd):
    v, d = vd
    b, otra = tmp_path / "b", tmp_path / "otra"
    b.mkdir()
    otra.mkdir()
    (b / "assets").symlink_to(otra)
    with pytest.raises((EntradaInvalida, ValueError), match="enlace"):
        preparar(v, d, "impultienda", b)
    assert list(otra.iterdir()) == []


def test_preparar_escribe_atomico_en_0640(tmp_path, vd):
    v, d = vd
    b = preparar(v, d, "impultienda", tmp_path / "b")
    for rel in ("index.html", "assets/estilo.css", "assets/utm.js"):
        assert stat.S_IMODE((b / rel).stat().st_mode) == 0o640, rel
    assert not [p for p in b.rglob("*.tmp")]


def _publicada(v):
    ruta = ruta_landing(v, P, "ZZ") / "landing.yaml"
    ly = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    ly.update(url="https://ejemplo-demo.test/", publicada="2026-11-16")
    ruta.write_text(yaml.safe_dump(ly), encoding="utf-8")
    return ruta


def test_preparar_no_cambia_hosting_de_una_publicada(tmp_path, vd):
    """M7: cambiar hosting o checkout de una landing publicada rompe los anuncios: solo con `rehacer`."""
    v, d = vd
    preparar(v, d, "impultienda", tmp_path / "b")
    ruta = _publicada(v)
    with pytest.raises(EntradaInvalida, match="rehacer"):
        preparar(v, d, "cloudflare", tmp_path / "b")
    assert yaml.safe_load(ruta.read_text(encoding="utf-8"))["hosting"] == "impultienda"
    preparar(v, d, "impultienda", tmp_path / "b")  # el mismo hosting sí
    preparar(v, d, "cloudflare", tmp_path / "b", rehacer=True)
    ly = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert ly["hosting"] == "cloudflare" and ly["checkout_url"] == f"{TIENDA}/checkout"


def test_preparar_no_cambia_checkout_de_una_publicada(tmp_path, vd):
    from dataclasses import replace

    v, d = vd
    preparar(v, d, "cloudflare", tmp_path / "b")
    _publicada(v)
    with pytest.raises(EntradaInvalida, match="checkout"):
        preparar(v, replace(d, tienda="https://otra-tienda.demo.test"), "cloudflare", tmp_path / "b")


def test_cli_preparar_hosting_de_publicada_sale_2(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    base = ["landing", "preparar", "--producto", P, "--pais", "ZZ"]
    assert cli.main([*base, "--hosting", "impultienda"]) == 0
    _publicada(entorno)
    assert cli.main([*base, "--hosting", "cloudflare"]) == 2
    assert "--rehacer" in capsys.readouterr().err


def test_guardar_comprueba_todo_antes_de_escribir(tmp_path, vd):
    """M5: sin landing.yaml (o con él roto) no se escribe nada en el vault."""
    v, d, b = _borrador(tmp_path, vd)
    raiz = ruta_landing(v, P, "ZZ")
    (raiz / "landing.yaml").write_text("hosting: [roto\n", encoding="utf-8")
    with pytest.raises(EntradaInvalida, match="landing.yaml"):
        guardar(v, d, b)
    assert not (raiz / "index.html").exists() and not (raiz / "assets").exists()


def test_guardar_rechaza_carpeta_enlazada(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    raiz = ruta_landing(v, P, "ZZ")
    otra = tmp_path / "otra"
    otra.mkdir()
    (raiz / "assets").symlink_to(otra)
    with pytest.raises((EntradaInvalida, ValueError), match="enlace"):
        guardar(v, d, b)
    assert list(otra.iterdir()) == [] and not (raiz / "index.html").exists()


def test_guardar_no_sigue_un_index_enlazado(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    fuera = tmp_path / "fuera.html"
    fuera.write_text("fuera", encoding="utf-8")
    (ruta_landing(v, P, "ZZ") / "index.html").symlink_to(fuera)
    guardar(v, d, b)
    indice = ruta_landing(v, P, "ZZ") / "index.html"
    assert fuera.read_text(encoding="utf-8") == "fuera"
    assert not indice.is_symlink() and stat.S_IMODE(indice.stat().st_mode) == 0o640


def test_guardar_rechaza_landing_yaml_enlazado(tmp_path, vd):
    v, d, b = _borrador(tmp_path, vd)
    ruta = ruta_landing(v, P, "ZZ") / "landing.yaml"
    fuera = tmp_path / "fuera.yaml"
    fuera.write_bytes(ruta.read_bytes())
    ruta.unlink()
    ruta.symlink_to(fuera)
    antes = fuera.read_bytes()
    with pytest.raises(EntradaInvalida, match="enlace"):
        guardar(v, d, b)
    assert fuera.read_bytes() == antes and not (ruta.parent / "index.html").exists()


def test_guardar_escribe_en_orden_index_antes_que_landing_yaml(tmp_path, vd, monkeypatch):
    """M5: assets, después index.html y al final landing.yaml (la versión solo se anota con todo en su sitio)."""
    from trovefy.landing import plantilla

    v, d, b = _borrador(tmp_path, vd)
    orden = []
    real = plantilla.escribir_medio

    def espia(ruta, datos, *, base=None):
        orden.append(Path(ruta).name)
        return real(ruta, datos, base=base)

    monkeypatch.setattr(plantilla, "escribir_medio", espia)
    guardar(v, d, b)
    assert orden[-2:] == ["index.html", "landing.yaml"] and set(orden[:-2]) == {"estilo.css", "utm.js"}


@pytest.mark.parametrize("accion", ["preparar", "guardar", "estado"])
def test_cli_landing_yaml_roto_sale_2(entorno, tmp_path, monkeypatch, capsys, accion):
    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    assert cli.main(["landing", "preparar", "--producto", P, "--pais", "ZZ", "--hosting", "impultienda"]) == 0
    (ruta_landing(entorno, P, "ZZ") / "landing.yaml").write_text("hosting: [roto\n", encoding="utf-8")
    capsys.readouterr()
    extra = ["--hosting", "impultienda"] if accion == "preparar" else []
    assert cli.main(["landing", accion, "--producto", P, "--pais", "ZZ", *extra]) == 2
    assert "landing.yaml" in capsys.readouterr().err
    assert os.path.exists(ruta_landing(entorno, P, "ZZ") / "landing.yaml")
