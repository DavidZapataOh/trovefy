"""Medios del snapshot de la Biblioteca (URLs solo en memoria)."""

import json
from pathlib import Path

from trovefy.caza import parser
from trovefy.caza.cliente import PaginaCapturada
from trovefy.referencia import medios

FIX = Path(__file__).resolve().parents[2] / "fixtures"


def pagina(ruta):
    d = json.loads((FIX / ruta).read_text())
    return PaginaCapturada(d["url_final"], d["html_final"], "", [r["cuerpo"] for r in d["respuestas"]])


def test_resultados_crudos_mismo_orden_que_parsear_detalle():
    p = pagina("biblioteca/palabra_impultienda.json")
    ids = [r["ad_archive_id"] for r in parser.resultados_crudos(p.cuerpos, p.html)]
    esperado = [a.library_id for a in parser.parsear_detalle(p.cuerpos, "ALL", p.html).anuncios]
    vistos = list(dict.fromkeys(ids))
    assert vistos == esperado and len(ids) >= len(esperado)


def test_medios_formato_y_urls():
    m = medios.medios_de_pagina(pagina("referencia/pagina_con_medios.json"))
    assert set(m) == {f"90000000000000{i}" for i in range(1, 5)}
    v = m["900000000000001"]
    assert v.formato == "video" and v.videos == ("https://video.fic-1.fna.fbcdn.net/v/a.mp4?oh=x&oe=y",)
    assert v.imagenes == ()
    i = m["900000000000002"]
    assert i.formato == "imagen" and i.imagenes == ("https://scontent.fic-1.fna.fbcdn.net/i.jpg",)
    c = m["900000000000003"]
    assert c.formato == "carrusel"
    assert c.videos == ("https://video.fic-1.fna.fbcdn.net/v/c.mp4",)
    assert c.imagenes == ("https://scontent.fic-1.fna.fbcdn.net/c.jpg",)
    n = m["900000000000004"]
    assert n.formato is None and n.videos == () and n.imagenes == ()


def test_formato_por_mapa():
    f = medios._formato
    assert [f(x, (), ()) for x in ("VIDEO", "IMAGE", "CAROUSEL", "DCO", "DPA", "RARO")] == [
        "video", "imagen", "carrusel", "dinamico", "dinamico", "otro",
    ]
    assert f(None, ("u",), ()) == "video" and f(None, (), ("u",)) == "imagen" and f(None, (), ()) is None
