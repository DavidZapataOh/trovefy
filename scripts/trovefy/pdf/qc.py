"""QC visual del PDF: hoja de contactos con ``pdftoppm`` + Pillow (§4.7).

Una cuadrícula de 6 columnas con cada página a 40 ppp y su número debajo, para que Claude (y el
usuario) vean de un vistazo el ritmo de la maqueta: páginas vacías, desbordes, portada. Se escribe en
0640 (contrato 10) en ``qc/contactos-vN.png``; una relectura de solo las páginas tocadas, o repetir la
hoja completa de la misma versión, va a la siguiente ``qc/contactos-vN-rK.png`` libre: nunca se pisa
una hoja (``render.escribir_exclusivo``, carpetas revisadas desde el vault). La vista previa para la
landing es del plan 18 (resolución 16).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from trovefy.pdf.render import escribir_exclusivo

COLUMNAS = 6
DPI_CONTACTOS = 40  # miniatura de una página A4 (≈ 331 × 468 px); fuente: plan 17, Tarea 10
BANDA = 18  # px bajo cada miniatura para su número de página
NO_PDFTOPPM = "no medido: falta pdftoppm (sudo apt install -y poppler-utils)"
_BLANCO = (255, 255, 255)
_TINTA = (60, 60, 60)
_SALIDA = re.compile(r"p-(\d+)\.png")


class QcNoDisponible(RuntimeError):
    """Falta ``pdftoppm`` (poppler-utils)."""


def _ocupada(ruta: Path) -> bool:
    return os.path.lexists(ruta)  # un enlace colgante también ocupa el nombre


def ruta_contactos(raiz: Path, version: int, relectura: bool = False) -> Path:
    """``<raíz>/qc/contactos-vN.png`` si está libre y no es ``relectura``; si no, el siguiente
    ``contactos-vN-rK.png`` libre (ruling L1: repetir la hoja completa nunca pisa la anterior)."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"versión mal escrita: «{version}»")
    carpeta = Path(raiz) / "qc"
    completa = carpeta / f"contactos-v{version}.png"
    if not relectura and not _ocupada(completa):
        return completa
    k = 1
    while _ocupada(carpeta / f"contactos-v{version}-r{k}.png"):
        k += 1
    return carpeta / f"contactos-v{version}-r{k}.png"


def _validar_paginas(paginas: list[int] | None) -> list[int] | None:
    if paginas is None:
        return None
    if not isinstance(paginas, list) or not paginas or not all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in paginas):
        raise ValueError(f"páginas mal escritas: {paginas!r} (lista de números desde 1)")
    return sorted(set(paginas))


def _pdftoppm(pdf: Path, carpeta: Path, pagina: int | None, correr) -> None:
    args = ["pdftoppm", "-r", str(DPI_CONTACTOS), "-png"]
    if pagina is not None:
        args += ["-f", str(pagina), "-l", str(pagina)]
    args += [str(pdf), str(carpeta / "p")]
    try:
        r = correr(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise QcNoDisponible(NO_PDFTOPPM) from None
    if r.returncode != 0:
        raise ValueError(f"pdftoppm no pudo leer {Path(pdf).name}: {(r.stderr or '').strip()[:300]}")


def _miniaturas(pdf: Path, paginas: list[int] | None, correr) -> list[tuple[int, object]]:
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="trovefy-qc-") as tmp:
        carpeta = Path(tmp)
        for pagina in paginas or [None]:
            _pdftoppm(pdf, carpeta, pagina, correr)
        salida = {}
        for f in carpeta.iterdir():
            m = _SALIDA.fullmatch(f.name)
            if m:
                with Image.open(f) as im:
                    salida[int(m.group(1))] = im.convert("RGB")
    if paginas is not None:
        faltan = [n for n in paginas if n not in salida]
        if faltan:
            raise ValueError(f"el PDF no tiene la página {', '.join(map(str, faltan))}")
    if not salida:
        raise ValueError(f"pdftoppm no sacó ninguna página de {Path(pdf).name}")
    return sorted(salida.items())


def hoja_de_contactos(pdf: Path, destino: Path, paginas: list[int] | None = None,
                      correr=subprocess.run, *, base: Path) -> Path:
    """Cuadrícula de ``COLUMNAS`` miniaturas (todas las páginas, o solo ``paginas``) con su número debajo.
    Crea ``destino`` en 0640 y lo devuelve. ``base`` es el vault: ninguna carpeta entre él y ``destino``
    puede ser un enlace (``ValueError``). ``FileExistsError`` si ``destino`` ya existe (pide la ruta a
    ``ruta_contactos``). ``QcNoDisponible`` si falta ``pdftoppm``."""
    paginas = _validar_paginas(paginas)
    from PIL import Image, ImageDraw, ImageFont

    miniaturas = _miniaturas(Path(pdf), paginas, correr)
    ancho = max(im.size[0] for _, im in miniaturas)
    alto = max(im.size[1] for _, im in miniaturas)
    filas = -(-len(miniaturas) // COLUMNAS)
    hoja = Image.new("RGB", (COLUMNAS * ancho, filas * (alto + BANDA)), _BLANCO)
    dibujo = ImageDraw.Draw(hoja)
    letra = ImageFont.load_default()
    for i, (numero, im) in enumerate(miniaturas):
        x, y = (i % COLUMNAS) * ancho, (i // COLUMNAS) * (alto + BANDA)
        hoja.paste(im, (x, y))
        dibujo.text((x + ancho // 2, y + alto + BANDA // 2), str(numero), fill=_TINTA, font=letra, anchor="mm")
    buf = BytesIO()
    hoja.save(buf, format="PNG", optimize=True)
    escribir_exclusivo(Path(destino), buf.getvalue(), base=Path(base))
    return Path(destino)
