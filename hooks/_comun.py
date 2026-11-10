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


def bases_vault(vault: pathlib.Path, vault_res: pathlib.Path) -> set[str]:
    """Todas las grafías posibles de la ruta del vault dentro de un comando."""
    bases = {str(vault), str(vault_res), "$TROVIFY_VAULT", "${TROVIFY_VAULT}"}
    literal = os.environ.get("TROVIFY_VAULT")
    if literal:
        bases.add(literal)
        bases.add(os.path.expandvars(literal))
        bases.add(os.path.expanduser(os.path.expandvars(literal)))
    home = os.environ.get("HOME") or os.path.expanduser("~")
    home = home.rstrip("/")
    for base in list(bases):
        if home and base.startswith(home + "/"):
            resto = base[len(home):]
            bases.update({"~" + resto, "$HOME" + resto, "${HOME}" + resto})
    return {b.rstrip("/") for b in bases if b.rstrip("/")}


_DENY_FIJO = (
    '{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
    '"permissionDecision": "deny", '
    '"permissionDecisionReason": "fallo interno del hook al emitir la decisi\\u00f3n"}}'
)


def _salir_bloqueando(motivo: str) -> NoReturn:
    """Último recurso: código 2 con stderr bloquea aunque stdout falle."""
    try:
        sys.stderr.write(f"trovify hook: {motivo}\n")
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001, S110 - no hay nada más que hacer
        pass
    os._exit(2)


def _diagnostico(texto: str) -> None:
    try:
        sys.stderr.write(f"trovify hook: {texto}\n")
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001, S110
        pass


def _emitir(decision: str, motivo: str) -> NoReturn:
    """Deny normal: JSON por stdout y código 0. Allow: código 0 sin salida."""
    if decision == "allow":
        sys.exit(0)
    try:
        try:
            texto = json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": motivo,
                    }
                }
            )
        except BaseException:  # noqa: BLE001
            texto = _DENY_FIJO
        sys.stdout.write(texto)
        sys.stdout.flush()
    except BaseException:  # noqa: BLE001
        _salir_bloqueando("no se pudo emitir la denegación: " + motivo)
    sys.exit(0)


def ejecutar_guardia(decidir: Callable[[dict], tuple[str, str]]) -> NoReturn:
    """Llama a ``decidir(entrada)`` y emite la decisión; ante cualquier duda, deny."""
    try:
        decision, motivo = decidir(leer_entrada())
        if decision not in ("allow", "deny") or not isinstance(motivo, str):
            raise ValueError("decisión no válida")
    except EntradaIlegible as exc:
        decision, motivo = "deny", f"entrada ilegible: {exc}"
    except BaseException as exc:  # noqa: BLE001 - fail-closed: cualquier fallo deniega
        decision, motivo = "deny", f"fallo interno del hook: {type(exc).__name__}"
        _diagnostico(motivo)
    if decision == "deny" and not motivo:
        motivo = "denegado por política de Trovify"
    _emitir(decision, motivo)
