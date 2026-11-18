"""Validación de los emails del checkout (plan 19, Tarea 10).

Los textos los escribe Claude en la sesión, en ``productos/<p-id>/checkout/<PAIS>/emails/<clave>.md`` (frontmatter
con ``asunto`` y el cuerpo en el idioma del país); el código solo valida: idioma y sin secretos. Por el ruling del
2026-11-17 solo se usa ``entrega``; el de ``seguimiento_72h`` (pedir una reseña) queda como opción del plan.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import yaml

from trovefy.idioma import detectar
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter

CLAVES_EMAIL: tuple[str, ...] = ("entrega", "seguimiento_72h")


def ruta_email(carpeta_pais: Path, clave: str) -> Path:
    """``checkout/<PAIS>/emails/<clave>.md`` dentro de la carpeta del país (`trovefy.embudo.contexto.ruta_pais`)."""
    if clave not in CLAVES_EMAIL:
        raise ValueError(f"email desconocido: {clave!r} ({', '.join(CLAVES_EMAIL)})")
    return Path(carpeta_pais) / "emails" / f"{clave}.md"


def validar_email(ruta: Path, idioma: str, clave: str) -> list[str]:
    """Problemas del email ``clave`` en ``ruta``; ``[]`` = bien. ``ValueError`` si la clave no es de `CLAVES_EMAIL`."""
    if clave not in CLAVES_EMAIL:
        raise ValueError(f"email desconocido: {clave!r} ({', '.join(CLAVES_EMAIL)})")
    ruta = Path(ruta)
    try:
        modo = os.lstat(ruta).st_mode
    except FileNotFoundError:
        return [f"no existe el email {clave} ({ruta.name})"]
    if stat.S_ISLNK(modo):
        return [f"el email {clave} es un enlace: escribe el archivo de verdad"]
    if not stat.S_ISREG(modo):
        return [f"el email {clave} no es un archivo"]
    try:
        meta, cuerpo = frontmatter.leer(ruta)
    except (OSError, ValueError, UnicodeDecodeError, yaml.YAMLError) as e:
        return [f"el email {clave} no se puede leer ({type(e).__name__})"]
    meta = meta if isinstance(meta, dict) else {}
    asunto = meta.get("asunto")
    asunto = asunto.strip() if isinstance(asunto, str) else ""
    cuerpo = (cuerpo or "").strip()
    problemas: list[str] = []
    if not asunto:
        problemas.append("falta el asunto (frontmatter «asunto»)")
    if not cuerpo:
        problemas.append("el cuerpo está vacío")
    texto = f"{asunto}\n{cuerpo}"
    secreto = buscar_secreto(texto)
    if secreto:
        problemas.append(f"aparece un secreto ({secreto}): no se usa")
    if cuerpo:
        visto = detectar(cuerpo, sorted({idioma, "es", "en"}))
        if visto is None:
            problemas.append(f"no se reconoce el idioma del cuerpo (se espera {idioma})")
        elif visto != idioma:
            problemas.append(f"el idioma del cuerpo es {visto}, no {idioma}")
    return problemas
