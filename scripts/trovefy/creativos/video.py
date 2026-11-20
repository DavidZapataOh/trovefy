"""Montaje de los vídeos con ffmpeg (plan 21, Tarea 7): órdenes como funciones puras y su ejecución con tiempo límite.

Cada plantilla se monta con sus piezas propias: ``broll_voz`` (clips que cortan cada 1,5 s), ``ugc`` (la persona
generada a pantalla completa, con su trozo de voz a la vez), ``claymation`` y ``3d`` (clips por capítulo, con rótulo),
``zoom_lento`` (clip corto de gancho y luego imágenes fijas con zoom lento), ``scroll_pdf`` (tira de páginas del PDF
vigente que sube dentro de un marco) y los demás formatos (clip o imagen por segmento). La voz va por partes, cada
una en su tramo, y la música por debajo (``amix``, ``video.musica_db``); subtítulos karaoke en ASS dentro de la zona
segura y el gancho en grande los primeros segundos. Nunca ``shell=True``: las rutas van como argumentos.
"""

from __future__ import annotations

import json
import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.guion import GuionVideo, Parte
from trovefy.referencia.watch import _ejecutar_grupo

TIMEOUT_S = 600
MARGEN_VOZ_S = 0.15  # un trozo de voz puede pasarse esto de su tramo (silencio final del TTS)


class VideoInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Visual:
    """Lo que se ve en un tramo: ``clip`` (mp4), ``imagen`` (fija o con zoom), ``tira`` (scroll del PDF) o
    ``color`` (el cierre). ``inicio`` es el segundo del clip desde el que se toma."""
    tipo: str
    ruta: Path | None
    segundos: float
    inicio: float = 0.0
    zoom: bool = False


@dataclass(frozen=True)
class Entradas:
    visuales: dict[str, list[Visual]]  # clave de la parte → lo que se ve
    voces: dict[str, Path]  # clave de la parte → su trozo de voz
    duraciones_voz: dict[str, float]
    musica: Path | None
    color_cierre: str = "#1E2A38"


# --- tramos ------------------------------------------------------------------------------------------------------


def cortes_broll(clips: list[Path], total: float, corte: float) -> list[Visual]:
    """Tramos de ``corte`` segundos que van rotando por los clips (L2 16:01); el último, lo que quede."""
    if not clips:
        raise VideoInvalido("el B-roll necesita clips")
    salida, t, i = [], 0.0, 0
    while t < total - 1e-6:
        dur = round(min(corte, total - t), 3)
        clip = clips[i % len(clips)]
        salida.append(Visual("clip", clip, dur, inicio=round(corte * (i // len(clips)), 3)))
        t += dur
        i += 1
    return salida


def tramos(guion: GuionVideo, clips: dict[str, Path], imagenes: dict[str, Path], tira: dict[str, Path],
           cfg: ConfigCreativos) -> dict[str, list[Visual]]:
    """Qué se ve en cada parte según la plantilla. ``clips``: clave de la parte → clip descargado; ``imagenes``:
    ref → archivo propio; ``tira``: clave del segmento → tira de páginas del PDF."""
    out: dict[str, list[Visual]] = {}
    gancho = guion.partes[0]
    if gancho.clip is not None:
        if "g" not in clips:
            raise VideoInvalido(f"{guion.ad}: falta el clip de gancho (trovefy creativos clips --solo-gancho)")
        out["g"] = [Visual("clip", clips["g"], gancho.segundos)]
    segs = guion.segmentos
    if guion.plantilla == "broll_voz":
        faltan = [s.clave for s in segs if s.clave not in clips]
        if faltan:
            raise VideoInvalido(f"{guion.ad}: faltan clips de {', '.join(faltan)}")
        lista = cortes_broll([clips[s.clave] for s in segs], sum(s.segundos for s in segs), float(cfg.corte_broll_s))
        out[segs[0].clave] = lista
        for s in segs[1:]:
            out[s.clave] = []
    else:
        for s in segs:
            out[s.clave] = [_visual(guion, s, clips, imagenes, tira)]
    if "g" not in out:
        primero = out[segs[0].clave][0]
        out["g"] = [Visual(primero.tipo, primero.ruta, gancho.segundos, zoom=primero.zoom)]
    out["c"] = [Visual("color", None, guion.partes[-1].segundos)]
    return out


def _visual(guion: GuionVideo, s: Parte, clips, imagenes, tira) -> Visual:
    if s.clip is not None:
        if s.clave not in clips:
            raise VideoInvalido(f"{guion.ad}: falta el clip de {s.clave}")
        return Visual("clip", clips[s.clave], s.segundos)
    if s.paginas:
        if s.clave not in tira:
            raise VideoInvalido(f"{guion.ad}: falta la tira de páginas de {s.clave}")
        return Visual("tira", tira[s.clave], s.segundos)
    if s.imagen not in imagenes:
        raise VideoInvalido(f"{guion.ad}: la imagen «{s.imagen}» no es un medio propio de la tanda o del entregable")
    return Visual("imagen", imagenes[s.imagen], s.segundos, zoom=True)


# --- ASS ---------------------------------------------------------------------------------------------------------


def _t(seg: float) -> str:
    cs = round(seg * 100)
    h, resto = divmod(cs, 360000)
    m, resto = divmod(resto, 6000)
    s, cs = divmod(resto, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_texto(texto: str) -> str:
    return texto.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_color(hex_: str) -> str:
    r, g, b = hex_[1:3], hex_[3:5], hex_[5:7]
    return f"&H00{b}{g}{r}".upper()


def subtitulos_ass(guion: GuionVideo, cfg: ConfigCreativos, fuentes: dict[str, str], duraciones_voz: dict[str, float],
                   tiempos: dict[str, list[tuple[str, float, float]]] | None = None, *, color_texto: str = "#FFFFFF",
                   color_resalte: str = "#FFD23F") -> str:
    """ASS con karaoke palabra a palabra. Con ``tiempos`` (los de WhisperX: palabra, inicio, fin) se usan tal cual;
    sin ellos, cada palabra dura su parte de la voz según sus letras. Todo dentro de la zona segura."""
    w, h = cfg.video_ancho, cfg.video_alto
    arriba = math.ceil(h * cfg.zona_segura_arriba_pct / 100)
    abajo = math.ceil(h * cfg.zona_segura_abajo_pct / 100)
    blanco, resalte = _ass_color(color_texto), _ass_color(color_resalte)
    tit, txt = fuentes.get("titulos", "Sans"), fuentes.get("texto", "Sans")
    lineas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding"),
        f"Style: Gancho,{tit},104,{blanco},{blanco},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,0,8,80,80,{arriba},1",
        (f"Style: Capitulo,{tit},72,{blanco},{blanco},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,0,8,80,80,"
         f"{arriba},1"),
        f"Style: Sub,{txt},66,{resalte},{blanco},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,0,2,90,90,{abajo},1",
        f"Style: Cierre,{tit},88,{blanco},{blanco},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,0,5,90,90,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t0 = 0.0
    capitulos = guion.plantilla == "3d"
    for parte in guion.partes:
        fin = t0 + parte.segundos
        if parte.clave == "g":
            lineas.append(f"Dialogue: 1,{_t(0)},{_t(min(cfg.gancho_s, parte.segundos))},Gancho,,0,0,0,,"
                          f"{_ass_texto(guion.gancho)}")
        elif parte.clave == "c":
            lineas.append(f"Dialogue: 1,{_t(t0)},{_t(fin)},Cierre,,0,0,0,,{_ass_texto(parte.texto_pantalla)}"
                          f"\\N{_ass_texto(guion.cta)}")
        elif capitulos:
            lineas.append(f"Dialogue: 1,{_t(t0)},{_t(fin)},Capitulo,,0,0,0,,{parte.n}/4 "
                          f"{_ass_texto(parte.texto_pantalla)}")
        lineas += _karaoke(parte, t0, duraciones_voz.get(parte.clave, parte.segundos),
                           (tiempos or {}).get(parte.clave))
        t0 = fin
    return "\n".join(lineas) + "\n"


def _karaoke(parte: Parte, t0: float, dur_voz: float, tiempos: list[tuple[str, float, float]] | None) -> list[str]:
    palabras = parte.texto_voz.split()
    if not palabras:
        return []
    if tiempos:
        marcas = [(p, t0 + a, t0 + b) for p, a, b in tiempos]
    else:
        total = sum(len(p) + 1 for p in palabras)
        dur = min(dur_voz, parte.segundos)
        marcas, t = [], t0
        for p in palabras:
            d = dur * (len(p) + 1) / total
            marcas.append((p, t, t + d))
            t += d
    salida = []
    for i in range(0, len(marcas), 4):
        grupo = marcas[i:i + 4]
        texto = "".join(f"{{\\k{max(1, round((b - a) * 100))}}}{_ass_texto(p)} " for p, a, b in grupo)
        salida.append(f"Dialogue: 0,{_t(grupo[0][1])},{_t(grupo[-1][2])},Sub,,0,0,0,,{texto.strip()}")
    return salida


# --- orden de ffmpeg ---------------------------------------------------------------------------------------------


def _escapar_filtro(ruta: Path) -> str:
    return str(ruta).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def comprobar_voz(guion: GuionVideo, entradas: Entradas) -> None:
    faltan = [p.clave for p in guion.partes if p.texto_voz and p.clave not in entradas.voces]
    if faltan or not entradas.voces:
        raise VideoInvalido(f"{guion.ad}: todos los vídeos llevan voz (L2 15:25); falta la de {', '.join(faltan) or 'todo'}")
    for p in guion.partes:
        d = entradas.duraciones_voz.get(p.clave)
        if d is not None and d > p.segundos + MARGEN_VOZ_S:
            raise VideoInvalido(f"{guion.ad}: la voz de {p.clave} dura {d:.1f} s y su tramo {p.segundos:g} s: acorta el "
                                "texto o alarga el tramo")


def orden_plantilla(guion: GuionVideo, entradas: Entradas, cfg: ConfigCreativos, ass: Path, salida: Path, *,
                    hasta_s: float | None = None) -> list[str]:
    """Argumentos de ffmpeg para montar ``guion`` (pura). ``hasta_s`` corta la salida (la prueba del gancho)."""
    total = guion.duracion
    if not cfg.duracion_s[0] <= total <= cfg.duracion_s[1]:
        raise VideoInvalido(f"{guion.ad}: dura {total:g} s; debe durar de {cfg.duracion_s[0]} a {cfg.duracion_s[1]} s")
    comprobar_voz(guion, entradas)
    if entradas.musica is None:
        raise VideoInvalido(f"{guion.ad}: falta la música de la tanda (L2 15:25): trovefy creativos musica")
    w, h, fps = cfg.video_ancho, cfg.video_alto, cfg.fps
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    filtros, etiquetas, n = [], [], 0
    for parte in guion.partes:
        for v in entradas.visuales.get(parte.clave, []):
            d = f"{v.segundos:.3f}"
            if v.tipo == "clip":
                args += ["-ss", f"{v.inicio:.3f}", "-i", str(v.ruta)]
                f = (f"[{n}:v]tpad=stop_mode=clone:stop_duration={d},trim=duration={d},setpts=PTS-STARTPTS,"
                     f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1,"
                     f"format=yuv420p[v{n}]")
            elif v.tipo == "imagen":
                frames = max(1, round(v.segundos * fps))
                args += ["-i", str(v.ruta)]
                f = (f"[{n}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                     f"zoompan=z='min(zoom+0.0007,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:"
                     f"s={w}x{h}:fps={fps},trim=duration={d},setsar=1,format=yuv420p[v{n}]")
            elif v.tipo == "tira":
                ancho, alto = int(w * 0.8), int(h * 0.8)
                args += ["-loop", "1", "-t", d, "-i", str(v.ruta)]
                f = (f"[{n}:v]scale={ancho}:-2,crop={ancho}:{alto}:0:'max(0,(ih-{alto})*t/{d})',"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={entradas.color_cierre},fps={fps},trim=duration={d},"
                     f"setsar=1,format=yuv420p[v{n}]")
            else:
                args += ["-f", "lavfi", "-t", d, "-i", f"color=c={entradas.color_cierre}:s={w}x{h}:r={fps}"]
                f = f"[{n}:v]setsar=1,format=yuv420p[v{n}]"
            filtros.append(f)
            etiquetas.append(f"[v{n}]")
            n += 1
    filtros.append(f"{''.join(etiquetas)}concat=n={len(etiquetas)}:v=1:a=0[vc]")
    filtros.append(f"[vc]subtitles=filename='{_escapar_filtro(ass)}'[vout]")
    voces = []
    for parte in guion.partes:
        d = f"{parte.segundos:.3f}"
        if parte.clave in entradas.voces:
            args += ["-i", str(entradas.voces[parte.clave])]
            filtros.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={d},"
                           f"atrim=duration={d},asetpts=PTS-STARTPTS[a{n}]")
        else:
            args += ["-f", "lavfi", "-t", d, "-i", "anullsrc=r=44100:cl=stereo"]
            filtros.append(f"[{n}:a]atrim=duration={d}[a{n}]")
        voces.append(f"[a{n}]")
        n += 1
    filtros.append(f"{''.join(voces)}concat=n={len(voces)}:v=0:a=1[voz]")
    args += ["-stream_loop", "-1", "-i", str(entradas.musica)]
    filtros.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={cfg.musica_db}dB,"
                   f"atrim=duration={total:.3f}[mus]")
    filtros.append("[voz][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    args += ["-filter_complex", ";".join(filtros), "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(fps),
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart",
             "-t", f"{(hasta_s if hasta_s is not None else total):.3f}", str(salida)]
    return args


# --- ejecución ---------------------------------------------------------------------------------------------------


def renderizar(orden: list[str], timeout_s: int = TIMEOUT_S, correr=_ejecutar_grupo) -> None:
    """Ejecuta la orden en su propio grupo de procesos; al vencer el plazo mata el grupo entero."""
    try:
        p = correr(orden, timeout=timeout_s, capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired:
        raise VideoInvalido(f"ffmpeg pasó de {timeout_s} s: se paró") from None
    if p.returncode != 0:
        raise VideoInvalido(f"ffmpeg falló: {(p.stderr or '').strip()[-400:]}")


def sondear(ruta: Path, correr=subprocess.run) -> dict:
    """Ancho, alto, códecs, duración, fps, tamaño y si el ``moov`` va delante (``+faststart``)."""
    p = correr(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(ruta)],
               capture_output=True, text=True, timeout=60, check=False)
    if p.returncode != 0:
        raise VideoInvalido(f"ffprobe no pudo leer {Path(ruta).name}")
    datos = json.loads(p.stdout or "{}")
    v = next((s for s in datos.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in datos.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = datos.get("format", {})
    num, _, den = str(v.get("r_frame_rate", "0/1")).partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {"ancho": v.get("width"), "alto": v.get("height"), "codec": v.get("codec_name"),
            "pix_fmt": v.get("pix_fmt"), "audio": a.get("codec_name"), "fps": fps,
            "duracion": float(fmt.get("duration") or 0), "bytes": int(fmt.get("size") or 0),
            "faststart": _moov_delante(Path(ruta))}


def _moov_delante(ruta: Path) -> bool:
    try:
        with open(ruta, "rb") as f:
            cabeza = f.read(1 << 20)
    except OSError:
        return False
    i_moov, i_mdat = cabeza.find(b"moov"), cabeza.find(b"mdat")
    return i_moov != -1 and (i_mdat == -1 or i_moov < i_mdat)


def duracion_audio(ruta: Path, correr=subprocess.run) -> float:
    try:
        with wave.open(str(ruta), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        pass
    p = correr(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(ruta)],
               capture_output=True, text=True, timeout=60, check=False)
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise VideoInvalido(f"no se pudo medir la duración de {Path(ruta).name}") from None


def orden_fotograma(video: Path, segundo: float, salida: Path) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{segundo:.3f}", "-i", str(video),
            "-frames:v", "1", "-q:v", "3", str(salida)]


def fotogramas(video: Path, segundos: list[float], destino: Path, prefijo: str, correr=_ejecutar_grupo) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    salida = []
    for i, s in enumerate(segundos, 1):
        ruta = destino / f"{prefijo}-{i}.jpg"
        renderizar(orden_fotograma(video, s, ruta), 120, correr)
        salida.append(ruta)
    return salida


def segundos_prueba(cfg: ConfigCreativos) -> list[float]:
    """0 s, 1,5 s y 4,5 s (§4.12 paso 5), dentro de la prueba de ``prueba_gancho_s`` segundos."""
    return [0.0, 1.5, min(4.5, cfg.prueba_gancho_s - 0.2)]


def segundos_hoja(duracion: float) -> list[float]:
    """Los 4 fotogramas de la hoja de contactos: 0 s, 3 s, la mitad y el final − 2 s."""
    return [0.0, min(3.0, duracion), round(duracion / 2, 2), max(0.0, round(duracion - 2, 2))]


def tira_pdf(pdf: Path, paginas: tuple[int, ...], salida: Path, ancho: int, correr=subprocess.run) -> Path:
    """Tira vertical con las ``paginas`` del PDF vigente (``pdftoppm``), una debajo de otra."""
    from PIL import Image

    salida.parent.mkdir(parents=True, exist_ok=True)
    imgs = []
    for n in paginas:
        base = salida.parent / f".{salida.stem}-p{n}"
        p = correr(["pdftoppm", "-f", str(n), "-l", str(n), "-png", "-r", "110", "-singlefile", str(pdf), str(base)],
                   capture_output=True, text=True, timeout=120, check=False)
        archivo = base.with_suffix(".png")
        if p.returncode != 0 or not archivo.is_file():
            raise VideoInvalido(f"pdftoppm no pudo sacar la página {n} del PDF vigente")
        with Image.open(archivo) as img:
            esc = ancho / img.width
            imgs.append(img.convert("RGB").resize((ancho, int(img.height * esc))))
        archivo.unlink()
    alto = sum(i.height for i in imgs) + 24 * (len(imgs) - 1)
    tira = Image.new("RGB", (ancho, alto), (255, 255, 255))
    y = 0
    for i in imgs:
        tira.paste(i, (0, y))
        y += i.height + 24
    tira.save(salida, "PNG")
    return salida

