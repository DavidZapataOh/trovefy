from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fabricas import operacion, pausar, presupuesto
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

def test_otros_tipos_24h_zona_desconocida_y_naive():
    p = cargar_propuesta(sin_expira(tipo="lote", operaciones=[operacion()]))
    q = cargar_propuesta(sin_expira())
    c = cot(2026, 11, 12, 10, 0)
    with pytest.raises(ValueError):
        caducidad(q, datetime(2026, 11, 12, 10, 0), BOG)
    with pytest.raises(ValueError):
        caducidad(q, c, "Marte/Olimpo")
    assert caducidad(p, c, SOF).tzinfo is not None
    assert recordatorios(q, c) == []

def test_creada_en_el_futuro_no_rompe():
    p = cargar_propuesta(presupuesto())
    assert caducidad(p, cot(2030, 1, 1, 10, 0), BOG) == cot(2030, 1, 1, 10, 45)
