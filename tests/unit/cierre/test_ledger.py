"""Ledgers con upsert de 7 días y reembolsos detectados (plan 24, Tarea 5)."""
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from trovefy.caja.config import cargar_caja
from trovefy.caja.gasto import CABECERA, gastos_de_tests
from trovefy.cierre.lectura import gasto_del_periodo, ventas_del_periodo
from trovefy.cierre.ledger import upsert_gasto, upsert_ventas
from trovefy.cierre.plataforma import leer_ventas
from trovefy.meta.insights import leer_insights
from trovefy.vault.escritura import ZONA_NEGOCIO

from .ejemplos import (
    CAMPANA,
    CUENTA,
    MANANA,
    TIENDA,
    TRM,
    campanas,
    vault_cierre,
    venta,
    ventas_pagina,
)


def _filas(dia="2026-11-19", gasto="99200"):
    filas, _ = leer_insights(campanas(dia, gasto), "campaign")
    return filas


def test_upsert_no_duplica(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_gasto(v, _filas(), CUENTA)
    upsert_gasto(v, _filas(), CUENTA)
    lineas = (v / "ledger/gasto/2026-11.csv").read_text().splitlines()
    assert lineas[0] == ",".join(CABECERA) and len(lineas) == 2


def test_dia_corregido_se_actualiza(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_gasto(v, _filas(gasto="99200"), CUENTA)
    upsert_gasto(v, _filas(gasto="100000") + _filas(dia="2026-11-18", gasto="5000"), CUENTA)
    g = {x.fecha: x.gasto for x in gasto_del_periodo(v, date(2026, 11, 1), date(2026, 11, 30), CAMPANA)}
    assert g == {date(2026, 11, 19): Decimal("100000.00"), date(2026, 11, 18): Decimal("5000.00")}


def test_gasto_cop_siempre_dos_decimales(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_gasto(v, _filas(gasto="83700"), CUENTA)
    assert "83700.00" in (v / "ledger/gasto/2026-11.csv").read_text()
    gastos = gastos_de_tests(v, cargar_caja(v), lambda d: TRM)
    assert gastos[0].usd_centavos == 2093 and gastos[0].motivo is None  # 83.700 / 4.000 = 20,925 → al alza


def test_cabecera_igual_a_caja(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_gasto(v, _filas(), CUENTA)
    assert (v / "ledger/gasto/2026-11.csv").read_text().splitlines()[0].split(",") == CABECERA


def test_pedido_desaparecido_es_reembolso(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_ventas(v, leer_ventas([ventas_pagina([venta("A"), venta("B")])], TIENDA, set()), MANANA)
    despues = datetime(2026, 11, 21, 8, 30, tzinfo=ZONA_NEGOCIO)
    r = upsert_ventas(v, leer_ventas([ventas_pagina([venta("A")], hasta="2026-11-20")], TIENDA, set()), despues)
    assert r.desaparecidas == ["B"]
    filas = {x.orden: x for x in ventas_del_periodo(v, date(2026, 11, 1), date(2026, 11, 30))}
    assert filas["B"].estado == "desaparecida" and filas["B"].detectada == date(2026, 11, 21)
    assert filas["A"].estado == "aprobada" and len(filas) == 2  # nunca se borra una fila


def test_lectura_incompleta_no_marca_desaparecidas(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_ventas(v, leer_ventas([ventas_pagina([venta("A"), venta("B")])], TIENDA, set()), MANANA)
    incompleta = leer_ventas([ventas_pagina([venta("A")], has_more=True)], TIENDA, set())
    assert upsert_ventas(v, incompleta, MANANA).desaparecidas == []
    export = replace(leer_ventas([ventas_pagina([venta("A")])], TIENDA, set()), fuente="export")
    assert upsert_ventas(v, export, MANANA).desaparecidas == []


def test_todas_reembolsadas_se_detectan(tmp_path):
    v = vault_cierre(tmp_path)
    upsert_ventas(v, leer_ventas([ventas_pagina([venta("A")])], TIENDA, set()), MANANA)
    r = upsert_ventas(v, leer_ventas([ventas_pagina([])], TIENDA, set()), MANANA)
    assert r.desaparecidas == ["A"]


def test_ventas_del_periodo(tmp_path):
    v = vault_cierre(tmp_path)
    lec = leer_ventas([ventas_pagina([venta("A"), venta("Z", fecha="2026-10-30T10:00:00-05:00")],
                                     desde="2026-10-30")], TIENDA, {"Z"})
    r = upsert_ventas(v, lec, MANANA)
    assert r.nuevas == 2 and {p.name for p in r.rutas} == {"2026-10.csv", "2026-11.csv"}
    assert [x.orden for x in ventas_del_periodo(v, date(2026, 11, 1), date(2026, 11, 30))] == ["A"]
    assert ventas_del_periodo(v, date(2026, 10, 1), date(2026, 10, 31))[0].estado == "prueba"
