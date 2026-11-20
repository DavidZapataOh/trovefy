"""Hoja de contactos para el ``revisor`` y textos para el ``nativo`` (plan 21, Tarea 10).

El dueño mira los anuncios antes de prenderlos (C1 31:26); la revisión independiente en otro contexto la piden
§4.12 y la idea de by-lua. ``hoja_contactos`` deja ``qc/contactos-t<N>-v<K>.png`` (nunca pisa: la siguiente K
libre): una celda por estático y 4 fotogramas por vídeo (0 s, 3 s, la mitad y el final − 2 s) con su segundo, cada
celda con su ``ADnn`` y su uso. ``textos_html`` deja ``qc/textos-t<N>-v<K>.html`` con una ``<section id="ad-NN">``
por anuncio. Los veredictos se anotan en ``QA.md`` atados a la huella de la tanda.
"""

from __future__ import annotations

import html
import io
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from trovefy.creativos import registro
from trovefy.creativos.brief import FichaTanda
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import Contexto, numero_tanda
from trovefy.creativos.guion import GuionVideo, cargar_guion
from trovefy.creativos.video import duracion_audio, fotogramas, segundos_hoja
from trovefy.producto.medios import escribir_medio
from trovefy.producto.qc_registro import parsear_veredicto
from trovefy.secretos import buscar_secreto

CELDA_IMG = (216, 270)
CELDA_VID = (144, 256)
ROTULO = 34
_VERSION = re.compile(r"(?:contactos|textos)-t\d+-v(\d+)\.(?:png|html)")


def _siguiente(qc: Path, prefijo: str, tanda: str) -> int:
    usadas = [int(m.group(1)) for p in qc.glob(f"{prefijo}-{tanda}-v*.*") if (m := _VERSION.fullmatch(p.name))]
    return max(usadas, default=0) + 1


def _fuente(tam: int):
    try:
        return ImageFont.load_default(tam)
    except TypeError:  # Pillow antiguo
        return ImageFont.load_default()


def _miniatura(img: Image.Image, tam: tuple[int, int]) -> Image.Image:
    from PIL import ImageOps

    return ImageOps.fit(img.convert("RGB"), tam)


def hoja_contactos(vault: Path, carpeta: Path, ficha: FichaTanda, *, duracion: Callable[[Path], float] = duracion_audio,
                   extraer: Callable[[Path, list[float], Path, str], list[Path]] = fotogramas) -> Path:
    qc = Path(carpeta) / "qc"
    qc.mkdir(parents=True, exist_ok=True)
    filas = []
    for e in ficha.elegidos:
        tipo = ficha.brief(e.ad).tipo
        ruta = registro.archivo_pieza(carpeta, e.ad, tipo)
        if not ruta.is_file():
            raise FileNotFoundError(f"falta {ruta.name}: produce la pieza antes de la hoja de contactos")
        if tipo == "imagen":
            with Image.open(ruta) as img:
                filas.append((e, [(_miniatura(img, CELDA_IMG), "")]))
        else:
            segs = segundos_hoja(duracion(ruta))
            fotos = extraer(ruta, segs, qc / ".fotogramas", e.ad)
            celdas = []
            for f, s in zip(fotos, segs, strict=True):
                with Image.open(f) as img:
                    celdas.append((_miniatura(img, CELDA_VID), f"{s:g} s"))
            filas.append((e, celdas))
    ancho = 24 + max(sum(c[0].width + 12 for c in celdas) for _, celdas in filas) + 24
    alto = 24 + sum(max(c[0].height for c in celdas) + ROTULO * 2 + 16 for _, celdas in filas)
    hoja = Image.new("RGB", (max(ancho, 700), alto), (250, 250, 250))
    d = ImageDraw.Draw(hoja)
    f_tit, f_seg = _fuente(24), _fuente(18)
    y = 24
    for e, celdas in filas:
        d.text((24, y), f"{e.ad} · {e.uso} · {ficha.brief(e.ad).formato}", fill=(20, 20, 20), font=f_tit)
        y += ROTULO
        x = 24
        for img, rot in celdas:
            hoja.paste(img, (x, y))
            if rot:
                d.text((x, y + img.height + 4), rot, fill=(60, 60, 60), font=f_seg)
            x += img.width + 12
        y += max(c[0].height for c in celdas) + ROTULO + 16
    buf = io.BytesIO()
    hoja.save(buf, "PNG")
    n = numero_tanda(Path(carpeta).name)
    destino = qc / f"contactos-t{n}-v{_siguiente(qc, 'contactos', f't{n}')}.png"
    escribir_medio(destino, buf.getvalue(), base=Path(vault))
    return destino


def textos_html(vault: Path, ctx: Contexto, carpeta: Path, ficha: FichaTanda, cfg: ConfigCreativos) -> Path:
    e_ = html.escape
    partes = [f'<!doctype html><html lang="{e_(ctx.idioma)}"><meta charset="utf-8"><title>{e_(ficha.tanda)}</title>',
              "<body>"]
    for el in ficha.elegidos:
        b = ficha.brief(el.ad)
        n = el.ad[2:]
        bloque = [f'<section id="ad-{n}">', f"<h2>{e_(ficha.nombre(el.ad))}</h2>",
                  f"<p class=\"texto\">{e_(b.texto)}</p>", f"<p class=\"titulo\">{e_(b.titulo)}</p>",
                  f"<p class=\"descripcion\">{e_(b.descripcion)}</p>", f"<p class=\"gancho\">{e_(b.gancho)}</p>"]
        if b.tipo == "video":
            g = cargar_guion(carpeta, el.ad, "video", cfg)
            assert isinstance(g, GuionVideo)
            bloque += [f"<p class=\"subtitulos\">{e_(p.texto_pantalla)}</p>" for p in g.partes if p.texto_pantalla]
            bloque.append(f"<p class=\"voz\">{e_(g.texto_voz)}</p>")
        else:
            g = cargar_guion(carpeta, el.ad, "imagen", cfg) if (Path(carpeta) / "guiones" / f"{el.ad}.yaml").is_file() \
                else None
            if g is not None:
                bloque += [f"<p class=\"bloque\">{e_(x.texto)}</p>" for x in g.bloques]
        bloque.append("</section>")
        partes += bloque
    partes.append("</body></html>")
    texto = "\n".join(partes) + "\n"
    if buscar_secreto(texto):
        raise ValueError("los textos traen algo con forma de secreto; no se escribe el HTML")
    qc = Path(carpeta) / "qc"
    qc.mkdir(parents=True, exist_ok=True)
    tn = f"t{numero_tanda(Path(carpeta).name)}"
    destino = qc / f"textos-{tn}-v{_siguiente(qc, 'textos', tn)}.html"
    with open(destino, "x", encoding="utf-8") as f:  # nunca pisa
        f.write(texto)
    destino.chmod(0o640)
    return destino


def anotar_agente(carpeta: Path, piezas: list[tuple[str, str]], agente: Literal["revisor", "nativo"], texto: str,
                  version: str, ahora: datetime) -> Literal["ok", "corregir"]:
    """Anota la respuesta citada del agente sobre la huella actual. Una respuesta que se contradice no vale."""
    if agente not in ("revisor", "nativo"):
        raise ValueError("el agente es revisor o nativo")
    veredicto = parsear_veredicto(texto)
    if veredicto is None:
        raise ValueError("la respuesta del agente no vale como veredicto: debe terminar en una sola línea "
                         "«VEREDICTO: ok» o «VEREDICTO: corregir», sin líneas «- » si dice ok")
    clave = "hoja" if agente == "revisor" else "textos"
    registro.anotar(carpeta, agente, {"huella": registro.huella(carpeta, piezas), "estado": veredicto,
                                      clave: version}, texto, ahora)
    return veredicto
