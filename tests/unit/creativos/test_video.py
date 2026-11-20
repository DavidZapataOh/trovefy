"""Órdenes de ffmpeg de cada plantilla y subtítulos (plan 21, Tarea 7). Aquí no se ejecuta ffmpeg."""

import re
import subprocess
from pathlib import Path

import pytest
from trovefy.creativos.config import cargar_plantilla
from trovefy.creativos.guion import GuionInvalido, validar_video
from trovefy.creativos.video import (
    Entradas,
    VideoInvalido,
    cortes_broll,
    orden_plantilla,
    renderizar,
    subtitulos_ass,
    tramos,
)

from .ejemplos import guion_video

CFG = cargar_plantilla()
R = Path("/tmp/no-existe")


def _entradas(g, *, voz=True, musica=True):
    clips = {p.clave: R / f"{p.clave}.mp4" for p in g.partes if p.clip is not None}
    vis = tramos(g, clips, {"mockup": R / "mockup.png"}, {s.clave: R / f"tira-{s.clave}.png" for s in g.segmentos},
                 CFG)
    voces = {p.clave: R / f"voz-{p.clave}.wav" for p in g.partes} if voz else {}
    return Entradas(vis, voces, {p.clave: p.segundos - 0.5 for p in g.partes}, R / "musica.mp3" if musica else None)


def _orden(plantilla, **kw):
    g = validar_video("AD09", guion_video(plantilla, **kw), CFG)
    return g, orden_plantilla(g, _entradas(g), CFG, R / "AD09.ass", R / "AD09.mp4")


@pytest.mark.parametrize("plantilla", ["broll_voz", "ugc", "claymation", "3d", "scroll_pdf", "zoom_lento"])
def test_orden_plantilla_sin_shell(plantilla):
    _, orden = _orden(plantilla)
    assert isinstance(orden, list) and orden[0] == "ffmpeg"
    assert all(isinstance(a, str) for a in orden)
    assert ";" not in orden and "|" not in orden and "&&" not in orden
    assert "+faststart" in orden and "yuv420p" in orden and "libx264" in orden and "aac" in orden
    filtro = orden[orden.index("-filter_complex") + 1]
    assert "1080:1920" in filtro or "1080x1920" in filtro


def test_broll_corta_cada_1_5_s():
    cortes = cortes_broll([R / "a.mp4", R / "b.mp4"], 20.0, 1.5)
    assert all(c.segundos == 1.5 for c in cortes[:-1]) and abs(sum(c.segundos for c in cortes) - 20) < 1e-6
    assert [c.ruta.name for c in cortes[:4]] == ["a.mp4", "b.mp4", "a.mp4", "b.mp4"]
    _, orden = _orden("broll_voz")
    filtro = orden[orden.index("-filter_complex") + 1]
    assert filtro.count("trim=duration=1.500") >= 12


def test_3d_cuatro_capitulos():
    with pytest.raises(GuionInvalido, match="4 capítulos"):
        validar_video("AD09", guion_video("3d", segmentos=3, segundos=6), CFG)
    g = validar_video("AD09", guion_video("3d"), CFG)
    ass = subtitulos_ass(g, CFG, {}, {})
    assert all(f"{n}/4" in ass for n in range(1, 5))


def test_ugc_sincroniza_con_la_voz():
    g, orden = _orden("ugc")
    filtro = orden[orden.index("-filter_complex") + 1]
    # cada tramo de la persona y su trozo de voz duran lo mismo y empiezan a la vez (concat en el mismo orden)
    for p in g.segmentos:
        assert orden.count(str(R / f"{p.clave}.mp4")) == 1 and str(R / f"voz-{p.clave}.wav") in orden
    assert filtro.count("apad=whole_dur=5.000") == 4 and filtro.count("trim=duration=5.000") >= 8


def test_zoom_lento_empieza_con_clip_de_gancho():
    _, orden = _orden("zoom_lento")
    entradas = [orden[i + 1] for i, a in enumerate(orden) if a == "-i"]
    assert entradas[0].endswith("g.mp4")
    assert "zoompan" in orden[orden.index("-filter_complex") + 1]


def test_voz_y_musica_mezcladas():
    _, orden = _orden("claymation")
    filtro = orden[orden.index("-filter_complex") + 1]
    assert "amix=inputs=2" in filtro and "volume=-18dB" in filtro and "-stream_loop" in orden


def test_sin_voz_falla():
    g = validar_video("AD09", guion_video("claymation"), CFG)
    with pytest.raises(VideoInvalido, match="llevan voz"):
        orden_plantilla(g, _entradas(g, voz=False), CFG, R / "a.ass", R / "a.mp4")
    with pytest.raises(GuionInvalido, match="voz"):
        validar_video("AD09", guion_video("claymation", voz=False), CFG)


def test_duracion_fuera_de_rango():
    with pytest.raises(GuionInvalido, match="debe durar de 20 a 30"):
        validar_video("AD09", guion_video("claymation", segundos=8.5), CFG)  # 3 + 34 + 3 = 40 s


def test_ass_karaoke_en_zona_segura():
    g = validar_video("AD09", guion_video("broll_voz"), CFG)
    ass = subtitulos_ass(g, CFG, {"titulos": "Ubuntu", "texto": "Noto Sans"}, {})
    estilos = {m.group(1): m.group(0).split(",") for m in re.finditer(r"^Style: (\w+),.*$", ass, re.MULTILINE)}
    assert int(estilos["Sub"][-2]) >= 0.35 * 1920 and estilos["Sub"][18] == "2"
    assert int(estilos["Gancho"][-2]) >= 0.14 * 1920 and estilos["Gancho"][18] == "8"
    assert "{\\k" in ass


def test_gancho_grande_tres_segundos():
    g = validar_video("AD09", guion_video("broll_voz"), CFG)
    ass = subtitulos_ass(g, CFG, {}, {})
    linea = next(x for x in ass.splitlines() if ",Gancho," in x and x.startswith("Dialogue"))
    assert "0:00:00.00,0:00:03.00" in linea and "Не можеш да заспиш вечер?" in linea


def test_scroll_pdf_usa_paginas_del_pdf_vigente():
    g, orden = _orden("scroll_pdf")
    assert any(a.endswith("tira-s01.png") for a in orden)
    assert "crop=864:1536" in orden[orden.index("-filter_complex") + 1]
    assert all(s.paginas == (1, 2) for s in g.segmentos)


def test_voz_mas_larga_que_su_tramo():
    g = validar_video("AD09", guion_video("claymation"), CFG)
    e = _entradas(g)
    e = Entradas(e.visuales, e.voces, {**e.duraciones_voz, "s01": 7.0}, e.musica)
    with pytest.raises(VideoInvalido, match="acorta"):
        orden_plantilla(g, e, CFG, R / "a.ass", R / "a.mp4")


def test_timeout_mata_grupo():
    def correr(*_a, **_k):
        raise subprocess.TimeoutExpired("ffmpeg", 1)

    with pytest.raises(VideoInvalido, match="se paró"):
        renderizar(["ffmpeg"], 1, correr)
