"""Estáticos 1080×1350 con la marca y medios propios (plan 21, Tarea 5)."""

import io
import stat

import pytest
from PIL import Image
from trovefy.creativos import estaticos
from trovefy.creativos.config import cargar_plantilla
from trovefy.creativos.estaticos import (
    TextoNoCabe,
    componer,
    contraste,
    cubrir,
    escribir_estatico,
)
from trovefy.creativos.guion import Bloque, GuionEstatico
from trovefy.pdf.fuentes import ruta_fuente
from trovefy.producto.medios import leer_manifiesto

from .ejemplos import png

CFG = cargar_plantilla()
PALETA = {"fondo": "#F4EFE6", "texto": "#1E2A38", "acento": "#C8553D"}


def _fuente():
    for familia in ("Noto Sans", "DejaVu Sans", "Ubuntu"):
        try:
            ruta = ruta_fuente(familia)
        except FileNotFoundError:
            ruta = None
        if ruta is not None:
            return ruta
    pytest.skip("no hay una fuente con cirílico en la máquina")


@pytest.fixture
def fuentes():
    f = _fuente()
    return {"titulos": f, "texto": f}


def _guion(bloques, fondo="color", ref=None, formato="tipografico"):
    return GuionEstatico("AD01", formato, fondo, ref, tuple(bloques))


GANCHO = Bloque("Не можеш да заспиш вечер?", "gancho", "arriba")


def test_componer_tamano_exacto(fuentes):
    img = componer(CFG, PALETA, _guion([GANCHO, Bloque("само 13,90 €", "precio", "abajo")]), {}, fuentes)
    assert img.size == (1080, 1350) and img.mode == "RGB"


def test_texto_largo_reduce_cuerpo(fuentes):
    corto = estaticos._ajustar("Сън", fuentes["titulos"], 96, 936, 400)[0].size
    largo = estaticos._ajustar("Методът ти помага да заспиш спокойно и без хапчета всяка вечер " * 3,
                               fuentes["titulos"], 96, 936, 400)[0].size
    assert largo < corto


def test_texto_que_no_cabe(fuentes):
    with pytest.raises(TextoNoCabe):
        componer(CFG, PALETA, _guion([Bloque("дума " * 400, "gancho", "arriba")]), {}, fuentes)


def test_contraste_bajo_pone_banda(fuentes, tmp_path):
    oscuro = tmp_path / "oscuro.png"
    oscuro.write_bytes(png(800, 1000, (25, 35, 50)))  # casi el color del texto
    img = componer(CFG, PALETA, _guion([GANCHO], "escena", "e01", "escena"), {"e01": oscuro}, fuentes)
    pixel = img.getpixel((60, 1350 // 3 // 2))  # dentro de la banda, fuera de las letras
    assert contraste(pixel, (30, 42, 56)) >= 4.5


def test_fondo_cover_sin_deformar():
    ancho = Image.new("RGB", (2000, 500), (10, 200, 10))
    out = cubrir(ancho, (1080, 1350))
    assert out.size == (1080, 1350)


def test_glifo_faltante_no_escribe(fuentes, monkeypatch):
    monkeypatch.setattr(estaticos, "glifos_faltantes", lambda texto, ruta: {"ж"})
    with pytest.raises(ValueError, match="tofu"):
        componer(CFG, PALETA, _guion([GANCHO]), {}, fuentes)


def test_ficha_solo_de_medios_propios(fuentes):
    with pytest.raises(ValueError, match="no es un medio propio"):
        componer(CFG, PALETA, _guion([GANCHO], "ficha", "anuncio-ajeno", "ficha_del_producto"), {}, fuentes)


def test_jpeg_sin_exif_y_0640(tmp_path, fuentes):
    carpeta = tmp_path / "productos" / "p" / "creativos" / "ZZ" / "t1"
    ruta, _ = escribir_estatico(tmp_path, carpeta, "AD01", componer(CFG, PALETA, _guion([GANCHO]), {}, fuentes))
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o640
    with Image.open(io.BytesIO(ruta.read_bytes())) as img:
        assert img.format == "JPEG" and not img.getexif()


def test_registra_origen_propio(tmp_path, fuentes):
    carpeta = tmp_path / "productos" / "p" / "creativos" / "ZZ" / "t1"
    _, sha = escribir_estatico(tmp_path, carpeta, "AD01", componer(CFG, PALETA, _guion([GANCHO]), {}, fuentes))
    m = leer_manifiesto(carpeta, carpeta=".", verificar=True)
    assert m["ad01"]["origen"] == "propio" and m["ad01"]["sha256"] == sha and m["ad01"]["archivo"] == "AD01.jpg"
