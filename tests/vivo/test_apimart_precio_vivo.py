"""Precio real de APIMart (endpoint público, sin clave). Se ejecuta con `-m vivo`."""

from datetime import date
from decimal import Decimal

import pytest
from trovefy.apimart.http import BASE_POR_DEFECTO
from trovefy.apimart.precios import precio_imagen


@pytest.mark.vivo
def test_precio_gpt_image_2_vivo(tmp_path):
    p = precio_imagen(tmp_path, BASE_POR_DEFECTO, "gpt-image-2", "1k", date.today())
    assert p is not None
    assert Decimal(0) < p.usd_por_imagen < Decimal(1)
