from datetime import date
from decimal import Decimal

import pytest
from trovefy.trm import trm_del_dia


@pytest.mark.vivo
def test_trm_vivo(tmp_path):
    t = trm_del_dia(tmp_path, date.today())
    assert t is not None
    assert Decimal(1000) <= t.cop_por_usd <= Decimal(10000)
