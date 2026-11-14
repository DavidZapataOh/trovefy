"""Medios (vídeos e imágenes) del ``snapshot`` de un anuncio de la Biblioteca.

Las URLs viven solo en memoria: nunca se escriben en el vault. Solo se conservan las que pasan
:func:`trovefy.referencia.descarga.url_permitida` (https, puerto 443, host de CDN de Meta).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from trovefy.caza.cliente import PaginaCapturada
from trovefy.caza.parser import resultados_crudos
from trovefy.referencia.descarga import url_permitida

Formato = Literal["video", "imagen", "carrusel", "dinamico", "otro"]

_MAPA: dict[str, Formato] = {
    "VIDEO": "video",
    "IMAGE": "imagen",
    "CAROUSEL": "carrusel",
    "DCO": "dinamico",
    "DPA": "dinamico",
}


@dataclass(frozen=True)
class MediosAnuncio:
    library_id: str
    formato: Formato | None
    videos: tuple[str, ...]
    imagenes: tuple[str, ...]


def _formato(display: Any, videos: tuple[str, ...], imagenes: tuple[str, ...]) -> Formato | None:
    if isinstance(display, str) and display:
        return _MAPA.get(display, "otro")
    if videos:
        return "video"
    if imagenes:
        return "imagen"
    return None


def _url(d: Any, *claves: str) -> str | None:
    if not isinstance(d, dict):
        return None
    for c in claves:
        v = d.get(c)
        if isinstance(v, str) and url_permitida(v):
            return v
    return None


def _lista(snap: dict, clave: str) -> list:
    v = snap.get(clave)
    return v if isinstance(v, list) else []


def medios_de_pagina(p: PaginaCapturada) -> dict[str, MediosAnuncio]:
    salida: dict[str, MediosAnuncio] = {}
    for r in resultados_crudos(p.cuerpos, p.html):
        lib = r.get("ad_archive_id")
        if isinstance(lib, int) and not isinstance(lib, bool):
            lib = str(lib)
        if not isinstance(lib, str) or not lib or lib in salida:
            continue
        snap = r.get("snapshot")
        snap = snap if isinstance(snap, dict) else {}
        videos: list[str] = []
        imagenes: list[str] = []
        for e in _lista(snap, "videos") + _lista(snap, "cards"):
            v = _url(e, "video_sd_url", "video_hd_url")
            if v and v not in videos:
                videos.append(v)
        for e in _lista(snap, "images") + _lista(snap, "cards"):
            i = _url(e, "original_image_url", "resized_image_url")
            if i and i not in imagenes:
                imagenes.append(i)
        vt, it = tuple(videos), tuple(imagenes)
        salida[lib] = MediosAnuncio(lib, _formato(snap.get("display_format"), vt, it), vt, it)
    return salida
