"""Lectura y escritura de Markdown con frontmatter YAML."""

import re
from pathlib import Path

import yaml

from trovefy.vault.escritura import escribir_atomico

_APERTURA = re.compile(r"---\r?\n")
_CIERRE = re.compile(r"\r?\n---\r?\n")


def leer(ruta: Path) -> tuple[dict, str]:
    texto = Path(ruta).read_text(encoding="utf-8")
    abre = _APERTURA.match(texto)
    if not abre:
        return {}, texto
    resto = texto[abre.end():]
    vacio = _APERTURA.match(resto)
    if vacio:
        return {}, resto[vacio.end():]
    cierre = _CIERRE.search(resto)
    if cierre is None:
        return {}, texto
    meta = yaml.safe_load(resto[: cierre.start()]) or {}
    return meta, resto[cierre.end():]


def renderizar(meta: dict, cuerpo: str) -> str:
    yaml_txt = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{yaml_txt}---\n{cuerpo}"


def escribir(ruta: Path, meta: dict, cuerpo: str) -> None:
    escribir_atomico(ruta, renderizar(meta, cuerpo))
