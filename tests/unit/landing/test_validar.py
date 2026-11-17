"""Tarea 5 del plan 18: validación estática y reseñas solo reales."""

import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from trovefy import cli
from trovefy.landing.entrada import cargar_datos, ruta_landing
from trovefy.landing.medios import preparar_medios
from trovefy.landing.plantilla import guardar, preparar, version_de
from trovefy.landing.validar import Resultado, anadir_resena, validar

from .conftest import PDF_FIJO, P, editar_md, vault_demo
from .test_medios import Ejecutar

BUENA = Path(__file__).resolve().parents[2] / "fixtures" / "landing" / "buena-zz.html"
SECRETO = "EAAB" + "x7Kq2" * 8


def montar(tmp_path, hosting="impultienda") -> Path:
    """Vault demo con medios, borrador preparado, la fixture buena como texto de Claude y guardada."""
    v = vault_demo(tmp_path)
    d = cargar_datos(v, P, "ZZ")
    preparar_medios(v, d, ejecutar=Ejecutar())
    b = preparar(v, d, hosting, tmp_path / "borrador")
    shutil.copyfile(BUENA, b / "index.html")
    guardar(v, d, b)
    return v


def html_de(v: Path) -> Path:
    return ruta_landing(v, P, "ZZ") / "index.html"


def mutar(v: Path, cambio, *, con_version=True) -> None:
    ruta = html_de(v)
    html = cambio(ruta.read_text(encoding="utf-8"))
    if con_version:
        html = re.sub(r'data-tf-version="[^"]*"', f'data-tf-version="{version_de(html)}"', html)
    ruta.write_text(html, encoding="utf-8")


def resultado(v: Path) -> Resultado:
    return validar(v, cargar_datos(v, P, "ZZ"))


def falla(v: Path, *trozos: str) -> Resultado:
    r = resultado(v)
    assert not r.ok
    texto = "\n".join(r.fallos)
    for t in trozos:
        assert t in texto, texto
    return r


@pytest.fixture
def v(tmp_path):
    return montar(tmp_path)


def test_buena_pasa(v):
    r = resultado(v)
    assert r.ok and r.fallos == (), r.fallos
    assert r.avisos == (), r.avisos


def test_dos_secciones_cambiadas_de_orden(v):
    def cambio(h):
        h = h.replace('data-tf-tipo="problema"', "@@A@@").replace('data-tf-tipo="villano"', 'data-tf-tipo="problema"')
        return h.replace("@@A@@", 'data-tf-tipo="villano"')
    mutar(v, cambio)
    falla(v, "sección 2", "orden")


def test_secciones_de_menos(v):
    mutar(v, lambda h: re.sub(r'<section data-tf-seccion="1[34]".*?</section>', "", h, flags=re.DOTALL))
    falla(v, "14–16")


def test_boton_principal_en_otra_seccion(v):
    mutar(v, lambda h: h.replace('<a data-tf-checkout href="/checkout">Искам наръчника</a>', "", 1))
    falla(v, "botón principal", "sección 1")


def test_href_checkout_distinto(v):
    mutar(v, lambda h: h.replace('href="/checkout">Купувам', 'href="/checkout?x=1">Купувам'))
    falla(v, "/checkout?x=1")


def test_lang_distinto(v):
    mutar(v, lambda h: h.replace('<html lang="bg">', '<html lang="ru">'))
    falla(v, "lang")


def test_sin_titulo_ni_descripcion(v):
    mutar(v, lambda h: re.sub(r"<title>.*?</title>|<meta name=\"description\"[^>]*>", "", h))
    falla(v, "<title>", "description")


def test_titulo_con_letra_rusa(v):
    mutar(v, lambda h: h.replace("<title>Somatix · Спокойно", "<title>Это Somatix · Спокойно"))
    falla(v, "título", "Это")


def test_texto_con_homoglifo(v):
    mutar(v, lambda h: h.replace("<p>Кратки вечерни", "<p>Крaтки вечерни", 1))  # «a» latina
    falla(v, "texto visible", "homoglifo")


def test_seccion_sin_hito_o_con_dos(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", "<h2>Цена</h2>")
          .replace("<h2 data-tf-hito>За кого е</h2>", "<h2 data-tf-hito>За кого е</h2><p data-tf-hito>x</p>"))
    falla(v, "sección 13", "sección 9", "data-tf-hito")


def test_formato_con_paginas_falsas(v):
    mutar(v, lambda h: h.replace("PDF от 3 страници", "PDF от 12 страници"))
    falla(v, "data-tf-formato", "3")


def test_garantia_sin_dias(v):
    mutar(v, lambda h: h.replace("Имате 30 дни", "Имате един месец"))
    falla(v, "data-tf-garantia", "30")


def test_precio_sin_coma_o_simbolo(v):
    mutar(v, lambda h: h.replace("<p data-tf-precio>14,90&nbsp;€</p>", "<p data-tf-precio>14.90 EUR</p>"))
    falla(v, "data-tf-precio", "14,90")


def test_resena_inventada_falla(v):
    mutar(v, lambda h: h.replace("</section>\n<section data-tf-seccion=\"8\"",
                                 '<blockquote data-tf-resena="r-1">Страхотно!</blockquote></section>\n'
                                 '<section data-tf-seccion="8"', 1))
    falla(v, "r-1", "resenas.yaml")


def test_estrellas_sin_resenas_falla(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", "<h2 data-tf-hito>Цена</h2><p>★★★★★</p>"))
    falla(v, "estrellas")


def test_prueba_social_sin_resenas_falla(v):
    mutar(v, lambda h: h.replace('data-tf-tipo="vista_previa"', 'data-tf-tipo="prueba_social"'))
    falla(v, "prueba_social")


def test_sin_vista_previa_falla(v):
    mutar(v, lambda h: re.sub(r"<img data-tf-vista[^>]*>", "", h))
    falla(v, "vista previa")


def test_vista_previa_de_pdf_viejo_falla(v):
    ent = v / "productos" / P / "entregable"
    (ent / "demo-bg-v2.pdf").write_bytes(PDF_FIJO.read_bytes() + b"\n% v2\n")
    editar_md(v, "PRODUCTO", lambda m: m["entregable"]["bg"]["principal"].update(pdf="entregable/demo-bg-v2.pdf"))
    falla(v, "la vista previa es de demo-bg-v1.pdf", "trovefy landing medios")


def test_imagen_externa_falla(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>",
                                 '<h2 data-tf-hito>Цена</h2><img src="https://otra-tienda.test/x.webp" alt="">'))
    falla(v, "https://otra-tienda.test/x.webp")


def test_css_externo_falla(v):
    css = ruta_landing(v, P, "ZZ") / "assets" / "estilo.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n@import url(https://fonts.ejemplo.test/a.css);\n",
                   encoding="utf-8")
    falla(v, "estilo.css", "https://fonts.ejemplo.test/a.css")


def test_enlace_a_dominio_propio_y_tienda_valen(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", '<h2 data-tf-hito>Цена</h2>'
                                 '<a href="https://ejemplo-demo.test/aviso-legal">правни</a>'
                                 '<a href="https://tienda.demo.test/terminos">условия</a><a href="#faq">въпроси</a>'))
    assert resultado(v).ok


def test_asset_sin_origen_falla(v):
    (ruta_landing(v, P, "ZZ") / "assets" / "ajena.webp").write_bytes(b"RIFF ajena")
    falla(v, "ajena.webp", "medios.json")


def test_asset_cambiado_falla(v):
    (ruta_landing(v, P, "ZZ") / "assets" / "vista-p3-480.webp").write_bytes(b"RIFF otra")
    falla(v, "vista-p3-480.webp", "sha256")


def test_script_extra_falla(v):
    mutar(v, lambda h: h.replace("</main>", "<script>setInterval(function(){}, 1000)</script></main>"))
    falla(v, "<script>")


def test_utm_manipulado_falla(v):
    (ruta_landing(v, P, "ZZ") / "assets" / "utm.js").write_text("fetch('/x')\n", encoding="utf-8")
    falla(v, "utm.js")


def test_iframe_form_y_on_fallan(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", '<h2 data-tf-hito onclick="x()">Цена</h2>'
                                 '<iframe src="assets/x.html"></iframe><form></form>'))
    falla(v, "<iframe>", "<form>", "onclick")


def test_version_editada_a_mano_falla(v):
    mutar(v, lambda h: h.replace("Цена</h2>", "Цената</h2>"), con_version=False)
    falla(v, "data-tf-version", "trovefy landing guardar")


def test_secreto_en_html_falla(v):
    mutar(v, lambda h: h.replace("</main>", f"<!-- {SECRETO} --></main>"))
    r = falla(v, "secreto")
    assert SECRETO not in "\n".join(r.fallos)


def test_aviso_de_largo_y_descripcion(v):
    mutar(v, lambda h: h.replace("Около десет минути.", "Около десет минути. " + "Много дълъг отговор. " * 60)
          .replace('content="Кратки', 'content="' + "Дълго описание " * 12 + "Кратки"))
    r = resultado(v)
    assert r.ok
    assert any("sección 14" in a for a in r.avisos) and any("160" in a for a in r.avisos)


def test_resena_sin_fuente_rechazada(v):
    with pytest.raises(ValueError, match="fuente"):
        anadir_resena(v, P, "ZZ", "Много полезно.", date(2026, 11, 16), "  ")
    assert not (ruta_landing(v, P, "ZZ") / "resenas.yaml").exists()


def test_resena_con_secreto_rechazada(v):
    with pytest.raises(ValueError, match="secreto"):
        anadir_resena(v, P, "ZZ", f"Много полезно {SECRETO}", date(2026, 11, 16), "pedido 1001")


def test_resena_real_valida(v):
    texto = "Правя упражненията всяка вечер и спя по-добре."
    rid = anadir_resena(v, P, "ZZ", texto, date(2026, 11, 16), "pedido 1001")
    assert rid == "r-20261116-1"
    assert anadir_resena(v, P, "ZZ", "Добро е.", date(2026, 11, 16), "email 2026-11-16") == "r-20261116-2"
    datos = yaml.safe_load((ruta_landing(v, P, "ZZ") / "resenas.yaml").read_text(encoding="utf-8"))
    assert datos["resenas"][0] == {"id": rid, "texto": texto, "fecha": "2026-11-16", "pais": "ZZ",
                                   "fuente": "pedido 1001"}
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Вижте страниците отвътре</h2>",
                                 f'<h2 data-tf-hito>Вижте страниците отвътре</h2>'
                                 f'<blockquote data-tf-resena="{rid}">{texto}</blockquote>'))
    assert resultado(v).ok, resultado(v).fallos


def test_resena_con_texto_cambiado_falla(v):
    rid = anadir_resena(v, P, "ZZ", "Добро е.", date(2026, 11, 16), "pedido 1001")
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>",
                                 f'<h2 data-tf-hito>Цена</h2><blockquote data-tf-resena="{rid}">Най-доброто!</blockquote>'))
    falla(v, rid, "texto")


def test_cli_validar(v, monkeypatch, capsys):
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    assert cli.main(["landing", "validar", "--producto", P, "--pais", "ZZ"]) == 0
    assert "sin fallos" in capsys.readouterr().out
    mutar(v, lambda h: h.replace('<html lang="bg">', '<html lang="ru">'))
    assert cli.main(["landing", "validar", "--producto", P, "--pais", "ZZ"]) == 1
    assert "lang" in capsys.readouterr().out


def test_cli_resena(v, monkeypatch, capsys):
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    args = ["landing", "resena", "--producto", P, "--pais", "ZZ", "--texto", "Добро е.", "--fecha", "2026-11-16"]
    assert cli.main([*args, "--fuente", "pedido 1001"]) == 0
    assert "r-20261116-1" in capsys.readouterr().out
    assert cli.main([*args, "--fuente", ""]) == 2
    assert cli.main([*args[:-2], "--fecha", "16/11/2026", "--fuente", "x"]) == 2
