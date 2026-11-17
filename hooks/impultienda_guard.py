"""Hook PreToolUse (matcher ``mcp__impultienda__.*``): el conector de Impultienda solo con el catálogo clasificado.

Deniega:

- una herramienta que no sea ``lectura`` o ``escritura`` en ``config/impultienda_tools.json`` (``cargar_catalogo``:
  si el catálogo no carga o está mal clasificado, se deniega todo);
- cualquier clave de ``tool_input`` (recursiva) que no esté en el esquema catalogado, y lo que prohíben las
  restricciones de la herramienta (parámetros y valores prohibidos, valores obligatorios);
- una ``escritura`` con STOP activo, o que no esté en un ``checkout/<PAIS>/PLAN-MCP.json`` aprobado por el
  ``plan_huella`` de su ``APROBACION.md`` con estos argumentos exactos.

Solo biblioteca estándar (importa ``trovefy.tienda.mcp`` de ``scripts/``, sin YAML); falla cerrado.
"""
from __future__ import annotations

import pathlib
import sys

from _comun import ejecutar_guardia, herramienta, stop_activo, vault_root

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PREFIJO = "mcp__impultienda__"
MOTIVO_STOP = "STOP activo: no se escribe en Impultienda"


def _mcp():
    scripts = str(RAIZ / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from trovefy.tienda import mcp

    return mcp


def clasificar(tool_name: str, tool_input: dict) -> tuple[str, str]:
    if not tool_name.startswith(PREFIJO):
        if tool_name.lower().startswith(PREFIJO):
            return "deny", f"{tool_name}: el conector de Impultienda se llama exactamente {PREFIJO}…"
        return "allow", ""
    nombre = tool_name[len(PREFIJO):]
    mcp = _mcp()
    catalogo = mcp.cargar_catalogo(RAIZ / "config" / "impultienda_tools.json")
    h = catalogo.get(nombre)
    if h is None:
        return "deny", f"{nombre}: no está en el catálogo del conector (config/impultienda_tools.json)"
    if h.clase not in ("lectura", "escritura"):
        return "deny", f"{nombre}: es {h.clase} en el catálogo ({h.motivo})"
    problemas = mcp.violaciones(h, tool_input)
    if problemas:
        return "deny", f"{nombre}: " + "; ".join(problemas)
    if h.clase == "escritura":
        vault = vault_root()
        if stop_activo(vault):
            return "deny", MOTIVO_STOP
        motivo = mcp.escritura_aprobada(vault, h, tool_input)
        if motivo is not None:
            return "deny", motivo
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(lambda e: clasificar(*herramienta(e)))
