"""Hook PreToolUse: Claude nunca escribe en Meta Ads (§5.3 punto 3).

Clasifica cada llamada en lectura o escritura y deniega toda escritura, sin
vía «allow con ticket». Solo biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

import itertools
import json
import re
from urllib.parse import unquote, urlsplit

from _comun import ejecutar_guardia, es_deposito, herramienta, stop_activo, vault_root

MOTIVO_STOP = "STOP activo: no se deposita nada"
MOTIVO = "escritura en Meta: solo la hace el ejecutor tras Aceptar"
_TOKENS_SERVIDOR = ("meta", "facebook", "fb")
_PREFIJOS_LECTURA = ("ads_get_", "ads_insights_")
_LECTURA_EXACTA = ("ads_library_search", "ads_account_get_activity_logs")
_HOST_GRAPH = re.compile(r"graph[\w.-]*\.facebook\.com|graph\.fb\.com", re.IGNORECASE)


def _servidor_es_meta(servidor: str) -> bool:
    """Por token (separado por no letras), no por subcadena: «metabase» no es Meta."""
    for t in re.split(r"[^a-z]+", servidor.lower()):
        if t in _TOKENS_SERVIDOR or t.startswith(("metaads", "facebookads")):
            return True
    return False


def _es_meta_mcp(nombre: str) -> tuple[bool, str]:
    if not nombre.startswith("mcp__"):
        return False, ""
    partes = nombre.split("__")
    corto = partes[-1]
    if len(partes) == 2:  # mcp__<servidor> sin herramienta: el servidor es el nombre
        servidor = partes[1]
    else:
        servidor = "__".join(partes[1:-1])
    meta = (
        _servidor_es_meta(servidor)
        or any(p.startswith("ads_") for p in partes[1:])
    )
    return meta, corto


_FICHAS_META = ("facebook", "instagram", "metaads")
_SUFIJOS_LECTURA_NOMBRE = ("_read", "_tools")


def _nombre_es_meta(nombre: str) -> bool:
    """H2: una herramienta de Meta en cualquier servidor (``mcp__higgsfield__meta_ads_write``): por fichas del
    nombre (``meta`` seguida de ``ads``, ``metaads…``, ``facebook…``, ``instagram…``), no por subcadena."""
    fichas = [f for f in re.split(r"[^a-z0-9]+", nombre.lower()) if f]
    if any(f.startswith(_FICHAS_META) for f in fichas):
        return True
    return any(a == "meta" and b.startswith("ads") for a, b in itertools.pairwise(fichas))


def _lectura_clara(corto: str) -> bool:
    """Lo único que pasa de una herramienta de Meta fuera de su servidor: ``ads_get_*``, ``*_read`` y el listado
    ``*_tools``. Todo lo demás (``*_write``, ``*_connect``, nombres nuevos) se deniega: falla cerrado."""
    return corto.startswith("ads_get_") or corto.endswith(_SUFIJOS_LECTURA_NOMBRE)


def _menciona_graph(texto: str) -> bool:
    return bool(_HOST_GRAPH.search(texto))


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def clasificar(tool_name: str, tool_input: dict) -> tuple[str, str]:
    tool_name = tool_name.lower()
    meta, corto = _es_meta_mcp(tool_name)
    if meta:
        if corto.startswith(_PREFIJOS_LECTURA) or corto in _LECTURA_EXACTA:
            return "allow", ""
        return "deny", MOTIVO
    if _nombre_es_meta(tool_name):
        corto = tool_name.split("__")[-1]
        return ("allow", "") if _lectura_clara(corto) else ("deny", MOTIVO)
    if tool_name.startswith("mcp__"):
        # Navegador/scrape por MCP hacia Graph: Claude lee Meta solo por el MCP oficial.
        try:
            volcado = json.dumps(tool_input).lower()
        except (TypeError, ValueError):
            return "deny", MOTIVO
        if _menciona_graph(volcado) or _menciona_graph(unquote(volcado)):
            return "deny", MOTIVO
    elif tool_name == "bash":
        comando = str(tool_input.get("command", ""))
        if es_deposito(comando) and stop_activo(vault_root()):
            return "deny", MOTIVO_STOP
        if _menciona_graph(str(tool_input.get("command", "")).lower()):
            return "deny", MOTIVO
    elif tool_name == "webfetch":
        # Siempre deny hacia Graph, con o sin token: Graph acepta method=post en GET
        # y el token puede ir codificado en porcentaje.
        url = str(tool_input.get("url", ""))
        if _HOST_GRAPH.fullmatch(_host(url)) or _menciona_graph(unquote(url).lower()):
            return "deny", MOTIVO
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(lambda e: clasificar(*herramienta(e)))
