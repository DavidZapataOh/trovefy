"""Rutas de cada pieza del entregable (contrato 2; piezas de la resolución 13).

``principal`` → ``productos/<p-id>/entregable/`` · ``bono-N`` → ``entregable/bonos/bono-N/`` ·
``bump`` → ``entregable/bump/`` · ``u1|u2|u3|downsell`` → ``entregable/upsells/<id>/``.
Los ids se validan con ``fullmatch``: nada de ``..``, barras ni saltos de línea.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

P_ID = re.compile(r"^p-\d{4}-[a-z0-9-]+$", re.ASCII)
PIEZA = re.compile(r"^(principal|bono-[1-9]|bump|u[1-3]|downsell)$")
UPSELLS = ("u1", "u2", "u3", "downsell")

TipoPieza = Literal["principal", "bono", "bump", "upsell"]


@dataclass(frozen=True)
class Pieza:
    id: str
    tipo: TipoPieza
    raiz: Path


def validar_p_id(p_id: str) -> str:
    if not isinstance(p_id, str) or not P_ID.fullmatch(p_id):
        raise ValueError(f"producto mal escrito: «{p_id}»; usa su p-id (por ejemplo p-0001-fise-terapie)")
    return p_id


def entregable(vault: Path, p_id: str) -> Path:
    """``productos/<p-id>/entregable/``: raíz de la pieza principal, de ``costes.csv`` y de ``FICHA.md``."""
    return Path(vault) / "productos" / validar_p_id(p_id) / "entregable"


def pieza(vault: Path, p_id: str, pieza_id: str) -> Pieza:
    base = entregable(vault, p_id)
    if not isinstance(pieza_id, str) or not PIEZA.fullmatch(pieza_id):
        raise ValueError(f"pieza mal escrita: «{pieza_id}»; usa principal, bono-N, bump, u1, u2, u3 o downsell")
    if pieza_id == "principal":
        return Pieza(pieza_id, "principal", base)
    if pieza_id.startswith("bono-"):
        return Pieza(pieza_id, "bono", base / "bonos" / pieza_id)
    if pieza_id == "bump":
        return Pieza(pieza_id, "bump", base / "bump")
    return Pieza(pieza_id, "upsell", base / "upsells" / pieza_id)
