"""Interruptor STOP: si existe el archivo (o un enlace, aunque esté roto), no se ejecuta nada."""

from __future__ import annotations

import json
import os
from datetime import datetime

from trovefy_ejecutor.config import RutasEjecutor


def stop_activo(rutas: RutasEjecutor) -> bool:
    # os.path.lexists se traga cualquier OSError y diría «no hay STOP»: aquí solo «no existe» es False.
    try:
        os.lstat(rutas.stop)
    except FileNotFoundError:
        return False
    except OSError:
        return True  # falla cerrada: sin poder mirar, se asume STOP
    return True


def activar_stop(rutas: RutasEjecutor, motivo: str, cuando: datetime) -> None:
    if not isinstance(cuando, datetime) or cuando.utcoffset() is None:
        raise ValueError("activar_stop: se exige datetime con zona horaria")
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
