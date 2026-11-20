"""Página del cierre y mensaje del bot (plan 24, Tarea 7)."""
from decimal import Decimal

from trovefy.cierre.salida import alerta_de, escribir_cierre, informe, leer_cierre
from trovefy_ejecutor.esquema import cargar_propuesta

from .ejemplos import MANANA, NOCHE, vault_cierre
from .test_calculo import cierre, v


def test_informe_como_el_bot():
    texto = informe(cierre(ventas=[v("A", "2644.92", "USD")]), "manana", ["no sale"])
    assert texto.splitlines() == ["Cierre del 19/11", "Gasto Meta: 1183,38", "Neto: 2644,92", "Ganancia: 1461,54"]


def test_informe_noche_con_proximos_movimientos():
    texto = informe(cierre(ventas=[]), "noche", ["P-20261119-004 presupuesto pendiente de tu Aceptar"])
    lineas = texto.splitlines()
    assert lineas[0] == "Cierre del 19/11 (hasta las 23:30)" and lineas[1].startswith("Gasto Meta:")
    assert lineas[-1] == "Próximos movimientos: P-20261119-004 presupuesto pendiente de tu Aceptar"
    assert informe(cierre(ventas=[]), "noche", []).endswith("Próximos movimientos: ninguno pendiente")


def test_informe_con_huecos_dice_motivo():
    texto = informe(cierre(ventas=[v("A")], com=["falta plataformas.whop.comision_pct"]), "manana", [])
    assert "Neto: — (falta la comisión de Whop)" in texto and "Ganancia: — (falta la comisión de Whop)" in texto


def test_ganancia_negativa():
    texto = informe(cierre(ventas=[v("A", "100", "USD")]), "manana", [])
    assert "Ganancia: -1083,38" in texto


def test_alerta_cumple_esquema():
    c = cierre(ventas=[])
    datos = alerta_de(c, informe(c, "manana", []), "manana")
    datos.update(version=1, id="P-20261120-001", creada=MANANA.isoformat())
    p = cargar_propuesta(datos)
    assert p.tipo == "alerta" and p.alerta.titulo == "Cierre 19/11"


def test_manana_reescribe_y_guarda_la_noche(tmp_path):
    vlt = vault_cierre(tmp_path)
    noche = cierre(ventas=[v("A", "10", "USD")])
    escribir_cierre(vlt, noche, informe(noche, "noche", []), "noche", NOCHE, alerta_id="P-20261119-010")
    man = cierre(ventas=[v("A", "10", "USD"), v("B", "20", "USD")])
    escribir_cierre(vlt, man, informe(man, "manana", []), "manana", MANANA, alerta_id="P-20261120-001")
    meta, cuerpo = leer_cierre(vlt, noche.dia)
    assert meta["momentos"]["noche"]["provisional"] is True and meta["momentos"]["manana"]["alerta_id"]
    assert meta["totales"]["bruto_usd"] == "30.00" and "Gasto Meta" in cuerpo
    # una noche tardía no pisa el definitivo
    escribir_cierre(vlt, noche, informe(noche, "noche", []), "noche", NOCHE, alerta_id="P-20261119-011")
    meta2, _ = leer_cierre(vlt, noche.dia)
    assert meta2["totales"]["bruto_usd"] == "30.00" and meta2["historial"]


def test_recalcular_conserva_alerta_anterior(tmp_path):
    vlt = vault_cierre(tmp_path)
    c = cierre(ventas=[])
    escribir_cierre(vlt, c, informe(c, "manana", []), "manana", MANANA, alerta_id="P-20261120-001")
    escribir_cierre(vlt, c, informe(c, "manana", []), "manana", MANANA, alerta_id="P-20261120-002")
    meta, _ = leer_cierre(vlt, c.dia)
    assert meta["momentos"]["manana"]["alerta_id"] == "P-20261120-002"
    assert meta["historial"][0]["alerta_id"] == "P-20261120-001"


def test_pagina_sin_datos_personales(tmp_path):
    vlt = vault_cierre(tmp_path)
    c = cierre(ventas=[v("A", "10", "USD")])
    ruta = escribir_cierre(vlt, c, informe(c, "manana", []), "manana", MANANA)
    texto = ruta.read_text()
    assert "@" not in texto and "email" not in texto and Decimal(c.gasto_usd[0]) == Decimal("1183.38")
