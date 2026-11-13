"""Base común de los hooks de Trovefy. Solo biblioteca estándar; falla cerrado.

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
import re
import sys
from collections.abc import Callable
from typing import NoReturn


class EntradaIlegible(Exception):
    """La entrada del hook no es un objeto JSON válido."""


def en_vault(entrada: dict, vault: pathlib.Path) -> bool:
    """¿El ``cwd`` del evento (resuelto) está dentro del vault (resuelto)?"""
    cwd = entrada.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False
    try:
        pathlib.Path(cwd).expanduser().resolve().relative_to(vault.resolve())
    except (ValueError, OSError):
        return False
    return True


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
    valor = os.environ.get("TROVEFY_VAULT")
    if valor:
        return pathlib.Path(valor).expanduser()
    return pathlib.Path("~/trovefy-cerebro").expanduser()


def stop_activo(vault: pathlib.Path) -> bool:
    return (vault / ".trovefy" / "STOP").exists()


def resolver(ruta: str, cwd: str | None) -> pathlib.Path:
    p = pathlib.Path(ruta).expanduser()
    if not p.is_absolute():
        p = pathlib.Path(cwd or os.getcwd()) / p
    return p.resolve(strict=False)


def bases_vault(vault: pathlib.Path, vault_res: pathlib.Path) -> set[str]:
    """Todas las grafías posibles de la ruta del vault dentro de un comando."""
    bases = {str(vault), str(vault_res), "$TROVEFY_VAULT", "${TROVEFY_VAULT}"}
    literal = os.environ.get("TROVEFY_VAULT")
    if literal:
        bases.add(literal)
        bases.add(os.path.expandvars(literal))
        bases.add(os.path.expanduser(os.path.expandvars(literal)))
    home = os.environ.get("HOME") or os.path.expanduser("~")
    home = home.rstrip("/")
    for base in tuple(bases):  # copia: el conjunto se amplía dentro del bucle
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
        sys.stderr.write(f"trovefy hook: {motivo}\n")
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001, S110 - no hay nada más que hacer
        pass
    os._exit(2)


def _diagnostico(texto: str) -> None:
    try:
        sys.stderr.write(f"trovefy hook: {texto}\n")
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
        motivo = "denegado por política de Trovefy"
    _emitir(decision, motivo)


# --- Detección de Bash que alcanza rutas protegidas del vault -----------------

_CD = re.compile(r"\b(?:cd|pushd)\s+(?:--\s+)?([^\s;&|()]+)")
_SEPARADORES = re.compile(r"[\s;&|()<>`=]+")
_OPERADORES_DESTRUCTIVOS = re.compile(
    r"\brm\b|\bmv\b|\btruncate\b|\bchmod\b|\bln\b"
    r"|\b(?:cp|install)\b|(?<!>)>(?!>|&[\d-])"
)
_SED = re.compile(r"\bsed\b")
_SED_INPLACE = re.compile(r"(?<![\w-])(?:-[a-zA-Z]*i|--in-place)")
_TEE = re.compile(r"\btee\b((?:\s+-\S+)*)")
_TEE_APPEND = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*a[a-zA-Z]*|--append)(?=\s|$)")


def bash_destructivo(comando: str) -> bool:
    if _OPERADORES_DESTRUCTIVOS.search(comando):
        return True
    if _SED.search(comando) and _SED_INPLACE.search(comando):
        return True
    return any(not _TEE_APPEND.search(m.group(1)) for m in _TEE.finditer(comando))


def _dentro(ruta: pathlib.Path, protegida: pathlib.Path) -> bool:
    return ruta == protegida or protegida in ruta.parents


def _destino_cd(destino: str, bases: set[str], vault_res: pathlib.Path) -> str | None:
    """Traduce ``~``, ``$HOME`` y las grafías del vault a una ruta; None si no se sabe."""
    for base in sorted(bases, key=len, reverse=True):
        if destino == base or destino.startswith(base + "/"):
            return str(vault_res) + destino[len(base):]
    home = (os.environ.get("HOME") or os.path.expanduser("~")).rstrip("/")
    for prefijo in ("${HOME}", "$HOME", "~"):
        if destino == prefijo or destino.startswith(prefijo + "/"):
            return home + destino[len(prefijo):] if home else None
    if destino.startswith("$") or destino == "-":
        return None
    return destino


def directorios_efectivos(
    comando: str, bases: set[str], vault_res: pathlib.Path, cwd: str | None
) -> list[pathlib.Path]:
    """Directorios del vault por los que pasa el comando: el cwd y cada ``cd``/``pushd``.

    Se recorre la cadena de ``cd`` en orden, cada destino resuelto contra el
    anterior; un destino que no se sabe resolver se ignora.
    """
    actual = resolver(cwd, None) if cwd else None
    recorrido = [actual] if actual is not None else []
    for m in _CD.finditer(comando):
        destino = _destino_cd(m.group(1), bases, vault_res)
        if destino is None:
            continue
        actual = resolver(destino, str(actual) if actual else None)
        recorrido.append(actual)
    return [d for d in recorrido if _dentro(d, vault_res)]


def bash_toca_protegidas(
    original: str,
    vault: pathlib.Path,
    vault_res: pathlib.Path,
    cwd: str | None,
    protegidas: tuple[str, ...],
) -> bool:
    """¿El comando alcanza alguna ruta ``<vault>/<protegida>``?

    Cubre rutas absolutas (todas las grafías del vault), cwd dentro del vault
    o de una protegida, ``cd`` al vault o a un subdirectorio, y rutas relativas
    con ``..`` resueltas contra ese directorio.
    """
    bases = bases_vault(vault, vault_res)
    comando = re.sub(r"[\"']", "", original)
    for base in bases:
        if any(f"{base}/{nombre}" in comando for nombre in protegidas):
            return True
    rutas = [vault_res / nombre for nombre in protegidas]
    for efectivo in directorios_efectivos(comando, bases, vault_res, cwd):
        if any(_dentro(efectivo, r) for r in rutas):
            return True
        for ficha in _SEPARADORES.split(comando):
            if not ficha or ficha.startswith(("-", "~", "$")):
                continue
            destino = resolver(ficha, str(efectivo))
            if any(_dentro(destino, r) for r in rutas):
                return True
    return False


# --- Comandos de solo lectura (lista blanca) ---------------------------------------------------

_SOLO_LECTURA = frozenset(
    {"ls", "cat", "head", "tail", "less", "wc", "grep", "find", "stat", "pwd", "echo", "cd", "pushd"}
)
_REDIRECCION_INOFENSIVA = re.compile(r"\d?>\s*/dev/null|\d>&\d|>&-")
_FIND_PELIGROSO = re.compile(r"-(?:delete|exec|execdir|ok|okdir|fprint\w*|fls)\b")
_SEGMENTOS = re.compile(r"&&|\|\||[;|\n]")


def solo_lectura(comando: str) -> bool:
    """¿Todo el comando es de la lista blanca de solo lectura, sin redirecciones?"""
    limpio = _REDIRECCION_INOFENSIVA.sub(" ", comando)
    if any(c in limpio for c in ("<", ">", "`", "$(")) or "&" in limpio.replace("&&", ""):
        return False
    for segmento in _SEGMENTOS.split(limpio):
        fichas = segmento.split()
        if not fichas:
            continue
        if fichas[0] not in _SOLO_LECTURA:
            return False
        if fichas[0] == "find" and _FIND_PELIGROSO.search(segmento):
            return False
    return True
