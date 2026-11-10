"""Base común de los hooks de Trovify. Solo biblioteca estándar; falla cerrado.

Formato (docs de Claude Code, PreToolUse): entrada JSON por stdin con
``tool_name``, ``tool_input`` y ``cwd``; para denegar se imprime
``{"hookSpecificOutput": {"hookEventName": "PreToolUse",
"permissionDecision": "deny", "permissionDecisionReason": ...}}`` y se sale
con código 0. Salir con 0 sin imprimir nada es «allow» (sin decisión).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from collections.abc import Callable
from typing import NoReturn


class EntradaIlegible(Exception):
    """La entrada del hook no es un objeto JSON válido."""


def leer_entrada() -> dict:
    try:
        crudo = sys.stdin.buffer.read().decode("utf-8")
    except Exception as exc:
        raise EntradaIlegible("stdin no legible") from exc
    if not crudo.strip():
        raise EntradaIlegible("stdin vacío")
    try:
        datos = json.loads(crudo)
    except ValueError as exc:
        raise EntradaIlegible("no es JSON") from exc
    if not isinstance(datos, dict):
        raise EntradaIlegible("no es un objeto JSON")
    return datos


def herramienta(entrada: dict) -> tuple[str, dict]:
    nombre = entrada.get("tool_name")
    datos = entrada.get("tool_input")
    if not isinstance(nombre, str) or not nombre:
        raise EntradaIlegible("falta tool_name")
    if not isinstance(datos, dict):
        raise EntradaIlegible("tool_input no es un objeto")
    return nombre, datos


def vault_root() -> pathlib.Path:
    valor = os.environ.get("TROVIFY_VAULT")
    if valor:
        return pathlib.Path(valor).expanduser()
    return pathlib.Path("~/trovify-cerebro").expanduser()


def stop_activo(vault: pathlib.Path) -> bool:
    return (vault / ".trovify" / "STOP").exists()


def resolver(ruta: str, cwd: str | None) -> pathlib.Path:
    p = pathlib.Path(ruta).expanduser()
    if not p.is_absolute():
        p = pathlib.Path(cwd or os.getcwd()) / p
    return p.resolve(strict=False)


def _emitir_deny(motivo: str) -> NoReturn:
    salida = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": motivo,
        }
    }
    sys.stdout.write(json.dumps(salida))
    sys.stdout.flush()
    sys.exit(0)


def ejecutar_guardia(decidir: Callable[[dict], tuple[str, str]]) -> NoReturn:
    """Llama a ``decidir(entrada)`` y emite la decisión; ante cualquier duda, deny."""
    try:
        decision, motivo = decidir(leer_entrada())
        if decision not in ("allow", "deny"):
            raise ValueError("decisión no válida")
    except EntradaIlegible as exc:
        _emitir_deny(f"entrada ilegible: {exc}")
    except Exception as exc:  # noqa: BLE001 - fail-closed: cualquier fallo deniega
        _emitir_deny(f"fallo interno del hook: {type(exc).__name__}")
    if decision == "deny":
        _emitir_deny(motivo or "denegado por política de Trovify")
    sys.exit(0)
