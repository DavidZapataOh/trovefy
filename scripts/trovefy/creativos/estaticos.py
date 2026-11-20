"""Estáticos 1080×1350 compuestos con Pillow (plan 21, Tarea 5).

Paleta y tipografías del brandbook (títulos con ``uso: titulos``, texto con ``uso: texto``); ningún bloque se sale
(se baja el cuerpo hasta un mínimo; si ni así cabe, ``TextoNoCabe``); contraste WCAG ≥ 4,5:1 sobre el color medio de
la zona (si no llega, una banda de color de la paleta detrás del texto); fondo recortado «cover» sin deformar.
``ficha``, ``mockup`` y ``portada`` usan solo medios propios del entregable; ``escena``, una escena de la tanda;
el tipográfico, ninguna imagen. Una letra que la fuente no tiene (tofu) para todo antes de escribir.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.guion import Bloque, GuionEstatico
from trovefy.pdf.fuentes import glifos_faltantes
from trovefy.producto.medios import escribir_medio, registrar_medio

CUERPOS = {"gancho": 96, "precio": 72, "apoyo": 52, "cta": 48}
CUERPO_MIN = 30
MARGEN = 72
CONTRASTE_MIN = 4.5
INTERLINEA = 1.18


class TextoNoCabe(ValueError):
    pass


def _rgb(color: str | None, defecto: tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
        try:
            return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
        except ValueError:
            pass
    return defecto


def _luminancia(c: tuple[int, int, int]) -> float:
    def canal(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def colores(paleta: dict) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """(fondo, texto, acento) de la paleta del brandbook, con claves habituales y valores por defecto sobrios."""
    def buscar(*claves: str) -> str | None:
        for k in claves:
            for nombre, v in paleta.items():
                if k in str(nombre).lower():
                    return v
        return None
    fondo = _rgb(buscar("fondo", "background", "base", "claro"), (245, 240, 232))
    texto = _rgb(buscar("texto", "text", "oscuro", "primario"), (30, 30, 30))
    acento = _rgb(buscar("acento", "accent", "cta", "secundario"), (200, 85, 61))
    return fondo, texto, acento


def cubrir(img: Image.Image, tam: tuple[int, int]) -> Image.Image:
    """Recorte «cover»: escala para cubrir y recorta al centro, sin deformar."""
    return ImageOps.fit(img.convert("RGB"), tam, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _partir(texto: str, fuente: ImageFont.FreeTypeFont, ancho: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if fuente.getlength(prueba) <= ancho:
            actual = prueba
            continue
        if not actual or fuente.getlength(palabra) > ancho:
            raise TextoNoCabe(f"«{palabra}» no cabe en una línea")
        lineas.append(actual)
        actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _ajustar(texto: str, ruta_fuente: Path, cuerpo: int, ancho: int, alto: int
             ) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    while cuerpo >= CUERPO_MIN:
        fuente = ImageFont.truetype(str(ruta_fuente), cuerpo)
        try:
            lineas = _partir(texto, fuente, ancho)
        except TextoNoCabe:
            lineas = None
        if lineas is not None:
            alto_txt = int(len(lineas) * cuerpo * INTERLINEA)
            if alto_txt <= alto:
                return fuente, lineas, alto_txt
        cuerpo -= 4
    raise TextoNoCabe(f"el texto «{texto[:40]}…» no cabe ni con cuerpo {CUERPO_MIN}: acórtalo")


def componer(cfg: ConfigCreativos, paleta: dict, guion: GuionEstatico, medios: dict[str, Path],
             fuentes: dict[str, Path]) -> Image.Image:
    """El estático en ``cfg.imagen_ancho × cfg.imagen_alto``. ``medios``: id → archivo propio (entregable o tanda);
    ``fuentes``: ``titulos`` y ``texto`` → archivo de la tipografía del brandbook."""
    w, h = cfg.imagen_ancho, cfg.imagen_alto
    fondo, color_texto, acento = colores(paleta)
    lienzo = Image.new("RGB", (w, h), fondo)
    if guion.fondo_tipo != "color":
        ruta = medios.get(guion.fondo_ref or "")
        if ruta is None:
            raise ValueError(f"{guion.ad}: el fondo «{guion.fondo_ref}» no es un medio propio (entregable o escenas)")
        with Image.open(ruta) as img:
            lienzo = cubrir(img, (w, h))
    for b in guion.bloques:
        ruta = fuentes["titulos" if b.rol == "gancho" else "texto"]
        faltan = glifos_faltantes(b.texto, ruta)
        if faltan:
            raise ValueError(f"{guion.ad}: la fuente {Path(ruta).name} no tiene {''.join(sorted(faltan))} (tofu)")
    zonas = {"arriba": (MARGEN, h // 3), "centro": (h // 3, 2 * h // 3), "abajo": (2 * h // 3, h - MARGEN)}
    dibujo = ImageDraw.Draw(lienzo)
    for posicion, (y0, y1) in zonas.items():
        bloques = [b for b in guion.bloques if b.posicion == posicion]
        if not bloques:
            continue
        hueco = (y1 - y0) // len(bloques)
        y = y0
        for b in bloques:
            _pintar(lienzo, dibujo, b, fuentes, w, y, hueco, color_texto, fondo, acento)
            y += hueco
    return lienzo


def _pintar(lienzo: Image.Image, dibujo: ImageDraw.ImageDraw, b: Bloque, fuentes: dict[str, Path], w: int, y: int,
            hueco: int, color_texto, fondo, acento) -> None:
    ancho = w - 2 * MARGEN
    fuente, lineas, alto = _ajustar(b.texto, fuentes["titulos" if b.rol == "gancho" else "texto"],
                                    CUERPOS[b.rol], ancho, hueco - 16)
    top = y + (hueco - alto) // 2
    caja = (MARGEN - 24, top - 16, w - MARGEN + 24, top + alto + 16)
    zona = lienzo.crop(caja).resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    color = color_texto if b.rol != "cta" else fondo
    if b.rol == "cta":
        dibujo.rounded_rectangle(caja, radius=24, fill=acento)
        zona = acento
    if contraste(color, zona) < CONTRASTE_MIN:
        banda = max((fondo, color_texto, acento), key=lambda c: contraste(color, c))
        if contraste(color, banda) < CONTRASTE_MIN:
            color = max(((255, 255, 255), (0, 0, 0)), key=lambda c: contraste(c, banda))
        dibujo.rectangle(caja, fill=banda)
    cuerpo = fuente.size
    for i, linea in enumerate(lineas):
        lx = (w - fuente.getlength(linea)) / 2
        dibujo.text((lx, top + i * cuerpo * INTERLINEA), linea, font=fuente, fill=color)


def jpeg(img: Image.Image) -> bytes:
    """JPEG calidad 90, sRGB, sin metadatos."""
    limpio = Image.new("RGB", img.size)
    limpio.paste(img.convert("RGB"))
    buf = io.BytesIO()
    limpio.save(buf, "JPEG", quality=90, optimize=True)
    return buf.getvalue()


def escribir_pieza(vault: Path, carpeta: Path, ad: str, datos: bytes, extension: str, **extra) -> tuple[Path, str]:
    """``<tanda>/ADnn.<ext>`` en 0640 y registrado en el ``medios.json`` de la tanda (``origen: propio``)."""
    ruta = Path(carpeta) / f"{ad}.{extension}"
    sha = escribir_medio(ruta, datos, base=Path(vault))
    registrar_medio(Path(carpeta), ad.lower(), ruta.name, sha, "propio", base=Path(vault), carpeta=".", **extra)
    return ruta, sha


def escribir_estatico(vault: Path, carpeta: Path, ad: str, img: Image.Image) -> tuple[Path, str]:
    return escribir_pieza(vault, carpeta, ad, jpeg(img), "jpg", tipo="imagen")
