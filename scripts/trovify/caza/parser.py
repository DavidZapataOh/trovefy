"""Lee anuncios de la Biblioteca pública de Meta a partir de lo que devuelve la página.

Los anuncios llegan por dos vías (ver tests/fixtures/biblioteca/README.md): la primera página
(30) va en bloques ``<script type="application/json">`` del HTML y las siguientes (10 cada una)
en respuestas de ``/api/graphql/``. En ambos casos cuelgan de
``...search_results_connection.edges[].node.collated_results[]``.

Ideas tomadas (reescritas, sin copiar código) de un repo de referencia (leer también los
bloques JSON del HTML) y un repo de referencia (estructura
``search_results_connection`` y campos del anuncio), ambos MIT; ver avisos privados.

Regla: si el formato no es el esperado se lanza ``FormatoDesconocido``; nunca se devuelve un
número o un anuncio a medias.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import UTC, date, datetime
from typing import Any

from trovify.caza.modelo import AnuncioBiblioteca

__all__ = ["FormatoDesconocido", "parsear_respuestas", "sin_resultados", "total_aproximado"]


class FormatoDesconocido(Exception):
    """Nada de lo recibido tiene la estructura esperada de la Biblioteca."""


_SCRIPT_JSON = re.compile(
    r'<script\b[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)


def _conexiones(nodo: Any):
    """Todos los ``search_results_connection`` (con ``edges`` lista) del árbol JSON."""
    if isinstance(nodo, dict):
        con = nodo.get("search_results_connection")
        if isinstance(con, dict) and isinstance(con.get("edges"), list):
            yield con
        for v in nodo.values():
            yield from _conexiones(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _conexiones(v)


def _texto(valor: Any) -> str | None:
    return valor if isinstance(valor, str) and valor != "" else None


def _fecha(epoch: Any, campo: str) -> date:
    # Meta da la fecha como segundos unix; se convierte a fecha en UTC (no en hora local).
    if isinstance(epoch, bool) or not isinstance(epoch, int | float):
        raise FormatoDesconocido(f"{campo} no es una marca de tiempo")
    return datetime.fromtimestamp(epoch, UTC).date()


def _id(valor: Any, campo: str) -> str:
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if not isinstance(valor, str) or not valor:
        raise FormatoDesconocido(f"falta {campo}")
    return valor


def _anuncio(a: Any, pais: str) -> AnuncioBiblioteca:
    if not isinstance(a, dict):
        raise FormatoDesconocido("anuncio que no es un objeto")
    snap = a.get("snapshot")
    if not isinstance(snap, dict):
        raise FormatoDesconocido("anuncio sin snapshot")
    activo = a.get("is_active")
    if not isinstance(activo, bool):
        raise FormatoDesconocido("is_active no es booleano")
    plataformas = a.get("publisher_platform")
    if not isinstance(plataformas, list):
        raise FormatoDesconocido("publisher_platform no es una lista")
    fin = a.get("end_date")
    cuenta = a.get("collation_count")
    tarjetas = [t for t in (snap.get("cards") or []) if isinstance(t, dict)]
    cuerpo = snap.get("body")
    texto = cuerpo.get("text") if isinstance(cuerpo, dict) else None
    # En carruseles el texto, el título y el enlace pueden venir solo en la primera tarjeta.
    primera = tarjetas[0] if tarjetas else {}
    if not _texto(texto):
        cuerpo_t = primera.get("body")
        texto = cuerpo_t.get("text") if isinstance(cuerpo_t, dict) else cuerpo_t
    return AnuncioBiblioteca(
        library_id=_id(a.get("ad_archive_id"), "ad_archive_id"),
        page_id=_id(a.get("page_id"), "page_id"),
        page_name=_texto(a.get("page_name")) or _texto(snap.get("page_name")) or "",
        inicio=_fecha(a.get("start_date"), "start_date"),
        fin=None if fin is None else _fecha(fin, "end_date"),
        activo=activo,
        plataformas=tuple(p for p in plataformas if isinstance(p, str)),
        texto=_texto(texto) or "",
        titulo=_texto(snap.get("title")) or _texto(primera.get("title")),
        enlace_destino=_texto(snap.get("link_url")) or _texto(primera.get("link_url")),
        collation_id=_texto(a.get("collation_id")),
        collation_count=cuenta if isinstance(cuenta, int) and not isinstance(cuenta, bool) else None,
        pais=pais,
    )


def parsear_respuestas(cuerpos: list[str], pais: str, html: str | None = None) -> list[AnuncioBiblioteca]:
    """Anuncios de las respuestas de datos y de los bloques JSON del HTML, sin repetidos.

    Lanza ``FormatoDesconocido`` si ningún documento trae ``search_results_connection``, o si un
    anuncio no trae los campos obligatorios. Una conexión reconocida con ``edges`` vacío es una
    búsqueda sin resultados: devuelve ``[]``.
    """
    textos = list(cuerpos)
    if html:
        textos += [_html.unescape(m) if "&quot;" in m else m for m in _SCRIPT_JSON.findall(html)]
    vistos: dict[str, AnuncioBiblioteca] = {}
    reconocido = False
    for t in textos:
        try:
            doc = json.loads(t)
        except (ValueError, TypeError):
            continue
        for con in _conexiones(doc):
            reconocido = True
            for edge in con["edges"]:
                nodo = edge.get("node") if isinstance(edge, dict) else None
                resultados = nodo.get("collated_results") if isinstance(nodo, dict) else None
                if not isinstance(resultados, list):
                    raise FormatoDesconocido("edge sin collated_results")
                for r in resultados:
                    a = _anuncio(r, pais)
                    vistos.setdefault(a.library_id, a)
    if not reconocido:
        raise FormatoDesconocido("ninguna respuesta trae search_results_connection")
    return list(vistos.values())


# --- Marcadores de texto (español e inglés) -----------------------------------------------

_TOTAL = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:results?|resultados?)\b", re.IGNORECASE
)
_SIN_RESULTADOS = re.compile(
    r"no hay ning[uú]n anuncio|no hay anuncios que coincidan|no ads match|no ads? (?:were )?found|no results? match",
    re.IGNORECASE,
)


def total_aproximado(texto: str) -> int | None:
    """Total que muestra Meta: «~1,700 results», «~1.700 resultados», «>50.000 resultados» (50000).

    Devuelve el número tal cual lo muestra Meta (un «>» no se modela como cota). Si el texto no
    tiene un número reconocible, ``None``.
    """
    m = _TOTAL.search(_html.unescape(texto or ""))
    if not m:
        return None
    return int(re.sub(r"[.,]", "", m.group(1)))


def sin_resultados(texto: str) -> bool:
    """¿Dice la página que ningún anuncio coincide con la búsqueda?"""
    return bool(_SIN_RESULTADOS.search(_html.unescape(texto or "")))
