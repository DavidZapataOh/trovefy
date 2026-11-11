"""Permisos del vault: `.claude/settings.json` con deny de toda escritura en Meta [§5.3]."""

import json
from pathlib import Path

from trovefy.vault.escritura import escribir_atomico

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


def generar_settings(
    meta_tools: list[str] | None = None,
    servidor_meta: str = "meta-ads",
    vault: Path | None = None,
) -> dict:
    allow = ["Bash(trovefy *)"]
    if vault is not None:
        allow.append(f"Read(/{Path(vault).expanduser().resolve()}/**)")
    deny = list(_DENY_FIJO)
    prefijo = f"mcp__{servidor_meta}__"
    if meta_tools is None:
        deny.append(f"{prefijo}ads_*")
    else:
        for nombre in dict.fromkeys(meta_tools):
            if es_lectura_meta(nombre):
                allow.append(prefijo + nombre)
            else:
                deny.append(prefijo + nombre)
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


def escribir_settings(vault: Path, sobrescribir: bool) -> bool:
    """Escribe `<vault>/.claude/settings.json`; devuelve si escribió."""
    ruta = Path(vault) / ".claude" / "settings.json"
    if ruta.exists() and not sobrescribir:
        return False
    s = generar_settings(leer_meta_tools(vault), vault=vault)
    escribir_atomico(ruta, json.dumps(s, indent=2, ensure_ascii=False) + "\n")
    return True
