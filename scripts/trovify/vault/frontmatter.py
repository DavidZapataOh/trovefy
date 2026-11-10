"""Lectura y escritura de Markdown con frontmatter YAML."""

from pathlib import Path

import yaml

from trovify.vault.escritura import escribir_atomico

_LIMITE = "---\n"


def leer(ruta: Path) -> tuple[dict, str]:
    texto = Path(ruta).read_text(encoding="utf-8")
    if not texto.startswith(_LIMITE):
        return {}, texto
    resto = texto[len(_LIMITE):]
    if resto.startswith(_LIMITE):
        return {}, resto[len(_LIMITE):]
    fin = resto.find("\n" + _LIMITE)
    if fin == -1:
        return {}, texto
    meta = yaml.safe_load(resto[: fin + 1]) or {}
    return meta, resto[fin + 1 + len(_LIMITE):]


def renderizar(meta: dict, cuerpo: str) -> str:
    yaml_txt = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{yaml_txt}---\n{cuerpo}"


def escribir(ruta: Path, meta: dict, cuerpo: str) -> None:
    escribir_atomico(ruta, renderizar(meta, cuerpo))
