"""Hook PreToolUse: ``raw/`` es inmutable y ``log.md`` solo se amplía (§3.3, §5.10).

Las rutas se comparan resueltas (``..`` y enlaces simbólicos incluidos), y por
ancestros de ruta, no por prefijo de texto. Solo biblioteca estándar; falla
cerrado.
"""
from __future__ import annotations

import pathlib

from _comun import (
    bash_destructivo,
    bash_toca_protegidas,
    ejecutar_guardia,
    herramienta,
    resolver,
    vault_root,
)

MOTIVO_RAW = "raw/ es inmutable: no se editan fuentes existentes"
MOTIVO_LOG = "log.md solo se amplía: no se reescribe ni se borra contenido"

def _cadena(valor: object) -> str:
    return valor if isinstance(valor, str) else ""


def _en_raw(destino: pathlib.Path, raw: pathlib.Path) -> bool:
    return raw in destino.parents


def _solo_amplia(actual: str, nuevo: str) -> bool:
    return nuevo.startswith(actual)


def _edicion_solo_amplia(actual: str, e: object) -> str | None:
    """Devuelve el contenido tras la edición, o None si no es una ampliación al final."""
    if not isinstance(e, dict):
        return None
    viejo, nuevo = _cadena(e.get("old_string")), _cadena(e.get("new_string"))
    if e.get("replace_all"):
        return None
    if not viejo or actual.count(viejo) != 1 or not actual.endswith(viejo) or not nuevo.startswith(viejo):
        return None
    return actual[: len(actual) - len(viejo)] + nuevo


def decidir(tool_name: str, tool_input: dict, cwd: str | None, vault: pathlib.Path) -> tuple[str, str]:
    vault_res = vault.resolve(strict=False)
    raw = vault_res / "raw"
    log = vault_res / "log.md"

    if tool_name == "Bash":
        comando = _cadena(tool_input.get("command"))
        if bash_destructivo(comando) and bash_toca_protegidas(comando, vault, vault_res, cwd, ("raw", "log.md")):
            return "deny", "raw/ es inmutable y log.md solo se amplía: comando destructivo sobre ellos"
        return "allow", ""

    if tool_name == "NotebookEdit":
        ruta = _cadena(tool_input.get("notebook_path"))
        if ruta:
            destino = resolver(ruta, cwd)
            if _en_raw(destino, raw) and destino.exists():
                return "deny", MOTIVO_RAW
        return "allow", ""

    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return "allow", ""
    ruta = _cadena(tool_input.get("file_path"))
    if not ruta:
        return "allow", ""
    destino = resolver(ruta, cwd)

    if _en_raw(destino, raw):
        if tool_name == "Write":
            if destino.exists() or destino.is_symlink():
                return "deny", MOTIVO_RAW
            return "allow", ""
        return "deny", MOTIVO_RAW

    if destino == log:
        if tool_name == "Write":
            if not destino.exists():
                return "allow", ""
            actual = destino.read_text(encoding="utf-8")
            if _solo_amplia(actual, _cadena(tool_input.get("content"))):
                return "allow", ""
            return "deny", MOTIVO_LOG
        if not destino.exists():
            return "deny", MOTIVO_LOG
        actual = destino.read_text(encoding="utf-8")
        if tool_name == "Edit":
            ediciones = [tool_input]
        else:
            ediciones = tool_input.get("edits")
            if not isinstance(ediciones, list) or not ediciones:
                return "deny", MOTIVO_LOG
        for e in ediciones:
            actual = _edicion_solo_amplia(actual, e)
            if actual is None:
                return "deny", MOTIVO_LOG
    return "allow", ""


def _decidir_evento(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    return decidir(nombre, datos, cwd, vault_root())


if __name__ == "__main__":
    ejecutar_guardia(_decidir_evento)
