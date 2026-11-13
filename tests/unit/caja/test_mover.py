
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from ejemplos_caja import CFG, TRM
from trovefy.caja.calculo import calcular
from trovefy.caja.mover import MovimientoInvalido, anotar_herramienta, mover
from trovefy.caja.movimientos import leer_movimientos

COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 9, 30, 15, tzinfo=COT)
CITA = 'muévele 50 de la reserva a tests, "ya" $50'


def estado():
    return calcular(CFG, [], [])


def test_mover_registra_cita_literal(tmp_path):
    ruta, m = mover(tmp_path, "reserva", "tests", 5000, CITA, estado(), AHORA)
    assert ruta == tmp_path / "decisiones" / "caja" / "2026-11-12-093015-mover.md"
    texto = ruta.read_bytes().decode("utf-8")
    assert f"> {CITA}\n" in texto
    assert "reserva: 200 → 150" in texto and "tests: 280 → 330" in texto
    filas = leer_movimientos(tmp_path)
    assert filas == [m] and m.decision == "decisiones/caja/2026-11-12-093015-mover.md"
    assert (m.tipo, m.origen, m.destino, m.usd_centavos) == ("mover", "reserva", "tests", 5000)
    assert m.nota == CITA


def test_decision_antes_que_la_fila(tmp_path, monkeypatch):
    def falla(*_a, **_k):
        raise OSError("disco")

    monkeypatch.setattr("trovefy.caja.mover.anotar_movimiento", falla)
    with pytest.raises(OSError):
        mover(tmp_path, "reserva", "tests", 5000, CITA, estado(), AHORA)
    assert (tmp_path / "decisiones" / "caja" / "2026-11-12-093015-mover.md").exists()
    assert leer_movimientos(tmp_path) == []


def test_mover_sin_cita_falla(tmp_path):
    for cita in ("", "   "):
        with pytest.raises(MovimientoInvalido):
            mover(tmp_path, "reserva", "tests", 5000, cita, estado(), AHORA)
    assert not (tmp_path / "decisiones").exists()


def test_mover_mas_de_lo_que_queda_falla(tmp_path):
    with pytest.raises(MovimientoInvalido):
        mover(tmp_path, "herramientas", "tests", 2001, CITA, estado(), AHORA)


def test_mover_a_cobrado_falla(tmp_path):
    for o, d in (("reserva", "cobrado"), ("cobrado", "tests")):
        with pytest.raises(MovimientoInvalido, match="el sobre cobrado llega con la conciliación"):
            mover(tmp_path, o, d, 100, CITA, estado(), AHORA)


def test_mover_invalidos(tmp_path):
    for o, d, c in (("tests", "tests", 100), ("tests", "reserva", 0), ("tests", "reserva", -5), ("nada", "tests", 100)):
        with pytest.raises(MovimientoInvalido):
            mover(tmp_path, o, d, c, CITA, estado(), AHORA)


def test_mover_origen_no_medido_falla(tmp_path):
    from ejemplos_caja import con_test

    est = calcular(con_test("vivo"), [], [])
    with pytest.raises(MovimientoInvalido, match="no medido"):
        mover(tmp_path, "tests", "reserva", 100, CITA, est, AHORA)


def test_anotar_usd(tmp_path):
    m = anotar_herramienta(tmp_path, Decimal("10.50"), "USD", "dominio", None, AHORA)
    assert (m.tipo, m.usd_centavos, m.moneda_original) == ("herramienta", 1050, "USD")
    assert leer_movimientos(tmp_path) == [m]


def test_anotar_cop_con_trm(tmp_path):
    m = anotar_herramienta(tmp_path, Decimal(100000), "COP", "x", TRM, AHORA)
    assert m.usd_centavos == 3033 and m.trm == "3297.07" and m.trm_fecha == "2026-11-11"


def test_anotar_cop_sin_trm_falla(tmp_path):
    with pytest.raises(MovimientoInvalido, match="no medido: sin TRM; no se anota"):
        anotar_herramienta(tmp_path, Decimal(100000), "COP", "x", None, AHORA)
    assert leer_movimientos(tmp_path) == []


def test_anotar_invalidos(tmp_path):
    for imp, mon in ((Decimal(0), "USD"), (Decimal(-1), "USD"), (Decimal(1), "EUR")):
        with pytest.raises(MovimientoInvalido):
            anotar_herramienta(tmp_path, imp, mon, "x", TRM, AHORA)
