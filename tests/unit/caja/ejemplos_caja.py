"""Fixtures de la caja (nombre propio: ``ejemplos`` ya lo usa tests/unit/caza)."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from trovefy.caja.config import ConfigCaja, CuentaCaja, TestCaja
from trovefy.caja.gasto import GastoTest
from trovefy.caja.movimientos import Movimiento
from trovefy.trm import Trm

TRM = Trm(Decimal("3297.07"), date(2026, 11, 11), date(2026, 11, 12))

CFG = ConfigCaja(
    capital=50000,
    sobres={"herramientas": 2000, "tests": 28000, "reserva": 20000},
    techo_test=3000,
    prorroga_hasta=5500,
    diario_test=2500,
    diario_prescala=2000,
    tope_diario_ejecutor=5000,
    reserva_desbloqueada=False,
    apimart_aviso=100,
    cuenta=CuentaCaja("act_0000000000000000", "COP"),
    tests=(),
)


def trm_fijo(dia: date) -> Trm | None:
    return TRM if dia in (date(2026, 11, 11), date(2026, 11, 12)) else None


def test_caja(
    estado="vivo", prorroga=False, campana="c1", producto="p1", pais="CO"
) -> TestCaja:
    return TestCaja(producto, pais, campana, estado, prorroga, None, 2500)


def con_test(estado="vivo", prorroga=False, campana="c1") -> ConfigCaja:
    return replace(CFG, tests=(test_caja(estado, prorroga, campana),))


def g(centavos, producto="p1", pais="CO") -> GastoTest:
    return GastoTest(producto, pais, centavos, None)


def mov(origen, destino, centavos, tipo="mover") -> Movimiento:
    return Movimiento(
        datetime(2026, 11, 12, tzinfo=UTC),
        tipo,
        origen,
        destino,
        centavos,
        "",
        "",
        "",
        "",
        "",
        "",
    )


def ledger(vault, filas, nombre="2026-11.csv"):
    d = vault / "ledger" / "gasto"
    d.mkdir(parents=True, exist_ok=True)
    cuerpo = "".join(f"{','.join(f)}\n" for f in filas)
    (d / nombre).write_text(
        "fecha,cuenta,campana,gasto,moneda\n" + cuerpo, encoding="utf-8"
    )
