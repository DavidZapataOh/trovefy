"""Un plan del MCP aprobado tal como lo deja `trovefy checkout aprobar` (solo para tests; HOME ya es un tmp_path).

El plan lleva su huella (operaciones, creado, etapa, producto, país), la aprobación cita la frase atada a esa huella y
el registro de mensajes del usuario (en ``~/.config/trovefy``) tiene ese mensaje, posterior al plan y marcado para él.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trovefy.checkout.mensajes import registrar_mensaje, usar_mensaje
from trovefy.tienda.mcp import frase_aprobacion, huella_del_plan

P = "p-0099-prueba-abc123"
CREADO = "2026-11-17T12:00:00-05:00"


def plan_aprobado(vault: Path, ops: list[dict], *, pais: str = "ZZ", producto: str = P, etapa: int = 1,
                  creado: str = CREADO, registrar: bool = True, cita: str | None = None) -> tuple[Path, dict]:
    d = Path(vault) / "productos" / producto / "checkout" / pais
    d.mkdir(parents=True, exist_ok=True)
    plan = {"producto": producto, "pais": pais, "etapa": etapa, "creado": creado, "operaciones": ops}
    plan["huella"] = huella_del_plan(plan)
    frase = frase_aprobacion(etapa, plan["huella"]) if cita is None else cita
    (d / "PLAN-MCP.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (d / "APROBACION.md").write_text(
        f"---\nplan_huella: {plan['huella']}\ncita: {json.dumps(frase, ensure_ascii=False)}\nfecha: \"{creado}\"\n"
        f"etapa: {etapa}\n---\n", encoding="utf-8")
    if registrar:
        t = datetime.fromisoformat(creado).timestamp()
        registrar_mensaje(frase, ahora=t + 60)
        assert usar_mensaje(frase, desde=t, huella=plan["huella"]) is not None
    return d, plan
