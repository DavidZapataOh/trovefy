"""Hook PreToolUse: Claude solo deja propuestas NUEVAS y válidas en el buzón del ejecutor.

Protege ``$TROVEFY_SPOOL`` (por defecto ``/var/spool/trovefy``): un ``Write`` solo se permite en
``entrada/P-AAAAMMDD-NNN.json`` (001-799), archivo nuevo, JSON que pasa ``cargar_propuesta`` con
``unidad: "minima"`` y ``id`` igual al nombre. Todo lo demás que escriba en el spool se deniega; con
``<vault>/.trovefy/STOP`` no se deposita nada. Solo biblioteca estándar (sin PyYAML); falla cerrado:
si el esquema no se puede importar o algo se tuerce, deny.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

from _comun import (
    _CD,
    ejecutar_guardia,
    herramienta,
    resolver,
    solo_lectura,
    stop_activo,
    vault_root,
)

MOTIVO_STOP = "STOP activo: no se deposita nada"
SPOOL_POR_DEFECTO = "/var/spool/trovefy"
_NOMBRE = re.compile(r"^P-([0-9]{8})-([0-9]{3})\.json$", re.ASCII)
_ESCRIBEN = ("Write", "Edit", "MultiEdit", "NotebookEdit")

try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta
    _ERROR_ESQUEMA: str | None = None
except BaseException as _exc:  # noqa: BLE001 - fail-closed: sin esquema no se valida, se deniega
    _ERROR_ESQUEMA = type(_exc).__name__


def _cadena(valor: object) -> str:
    return valor if isinstance(valor, str) else ""


def _dentro(ruta: pathlib.Path, base: pathlib.Path) -> bool:
    return ruta == base or base in ruta.parents


def _lexica(ruta: str, cwd: str | None) -> pathlib.Path:
    p = pathlib.Path(ruta).expanduser()
    if not p.is_absolute():
        p = pathlib.Path(cwd or os.getcwd()) / p
    return pathlib.Path(os.path.normpath(p))


def _validar_contenido(nombre: str, contenido: object) -> str | None:
    """Motivo de denegación o None si la propuesta es depositable."""
    if _ERROR_ESQUEMA is not None:
        return "no se pudo validar el esquema"
    m = _NOMBRE.match(nombre)
    if not m:
        return "el nombre debe ser P-AAAAMMDD-NNN.json"
    if not 1 <= int(m.group(2)) <= 799:
        return "el número del id debe estar entre 001 y 799"
    if not isinstance(contenido, str):
        return "contenido no es texto"
    try:
        datos = json.loads(contenido)
    except (ValueError, RecursionError):
        return "el contenido no es JSON válido"
    if not isinstance(datos, dict):
        return "el contenido debe ser un objeto JSON"
    ops = datos.get("operaciones")
    if isinstance(ops, list):
        for op in ops:
            if isinstance(op, dict) and "unidad" in op and op["unidad"] != "minima":
                return 'unidad: debe ser "minima"'
    try:
        cargar_propuesta(datos)
    except PropuestaInvalida as exc:
        return f"propuesta inválida: {exc.motivo}"
    if datos.get("id") != nombre[: -len(".json")]:
        return "el id de la propuesta debe coincidir con el nombre del archivo"
    return None


def _decidir_escritura(
    tool_name: str, tool_input: dict, spool: pathlib.Path, spool_res: pathlib.Path, vault: pathlib.Path,
    cwd: str | None,
) -> tuple[str, str]:
    ruta = _cadena(tool_input.get("file_path")) or _cadena(tool_input.get("notebook_path"))
    if not ruta:
        return "allow", ""
    lexica = _lexica(ruta, cwd)
    real = resolver(ruta, cwd)
    en_lexico = _dentro(lexica, spool) or _dentro(lexica, spool_res)
    if not (en_lexico or _dentro(real, spool_res)):
        return "allow", ""
    if stop_activo(vault):
        return "deny", MOTIVO_STOP
    if tool_name != "Write":
        return "deny", "el buzón es de solo escritura nueva: usa `trovefy buzon depositar`"
    entrada = spool_res / "entrada"
    if real.parent != entrada or lexica.parent not in (spool / "entrada", entrada):
        return "deny", "solo se escribe en entrada/ del buzón: usa `trovefy buzon depositar`"
    if os.path.lexists(real) or os.path.lexists(lexica):
        return "deny", "el buzón admite solo archivos nuevos (no se sobrescribe)"
    motivo = _validar_contenido(real.name, tool_input.get("content"))
    return ("deny", motivo) if motivo else ("allow", "")


def _menciona_spool(comando: str, spool: pathlib.Path, spool_res: pathlib.Path, cwd: str | None) -> bool:
    sin_comillas = re.sub(r"[\"']", "", comando)
    marcas = {str(spool), str(spool_res), SPOOL_POR_DEFECTO, "$TROVEFY_SPOOL", "${TROVEFY_SPOOL}"}
    if any(m.rstrip("/") in sin_comillas for m in marcas if m.rstrip("/")):
        return True
    actual = resolver(cwd, None) if cwd else None
    if actual is not None and _dentro(actual, spool_res):
        return True
    for m in _CD.finditer(sin_comillas):
        destino = m.group(1)
        if destino.startswith("$") or destino == "-":
            if destino.startswith("$"):
                return True  # destino no resoluble: se asume lo peor
            continue
        actual = resolver(destino, str(actual) if actual else cwd)
        if _dentro(actual, spool_res):
            return True
    return False


def decidir(
    tool_name: str, tool_input: dict, vault: pathlib.Path, spool: pathlib.Path, cwd: str | None = None
) -> tuple[str, str]:
    spool = pathlib.Path(spool)
    spool_res = spool.resolve(strict=False)
    if tool_name in _ESCRIBEN:
        return _decidir_escritura(tool_name, tool_input, spool, spool_res, vault, cwd)
    if tool_name == "Bash":
        comando = _cadena(tool_input.get("command"))
        if _menciona_spool(comando, spool, spool_res, cwd):
            if stop_activo(vault) and not solo_lectura(comando):
                return "deny", MOTIVO_STOP
            if solo_lectura(comando):
                return "allow", ""
            return "deny", "el buzón no se toca por shell: usa `trovefy buzon depositar`"
        if stop_activo(vault) and re.search(r"\btrovefy\s+buzon\s+depositar\b", comando):
            return "deny", MOTIVO_STOP
    return "allow", ""


def _decidir_evento(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    spool = pathlib.Path(os.environ.get("TROVEFY_SPOOL") or SPOOL_POR_DEFECTO)
    return decidir(nombre, datos, vault_root(), spool, cwd)


if __name__ == "__main__":
    ejecutar_guardia(_decidir_evento)
