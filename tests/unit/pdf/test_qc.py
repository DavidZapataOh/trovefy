import stat
import subprocess
from pathlib import Path

import pytest
from fixtures.pdf.herramientas import faltan, requerir
from trovefy.pdf.qc import (
    BANDA,
    COLUMNAS,
    DPI_CONTACTOS,
    QcNoDisponible,
    hoja_de_contactos,
    ruta_contactos,
)

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "pdf" / "contactos-3pag.png"
# Tolerancia del golden: fracción de píxeles que pueden cambiar (antialiasing de otra versión de poppler).
TOLERANCIA = 0.02
HTML_3PAG = """<html><head><style>
@page{size:A4;margin:0}
div{height:296.8mm;break-after:page;box-sizing:border-box;border:12mm solid}
.a{background:#1F4E5F;border-color:#F2C14E}.b{background:#FAF7F2;border-color:#1F4E5F}.c{background:#F2C14E;border-color:#FAF7F2}
</style></head><body><div class="a"></div><div class="b"></div><div class="c"></div></body></html>"""


_SIN_PDF = faltan("pdftoppm", weasyprint=True)


@pytest.fixture
def _herramientas_pdf():
    requerir(_SIN_PDF)  # con CI definido, falla en vez de saltar (ruling L7)


necesita_pdf = pytest.mark.usefixtures("_herramientas_pdf")


@pytest.fixture
def pdf_3pag(tmp_path, _herramientas_pdf) -> Path:
    import weasyprint

    ruta = tmp_path / "entregable" / "respira-es-v1.pdf"
    ruta.parent.mkdir(parents=True)
    weasyprint.HTML(string=HTML_3PAG).write_pdf(ruta)
    return ruta


def _imagen(ruta: Path):
    from PIL import Image

    with Image.open(ruta) as im:
        return im.convert("RGB")


def test_constantes():
    assert (COLUMNAS, DPI_CONTACTOS) == (6, 40)


def test_ruta_contactos(tmp_path):
    assert ruta_contactos(tmp_path, 3) == tmp_path / "qc" / "contactos-v3.png"
    assert ruta_contactos(tmp_path, 3, relectura=True).name == "contactos-v3-r1.png"
    (tmp_path / "qc").mkdir()
    (tmp_path / "qc" / "contactos-v3-r1.png").write_bytes(b"x")
    (tmp_path / "qc" / "contactos-v3-r2.png").write_bytes(b"x")
    assert ruta_contactos(tmp_path, 3, relectura=True).name == "contactos-v3-r3.png"
    with pytest.raises(ValueError):
        ruta_contactos(tmp_path, 0)


def test_ruta_contactos_repetida_no_pisa(tmp_path):
    """Repetir la hoja completa de una versión va a la siguiente ``-rK`` libre (ruling L1)."""
    (tmp_path / "qc").mkdir()
    (tmp_path / "qc" / "contactos-v3.png").write_bytes(b"x")
    assert ruta_contactos(tmp_path, 3).name == "contactos-v3-r1.png"
    (tmp_path / "qc" / "contactos-v3-r1.png").write_bytes(b"x")
    assert ruta_contactos(tmp_path, 3).name == "contactos-v3-r2.png"
    assert ruta_contactos(tmp_path, 4).name == "contactos-v4.png"


def test_ruta_contactos_cuenta_enlaces_colgantes(tmp_path):
    (tmp_path / "qc").mkdir()
    (tmp_path / "qc" / "contactos-v1.png").symlink_to(tmp_path / "no-existe.png")
    assert ruta_contactos(tmp_path, 1).name == "contactos-v1-r1.png"


@necesita_pdf
def test_hoja_completa_repetida_no_sobrescribe(pdf_3pag):
    raiz, vault = pdf_3pag.parent, pdf_3pag.parent.parent
    primera = hoja_de_contactos(pdf_3pag, ruta_contactos(raiz, 1), base=vault)
    antes = primera.read_bytes()
    segunda = hoja_de_contactos(pdf_3pag, ruta_contactos(raiz, 1), base=vault)
    assert (primera.name, segunda.name) == ("contactos-v1.png", "contactos-v1-r1.png")
    assert primera.read_bytes() == antes


@necesita_pdf
def test_destino_que_ya_existe_no_se_pisa(pdf_3pag):
    destino = pdf_3pag.parent / "qc" / "contactos-v1.png"
    destino.parent.mkdir()
    destino.write_bytes(b"anterior")
    with pytest.raises(FileExistsError):
        hoja_de_contactos(pdf_3pag, destino, base=pdf_3pag.parent.parent)
    assert destino.read_bytes() == b"anterior"


@necesita_pdf
def test_carpeta_qc_enlazada_no_escribe_fuera(pdf_3pag, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (pdf_3pag.parent / "qc").symlink_to(fuera, target_is_directory=True)
    with pytest.raises(ValueError, match="enlace simbólico"):
        hoja_de_contactos(pdf_3pag, ruta_contactos(pdf_3pag.parent, 1), base=pdf_3pag.parent.parent)
    assert list(fuera.iterdir()) == []


@necesita_pdf
def test_hoja_de_contactos_cuadricula(pdf_3pag):
    from PIL import ImageChops

    destino = ruta_contactos(pdf_3pag.parent, 1)
    assert hoja_de_contactos(pdf_3pag, destino, base=pdf_3pag.parent.parent) == destino
    assert stat.S_IMODE(destino.stat().st_mode) == 0o640
    im = _imagen(destino)
    ancho, alto = im.size
    assert ancho % COLUMNAS == 0 and 329 <= ancho // COLUMNAS <= 333  # A4 a 40 ppp: 210 mm ≈ 331 px
    assert 466 <= alto - BANDA <= 470  # una fila: 297 mm ≈ 468 px + la banda del número
    golden = _imagen(GOLDEN)
    assert golden.size == im.size
    diferencia = ImageChops.difference(im, golden).convert("L").point(lambda v: 255 if v > 24 else 0)
    distintos = sum(diferencia.histogram()[255:])
    assert distintos / (ancho * alto) < TOLERANCIA


@necesita_pdf
def test_relectura_solo_paginas_tocadas(pdf_3pag):
    destino = ruta_contactos(pdf_3pag.parent, 1, relectura=True)
    assert destino.name == "contactos-v1-r1.png"
    hoja_de_contactos(pdf_3pag, destino, paginas=[2], base=pdf_3pag.parent.parent)
    im = _imagen(destino)
    miniatura = im.size[0] // COLUMNAS
    # una sola miniatura: la página 2 (fondo claro) en la primera celda; el resto de la fila en blanco
    assert im.getpixel((miniatura // 2, (im.size[1] - BANDA) // 2)) == (250, 247, 242)
    assert im.getpixel((miniatura + miniatura // 2, (im.size[1] - BANDA) // 2)) == (255, 255, 255)


@necesita_pdf
def test_pagina_que_no_existe(pdf_3pag, tmp_path):
    with pytest.raises(ValueError, match="9"):
        hoja_de_contactos(pdf_3pag, tmp_path / "qc" / "x.png", paginas=[9], base=tmp_path)


@pytest.mark.parametrize("paginas", [[], [0], [-1], [True], ["2"]])
def test_paginas_invalidas(tmp_path, paginas):
    with pytest.raises(ValueError):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", paginas=paginas,
                          correr=lambda *a, **k: pytest.fail("no debe ejecutar pdftoppm"), base=tmp_path)


def test_sin_pdftoppm(tmp_path):
    def correr(args, **kw):
        raise FileNotFoundError(args[0])

    with pytest.raises(QcNoDisponible) as exc:
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", correr=correr, base=tmp_path)
    assert str(exc.value) == "no medido: falta pdftoppm (sudo apt install -y poppler-utils)"
    assert not (tmp_path / "qc" / "x.png").exists()


def test_pdftoppm_falla(tmp_path):
    def correr(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Syntax Error: no es un PDF")

    with pytest.raises(ValueError, match="no es un PDF"):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", correr=correr, base=tmp_path)


def test_pdftoppm_argumentos(tmp_path):
    llamadas = []

    def correr(args, **kw):
        llamadas.append(list(args))
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="x")

    with pytest.raises(ValueError):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", paginas=[2], correr=correr, base=tmp_path)
    args = llamadas[0]
    assert args[:4] == ["pdftoppm", "-r", "40", "-png"] and args[4:8] == ["-f", "2", "-l", "2"]
    assert args[8] == str(tmp_path / "a.pdf")
