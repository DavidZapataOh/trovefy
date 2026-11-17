"""Ruling R1 (resolución 23): `assets/pixel.js` en la ruta Cloudflare.

`preparar` lo escribe desde `templates/landing/pixel.js` con el `dataset_id` de `checkout/<PAIS>/TRACKING.md`
cuando el hosting es cloudflare; `guardar` lo deja en el vault y `validar` lo compara byte a byte.
"""

import shutil
from pathlib import Path

import pytest
from trovefy.landing.entrada import EntradaInvalida, ruta_landing
from trovefy.landing.medios import preparar_medios
from trovefy.landing.plantilla import PIXEL_PLANTILLA, guardar, pixel_js, preparar
from trovefy.landing.validar import validar

from .conftest import TIENDA, Ejecutar, P, cargar, escribir_md, vault_demo

BUENA = Path(__file__).resolve().parents[2] / "fixtures" / "landing" / "buena-zz.html"
DATASET = "1111111111111111"
ETIQUETA = '<script src="assets/pixel.js" defer></script>'


def tracking(v: Path, dataset_id=DATASET, pais: str = "ZZ") -> Path:
    ruta = v / "productos" / P / "checkout" / pais / "TRACKING.md"
    escribir_md(ruta, {"tipo": "tracking", "producto": P, "pais": pais, "dataset_id": dataset_id,
                       "estado": "pendiente"})
    return ruta


def montar(tmp_path, *, con_tracking=True, etiqueta=True, hosting="cloudflare") -> Path:
    v = vault_demo(tmp_path)
    if con_tracking:
        tracking(v)
    d = cargar(v)
    preparar_medios(v, d, ejecutar=Ejecutar())
    b = preparar(v, d, hosting, tmp_path / "borrador")
    html = BUENA.read_text(encoding="utf-8")
    if hosting == "cloudflare":
        html = html.replace('href="/checkout"', f'href="{TIENDA}/checkout"')
    if etiqueta:
        html = html.replace('<script src="assets/utm.js" defer></script>',
                            f'<script src="assets/utm.js" defer></script>\n{ETIQUETA}')
    (b / "index.html").write_text(html, encoding="utf-8")
    guardar(v, d, b)
    return v


def esperado() -> bytes:
    return PIXEL_PLANTILLA.read_text(encoding="utf-8").replace("{{dataset_id}}", DATASET).encode("utf-8")


def test_plantilla_solo_pageview_y_viewcontent():
    texto = PIXEL_PLANTILLA.read_text(encoding="utf-8")
    assert "{{dataset_id}}" in texto and "connect.facebook.net" in texto
    assert "'PageView'" in texto and "'ViewContent'" in texto
    assert "Purchase" not in texto and "InitiateCheckout" not in texto


def test_plantilla_sin_autoconfig_antes_de_init():
    """I-3: sin autoConfig el píxel no manda eventos automáticos (clics, metadatos) además de los dos nuestros."""
    texto = PIXEL_PLANTILLA.read_text(encoding="utf-8")
    apagado = "fbq('set','autoConfig',false,'{{dataset_id}}');"
    assert apagado in texto
    assert texto.index(apagado) < texto.index("fbq('init'")
    assert texto.count("fbq(") == 4  # set autoConfig, init, PageView, ViewContent


@pytest.mark.parametrize("dataset_id", ["١٢٣٤٥٦٧", "１２３４５６７", "123456\n"])
def test_dataset_solo_digitos_ascii(tmp_path, dataset_id):
    """L-2: `[0-9]{6,20}`; `\\d` aceptaría dígitos de otros alfabetos."""
    v = vault_demo(tmp_path)
    tracking(v, dataset_id)
    with pytest.raises(EntradaInvalida, match="dataset_id"):
        pixel_js(v, cargar(v))


def test_pixel_js_sin_tracking_es_none(tmp_path):
    v = vault_demo(tmp_path)
    assert pixel_js(v, cargar(v)) is None


def test_pixel_js_con_tracking(tmp_path):
    v = vault_demo(tmp_path)
    tracking(v)
    assert pixel_js(v, cargar(v)) == esperado()


@pytest.mark.parametrize("dataset_id", [None, "abc", "12", "1111'); fetch('x", 12.5])
def test_dataset_invalido_es_error(tmp_path, dataset_id):
    v = vault_demo(tmp_path)
    tracking(v, dataset_id)
    with pytest.raises(EntradaInvalida, match="dataset_id"):
        pixel_js(v, cargar(v))


def test_dataset_numerico_vale(tmp_path):
    v = vault_demo(tmp_path)
    tracking(v, int(DATASET))
    assert pixel_js(v, cargar(v)) == esperado()


def test_preparar_cloudflare_escribe_pixel_y_etiqueta(tmp_path):
    v = vault_demo(tmp_path)
    tracking(v)
    b = preparar(v, cargar(v), "cloudflare", tmp_path / "b")
    assert (b / "assets" / "pixel.js").read_bytes() == esperado()
    assert ETIQUETA in (b / "index.html").read_text(encoding="utf-8")
    assert (ruta_landing(v, P, "ZZ") / "assets" / "pixel.js").read_bytes() == esperado()


def test_preparar_impultienda_sin_pixel(tmp_path):
    v = vault_demo(tmp_path)
    tracking(v)
    b = preparar(v, cargar(v), "impultienda", tmp_path / "b")
    assert not (b / "assets" / "pixel.js").exists()
    assert "pixel.js" not in (b / "index.html").read_text(encoding="utf-8")


def test_preparar_cloudflare_sin_tracking_sin_pixel(tmp_path):
    v = vault_demo(tmp_path)
    b = preparar(v, cargar(v), "cloudflare", tmp_path / "b")
    assert not (b / "assets" / "pixel.js").exists()
    assert "pixel.js" not in (b / "index.html").read_text(encoding="utf-8")


def test_validar_pixel_igual_pasa(tmp_path):
    v = montar(tmp_path)
    assert (ruta_landing(v, P, "ZZ") / "assets" / "pixel.js").read_bytes() == esperado()
    r = validar(v, cargar(v))
    assert r.ok, r.fallos


def test_validar_pixel_editado_falla(tmp_path):
    v = montar(tmp_path)
    ruta = ruta_landing(v, P, "ZZ") / "assets" / "pixel.js"
    ruta.write_bytes(ruta.read_bytes().replace(DATASET.encode(), b"2222222222222222"))
    r = validar(v, cargar(v))
    assert not r.ok and any("pixel.js no es el de la plantilla" in f for f in r.fallos), r.fallos


def test_validar_pixel_sin_etiqueta_falla(tmp_path):
    v = montar(tmp_path, etiqueta=False)
    r = validar(v, cargar(v))
    assert not r.ok and any("no carga assets/pixel.js" in f for f in r.fallos), r.fallos


def test_validar_pixel_sin_tracking_sobra(tmp_path):
    v = montar(tmp_path, con_tracking=False, etiqueta=False)
    shutil.copyfile(Path(__file__), ruta_landing(v, P, "ZZ") / "assets" / "pixel.js")
    r = validar(v, cargar(v))
    assert not r.ok and any("TRACKING.md" in f for f in r.fallos), r.fallos


def test_validar_cloudflare_sin_tracking_avisa(tmp_path):
    v = montar(tmp_path, con_tracking=False, etiqueta=False)
    r = validar(v, cargar(v))
    assert r.ok, r.fallos
    assert any("píxel" in a and "trovefy tracking preparar" in a for a in r.avisos), r.avisos


def test_guardar_quita_pixel_viejo_si_ya_no_toca(tmp_path):
    v = montar(tmp_path)
    (v / "productos" / P / "checkout" / "ZZ" / "TRACKING.md").unlink()
    d = cargar(v)
    b = preparar(v, d, "cloudflare", tmp_path / "borrador")
    html = (b / "index.html").read_text(encoding="utf-8").replace(f"\n{ETIQUETA}", "")
    (b / "index.html").write_text(html, encoding="utf-8")
    guardar(v, d, b)
    assert not (ruta_landing(v, P, "ZZ") / "assets" / "pixel.js").exists()
