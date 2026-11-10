"""Destilado: validación de citas en las páginas de ``wiki/metodo/``."""

import posixpath
import re
from pathlib import Path

import yaml

from trovify.vault.frontmatter import leer

CITA = re.compile(
    r"(?<![A-Za-z0-9])(?:T[1-3]|[SCLV][1-2])\s\d{1,2}:\d{2}(?::\d{2})?(?!\d)"
    r"|§\d+(?:\.\d+)*"
    r"|(?<![^\s(\[`])raw/\S+?\.md"
)
_SECCION = re.compile(r"^## (.*?)\s*$", re.MULTILINE)



def _norm(entrada) -> str | None:
    if not isinstance(entrada, str) or not entrada.strip():
        return None
    return posixpath.normpath(entrada.strip().replace("\\", "/"))


def _fuentes(meta: dict) -> list[str]:
    bruto = meta.get("fuentes")
    if isinstance(bruto, str):
        bruto = [bruto]
    if not isinstance(bruto, list):
        return []
    return [n for n in (_norm(e) for e in bruto) if n]


def _paginas_metodo(vault: Path) -> list[Path]:
    base = vault / "wiki" / "metodo"
    return sorted(base.rglob("*.md")) if base.is_dir() else []


def pendientes(vault: Path) -> list[Path]:
    """Archivos de ``raw/`` que ninguna página de ``wiki/metodo/`` lista en ``fuentes``."""
    vault = Path(vault)
    citadas: set[str] = set()
    for p in _paginas_metodo(vault):
        try:
            meta, _ = leer(p)
        except (OSError, yaml.YAMLError):
            continue
        citadas.update(_fuentes(meta))
    raw = vault / "raw"
    if not raw.is_dir():
        return []
    return [
        f for f in sorted(raw.rglob("*.md"))
        if f.is_file() and f.relative_to(vault).as_posix() not in citadas
    ]


def validar_pagina(vault: Path, ruta: Path) -> list[str]:
    vault, ruta = Path(vault), Path(ruta)
    nombre = ruta.relative_to(vault).as_posix() if ruta.is_relative_to(vault) else ruta.as_posix()
    try:
        meta, cuerpo = leer(ruta)
    except (OSError, yaml.YAMLError) as exc:
        return [f"{nombre}: no se pudo leer ({exc})"]
    if not isinstance(meta, dict):
        meta = {}
    problemas = []
    if meta.get("tipo") != "metodo":
        problemas.append(f"{nombre}: falta «tipo: metodo» en el frontmatter")
    if not meta.get("fecha"):
        problemas.append(f"{nombre}: falta «fecha» en el frontmatter")
    fuentes = _fuentes(meta)
    if not fuentes:
        problemas.append(f"{nombre}: falta «fuentes» en el frontmatter")
    raiz = vault.resolve()
    for f in fuentes:
        destino = (raiz / f).resolve()
        if f.startswith("/") or not destino.is_relative_to(raiz) or not destino.is_file():
            problemas.append(f"{nombre}: la fuente «{f}» no existe en el vault")
    for m in CITA.finditer(cuerpo):
        c = m.group(0)
        if c.startswith("raw/") and not (raiz / c).resolve().is_relative_to(raiz) or (
            c.startswith("raw/") and not (raiz / c).is_file()
        ):
            problemas.append(f"{nombre}: la cita «{c}» no existe en el vault")
    marcas = list(_SECCION.finditer(cuerpo))
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(cuerpo)
        if not CITA.search(cuerpo[m.end():fin]):
            problemas.append(f"{nombre}: la sección «{m.group(1)}» no tiene ninguna cita")
    return problemas


def validar_todo(vault: Path) -> list[str]:
    problemas: list[str] = []
    for p in _paginas_metodo(Path(vault)):
        problemas.extend(validar_pagina(vault, p))
    return problemas
