"""Rutas del vault: TROVEFY_VAULT si existe, si no ~/trovefy-cerebro."""

import os
from pathlib import Path


def vault_root() -> Path:
    valor = os.environ.get("TROVEFY_VAULT")
    if valor:
        return Path(valor).expanduser()
    return Path.home() / "trovefy-cerebro"
