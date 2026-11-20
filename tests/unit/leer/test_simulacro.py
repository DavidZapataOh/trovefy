"""Simulacro de tres días (plan 23, Tarea 12, paso 1): cortes, surf, base y muerto, con el Aceptar simulado.

El Aceptar se simula con la copia que deja el ejecutor en ``propuestas/`` (la misma forma que ``CopiaVault``); no se
habla con Meta ni con Telegram.
"""
import json
from datetime import datetime

from trovefy import cli
from trovefy.montar.tanda import bloque_pais
from unit.montar.ejemplos import copia_ejecutor

from .ejemplos import CONJUNTOS, PAIS, P, meta_adsets
from .test_cli import BASE, _entrada, _filas, _importar, entorno  # noqa: F401 - fixture

D1 = datetime.fromisoformat("2026-11-20T07:30:00-05:00")
D2 = datetime.fromisoformat("2026-11-20T18:00:00-05:00")


def _ultima(tmp):
    return json.loads(_entrada(tmp)[-1].read_text(encoding="utf-8"))


def test_tres_dias_sin_ventas_acaba_en_muerto(entorno):  # noqa: F811
    v, tmp = entorno
    # día 1: US$ 4 por conjunto; uno con CPC 0,7 → pausar 1 conjunto
    filas = _filas(["16000", "16000", "16000"])
    filas["ad_entities"][1]["insights"]["data"][0]["link_click"] = "5"  # 4 USD / 5 clics = 0,80
    _importar(tmp, D1, adsets=filas)
    assert cli.main(["leer", "parte", *BASE, "--ahora", D1.isoformat()]) == 1
    p = _ultima(tmp)
    assert p["tipo"] == "pausar" and p["operaciones"][0]["id"] == CONJUNTOS["AD02 G1 villano"]
    copia_ejecutor(v, _entrada(tmp)[-1].stem, "pausar", "ejecutada")
    # día 2, intradía: la oferta sin ventas llega a US$ 25 → pausar campaña, alta
    filas = _filas(["40000", "20000", "40000"])
    filas["ad_entities"][1]["effective_status"] = "PAUSED"
    _importar(tmp, D2, intradia=True, adsets=filas)
    assert cli.main(["leer", "intradia", *BASE, "--ahora", D2.isoformat()]) == 1
    p = _ultima(tmp)
    assert p["operaciones"][0]["entidad"] == "campaign" and p["prioridad"] == "alta"
    copia_ejecutor(v, _entrada(tmp)[-1].stem, "pausar", "ejecutada")
    assert cli.main(["leer", "estado", *BASE, "--ahora", D2.isoformat()]) == 0
    b = bloque_pais(v, P, PAIS)
    assert b["estado"] == "muerto"
    assert any(e.startswith("stop: [[wiki/analisis/partes/") for e in b["historial"][-1]["evidencia"])


def test_con_ventas_surf_base_y_sin_muerto_antes_de_72h(entorno):  # noqa: F811
    v, tmp = entorno
    ad3 = CONJUNTOS["AD03 G1 sueño"]
    dia = meta_adsets([{"id": ad3, "name": "AD03 G1 sueño", "daily_budget": "20000",
                        "insights": {"amount_spent": "20000"}}])
    _importar(tmp, D2, intradia=True, adsets=_filas(["30000", "30000", "40000"]),
              ventas=[("AD03 G1 sueño", 1, 13.9)], ventas_dia=[("AD03 G1 sueño", 1, 13.9)], dia=dia)
    assert cli.main(["leer", "intradia", *BASE, "--ahora", D2.isoformat()]) == 1
    p = _ultima(tmp)
    assert p["tipo"] == "presupuesto" and p["operaciones"][0]["a"] == 40000
    copia_ejecutor(v, _entrada(tmp)[-1].stem, "presupuesto", "ejecutada")
    noche = datetime.fromisoformat("2026-11-20T23:00:00-05:00")
    _importar(tmp, noche, intradia=True, adsets=_filas(["30000", "30000", "40000"], ["20000", "20000", "40000"]),
              ventas=[("AD03 G1 sueño", 1, 13.9)])
    assert cli.main(["leer", "base", *BASE, "--ahora", noche.isoformat()]) == 1
    p = _ultima(tmp)
    assert p["operaciones"] == [{"entidad": "adset", "id": ad3, "campo": "daily_budget", "de_esperado": 40000,
                                 "a": 20000, "unidad": "minima", "moneda": "COP"}]
    b = bloque_pais(v, P, PAIS)
    assert b["estado"] == "test" and b["lectura"]["surf"][ad3]["presupuesto"] == 40000
