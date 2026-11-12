"""Comprueba contra la Graph API real que cada idioma de ``montaje.IDIOMAS_META`` se resuelve a exactamente
una clave (marca vivo; se ejecuta con ``-m vivo``). Toma el token de ``TROVEFY_SECRETOS`` (ruta al archivo
de secretos del ejecutor); sin él, se salta. Solo lectura (``GET /search``)."""
import os
from pathlib import Path

import pytest
from trovefy_ejecutor.graph import ClienteGraph
from trovefy_ejecutor.montaje import IDIOMAS_META, filas_exactas


@pytest.mark.vivo
@pytest.mark.parametrize(("codigo", "nombre"), sorted(IDIOMAS_META.items()))
def test_idioma_de_la_tabla_resuelve_en_meta(codigo, nombre):
    from trovefy_ejecutor.secretos import cargar_secretos

    ruta = os.environ.get("TROVEFY_SECRETOS")
    if not ruta:
        pytest.skip("sin TROVEFY_SECRETOS")
    # El token no se guarda en una variable local: con --showlocals pytest la imprimiría.
    cliente = ClienteGraph(cargar_secretos(Path(ruta)).meta_token or pytest.skip("sin META_TOKEN"))
    filas = cliente.buscar("adlocale", nombre, ["key", "name"])
    claves = filas_exactas(filas, nombre)
    assert len(claves) == 1, f"{codigo} → {nombre!r}: {len(claves)} filas exactas"
