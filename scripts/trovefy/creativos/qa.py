"""QA automática de la tanda (plan 21, Tarea 8): el anunciante «mira el anuncio antes de entregarlo» (L2 15:25).

Cada regla tiene nombre (``cantidad``, ``mezcla``, ``archivo``, ``imagen``, ``video``, ``texto``, ``idioma``,
``precio``, ``url``, ``cta``, ``nombre``, ``meta``, ``secreto``, ``coste``) y dice si bloquea. Un archivo de la
tanda que no esté en su ``medios.json`` con un origen propio no vale (nada ajeno). Un vídeo sin voz o sin música
es un fallo (L2 15:25), no un «no aplica».
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from trovefy.apimart.gasto import gastado_usd, leer_costes
from trovefy.creativos import coste, registro
from trovefy.creativos.brief import _ALFABETO, BriefInvalido, FichaTanda, validar_brief
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import Contexto
from trovefy.creativos.guion import GuionInvalido, GuionVideo, cargar_guion
from trovefy.creativos.video import VideoInvalido, sondear
from trovefy.idioma import detectar
from trovefy.landing.diacriticos import revisar_texto
from trovefy.producto.medios import MODO_MEDIO, leer_manifiesto
from trovefy.secretos import buscar_secreto

MAX_IMAGEN = 30 * 2**20
MAX_VIDEO = 100 * 1024 * 1024  # = trovefy_ejecutor.montaje.MAX_VIDEO (subida simple a Meta)
ORIGENES = ("propio", "apimart", "elevenlabs")
CTA = re.compile(r"^[A-Z][A-Z0-9_]{0,59}$")
NOMBRE = re.compile(r"^AD\d{2} G\d+ .{1,30}$")
_PRECIO_CIFRAS = re.compile(r"\d+[,.]\d{2}")
SILENCIO_DB = -60.0
_MAX_VOL = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")


@dataclass(frozen=True)
class Hallazgo:
    ad: str | None
    regla: str
    texto: str
    bloquea: bool


def volumen_max(ruta: Path, correr=subprocess.run) -> float | None:
    """Volumen máximo de la pista de audio (``volumedetect``); ``None`` si no se pudo medir."""
    p = correr(["ffmpeg", "-hide_banner", "-nostats", "-i", str(ruta), "-af", "volumedetect", "-vn", "-f", "null",
                "-"], capture_output=True, text=True, timeout=300, check=False)
    m = _MAX_VOL.search(p.stderr or "")
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


def _archivo(carpeta: Path, ad: str, tipo: str, manifiesto: dict, h: list[Hallazgo]) -> Path | None:
    ruta = registro.archivo_pieza(carpeta, ad, tipo)
    try:
        info = os.lstat(ruta)
    except FileNotFoundError:
        h.append(Hallazgo(ad, "archivo", f"falta {ruta.name}", True))
        return None
    if not stat.S_ISREG(info.st_mode):
        h.append(Hallazgo(ad, "archivo", f"{ruta.name} no es un archivo regular (¿un enlace?)", True))
        return None
    if stat.S_IMODE(info.st_mode) != MODO_MEDIO:
        h.append(Hallazgo(ad, "archivo", f"{ruta.name} tiene modo {stat.S_IMODE(info.st_mode):o}; debe ser 640", True))
    sha = registro.sha_archivo(ruta)
    entrada = manifiesto.get(ad.lower())
    if not entrada or entrada.get("sha256") != sha or entrada.get("archivo") != ruta.name \
            or entrada.get("origen") not in ORIGENES:
        h.append(Hallazgo(ad, "archivo", f"{ruta.name} no está en medios.json de la tanda con su sha256 y un origen "
                                         "propio: no sale de una orden de este plan", True))
    return ruta


def _imagen(ad: str, ruta: Path, cfg: ConfigCreativos, h: list[Hallazgo]) -> None:
    if ruta.stat().st_size > MAX_IMAGEN:
        h.append(Hallazgo(ad, "imagen", "pasa de 30 MB", True))
    with Image.open(ruta) as img:
        if img.format != "JPEG" or img.mode != "RGB":
            h.append(Hallazgo(ad, "imagen", f"{img.format} {img.mode}; debe ser JPEG RGB (sRGB)", True))
        if img.size != (cfg.imagen_ancho, cfg.imagen_alto):
            h.append(Hallazgo(ad, "imagen", f"mide {img.size[0]}×{img.size[1]}; debe medir "
                                            f"{cfg.imagen_ancho}×{cfg.imagen_alto}", True))


def _video(ad: str, ruta: Path, cfg: ConfigCreativos, h: list[Hallazgo], sondeo: Callable, volumen: Callable) -> None:
    try:
        info = sondeo(ruta)
    except (VideoInvalido, OSError, ValueError) as exc:
        h.append(Hallazgo(ad, "video", f"no se pudo leer: {exc}", True))
        return
    malos = []
    if (info.get("ancho"), info.get("alto")) != (cfg.video_ancho, cfg.video_alto):
        malos.append(f"mide {info.get('ancho')}×{info.get('alto')}")
    if info.get("codec") != "h264" or info.get("pix_fmt") != "yuv420p":
        malos.append(f"vídeo {info.get('codec')}/{info.get('pix_fmt')} (debe ser h264/yuv420p)")
    if info.get("audio") != "aac":
        malos.append("sin pista AAC: todos los vídeos llevan voz y música (L2 15:25)")
    dur = info.get("duracion") or 0
    if not cfg.duracion_s[0] - 0.5 <= dur <= cfg.duracion_s[1] + 0.5:
        malos.append(f"dura {dur:.1f} s (debe durar de {cfg.duracion_s[0]} a {cfg.duracion_s[1]} s)")
    if (info.get("bytes") or 0) > MAX_VIDEO:
        malos.append("pasa de 100 MB")
    if not info.get("faststart"):
        malos.append("sin +faststart")
    for m in malos:
        h.append(Hallazgo(ad, "video", m, True))
    if info.get("audio") == "aac":
        v = volumen(ruta)
        if v is None:
            h.append(Hallazgo(ad, "video", "no medido: volumen del audio", True))
        elif v <= SILENCIO_DB:
            h.append(Hallazgo(ad, "video", "la pista de audio es silencio: falta la voz y la música (L2 15:25)", True))


def _textos(ad: str, b, nombre: str, ctx: Contexto, cfg: ConfigCreativos, h: list[Hallazgo]) -> None:
    if len(b.texto) > cfg.principal_max:
        h.append(Hallazgo(ad, "texto", f"texto principal de {len(b.texto)} letras (máximo {cfg.principal_max})", True))
    if len(b.titulo) > cfg.titulo_max:
        h.append(Hallazgo(ad, "texto", f"título de {len(b.titulo)} letras (máximo {cfg.titulo_max})", True))
    if len(b.descripcion) > cfg.descripcion_max:
        h.append(Hallazgo(ad, "texto", f"descripción de {len(b.descripcion)} letras (máximo {cfg.descripcion_max})",
                          True))
    if b.gancho.casefold() not in b.texto[:cfg.principal_visible].casefold():
        h.append(Hallazgo(ad, "texto", f"el gancho no está en las primeras {cfg.principal_visible} letras", True))
    idioma = detectar(b.texto, list(cfg.idiomas_candidatos))
    if idioma is not None and idioma != ctx.idioma:
        h.append(Hallazgo(ad, "idioma", f"el texto parece {idioma}, no {ctx.idioma}", True))
    for t in (b.texto, b.titulo, b.descripcion):
        for x in revisar_texto(t, ctx.idioma):
            if x.regla in _ALFABETO:
                h.append(Hallazgo(ad, "idioma", x.detalle, True))
    if b.precio_dicho is not None and (ctx.precio_texto is None or ctx.precio_texto not in b.precio_dicho):
        h.append(Hallazgo(ad, "precio", f"«{b.precio_dicho}» no es {ctx.precio_texto or 'el precio (no medido)'}",
                          True))
    if not CTA.fullmatch(b.cta):
        h.append(Hallazgo(ad, "cta", f"«{b.cta}» no es un código de botón de Meta", True))
    if not NOMBRE.fullmatch(nombre) or len(nombre) > 60:
        h.append(Hallazgo(ad, "nombre", f"«{nombre}» no es «ADnn Gn <ángulo>» de 60 letras como mucho", True))
    lista = cfg.expresiones_riesgo.get(ctx.idioma)
    if lista is None:
        h.append(Hallazgo(ad, "meta", f"no medido: sin lista de expresiones de riesgo para {ctx.idioma} (la revisa el "
                                      "nativo)", False))
    else:
        for e in lista:
            if e.casefold() in f"{b.texto} {b.titulo} {b.descripcion}".casefold():
                h.append(Hallazgo(ad, "meta", f"«{e}» suele hacer que Meta rechace el anuncio (§4.12 paso 6)", True))


def revisar_tanda(vault: Path, ctx: Contexto, cfg: ConfigCreativos, ficha: FichaTanda, carpeta: Path, *,
                  renovacion=None, sondeo: Callable = sondear, volumen: Callable = volumen_max,
                  datos_brief: dict | None = None) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    if datos_brief is not None:
        try:
            validar_brief(datos_brief, ctx, cfg, carpeta=carpeta, renovacion=renovacion)
        except BriefInvalido as exc:
            h += [Hallazgo(None, "mezcla", m, True) for m in exc.motivos]
    if renovacion is None:
        if len(ficha.elegidos) != cfg.piezas:
            h.append(Hallazgo(None, "cantidad", f"{len(ficha.elegidos)} piezas; deben ser {cfg.piezas}", True))
        usos = [e.uso for e in ficha.elegidos]
        if usos.count("test") != cfg.al_test or usos.count("reserva") != cfg.reserva:
            h.append(Hallazgo(None, "cantidad", f"{usos.count('test')} test y {usos.count('reserva')} reserva; deben "
                                                f"ser {cfg.al_test} y {cfg.reserva}", True))
    try:
        manifiesto = leer_manifiesto(carpeta, carpeta=".")
    except ValueError as exc:
        manifiesto = {}
        h.append(Hallazgo(None, "archivo", f"medios.json de la tanda no se puede leer: {exc}", True))
    if not ctx.url_anuncio:
        h.append(Hallazgo(None, "url", "no medido: sin landing en PRODUCTO.md no hay URL del anuncio", True))
    textos = []
    for e in ficha.elegidos:
        b = ficha.brief(e.ad)
        ruta = _archivo(carpeta, e.ad, b.tipo, manifiesto, h)
        if ruta is not None and b.tipo == "imagen":
            _imagen(e.ad, ruta, cfg, h)
        if ruta is not None and b.tipo == "video":
            _video(e.ad, ruta, cfg, h, sondeo, volumen)
        if b.tipo == "video":
            try:
                g = cargar_guion(carpeta, e.ad, "video", cfg)
            except (GuionInvalido, FileNotFoundError) as exc:
                h.append(Hallazgo(e.ad, "video", f"guion: {exc}", True))
                g = None
            if isinstance(g, GuionVideo):
                if _PRECIO_CIFRAS.search(g.texto_voz):
                    h.append(Hallazgo(e.ad, "precio", "el guion de voz dice el precio en cifras: dilo en palabras, "
                                                      "como lo diría un nativo (L1 59:55)", True))
                textos.append(g.texto_voz)
        _textos(e.ad, b, ficha.nombre(e.ad), ctx, cfg, h)
        textos += [b.texto, b.titulo, b.descripcion]
    if buscar_secreto("\n".join(textos)):
        h.append(Hallazgo(None, "secreto", "un texto trae algo con forma de secreto", True))
    try:
        gastado = gastado_usd(leer_costes(vault, ctx.producto, carpeta))
        tope = coste.tope_vigente(vault, ctx.producto, ctx.pais, ficha.tanda, cfg)
        if gastado > tope:
            h.append(Hallazgo(None, "coste", f"gastado {gastado} USD sobre un tope de {tope} USD", True))
    except ValueError as exc:
        h.append(Hallazgo(None, "coste", f"no medido: el libro del gasto no se puede leer ({exc})", True))
    return h


def escribir_qa_auto(carpeta: Path, piezas: list[tuple[str, str]], hallazgos: list[Hallazgo],
                     ahora: datetime) -> Path:
    bloquean = [x for x in hallazgos if x.bloquea]
    texto = "\n".join(f"{'✗' if x.bloquea else '·'} {x.ad or 'tanda'} · {x.regla} · {x.texto}" for x in hallazgos)
    return registro.anotar(carpeta, "automatica", {"huella": registro.huella(carpeta, piezas),
                                                   "estado": "bloquea" if bloquean else "ok",
                                                   "bloquean": len(bloquean)}, texto or "sin hallazgos", ahora)
