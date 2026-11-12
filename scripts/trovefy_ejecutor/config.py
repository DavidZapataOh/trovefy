"""Rutas del ejecutor (§5.1). No usa ``Path.home()``: todo es redirigible."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RutasEjecutor:
    secretos: Path
    limites: Path
    base: Path
    auditoria: Path
    stop: Path
    spool: Path
    vault: Path | None


def rutas_por_defecto(entorno: Mapping[str, str] = os.environ) -> RutasEjecutor:
    h = Path(entorno.get("TROVEFY_EJECUTOR_HOME", "/home/trovefy-exec"))
    config = h / ".config" / "trovefy-ejecutor"
    datos = h / ".local" / "share" / "trovefy-ejecutor"
    vault = entorno.get("TROVEFY_VAULT")
    return RutasEjecutor(
        secretos=config / "secretos.env",
        limites=config / "limites.yaml",
        base=datos / "estado.sqlite",
        auditoria=datos / "auditoria.jsonl",
        stop=datos / "STOP",
        spool=Path(entorno.get("TROVEFY_SPOOL", "/var/spool/trovefy")),
        vault=Path(vault) if vault else None,
    )
