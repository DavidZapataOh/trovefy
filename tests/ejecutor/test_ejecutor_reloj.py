from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fabricas import ADSET, alerta, estructura, operacion, pausar, presupuesto
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.reloj import (
    ZONA_COT,
    base_caducidad,
    caducidad,
    en_silencio,
    fin_silencio,
    recordatorios,
)

BOG, SOF = "America/Bogota", "Europe/Sofia"
def cot(*a): return datetime(*a, tzinfo=ZONA_COT)
def sin_expira(**c): return {k: v for k, v in presupuesto(**c).items() if k != "expira_en_min"}

def test_presupuesto_fin_del_dia_bogota_cruzando_medianoche():
    p = cargar_propuesta(sin_expira())
    assert caducidad(p, cot(2026, 11, 12, 23, 30), BOG) == cot(2026, 11, 13, 0, 0)
    assert caducidad(p, cot(2026, 11, 12, 0, 0), BOG) == cot(2026, 11, 13, 0, 0)

def test_expira_en_min_solo_acorta():
    p = cargar_propuesta(presupuesto())                       # expira_en_min = 45
    assert caducidad(p, cot(2026, 11, 12, 14, 5), BOG) == cot(2026, 11, 12, 14, 50)
    assert caducidad(p, cot(2026, 11, 12, 23, 30), BOG) == cot(2026, 11, 13, 0, 0)

def test_fin_del_dia_en_sofia_desde_cot():
    p = cargar_propuesta(sin_expira())
    # 18:00 COT del 12 = 01:00 del 13 en Sofía → caduca a las 00:00 del 14 en Sofía = 17:00 COT del 13
    assert caducidad(p, cot(2026, 11, 12, 18, 0), SOF) == cot(2026, 11, 13, 17, 0)

def test_dia_con_cambio_de_hora():
    p = cargar_propuesta(sin_expira())
    c = datetime(2026, 10, 25, 10, 0, tzinfo=ZoneInfo(SOF))   # el 25-oct en Sofía dura 25 h
    assert caducidad(p, c, SOF) == datetime(2026, 10, 25, 22, 0, tzinfo=UTC)

def test_lote_23_59_con_minimo():
    p = cargar_propuesta(sin_expira(tipo="lote", operaciones=[operacion()]))
    assert caducidad(p, cot(2026, 11, 12, 23, 0), BOG) == cot(2026, 11, 12, 23, 59)
    assert caducidad(p, cot(2026, 11, 12, 23, 50), BOG) == cot(2026, 11, 13, 0, 20)

def test_pausar_6h_y_recordatorios():
    p = cargar_propuesta({k: v for k, v in pausar().items() if k != "expira_en_min"}); c = cot(2026, 11, 12, 20, 0)
    assert caducidad(p, c, BOG) == c + timedelta(hours=6)
    assert recordatorios(p, c) == [c + timedelta(hours=1), c + timedelta(hours=3)]

def test_base_caducidad_no_rejuvenece():
    p = cargar_propuesta(presupuesto())                      # creada 14:05 COT
    assert base_caducidad(p, cot(2026, 11, 13, 9, 0)) == cot(2026, 11, 12, 14, 5)

@pytest.mark.parametrize("h,m,silencio", [(22, 59, False), (23, 0, True), (3, 0, True), (6, 29, True), (6, 30, False)])
def test_silencio_bordes(h, m, silencio):
    assert en_silencio(cot(2026, 11, 12, h, m)) is silencio

def test_silencio_desde_otra_zona_y_naive():
    assert en_silencio(datetime(2026, 11, 13, 4, 30, tzinfo=UTC))   # 23:30 COT
    assert fin_silencio(cot(2026, 11, 12, 23, 30)) == cot(2026, 11, 13, 6, 30)
    with pytest.raises(ValueError):
        en_silencio(datetime(2026, 11, 12, 23, 30))

def _sin(d): return {k: v for k, v in d.items() if k != "expira_en_min"}

def _de_tipo(tipo):
    """Propuesta válida de `tipo` sin expira_en_min. activar, alerta y estructura vienen de las fábricas;
    el resto reutiliza una propuesta válida con el tipo cambiado (caducidad solo mira tipo y expira_en_min)."""
    if tipo == "activar":
        return cargar_propuesta(_sin(pausar(tipo="activar", operaciones=[
            {"entidad": "adset", "id": ADSET, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}])))
    if tipo == "alerta":
        return cargar_propuesta(alerta())
    if tipo == "crear_estructura_pausada":
        return cargar_propuesta(estructura())
    return replace(cargar_propuesta(_sin(presupuesto())), tipo=tipo)

@pytest.mark.parametrize("tipo", ["activar", "agenda", "regla_meta", "puja", "spend_cap", "limite_cuenta",
                                  "limite_ejecutor", "noop", "alerta", "crear_estructura_pausada"])
@pytest.mark.parametrize("zona", [BOG, SOF])
def test_tipos_de_24h(tipo, zona):
    p = _de_tipo(tipo)
    c = cot(2026, 11, 12, 10, 0)
    r = caducidad(p, c, zona)
    assert r == c + timedelta(hours=24)
    assert r.utcoffset() == c.astimezone(ZoneInfo(zona)).utcoffset()

def test_pausar_con_expira_en_min_caduca_a_los_45():
    p = cargar_propuesta(pausar()); c = cot(2026, 11, 12, 20, 0)
    assert caducidad(p, c, BOG) == c + timedelta(minutes=45)

def test_recordatorios_no_pasan_de_la_caducidad():
    c = cot(2026, 11, 12, 20, 0)
    assert recordatorios(cargar_propuesta(pausar()), c) == []                      # expira a los 45 min
    p = cargar_propuesta(pausar(expira_en_min=120))
    assert recordatorios(p, c) == [c + timedelta(hours=1)]
    assert recordatorios(cargar_propuesta(pausar(expira_en_min=60)), c) == []      # el borde excluye

def test_zona_desconocida_naive_y_sin_recordatorios():
    q = cargar_propuesta(sin_expira())
    c = cot(2026, 11, 12, 10, 0)
    with pytest.raises(ValueError):
        caducidad(q, datetime(2026, 11, 12, 10, 0), BOG)
    with pytest.raises(ValueError):
        caducidad(q, c, "Marte/Olimpo")
    assert recordatorios(q, c) == []

def test_lote_en_sofia():
    p = cargar_propuesta(sin_expira(tipo="lote", operaciones=[operacion()]))
    # 12:00 COT = 19:00 Sofía del 12 → 23:59 Sofía = 16:59 COT
    assert caducidad(p, cot(2026, 11, 12, 12, 0), SOF) == cot(2026, 11, 12, 16, 59)
    # 15:50 COT = 22:50 Sofía → faltan 69 min, se mantiene 23:59 Sofía
    assert caducidad(p, cot(2026, 11, 12, 15, 50), SOF) == cot(2026, 11, 12, 16, 59)
    # 16:45 COT = 23:45 Sofía → faltan 14 min → creada + 30 min
    assert caducidad(p, cot(2026, 11, 12, 16, 45), SOF) == cot(2026, 11, 12, 17, 15)

def test_fin_silencio_pasada_medianoche():
    assert fin_silencio(cot(2026, 11, 13, 2, 0)) == cot(2026, 11, 13, 6, 30)
    assert fin_silencio(cot(2026, 11, 13, 6, 30)) == cot(2026, 11, 14, 6, 30)

def test_base_caducidad_con_creada_futura_usa_recibida():
    p = cargar_propuesta(presupuesto(creada="2030-01-01T10:00:00-05:00"))
    r = cot(2026, 11, 12, 14, 0)
    assert base_caducidad(p, r) == r
    assert caducidad(p, base_caducidad(p, r), BOG) == r + timedelta(minutes=45)
