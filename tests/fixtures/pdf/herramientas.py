"""Herramientas del sistema que necesitan las pruebas del PDF (WeasyPrint/Pango, poppler, fontconfig).

Fuera de CI, si falta alguna, la prueba se salta con el motivo. Con ``CI`` definido (ruling L7) el
salto pasa a fallo: allí el workflow las instala y que falten es un error del entorno.
"""

import os
import shutil

import pytest


def falta_weasyprint() -> str | None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:
        return f"WeasyPrint no disponible ({exc}): sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0"
    return None


def faltan(*programas: str, weasyprint: bool = False) -> str | None:
    """Motivo de lo primero que falta, o ``None`` si está todo."""
    if weasyprint and (motivo := falta_weasyprint()):
        return motivo
    for programa in programas:
        if shutil.which(programa) is None:
            return f"falta {programa} (poppler-utils / fontconfig)"
    return None


def requerir(motivo: str | None) -> None:
    """Nada si ``motivo`` es ``None``; si no, salta la prueba (o falla, con ``CI`` definido)."""
    if motivo is None:
        return
    if os.environ.get("CI"):
        pytest.fail(f"en CI no se salta: {motivo}", pytrace=False)
    pytest.skip(motivo)
