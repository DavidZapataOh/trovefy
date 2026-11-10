"""Hook PreToolUse: Claude nunca escribe en Meta Ads (§5.3 punto 3).

La idea del clasificador viene de ``refine_action`` de
un repo de referencia (MIT); aquí está reimplementada y sin la
vía «allow con ticket». Solo biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

import json
from urllib.parse import unquote, urlsplit

from _comun import ejecutar_guardia, herramienta

MOTIVO = "escritura en Meta: solo la hace el ejecutor tras Aceptar"
_SERVIDORES = ("meta", "facebook", "fb")
_PREFIJOS_LECTURA = ("ads_get_", "ads_insights_")
_LECTURA_EXACTA = ("ads_library_search", "ads_account_get_activity_logs")
_HOSTS_GRAPH = ("graph.facebook.com", "graph.fb.com")


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
        any(s in servidor for s in _SERVIDORES)
        or any(p.startswith("ads_") for p in partes[1:])
    )
    return meta, corto


def _menciona_graph(texto: str) -> bool:
    return any(h in texto for h in _HOSTS_GRAPH)


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
    if tool_name.startswith("mcp__"):
        # Navegador/scrape por MCP hacia Graph: Claude lee Meta solo por el MCP oficial.
        try:
            volcado = json.dumps(tool_input).lower()
        except (TypeError, ValueError):
            return "deny", MOTIVO
        if _menciona_graph(volcado) or _menciona_graph(unquote(volcado)):
            return "deny", MOTIVO
    elif tool_name == "bash":
        if _menciona_graph(str(tool_input.get("command", "")).lower()):
            return "deny", MOTIVO
    elif tool_name == "webfetch":
        # Siempre deny hacia Graph, con o sin token: Graph acepta method=post en GET
        # y el token puede ir codificado en porcentaje.
        url = str(tool_input.get("url", ""))
        if _host(url) in _HOSTS_GRAPH or _menciona_graph(unquote(url).lower()):
            return "deny", MOTIVO
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(lambda e: clasificar(*herramienta(e)))
