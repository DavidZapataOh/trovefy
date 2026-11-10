"""Hook PreToolUse: con ``<vault>/.trovify/STOP`` no se deposita nada (§5.9).

Deniega escribir en ``/var/spool/trovify/`` y en ``<vault>/propuestas/``.
Las rutas se comparan resueltas. Las lecturas nunca se bloquean. Solo
biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

import pathlib
import re

from _comun import (
    bases_vault,
    bash_destructivo,
    bash_toca_protegidas,
    directorios_efectivos,
    ejecutar_guardia,
    herramienta,
    resolver,
    stop_activo,
    vault_root,
)

MOTIVO = "STOP activo: no se deposita nada (ni en el buzón ni en propuestas/)"
SPOOL = pathlib.Path("/var/spool/trovify")


def _cadena(valor: object) -> str:
    return valor if isinstance(valor, str) else ""


_ESCRIBE = re.compile(r"\b(?:touch|mkdir|dd|rsync|tee)\b|>>")
_SOLO_LECTURA = frozenset(
    {"ls", "cat", "head", "tail", "less", "wc", "grep", "find", "stat", "pwd", "echo", "cd", "pushd"}
)
_REDIRECCION_INOFENSIVA = re.compile(r"\d?>\s*/dev/null|\d>&\d|>&-")
_FIND_PELIGROSO = re.compile(r"-(?:delete|exec|execdir|ok|okdir|fprint\w*|fls)\b")
_SEGMENTOS = re.compile(r"&&|\|\||[;|\n]")


def _solo_lectura(comando: str) -> bool:
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


def _bash_menciona(original: str, vault: pathlib.Path, vault_res: pathlib.Path, cwd: str | None) -> bool:
    for comando in (original, re.sub(r"[\"']", "", original)):
        if "/var/spool/trovify" in comando:
            return True
    sin_comillas = re.sub(r"[\"']", "", original)
    bases = bases_vault(vault, vault_res)
    if any(b + "/propuestas" in sin_comillas for b in bases):
        return True
    propuestas = vault_res / "propuestas"
    en_propuestas = any(
        d == propuestas or propuestas in d.parents
        for d in directorios_efectivos(sin_comillas, bases, vault_res, cwd)
    )
    if en_propuestas:
        # Con el directorio efectivo dentro de propuestas/ solo se deja pasar lo de solo lectura.
        return not _solo_lectura(sin_comillas)
    if not bash_toca_protegidas(original, vault, vault_res, cwd, ("propuestas",)):
        return False
    # Alcanzada por ruta relativa: solo se deniega lo que escribe.
    return bash_destructivo(original) or bool(_ESCRIBE.search(original))


def decidir(tool_name: str, tool_input: dict, vault: pathlib.Path, cwd: str | None = None) -> tuple[str, str]:
    if not stop_activo(vault):
        return "allow", ""
    vault_res = vault.resolve(strict=False)
    if tool_name == "Bash":
        if _bash_menciona(_cadena(tool_input.get("command")), vault, vault_res, cwd):
            return "deny", MOTIVO
        return "allow", ""
    if tool_name in ("Write", "Edit", "MultiEdit"):
        ruta = _cadena(tool_input.get("file_path"))
        if ruta:
            destino = resolver(ruta, cwd)
            prohibidos = (SPOOL.resolve(strict=False), vault_res / "propuestas")
            if any(p == destino or p in destino.parents for p in prohibidos):
                return "deny", MOTIVO
    return "allow", ""


def _decidir_evento(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    return decidir(nombre, datos, vault_root(), cwd)


if __name__ == "__main__":
    ejecutar_guardia(_decidir_evento)
