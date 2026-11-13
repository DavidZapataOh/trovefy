import os
from datetime import UTC, datetime

import pytest
from trovefy.caja.movimientos import (
    CABECERA,
    Movimiento,
    MovimientosCorruptos,
    anotar_movimiento,
    leer_movimientos,
)


def _m(n=1, **kw):
    base = {
        "fecha": datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
        "tipo": "mover",
        "origen": "reserva",
        "destino": "tests",
        "usd_centavos": 1000 * n,
        "importe_original": "",
        "moneda_original": "",
        "trm": "",
        "trm_fecha": "",
        "nota": "a, b",
        "decision": "D-1",
    }
    base.update(kw)
    return Movimiento(**base)


def test_movimientos_solo_se_anaden(tmp_path):
    anotar_movimiento(tmp_path, _m(1))
    ruta = tmp_path / "ledger" / "caja" / "movimientos.csv"
    lineas1 = ruta.read_bytes().split(b"\n")
    anotar_movimiento(tmp_path, _m(2))
    lineas2 = ruta.read_bytes().split(b"\n")
    assert len(ruta.read_text().splitlines()) == 3
    assert lineas2[:2] == lineas1[:2]
    assert ruta.read_text().splitlines()[0].split(",") == CABECERA
    assert [m.usd_centavos for m in leer_movimientos(tmp_path)] == [1000, 2000]
    assert leer_movimientos(tmp_path)[0] == _m(1)


def test_sin_archivo_lista_vacia(tmp_path):
    assert leer_movimientos(tmp_path) == []


def test_fila_corrupta(tmp_path):
    anotar_movimiento(tmp_path, _m())
    ruta = tmp_path / "ledger" / "caja" / "movimientos.csv"
    with open(ruta, "a") as f:
        f.write("2026-11-12T10:00:00+00:00,mover,a,b\n")
    with pytest.raises(MovimientosCorruptos):
        leer_movimientos(tmp_path)


def test_importe_ilegible(tmp_path):
    anotar_movimiento(tmp_path, _m())
    ruta = tmp_path / "ledger" / "caja" / "movimientos.csv"
    ruta.write_text(ruta.read_text().replace("1000", "12.5"))
    with pytest.raises(MovimientosCorruptos):
        leer_movimientos(tmp_path)


def test_rechaza_enlace_simbolico(tmp_path):
    (tmp_path / "ledger" / "caja").mkdir(parents=True)
    destino = tmp_path / "otro.csv"
    destino.write_text("x\n")
    os.symlink(destino, tmp_path / "ledger" / "caja" / "movimientos.csv")
    with pytest.raises(OSError):
        anotar_movimiento(tmp_path, _m())
    assert destino.read_text() == "x\n"
