"""Hook PreToolUse: ningún token o clave se escribe fuera de los .env (§5.10).

Revisa lo que Claude va a escribir o ejecutar. Excepción: la ruta destino
resuelta está dentro de ``~/.config/trovify/`` y acaba en ``.env`` (nunca para
Bash, cuyo destino no se puede determinar). El motivo nombra el patrón, jamás
el valor. Solo biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

import os
import pathlib
import re

from _comun import ejecutar_guardia, herramienta, resolver

PATRONES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("token de Meta", re.compile(r"EAA[A-Za-z0-9]{20,}")),
    # Con o sin prefijo «bot»: no se exige \b antes de los dígitos.
    ("token de bot de Telegram", re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("clave sk-", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("access_token=", re.compile(r"access_token=")),
)


def buscar_secreto(texto: str) -> str | None:
    for nombre, patron in PATRONES:
        if patron.search(texto):
            return nombre
    return None


def _cadena(valor: object) -> str:
    return valor if isinstance(valor, str) else ""


def textos_a_revisar(tool_name: str, tool_input: dict) -> list[tuple[str | None, str]]:
    if tool_name == "Write":
        return [(_cadena(tool_input.get("file_path")) or None, _cadena(tool_input.get("content")))]
    if tool_name == "Edit":
        return [(_cadena(tool_input.get("file_path")) or None, _cadena(tool_input.get("new_string")))]
    if tool_name == "MultiEdit":
        ruta = _cadena(tool_input.get("file_path")) or None
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return []
        return [(ruta, _cadena(e.get("new_string"))) for e in edits if isinstance(e, dict)]
    if tool_name == "NotebookEdit":
        return [(_cadena(tool_input.get("notebook_path")) or None, _cadena(tool_input.get("new_source")))]
    if tool_name == "Bash":
        return [(None, _cadena(tool_input.get("command")))]
    return []


def _es_env_permitido(ruta: str | None, cwd: str | None) -> bool:
    if not ruta:
        return False
    home = os.environ.get("HOME")
    if not home:
        return False
    permitido = pathlib.Path(home, ".config", "trovify").resolve(strict=False)
    destino = resolver(ruta, cwd)
    return destino.name.endswith(".env") and permitido in destino.parents


def decidir(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    for ruta, texto in textos_a_revisar(nombre, datos):
        patron = buscar_secreto(texto)
        if patron and not _es_env_permitido(ruta, cwd):
            return "deny", (
                f"secreto detectado: {patron}; los secretos solo van en "
                "~/.config/trovify/*.env"
            )
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(decidir)
