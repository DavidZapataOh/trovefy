"""Interruptor STOP: si existe el archivo (o un enlace, aunque esté roto), no se ejecuta nada."""

from __future__ import annotations

import json
import os
from datetime import datetime

from trovefy_ejecutor.config import RutasEjecutor


def stop_activo(rutas: RutasEjecutor) -> bool:
    try:
        return os.path.lexists(rutas.stop)
    except OSError:
        return True  # falla cerrada


def activar_stop(rutas: RutasEjecutor, motivo: str, cuando: datetime) -> None:
    rutas.stop.parent.mkdir(parents=True, exist_ok=True)
    tmp = rutas.stop.with_name(rutas.stop.name + ".tmp")
    tmp.write_text(
        json.dumps({"desde": cuando.isoformat(), "motivo": motivo}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, rutas.stop)


def quitar_stop(rutas: RutasEjecutor) -> bool:
    try:
        os.unlink(rutas.stop)
    except FileNotFoundError:
        return False
    return True
