"""`/cierre` (plan 24): las 3 cifras del bot «Gasto Meta · Neto · Ganancia» a las 23:30 y a las 08:30.

**Qué hacen los vídeos:** «Cierre del 03/11 — Gasto Meta: 1183,38 — Neto Whop: 2644,92 — Ganancia: 1461,54» (T3 13:42);
«23:30 Cierre de caja contra la pasarela → ledger → cerebro» (C1 0:50:20) y «[8:30] Ganancia de ayer en Meta» (L2 22:40).

Mismo patrón que `/leer`: Claude llama al MCP (solo lectura) y guarda las respuestas crudas en
``~/.cache/trovefy/cierre/<día>/``; la CLI nunca llama al MCP, solo interpreta esos archivos, hace *upsert* de los
ledgers, calcula y escribe la página del cierre. Dato ausente = «—» con su motivo; jamás una estimación.
"""
from __future__ import annotations

from pathlib import Path

SKILL = "cierre"
ORIGEN = "/cierre"
VENTANA_DIAS = 7  # Meta y la tienda corrigen días pasados (§4.19): se releen 7 días
ZONA_CUENTA_POR_DEFECTO = "America/Bogota"  # D-37; manda la que devuelve ads_get_ad_accounts


def carpeta_cache(dia_iso: str) -> Path:
    """Respuestas crudas del MCP, fuera del vault (0600)."""
    return Path.home() / ".cache" / "trovefy" / "cierre" / dia_iso
