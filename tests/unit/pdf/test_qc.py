import shutil
import stat
import subprocess
from pathlib import Path

import pytest
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


def _sin_weasy() -> str | None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:
        return f"WeasyPrint no disponible ({exc})"
    if shutil.which("pdftoppm") is None:
        return "falta pdftoppm (poppler-utils)"
    return None


necesita_pdf = pytest.mark.skipif(_sin_weasy() is not None, reason=_sin_weasy() or "")


@pytest.fixture
def pdf_3pag(tmp_path) -> Path:
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


@necesita_pdf
def test_hoja_de_contactos_cuadricula(pdf_3pag):
    from PIL import ImageChops

    destino = ruta_contactos(pdf_3pag.parent, 1)
    assert hoja_de_contactos(pdf_3pag, destino) == destino
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
    hoja_de_contactos(pdf_3pag, destino, paginas=[2])
    im = _imagen(destino)
    miniatura = im.size[0] // COLUMNAS
    # una sola miniatura: la página 2 (fondo claro) en la primera celda; el resto de la fila en blanco
    assert im.getpixel((miniatura // 2, (im.size[1] - BANDA) // 2)) == (250, 247, 242)
    assert im.getpixel((miniatura + miniatura // 2, (im.size[1] - BANDA) // 2)) == (255, 255, 255)


@necesita_pdf
def test_pagina_que_no_existe(pdf_3pag, tmp_path):
    with pytest.raises(ValueError, match="9"):
        hoja_de_contactos(pdf_3pag, tmp_path / "qc" / "x.png", paginas=[9])


@pytest.mark.parametrize("paginas", [[], [0], [-1], [True], ["2"]])
def test_paginas_invalidas(tmp_path, paginas):
    with pytest.raises(ValueError):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", paginas=paginas,
                          correr=lambda *a, **k: pytest.fail("no debe ejecutar pdftoppm"))


def test_sin_pdftoppm(tmp_path):
    def correr(args, **kw):
        raise FileNotFoundError(args[0])

    with pytest.raises(QcNoDisponible) as exc:
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", correr=correr)
    assert str(exc.value) == "no medido: falta pdftoppm (sudo apt install -y poppler-utils)"
    assert not (tmp_path / "qc" / "x.png").exists()


def test_pdftoppm_falla(tmp_path):
    def correr(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Syntax Error: no es un PDF")

    with pytest.raises(ValueError, match="no es un PDF"):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", correr=correr)


def test_pdftoppm_argumentos(tmp_path):
    llamadas = []

    def correr(args, **kw):
        llamadas.append(list(args))
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="x")

    with pytest.raises(ValueError):
        hoja_de_contactos(tmp_path / "a.pdf", tmp_path / "qc" / "x.png", paginas=[2], correr=correr)
    args = llamadas[0]
    assert args[:4] == ["pdftoppm", "-r", "40", "-png"] and args[4:8] == ["-f", "2", "-l", "2"]
    assert args[8] == str(tmp_path / "a.pdf")
