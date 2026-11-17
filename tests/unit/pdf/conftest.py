"""Fixtures del paquete ``trovefy.pdf``: una fuente de prueba sin cirílico, creada con fontTools."""

from pathlib import Path

import pytest
from fixtures.pdf.fuente_latina import crear_fuente_latina


@pytest.fixture(scope="session")
def latin_only(tmp_path_factory) -> Path:
    """``latin-only.ttf``: fuente de prueba sin cirílico (se genera; no se versiona un binario)."""
    return crear_fuente_latina(tmp_path_factory.mktemp("fuentes") / "latin-only.ttf")
