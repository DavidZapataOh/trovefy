"""Paso 14: MCP oficial de Meta conectado y ``permissions.deny`` con los nombres reales.

Solo LEE archivos del vault (``config/meta_tools.json`` y ``.claude/settings.json``): sin red,
sin navegador, sin ``claude mcp``. El OAuth (P-02) se informa tal como lo anotó el usuario.
"""

import fnmatch
import json
from pathlib import Path

from trovefy.arranque.estado import ArranqueCorrupto, ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import guardar_evidencia
from trovefy.meta.herramientas import ListaIlegible, leer_documento
from trovefy.vault.permisos import es_lectura_meta, servidor_valido

ARREGLO_PREPARAR = "trovefy meta herramientas preparar (y reinicia Claude Code para ver las herramientas del MCP)"
ARREGLO_IMPORTAR = "trovefy meta herramientas importar ARCHIVO"
ARREGLO_PERMISOS = "trovefy meta herramientas importar ARCHIVO (regenera permissions.deny)"
_OAUTH = ("lectura", "completo")


def _falla(motivo: str, *arreglos: str) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, [], motivo, list(arreglos or (ARREGLO_IMPORTAR,)), {}, [f"✗ {motivo}"])


def _oauth(vault: Path) -> str:
    try:
        paso = next((p for p in cargar(vault) if p.id == "14"), None)
    except ArranqueCorrupto:
        return "no medido"
    valor = (paso.datos if paso else {}).get("oauth")
    return valor if valor in _OAUTH else "no medido"


@verificador("14")
def verificar_mcp(vault: Path) -> ResultadoVerificacion:
    try:
        doc = leer_documento(vault)
    except ListaIlegible as e:
        return _falla(f"config/meta_tools.json no se puede leer ({e})")
    tools = [t for t in (doc or {}).get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
    if doc is None or not tools:
        return _falla("falta config/meta_tools.json o no trae herramientas", ARREGLO_PREPARAR, ARREGLO_IMPORTAR)
    servidor = doc.get("servidor", "meta-ads")
    if not servidor_valido(servidor):
        return _falla("el servidor de config/meta_tools.json no es un nombre válido (letras, números, «_» o «-»)",
                      "trovefy meta herramientas importar ARCHIVO --servidor meta-ads")

    ruta = Path(vault) / ".claude" / "settings.json"
    try:
        deny = json.loads(ruta.read_text(encoding="utf-8"))["permissions"]["deny"]
        if not isinstance(deny, list) or not all(isinstance(x, str) for x in deny):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        return _falla(".claude/settings.json falta o no se puede leer; no se toca", ARREGLO_PERMISOS)

    prefijo = f"mcp__{servidor}__"
    lecturas = [t["name"] for t in tools if es_lectura_meta(t["name"].lower())]
    escrituras = [t["name"] for t in tools if not es_lectura_meta(t["name"].lower())]
    faltan = [n for n in escrituras if prefijo + n not in deny]  # solo nombres exactos: un comodín no cuenta
    if faltan:
        return _falla(f"permissions.deny no está al día: faltan {', '.join(faltan)}", ARREGLO_PERMISOS)
    tapadas = [n for n in lecturas if any(fnmatch.fnmatchcase(prefijo + n, r) for r in deny)]
    if tapadas:
        return _falla(
            f"permissions.deny bloquea lecturas ({', '.join(tapadas)}); quita el deny general de la fase 0",
            ARREGLO_PERMISOS,
        )

    oauth = _oauth(vault)
    hay_biblioteca = "ads_library_search" in lecturas
    datos = {
        "servidor": servidor, "lectura": str(len(lecturas)), "escritura": str(len(escrituras)),
        "ads_library_search": "si" if hay_biblioteca else "no", "oauth": oauth,
    }
    ev = guardar_evidencia(vault, "14", "mcp", {**datos, "fecha_inventario": doc.get("fecha")})
    motivo = (
        f"MCP de Meta ({servidor}): {len(lecturas)} de lectura permitidas, "
        f"{len(escrituras)} de escritura denegadas; OAuth: "
        + (oauth if oauth != "no medido" else "no medido (P-02)")
    )
    if not hay_biblioteca:
        motivo += "; /cazar no podrá usar el MCP (falta ads_library_search)"
    return ResultadoVerificacion(True, ["config/meta_tools.json", ev], motivo, [], datos, [f"✓ {motivo}"])
