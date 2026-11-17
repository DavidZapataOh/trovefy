"""Tarea 5 del plan 18: validación estática y reseñas solo reales."""

import re
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from trovefy import cli, landing_cli
from trovefy.landing.entrada import EntradaInvalida, ruta_landing
from trovefy.landing.medios import preparar_medios
from trovefy.landing.plantilla import guardar, preparar, version_de
from trovefy.landing.validar import (
    Resultado,
    anadir_resena,
    prueba_social_falsa,
    validar,
)

from .conftest import PDF_FIJO, Ejecutar, P, cargar, editar_md, vault_demo

BUENA = Path(__file__).resolve().parents[2] / "fixtures" / "landing" / "buena-zz.html"
SECRETO = "EAAB" + "x7Kq2" * 8


def montar(tmp_path, hosting="impultienda") -> Path:
    """Vault demo con medios, borrador preparado, la fixture buena como texto de Claude y guardada."""
    v = vault_demo(tmp_path)
    d = cargar(v)
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
    return validar(v, cargar(v))


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
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
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


# --- Ronda de revisión T1–5: lista blanca (I1, I2), prueba social (I3), vistas (M1) y precio (M2) ------------

H1 = "<h1 data-tf-hito>Спокойно тяло за 14 дни</h1>"
FIN = "</main>"

# Cada sonda de la revisión, convertida en regresión: (cambio, trozo que tiene que salir en los fallos).
SONDAS = {
    "meta_refresh": (lambda h: h.replace("<head>", '<head><meta http-equiv="refresh" '
                                         'content="0;url=https://evil.test/">'), "http-equiv"),
    "xlink_href": (lambda h: h.replace(FIN, '<svg><image xlink:href="https://evil.test/x.png" width="1" '
                                       'height="1"/></svg>' + FIN), "<svg>"),
    "a_ping": (lambda h: h.replace('<a data-tf-checkout href="/checkout">Искам наръчника</a>',
                                   '<a data-tf-checkout href="/checkout" ping="https://evil.test/p">Искам наръчника</a>',
                                   1), "ping"),
    "body_background": (lambda h: h.replace("<body>", '<body background="https://evil.test/bg.png">'), "background"),
    "link_imagesrcset": (lambda h: h.replace("<head>", '<head><link rel="preload" as="image" '
                                             'imagesrcset="https://evil.test/x.png 1x">'), "imagesrcset"),
    "css_image_set": (lambda h: h.replace("<head>", '<head><style>body{background-image:image-set('
                                          '"https://evil.test/x.png" 1x)}</style>'), "evil.test"),
    "css_escaped_url": (lambda h: h.replace("<head>", "<head><style>body{background:u\\72l("
                                            "https://evil.test/x.png)}</style>"), "evil.test"),
    "css_star_content": (lambda h: h.replace("<head>", '<head><style>h1::after{content:'
                                             '"\\2605\\2605\\2605\\2605\\2605"}</style>'), "estrellas"),
    "stars_title": (lambda h: h.replace("<title>Somatix", "<title>★★★★★ Somatix"), "estrellas"),
    "stars_alt_other": (lambda h: h.replace(H1, "<h1 data-tf-hito>Спокойно тяло за 14 дни ✭✭✭✭✭ 4,9/5</h1>"),
                        "4,9/5"),
    "fake_testimonial": (lambda h: h.replace(FIN, "<blockquote>„Най-добрата покупка тази година!“ — Мария, "
                                             "София</blockquote>" + FIN), "<blockquote>"),
    "fake_quota": (lambda h: h.replace(H1, H1 + "<p>Остават само 7 броя на тази цена. 1 284 души вече купиха "
                                       "наръчника.</p>"), "Остават само"),
    "static_countdown": (lambda h: h.replace(H1, H1 + "<p>Офертата изтича след 02:59:41</p>"), "02:59:41"),
    "greek_homoglyph": (lambda h: h.replace("Денят свършва", "Денят свършвα"), "homoglifo"),
    "js_svg_a": (lambda h: h.replace(FIN, '<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>' + FIN),
                 "<svg>"),
    "base_tienda": (lambda h: h.replace("<head>", '<head><base href="https://tienda.demo.test/">'), "<base>"),
    "fake_old_price": (lambda h: h.replace("<p data-tf-precio>14,90&nbsp;€</p>",
                                           "<p data-tf-precio><s>49,90 €</s> 14,90&nbsp;€</p>"), "49,90"),
    "meter": (lambda h: h.replace(FIN, '<p>Продадени</p><progress value="93" max="100"></progress>' + FIN),
              "<progress>"),
    "backslash_link": (lambda h: h.replace(FIN, '<a href="\\\\evil.test/x">виж</a>' + FIN), "evil.test"),
    "slash_backslash": (lambda h: h.replace(FIN, '<a href="/\\evil.test/x">виж</a>' + FIN), "evil.test"),
    "noscript_diff": (lambda h: h.replace(FIN, '<noscript><p title="</noscript><img src=https://evil.test/x.png '
                                          'onerror=alert(1)>"></p></noscript>' + FIN), "<noscript>"),
    "xmp_diff": (lambda h: h.replace(FIN, '<xmp><p title="</xmp><img src=https://evil.test/x.png onerror=alert(1)>">'
                                     "</p>" + FIN), "<xmp>"),
    "noembed_diff": (lambda h: h.replace(FIN, '<noembed><p title="</noembed><img src=https://evil.test/x.png '
                                         'onerror=alert(1)>"></p>' + FIN), "<noembed>"),
    "vista_no_pdf": (lambda h: h.replace("assets/vista-p1-480.webp", "assets/portada-480.webp"), "vista_pdf"),
}


@pytest.mark.parametrize("nombre", list(SONDAS))
def test_sonda_de_la_revision_falla(v, nombre):
    cambio, trozo = SONDAS[nombre]
    mutar(v, cambio)
    falla(v, trozo)


def test_mailto_vale_y_tel_no(v):
    """R3: `mailto:` (sin host) para el soporte de la garantía; `tel:` sigue fuera."""
    mutar(v, lambda h: h.replace(FIN, '<a href="mailto:a@ejemplo-demo.test">имейл</a>' + FIN))
    assert resultado(v).ok, resultado(v).fallos
    mutar(v, lambda h: h.replace(FIN, '<a href="tel:+35921234567">телефон</a>' + FIN))
    falla(v, "tel:")


@pytest.mark.parametrize("href", [
    "java\nscript:alert(1)", " javascript:alert(1)", "JAVASCRIPT:alert(1)", "https://ejemplo-demo.test@evil.test/",
    "http://ejemplo-demo.test/", "//evil.test/x", "https://evil.test\\@ejemplo-demo.test/", "data:text/html,x",
    "https://ejemplo-demo.test:99999/", "mailto://evil.test/x",
])
def test_href_raro_falla(v, href):
    mutar(v, lambda h: h.replace(FIN, f'<a href="{href}">виж</a>' + FIN))
    falla(v, "href de <a>")


def test_href_absoluto_al_dominio_propio_vale(v):
    mutar(v, lambda h: h.replace(FIN, '<a href="https://www.ejemplo-demo.test/aviso-legal">правни</a>' + FIN))
    assert resultado(v).ok, resultado(v).fallos


@pytest.mark.parametrize("src", ["assets/%2e%2e/x.webp", "assets/../x.webp", "otra/x.webp", "/assets/x.webp", ""])
def test_recurso_fuera_de_assets_falla(v, src):
    mutar(v, lambda h: h.replace(FIN, f'<img src="{src}" alt="x">' + FIN))
    falla(v, "src de <img>")


@pytest.mark.parametrize(("cambio", "trozo"), [
    (lambda h: h.replace("<head>", '<head><meta name="referrer" content="unsafe-url">'), "referrer"),
    (lambda h: h.replace("<head>", '<head><meta property="og:image" content="https://evil.test/x.png">'),
     "property"),
    (lambda h: h.replace('<script src="assets/utm.js" defer>', '<script src="assets/utm.js" type="module" defer>'),
     "type"),
    (lambda h: h.replace('<link rel="stylesheet"', '<link rel="stylesheet preload"'), "rel"),
    (lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", '<h2 data-tf-hito data-otro="1">Цена</h2>'), "data-otro"),
    (lambda h: h.replace("<h2 data-tf-hito>Цена</h2>", '<h2 data-tf-hito class="a" class="b">Цена</h2>'),
     "repetido"),
    (lambda h: h.replace(FIN, "<template><p>x</p></template>" + FIN), "<template>"),
    (lambda h: h.replace(FIN, "<textarea>x</textarea>" + FIN), "<textarea>"),
    (lambda h: h.replace(FIN, "<math><mi>x</mi></math>" + FIN), "<math>"),
    (lambda h: h.replace("<!DOCTYPE html>", '<!DOCTYPE html PUBLIC "x">'), "DOCTYPE"),
    (lambda h: h + "<p", "sin cerrar"),
])
def test_fuera_de_la_lista_blanca_falla(v, cambio, trozo):
    mutar(v, cambio)
    falla(v, trozo)


def test_meta_content_type_vale(v):
    mutar(v, lambda h: h.replace("<head>", '<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">'))
    assert resultado(v).ok, resultado(v).fallos


@pytest.mark.parametrize("css", [
    "body{background:url(//evil.test/x.png)}", "body{background:url('HTTPS://evil.test/x.png')}",
    'body{background:-webkit-image-set("data:image/png;base64,AAAA" 1x)}', 'body{background:image-set("../x.png" 1x)}',
    "@import 'otra.css';", "body{background:url(../x.png)}",
    "body{background:url(data:image/png;base64,AAAA)}", "a{background:url(h\\74tps://evil.test/x)}",
    "/* x */ a{background:url(\\2f\\2f evil.test/x)}",
])
def test_css_remoto_o_escapado_falla(v, css):
    ruta = ruta_landing(v, P, "ZZ") / "assets" / "estilo.css"
    ruta.write_text(ruta.read_text(encoding="utf-8") + "\n" + css + "\n", encoding="utf-8")
    falla(v, "estilo.css")


def test_estilo_en_linea_remoto_falla(v):
    mutar(v, lambda h: h.replace("<h2 data-tf-hito>Цена</h2>",
                                 '<h2 data-tf-hito style="background:url(https://evil.test/x)">Цена</h2>'))
    falla(v, "estilo en línea", "evil.test")


@pytest.mark.parametrize(("cambio", "trozo"), [
    (lambda h: h.replace('content="Кратки', 'content="Остават само 3 броя. Кратки'), "Остават само"),
    (lambda h: h.replace("<title>Somatix", "<title>Само днес · Somatix"), "Само днес"),
    (lambda h: h.replace('<a data-tf-checkout href="/checkout">Купувам',
                         '<a data-tf-checkout href="/checkout" aria-label="Над 2000 купувачи">Купувам'), "купувачи"),
    (lambda h: h.replace(FIN, "<p>Цената на книжарницата е <span>29,90 €</span>.</p>" + FIN), "29,90"),
    (lambda h: h.replace(FIN, "<p>Бонусите са на стойност 19 евро.</p>" + FIN), "19 евро"),
    (lambda h: h.replace(FIN, "<p>Вече 3 400 клиенти го използват.</p>" + FIN), "клиенти"),
    (lambda h: h.replace(FIN, "<p>Оценка 4.8 / 5 от читателите.</p>" + FIN), "4.8 / 5"),
    (lambda h: h.replace(FIN, "<p>⋆⋆⋆⋆⋆</p>" + FIN), "estrellas"),
    (lambda h: h.replace(FIN, "<p>Хиляди хора <q>го обичат</q>.</p>" + FIN), "<q>"),
    (lambda h: h.replace(FIN, "<p><cite>Мария</cite></p>" + FIN), "<cite>"),
    (lambda h: h.replace(FIN, '<meter value="0.9">90%</meter>' + FIN), "<meter>"),
])
def test_prueba_social_inventada_falla(v, cambio, trozo):
    mutar(v, cambio)
    falla(v, trozo)


def test_contenido_css_inventado_falla(v):
    ruta = ruta_landing(v, P, "ZZ") / "assets" / "estilo.css"
    ruta.write_text(ruta.read_text(encoding="utf-8") + '\n.x::after{content:"Остават само 3 броя"}\n',
                    encoding="utf-8")
    falla(v, "estilo.css", "Остават само")


def test_texto_bulgaro_normal_pasa(v):
    """Lo que una landing búlgara dice de verdad (pago, soporte, plazos, el precio repetido) no salta."""
    extra = ("<p>Плащане с Visa, Mastercard или Impul Pay. Получавате файла по имейл веднага.</p>"
             "<p>Пишете ни на support@ejemplo-demo.test и ще ви отговорим до 24 часа.</p>"
             '<p>Само 14,90 € за целия наръчник. <a href="mailto:support@ejemplo-demo.test">Пишете ни</a>.</p>'
             "<p>Отговаряме в работни дни от 9:00 до 18:00 часа.</p>")
    mutar(v, lambda h: h.replace("<dt>Колко време", "<dt>Как плащам?</dt><dd>" + extra + "</dd><dt>Колко време"))
    assert resultado(v).ok, resultado(v).fallos


def test_prueba_social_falsa_bg_y_ro():
    precio = Decimal("14.90")
    assert prueba_social_falsa("Наръчник в PDF за 14,90 € и гаранция 30 дни.", "bg", precio) == []
    for texto in ("Остават само 7 броя", "1 284 души вече купиха наръчника", "Над 900 купувачи",
                  "Изтича след 00:14:59", "Обичайна цена 29,90 €"):
        assert prueba_social_falsa(texto, "bg", precio), texto
    assert prueba_social_falsa("Ghidul costă 14,90 € și are garanție de 30 de zile.", "ro", precio) == []
    for texto in ("Au mai rămas doar 5 bucăți", "Peste 1.200 de clienți mulțumiți", "Oferta expiră la miezul nopții",
                  "Stoc limitat", "Preț vechi 99 lei", "Deja au cumpărat 300 de persoane", "Au mai rămaş 3 bucăţi"):
        assert prueba_social_falsa(texto, "ro", precio), texto


def test_precio_con_digitos_alrededor_falla(v):
    """M2: «114,90 €» no es «14,90 €»."""
    mutar(v, lambda h: h.replace("<p data-tf-precio>14,90&nbsp;€</p>", "<p data-tf-precio>114,90&nbsp;€</p>"))
    falla(v, "data-tf-precio")
    mutar(v, lambda h: h.replace("<p data-tf-precio>114,90&nbsp;€</p>", "<p data-tf-precio>14,905&nbsp;€</p>"))
    falla(v, "data-tf-precio")


def test_tienda_sin_https_no_abre_su_host(v):
    """M10: la tienda solo cuenta como origen si es https y pasa la misma regla que checkout_url."""
    mutar(v, lambda h: h.replace(FIN, '<a href="https://tienda.demo.test/terminos">условия</a>' + FIN))
    assert resultado(v).ok
    mercados = v / "config" / "mercados.yaml"
    mercados.write_text(mercados.read_text(encoding="utf-8").replace('"https://tienda.demo.test"',
                                                                     '"http://tienda.demo.test"'), encoding="utf-8")
    falla(v, "tienda.demo.test/terminos")


def test_landing_yaml_roto_es_error_de_entrada(v, monkeypatch, capsys):
    (ruta_landing(v, P, "ZZ") / "landing.yaml").write_text("hosting: [roto\n", encoding="utf-8")
    with pytest.raises(EntradaInvalida, match="landing.yaml"):
        resultado(v)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    assert cli.main(["landing", "validar", "--producto", P, "--pais", "ZZ"]) == 2
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 2
    assert "landing.yaml" in capsys.readouterr().err
