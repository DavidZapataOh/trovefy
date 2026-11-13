"""Permisos del vault: `.claude/settings.json` con deny de toda escritura en Meta [§5.3]."""

import json
import re
from pathlib import Path

from trovefy.vault.escritura import escribir_atomico

# Solo nombres exactos en las reglas MCP: el soporte de comodines parciales (`mcp__srv__ads_create_*`) no está
# confirmado en Claude Code. Lo desconocido lo para `hooks/meta_guard.py` (falla cerrado).
SERVIDOR_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PREFIJOS_LECTURA = ("ads_get_", "ads_insights_")
_LECTURA_EXACTA = ("ads_library_search", "ads_account_get_activity_logs")

# Rutas absolutas con «//» (un solo «/» es relativo al origen de la configuración).
_DENY_FIJO = [
    "Bash(curl*graph.facebook.com*)",
    "Bash(*graph.facebook.com*)",
    "Bash(sudo *)",
    "Bash(su *)",
    "Bash(* | sh)",
    "Bash(* | bash)",
    "Read(//home/trovefy-exec/**)",
    "Edit(//var/spool/trovefy/procesadas/**)",
]


def es_lectura_meta(nombre: str) -> bool:
    """Misma lista blanca de lectura que `hooks/meta_guard.py`."""
    return nombre.startswith(_PREFIJOS_LECTURA) or nombre in _LECTURA_EXACTA


def servidor_valido(nombre: object) -> bool:
    return isinstance(nombre, str) and SERVIDOR_RE.fullmatch(nombre) is not None


def generar_settings(
    meta_tools: list[str] | None = None,
    servidor_meta: str = "meta-ads",
    vault: Path | None = None,
    deny_general: bool = True,
) -> dict:
    """Sin `meta_tools`: deny general de la fase 0 (`mcp__<srv>__ads_*`) salvo con ``deny_general=False``
    (`trovefy meta herramientas preparar`, para poder volcar las herramientas; meta_guard sigue parando las de
    escritura). Con `meta_tools`: cada nombre exacto en allow (lectura) o deny (el resto)."""
    if not servidor_valido(servidor_meta):
        raise ValueError(f"nombre de servidor MCP no válido: {servidor_meta!r} (usa letras, números, «_» o «-»)")
    allow = ["Bash(trovefy *)"]
    if vault is not None:
        allow.append(f"Read(/{Path(vault).expanduser().resolve()}/**)")
    deny = list(_DENY_FIJO)
    prefijo = f"mcp__{servidor_meta}__"
    if meta_tools is None:
        if deny_general:
            deny.append(f"{prefijo}ads_*")
    else:
        for nombre in dict.fromkeys(meta_tools):
            if es_lectura_meta(nombre.lower()):
                allow.append(prefijo + nombre)
            else:
                deny.append(prefijo + nombre)
    allow = list(dict.fromkeys(allow))
    deny = list(dict.fromkeys(deny))
    return {"permissions": {"allow": allow, "deny": deny}}


def leer_meta_tools(vault: Path) -> list[str] | None:
    """Lee `<vault>/config/meta_tools.json`: lista de nombres u objeto con «tools»."""
    ruta = Path(vault) / "config" / "meta_tools.json"
    if not ruta.is_file():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(datos, dict):
        datos = datos.get("tools", [])
    return [t["name"] if isinstance(t, dict) else t for t in datos]


def leer_servidor_meta(vault: Path) -> str:
    """Servidor de `meta_tools.json` (`servidor`) o «meta-ads» si no consta."""
    ruta = Path(vault) / "config" / "meta_tools.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "meta-ads"
    srv = datos.get("servidor") if isinstance(datos, dict) else None
    return srv if servidor_valido(srv) else "meta-ads"


class SettingsIlegible(Exception):
    """`.claude/settings.json` existe pero no se puede interpretar: nunca se pisa."""


def _lista(permisos: dict, clave: str) -> list:
    valor = permisos.get(clave, [])
    if not isinstance(valor, list):
        raise SettingsIlegible(f"«permissions.{clave}» no es una lista")
    return valor


def fusionar_settings(actual: dict, generado: dict, previas: set[str]) -> dict:
    """Generadas primero y después las del usuario (las de `actual` fuera de `previas`)."""
    if not isinstance(actual, dict):
        raise SettingsIlegible("settings.json no es un objeto")
    permisos = actual.get("permissions", {})
    if not isinstance(permisos, dict):
        raise SettingsIlegible("«permissions» no es un objeto")
    salida = dict(actual)
    nuevos = dict(permisos)
    for clave in ("allow", "deny"):
        gen = generado.get("permissions", {}).get(clave, [])
        propias = [e for e in _lista(permisos, clave) if e not in previas]
        nuevos[clave] = list(dict.fromkeys([*gen, *propias]))
    salida["permissions"] = nuevos
    return salida


def _ruta_generados(vault: Path) -> Path:
    return Path(vault) / "config" / "permisos_generados.json"


def _leer_generados(vault: Path) -> set[str] | None:
    try:
        d = json.loads(_ruta_generados(vault).read_text(encoding="utf-8"))
        return {e for c in ("allow", "deny") for e in d[c] if isinstance(e, str)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _guardar_generados(vault: Path, s: dict) -> None:
    p = s["permissions"]
    doc = {"allow": p["allow"], "deny": p["deny"]}
    escribir_atomico(_ruta_generados(vault), json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def escribir_settings(vault: Path, sobrescribir: bool, preparar: bool = False, servidor: str | None = None) -> bool:
    """Escribe `<vault>/.claude/settings.json`; devuelve si escribió.

    Con archivo existente y `sobrescribir`, fusiona sin quitar nada del usuario; un archivo ilegible nunca se pisa.
    Con `preparar` y sin `meta_tools.json`, sin el deny general de la fase 0 (para volcar las herramientas).
    """
    ruta = Path(vault) / ".claude" / "settings.json"
    existe = ruta.exists()
    if existe and not sobrescribir:
        return False
    s = generar_settings(leer_meta_tools(vault), servidor_meta=servidor or leer_servidor_meta(vault), vault=vault,
                         deny_general=not preparar)
    if existe:
        try:
            actual = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SettingsIlegible(f"{ruta} no se puede leer: {e}") from e
        previas = _leer_generados(vault)
        if previas is None:
            fase0 = generar_settings(None, vault=vault)["permissions"]
            previas = {*fase0["allow"], *fase0["deny"]}
        resultado = fusionar_settings(actual, s, previas)
    else:
        resultado = s
    escribir_atomico(ruta, json.dumps(resultado, indent=2, ensure_ascii=False) + "\n")
    _guardar_generados(vault, s)
    return True
