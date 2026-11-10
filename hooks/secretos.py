"""Hook PreToolUse: ningún token o clave se escribe fuera de los .env (§5.10).

Alcance (el plugin corre en todos los proyectos del usuario): las escrituras
(Write/Edit/MultiEdit/NotebookEdit) se revisan solo si el destino resuelto está
en el vault, en el repo de Trovify (``CLAUDE_PLUGIN_ROOT``) o en
``~/.config/trovify/``; allí los ``*.env`` están exentos. Bash se revisa en
cualquier cwd, pero solo con los patrones de token de Meta y de bot de
Telegram. El motivo nombra el patrón, jamás el valor. Solo biblioteca estándar;
falla cerrado.
"""
from __future__ import annotations

import os
import pathlib
import re

from _comun import ejecutar_guardia, herramienta, resolver, vault_root

PATRONES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("token de Meta", re.compile(r"EAA[A-Za-z0-9]{20,}")),
    # Con o sin prefijo «bot»: no se exige \b antes de los dígitos.
    ("token de bot de Telegram", re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("clave sk-", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("access_token=", re.compile(r"access_token=")),
)


_NOMBRES_BASH = ("token de Meta", "token de bot de Telegram")
_NOMBRE_MENCION = "access_token="

# Por nombre, no por posición: reordenar PATRONES no cambia qué escanea cada consumidor.
PATRONES_BASH = tuple(p for p in PATRONES if p[0] in _NOMBRES_BASH)
PATRONES_TOKEN = tuple(p for p in PATRONES if p[0] != _NOMBRE_MENCION)


def buscar_secreto(texto: str, patrones=PATRONES) -> str | None:
    for nombre, patron in patrones:
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


def _config_trovify() -> pathlib.Path | None:
    home = os.environ.get("HOME")
    if not home:
        return None
    return pathlib.Path(home, ".config", "trovify").resolve(strict=False)


def _raices_protegidas() -> list[pathlib.Path]:
    raices = [vault_root().resolve(strict=False)]
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin:
        raices.append(pathlib.Path(plugin).expanduser().resolve(strict=False))
    config = _config_trovify()
    if config is not None:
        raices.append(config)
    return raices


def _dentro(destino: pathlib.Path, raiz: pathlib.Path) -> bool:
    return destino == raiz or raiz in destino.parents


def _en_alcance(destino: pathlib.Path) -> bool:
    return any(_dentro(destino, r) for r in _raices_protegidas())


def _es_env_permitido(destino: pathlib.Path) -> bool:
    config = _config_trovify()
    return config is not None and destino.name.endswith(".env") and config in destino.parents


def decidir(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    for ruta, texto in textos_a_revisar(nombre, datos):
        if ruta is None:  # Bash: cualquier cwd, solo tokens de Meta y Telegram
            patron = buscar_secreto(texto, PATRONES_BASH)
        else:
            destino = resolver(ruta, cwd)
            if not _en_alcance(destino) or _es_env_permitido(destino):
                continue
            patron = buscar_secreto(texto)
        if patron:
            return "deny", (
                f"secreto detectado: {patron}; los secretos solo van en "
                "~/.config/trovify/*.env"
            )
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(decidir)
