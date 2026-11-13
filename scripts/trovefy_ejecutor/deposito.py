"""Origen de un archivo del buzón `entrada/`: nombre y propietario (sin seguir enlaces)."""
from __future__ import annotations

import os
import re
from pathlib import Path

NOMBRE = re.compile(r"^P-\d{8}-\d{3}\.json$")


class DepositoRechazado(Exception):
    def __init__(self, motivo: str, uid: int | None = None) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.uid = uid


def comprobar_origen(ruta: Path, uids_permitidos: set[int]) -> None:
    if not NOMBRE.fullmatch(ruta.name):
        raise DepositoRechazado("nombre no válido")
    try:
        st = os.lstat(ruta)
    except OSError:
        raise DepositoRechazado("archivo ilegible") from None
    if st.st_uid not in uids_permitidos:
        raise DepositoRechazado(f"depositado por uid {st.st_uid}", st.st_uid)
