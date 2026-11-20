"""``TANDA.md``: la ficha de la tanda y su estado (tipo, aprobación del coste, rehacer). Solo lo escribe
``trovefy creativos``.

El frontmatter guarda el estado (``tipo: test|renovacion``, ``aprobacion``, ``rehacer``, ``plan_renovacion``); el
cuerpo es la ficha (la reescribe ``trovefy creativos brief``) y, debajo de ``## Historial``, las anotaciones.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, escribir_atomico
from trovefy.vault.producto import secreto_en

NOMBRE = "TANDA.md"
HISTORIAL = "## Historial"


def ruta(carpeta: Path) -> Path:
    return Path(carpeta) / NOMBRE


def leer(carpeta: Path) -> tuple[dict, str, list[str]]:
    """(meta, ficha, líneas del historial). Sin ``TANDA.md``: ``({}, "", [])``."""
    r = ruta(carpeta)
    if not r.is_file():
        return {}, "", []
    try:
        meta, cuerpo = frontmatter.leer(r)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{NOMBRE} no se puede leer ({type(exc).__name__})") from None
    ficha, _, hist = cuerpo.partition(f"\n{HISTORIAL}\n")
    return (meta if isinstance(meta, dict) else {}), ficha.rstrip("\n"), [x for x in hist.splitlines() if x.strip()]


def guardar(carpeta: Path, meta: dict, ficha: str, historial: list[str]) -> Path:
    cuerpo = ficha.rstrip("\n") + f"\n\n{HISTORIAL}\n\n" + "\n".join(historial) + "\n"
    texto = frontmatter.renderizar(meta, cuerpo)
    if secreto_en(meta) or buscar_secreto(texto):
        raise ValueError(f"{NOMBRE} traería algo con forma de secreto; no se escribe")
    r = ruta(carpeta)
    escribir_atomico(r, texto)
    return r


def actualizar(carpeta: Path, cambios: dict, linea: str | None, ahora: datetime) -> Path:
    """Fusiona ``cambios`` en el frontmatter (sustituye claves de primer nivel) y añade ``linea`` al historial."""
    meta, ficha, hist = leer(carpeta)
    meta = {**meta, **cambios}
    if linea:
        hist.append(f"- {ahora.astimezone(ZONA_NEGOCIO):%Y-%m-%d %H:%M} · {linea}")
    if not ficha:
        ficha = f"# Tanda {Path(carpeta).name}"
    return guardar(carpeta, meta, ficha, hist)


def tipo(carpeta: Path) -> str:
    meta, _, _ = leer(carpeta)
    return "renovacion" if meta.get("tipo") == "renovacion" else "test"
