"""Render real con ffmpeg (plan 21, Tarea 7): 6 s de un B-roll con voz, música y subtítulos, y la prueba del gancho."""

import shutil
import subprocess

import pytest
from trovefy.creativos.config import cargar_plantilla
from trovefy.creativos.guion import validar_video
from trovefy.creativos.video import (
    Entradas,
    fotogramas,
    orden_plantilla,
    renderizar,
    segundos_prueba,
    sondear,
    subtitulos_ass,
    tramos,
)


def guion_video(plantilla):
    segs = [{"texto_voz": f"Стъпка {i}: дишай бавно.", "texto_pantalla": f"Стъпка {i}", "segundos": 5,
             "clip": {"prompt": f"plano {i}", "tipo": "texto"}} for i in range(1, 5)]
    return {"plantilla": plantilla, "gancho": "Не можеш да заспиш вечер?",
            "clip_gancho": {"prompt": "reloj", "segundos": 3}, "segmentos": segs,
            "cierre": {"texto": "Ruta Calma 3R · 13,90 €", "cta": "Натисни бутона отдолу", "segundos": 3}, "voz": True}

pytestmark = [pytest.mark.integracion,
              pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="falta ffmpeg")]
CFG = cargar_plantilla()


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=120)


@pytest.fixture
def piezas(tmp_path):
    for n, color in (("g", "red"), ("s01", "green"), ("s02", "blue"), ("s03", "yellow"), ("s04", "purple")):
        _ff("-f", "lavfi", "-i", f"color=c={color}:s=720x1280:r=24:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(tmp_path / f"{n}.mp4"))
        _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(tmp_path / f"voz-{n}.wav"))
    _ff("-f", "lavfi", "-i", "sine=frequency=220:duration=10", str(tmp_path / "voz-c.wav"))
    _ff("-f", "lavfi", "-i", "sine=frequency=330:duration=8", "-c:a", "libmp3lame", str(tmp_path / "musica.mp3"))
    return tmp_path


def _render(piezas, hasta):
    g = validar_video("AD09", guion_video("broll_voz"), CFG)
    clips = {k: piezas / f"{k}.mp4" for k in ("g", "s01", "s02", "s03", "s04")}
    voces = {p.clave: piezas / f"voz-{p.clave}.wav" for p in g.partes}
    voces["c"] = piezas / "voz-g.wav"
    e = Entradas(tramos(g, clips, {}, {}, CFG), voces, {p.clave: 2.0 for p in g.partes}, piezas / "musica.mp3")
    ass = piezas / "AD09.ass"
    ass.write_text(subtitulos_ass(g, CFG, {"titulos": "Ubuntu", "texto": "Noto Sans"}, {}), encoding="utf-8")
    salida = piezas / "AD09.mp4"
    renderizar(orden_plantilla(g, e, CFG, ass, salida, hasta_s=hasta))
    return salida


def test_render_real_6s(piezas):
    info = sondear(_render(piezas, 6))
    assert (info["ancho"], info["alto"], info["codec"], info["audio"]) == (1080, 1920, "h264", "aac")
    assert 5.5 <= info["duracion"] <= 6.5 and info["pix_fmt"] == "yuv420p" and info["faststart"]


def test_prueba_gancho_tres_fotogramas(piezas):
    video = _render(piezas, CFG.prueba_gancho_s)
    fotos = fotogramas(video, segundos_prueba(CFG), piezas / "qc", "gancho-AD09")
    assert len(fotos) == 3 and all(f.stat().st_size > 0 for f in fotos)


@pytest.mark.parametrize("plantilla", ["zoom_lento", "scroll_pdf"])
def test_render_imagenes_y_tira(piezas, plantilla):
    from PIL import Image

    Image.new("RGB", (800, 1000), (200, 120, 90)).save(piezas / "mockup.png")
    Image.new("RGB", (864, 4000), (240, 240, 240)).save(piezas / "tira.png")
    datos = guion_video("broll_voz")
    datos["plantilla"] = plantilla
    for s in datos["segmentos"]:
        s.pop("clip")
        if plantilla == "zoom_lento":
            s["imagen"] = "mockup"
        else:
            s["paginas"] = [1, 2]
    g = validar_video("AD10", datos, CFG)
    tira = {s.clave: piezas / "tira.png" for s in g.segmentos}
    voces = {p.clave: piezas / "voz-g.wav" for p in g.partes}
    e = Entradas(tramos(g, {"g": piezas / "g.mp4"}, {"mockup": piezas / "mockup.png"}, tira, CFG), voces,
                 {p.clave: 2.0 for p in g.partes}, piezas / "musica.mp3")
    ass = piezas / "AD10.ass"
    ass.write_text(subtitulos_ass(g, CFG, {}, {}), encoding="utf-8")
    salida = piezas / "AD10.mp4"
    renderizar(orden_plantilla(g, e, CFG, ass, salida, hasta_s=8))
    info = sondear(salida)
    assert (info["ancho"], info["alto"]) == (1080, 1920) and 7.5 <= info["duracion"] <= 8.5
