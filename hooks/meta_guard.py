"""Hook PreToolUse: Claude nunca escribe en Meta Ads (§5.3 punto 3).

La idea del clasificador viene de ``refine_action`` de
un repo de referencia (MIT); aquí está reimplementada y sin la
vía «allow con ticket». Solo biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

from urllib.parse import urlsplit

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
    servidor = "__".join(partes[1:-1]).lower()
    meta = any(s in servidor for s in _SERVIDORES) or corto.lower().startswith("ads_")
    return meta, corto.lower()


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def clasificar(tool_name: str, tool_input: dict) -> tuple[str, str]:
    meta, corto = _es_meta_mcp(tool_name)
    if meta:
        if corto.startswith(_PREFIJOS_LECTURA) or corto in _LECTURA_EXACTA:
            return "allow", ""
        return "deny", MOTIVO
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", "")).lower()
        if any(h in cmd for h in _HOSTS_GRAPH):
            return "deny", MOTIVO
    elif tool_name == "WebFetch":
        url = str(tool_input.get("url", ""))
        bajo = url.lower()
        apunta = _host(url) in _HOSTS_GRAPH or any(h in bajo for h in _HOSTS_GRAPH)
        if apunta and "access_token" in bajo:
            return "deny", MOTIVO
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(lambda e: clasificar(*herramienta(e)))
