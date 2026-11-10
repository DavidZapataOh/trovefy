"""Rutas del vault: TROVIFY_VAULT si existe, si no ~/trovify-cerebro."""

import os
from pathlib import Path


def vault_root() -> Path:
    valor = os.environ.get("TROVIFY_VAULT")
    if valor:
        return Path(valor).expanduser()
    return Path.home() / "trovify-cerebro"
