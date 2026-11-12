from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fabricas import ADSET, CUENTA, alerta, estructura, operacion, pausar, presupuesto
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.limites import (
    CLAVES_CUENTA,
    ContextoVivo,
    comprobar,
    contexto_para,
)

AHORA = datetime(2026, 11, 12, 19, 10, tzinfo=UTC)
OTRO = "120245000000000102"
PAGINA = "1357661930771909"


def ctx(**c):
    base = {"ahora": AHORA, "stop": False, "valores": {(ADSET, "daily_budget"): 20000},
                "presupuestos_activos": {ADSET: 20000, OTRO: 100000}, "presupuesto_al_activar": {},
                "ultimos_cambios": {}, "cambios_ultima_hora": {}}
    return ContextoVivo(**{**base, **c})


def codigos(v): return [x.split(":")[0] for x in v]


def con_pagina(limites):
    lc = limites.cuentas[CUENTA]
    return replace(limites, cuentas={CUENTA: replace(lc, paginas_permitidas=frozenset({PAGINA}))})


def limite_ejecutor(id_, campo, cuenta=None, a=40, moneda="COP"):
    op = {"entidad": "ejecutor", "id": id_, "campo": campo, "de_esperado": 30, "a": a}
    if campo in CLAVES_CUENTA:  # resolución 22: las claves de dinero llevan unidad y moneda
        op |= {"unidad": "minima", "moneda": moneda}
    d = presupuesto(tipo="limite_ejecutor", operaciones=[op])
    if cuenta is None:
        d.pop("cuenta")
    else:
        d["cuenta"] = cuenta
    return d


def test_pasa(limites_cop):
    assert comprobar(cargar_propuesta(presupuesto()), limites_cop, ctx()) == []


def test_cuenta_ajena(limites_cop):
    v = comprobar(cargar_propuesta(presupuesto(cuenta="act_1234567890")), limites_cop, ctx(stop=False))
    assert codigos(v) == ["cuenta_no_permitida"]


# Los números se comprueban contra la plantilla real (tope 165.000, conjunto 99.000, paso 50 %).
@pytest.mark.parametrize("a,c,cod", [
    (30001, {}, "paso_excesivo"),                                   # 20.000 → 30.001 > +50 %
    (130000, {"valores": {(ADSET, "daily_budget"): 100000}}, "importe_sobre_limite"),
    (26000, {"valores": {}}, "valor_vivo_desconocido"),
    (26000, {"ultimos_cambios": {(ADSET, "daily_budget"): AHORA - timedelta(minutes=119)}}, "cadencia_presupuesto"),
    (26000, {"cambios_ultima_hora": {ADSET: 4}}, "max_cambios_hora"),
    (26000, {"presupuestos_activos": {ADSET: 20000, OTRO: 175000}}, "tope_diario_cuenta"),
    (26000, {"stop": True}, "stop_activo"),
])
def test_violaciones_presupuesto(limites_cop, a, c, cod):
    v = comprobar(cargar_propuesta(presupuesto(operaciones=[operacion(a=a)])), limites_cop, ctx(**c))
    assert cod in codigos(v)


def test_paso_justo_en_50_pct_pasa(limites_cop):
    assert comprobar(cargar_propuesta(presupuesto(operaciones=[operacion(a=30000)])), limites_cop, ctx()) == []


def test_cadencia_justo_en_120_min_pasa(limites_cop):
    c = ctx(ultimos_cambios={(ADSET, "daily_budget"): AHORA - timedelta(minutes=120)})
    assert comprobar(cargar_propuesta(presupuesto()), limites_cop, c) == []


def test_tope_justo_en_el_limite_pasa(limites_cop):
    # 26.000 + 139.000 = 165.000 = tope
    c = ctx(presupuestos_activos={ADSET: 20000, OTRO: 139000})
    assert comprobar(cargar_propuesta(presupuesto()), limites_cop, c) == []


def test_valor_vivo_no_entero_es_desconocido(limites_cop):
    v = comprobar(cargar_propuesta(presupuesto()), limites_cop, ctx(valores={(ADSET, "daily_budget"): "20000"}))
    assert "valor_vivo_desconocido" in codigos(v)


def test_bajada_sin_tope_de_paso_y_no_frenada_por_tope(limites_cop):
    # La cuenta ya está por encima del tope; bajar presupuesto reduce el gasto y pasa.
    c = ctx(valores={(ADSET, "daily_budget"): 90000}, presupuestos_activos={ADSET: 90000, OTRO: 100000})
    assert comprobar(cargar_propuesta(presupuesto(operaciones=[operacion(de_esperado=90000, a=1000)])),
                     limites_cop, c) == []


def test_pausar_pasa_aunque_la_cuenta_supere_el_tope(limites_cop):
    assert comprobar(cargar_propuesta(pausar()), limites_cop, ctx(presupuestos_activos={OTRO: 500000})) == []


def test_lote_se_evalua_con_su_efecto_acumulado(limites_cop):
    b = "120245000000000103"
    c = ctx(valores={(ADSET, "daily_budget"): 60000, (b, "daily_budget"): 60000},
            presupuestos_activos={ADSET: 60000, b: 60000, OTRO: 40000})
    sola = presupuesto(operaciones=[operacion(de_esperado=60000, a=63000)])
    assert comprobar(cargar_propuesta(sola), limites_cop, c) == []
    lote = presupuesto(tipo="lote", operaciones=[operacion(de_esperado=60000, a=63000),
                                                 operacion(id=b, de_esperado=60000, a=63000)])
    assert codigos(comprobar(cargar_propuesta(lote), limites_cop, c)) == ["tope_diario_cuenta"]


def _activar(id_=ADSET):
    return presupuesto(tipo="activar", operaciones=[
        {"entidad": "adset", "id": id_, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}])


def test_activar_sin_presupuesto_conocido(limites_cop):
    v = comprobar(cargar_propuesta(_activar("120245000000000109")), limites_cop, ctx())
    assert "valor_vivo_desconocido" in codigos(v)


def test_activar_suma_al_total(limites_cop):
    nuevo = "120245000000000109"
    assert comprobar(cargar_propuesta(_activar(nuevo)), limites_cop,
                     ctx(presupuesto_al_activar={nuevo: 45000})) == []
    v = comprobar(cargar_propuesta(_activar(nuevo)), limites_cop, ctx(presupuesto_al_activar={nuevo: 46000}))
    assert codigos(v) == ["tope_diario_cuenta"]


def test_activar_sin_offset_se_bloquea(limites_cop_sin_offset):
    nuevo = "120245000000000109"
    v = comprobar(cargar_propuesta(_activar(nuevo)), limites_cop_sin_offset, ctx(presupuesto_al_activar={nuevo: 1}))
    assert codigos(v) == ["moneda_no_configurada"]


def test_cop_sin_offset_bloquea_importes(limites_cop_sin_offset):
    for d in (presupuesto(), estructura()):
        assert codigos(comprobar(cargar_propuesta(d), limites_cop_sin_offset, ctx())) == ["moneda_no_configurada"]
    v = comprobar(cargar_propuesta(presupuesto()), limites_cop_sin_offset, ctx())
    assert v == ["moneda_no_configurada: COP sin offset confirmado (P-21)"]


def test_cop_sin_offset_deja_pausar(limites_cop_sin_offset):
    assert comprobar(cargar_propuesta(pausar()), limites_cop_sin_offset, ctx()) == []


def test_moneda_distinta(limites_cop):
    v = comprobar(cargar_propuesta(presupuesto(operaciones=[operacion(moneda="USD")])), limites_cop, ctx())
    assert codigos(v) == ["moneda_distinta"]


def test_tipo_no_permitido(limites_cop):
    lim = replace(limites_cop, acciones_permitidas=frozenset({"pausar"}))
    assert codigos(comprobar(cargar_propuesta(presupuesto()), lim, ctx())) == ["tipo_no_permitido"]


def test_alerta_pasa_con_stop(limites_cop):
    assert comprobar(cargar_propuesta(alerta()), limites_cop, ctx(stop=True)) == []


def test_alerta_no_permitida_y_futura(limites_cop):
    lim = replace(limites_cop, acciones_permitidas=frozenset({"pausar"}))
    v = comprobar(cargar_propuesta(alerta(creada="2026-11-12T15:00:00-05:00")), lim, ctx(stop=True))
    assert codigos(v) == ["creada_en_el_futuro", "tipo_no_permitido"]


def test_creada_en_el_futuro(limites_cop):
    v = comprobar(cargar_propuesta(presupuesto(creada="2026-11-12T15:00:00-05:00")), limites_cop, ctx())
    assert "creada_en_el_futuro" in codigos(v)
    # 5 minutos de margen exactos: pasa
    assert comprobar(cargar_propuesta(presupuesto(creada="2026-11-12T14:15:00-05:00")), limites_cop, ctx()) == []


def test_puja_enfriamiento(limites_cop):
    d = presupuesto(tipo="puja", operaciones=[operacion(campo="bid_amount", de_esperado=None, a=5000)])
    c = ctx(ultimos_cambios={(ADSET, "estructura"): AHORA - timedelta(hours=47)})
    assert codigos(comprobar(cargar_propuesta(d), limites_cop, c)) == ["enfriamiento_puja_estructura"]
    c = ctx(ultimos_cambios={(ADSET, "bid_amount"): AHORA - timedelta(hours=48)})
    assert comprobar(cargar_propuesta(d), limites_cop, c) == []


def test_spend_cap_campana(limites_cop):
    def d(a):
        return presupuesto(tipo="spend_cap", operaciones=[
            operacion(entidad="campaign", campo="spend_cap", de_esperado=None, a=a)])
    assert comprobar(cargar_propuesta(d(181500)), limites_cop, ctx()) == []
    assert codigos(comprobar(cargar_propuesta(d(181501)), limites_cop, ctx())) == ["importe_sobre_limite"]


def test_limite_ejecutor(limites_cop):
    assert comprobar(cargar_propuesta(limite_ejecutor("global", "paso_max_pct")), limites_cop, ctx()) == []
    assert comprobar(cargar_propuesta(limite_ejecutor(CUENTA, "tope_gasto_diario_total")), limites_cop, ctx()) == []
    for id_, campo in (("global", "tope_gasto_diario_total"), (CUENTA, "paso_max_pct"),
                       ("act_999", "tope_gasto_diario_total"), ("global", "inventada")):
        v = comprobar(cargar_propuesta(limite_ejecutor(id_, campo)), limites_cop, ctx())
        assert codigos(v) == ["clave_limite_desconocida"], (id_, campo)
    v = comprobar(cargar_propuesta(limite_ejecutor("global", "paso_max_pct", cuenta="act_999")), limites_cop, ctx())
    assert codigos(v) == ["cuenta_no_permitida"]


def test_estructura_pasa(limites_cop):
    d = estructura(); d["campana"]["spend_cap"] = 99000
    assert comprobar(cargar_propuesta(d), con_pagina(limites_cop), ctx()) == []


def test_estructura_pagina_y_spend_cap(limites_cop):
    d = estructura(pagina_id="111"); d["campana"]["spend_cap"] = 130000
    assert {"pagina_no_permitida", "spend_cap_sobre_limite"} <= set(codigos(comprobar(cargar_propuesta(d), limites_cop, ctx())))


def test_estructura_dataset_e_importes(limites_cop):
    d = estructura(dataset_id="1"); d["campana"]["spend_cap"] = 99000
    c0 = d["conjuntos"][0]
    d["conjuntos"] = [{**c0, "nombre": "A", "daily_budget": 99001}, {**c0, "nombre": "B", "daily_budget": 90000}]
    v = codigos(comprobar(cargar_propuesta(d), con_pagina(limites_cop), ctx()))
    assert v == ["dataset_no_permitido", "importe_sobre_limite", "tope_diario_cuenta"]


def test_estructura_cbo(limites_cop):
    d = estructura(); d["campana"].update(spend_cap=99000, tipo_presupuesto="CBO", daily_budget=132001)
    d["conjuntos"][0].pop("daily_budget")
    assert codigos(comprobar(cargar_propuesta(d), con_pagina(limites_cop), ctx())) == ["importe_sobre_limite"]


def test_estructura_con_stop(limites_cop):
    d = estructura(); d["campana"]["spend_cap"] = 99000
    assert codigos(comprobar(cargar_propuesta(d), con_pagina(limites_cop), ctx(stop=True))) == ["stop_activo"]


def test_sin_duplicados(limites_cop):
    b = "120245000000000103"
    lote = presupuesto(tipo="lote", operaciones=[operacion(), operacion(id=b)])
    v = comprobar(cargar_propuesta(lote), limites_cop,
                  ctx(valores={}, presupuestos_activos={ADSET: 20000, b: 20000, OTRO: 100000}))
    assert len(v) == len(set(v)) == 2 and codigos(v) == ["valor_vivo_desconocido"] * 2


def test_contexto_naive_rechazado():
    with pytest.raises(ValueError):
        ctx(ahora=datetime(2026, 11, 12, 19, 10))


def test_contexto_para_desde_almacen(tmp_path, limites_cop):
    alm = Almacen(tmp_path / "e.sqlite")
    for m in (5, 20, 40, 59):
        alm.registrar_cambio(ADSET, "daily_budget", AHORA - timedelta(minutes=m))
    alm.registrar_cambio(ADSET, "daily_budget", AHORA - timedelta(minutes=61))
    alm.registrar_cambio(ADSET, "estructura", AHORA - timedelta(hours=3))
    p = cargar_propuesta(presupuesto())
    c = contexto_para(p, alm, ahora=AHORA, stop=False, valores={(ADSET, "daily_budget"): 20000},
                      presupuestos_activos={ADSET: 20000}, presupuesto_al_activar={})
    assert c.cambios_ultima_hora[ADSET] == 4
    assert c.ultimos_cambios[(ADSET, "daily_budget")] == AHORA - timedelta(minutes=5)
    assert c.ultimos_cambios[(ADSET, "estructura")] == AHORA - timedelta(hours=3)
    assert (ADSET, "bid_amount") not in c.ultimos_cambios
    assert "max_cambios_hora" in codigos(comprobar(p, limites_cop, c))


# --- C1: el tope diario no depende del orden de las operaciones de un lote ---------------------
PAUSADO = "120245000000000109"
CAMPANA = "120245000000000200"


def _op_activar(id_, entidad="adset"):
    return {"entidad": entidad, "id": id_, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}


def _ctx_pausado(**c):
    base = {"valores": {(PAUSADO, "daily_budget"): 60000, (PAUSADO, "status"): "PAUSED"},
            "presupuestos_activos": {OTRO: 100000}, "presupuesto_al_activar": {PAUSADO: 60000, CAMPANA: 10000}}
    return ctx(**{**base, **c})


@pytest.mark.parametrize("orden", ["subir_y_activar", "activar_y_subir"])
def test_lote_subir_y_activar_pausado_respeta_el_tope_en_cualquier_orden(limites_cop, orden):
    # 100.000 activos + 90.000 de PAUSADO = 190.000 > 165.000, sea cual sea el orden.
    subir = operacion(id=PAUSADO, de_esperado=60000, a=90000)
    ops = [subir, _op_activar(PAUSADO)] if orden == "subir_y_activar" else [_op_activar(PAUSADO), subir]
    v = comprobar(cargar_propuesta(presupuesto(tipo="lote", operaciones=ops)), limites_cop, _ctx_pausado())
    assert codigos(v) == ["tope_diario_cuenta"]


@pytest.mark.parametrize("orden", ["subir_y_activar_padre", "activar_padre_y_subir"])
def test_lote_presupuesto_pendiente_y_activar_otra_entidad_es_desconocido(limites_cop, orden):
    subir = operacion(id=PAUSADO, de_esperado=60000, a=61000)
    padre = _op_activar(CAMPANA, entidad="campaign")
    ops = [subir, padre] if orden == "subir_y_activar_padre" else [padre, subir]
    v = comprobar(cargar_propuesta(presupuesto(tipo="lote", operaciones=ops)), limites_cop, _ctx_pausado())
    assert "valor_vivo_desconocido" in codigos(v)


# --- M5: subir gasto de una entidad que no está en presupuestos_activos exige saberla PAUSED -----
@pytest.mark.parametrize("status,pasa", [(None, False), ("ACTIVE", False), ("PAUSED", True)])
def test_subir_presupuesto_fuera_de_activos_exige_pausada(limites_cop, status, pasa):
    valores = {(PAUSADO, "daily_budget"): 60000}
    if status is not None:
        valores[(PAUSADO, "status")] = status
    d = presupuesto(operaciones=[operacion(id=PAUSADO, de_esperado=60000, a=61000)])
    v = comprobar(cargar_propuesta(d), limites_cop, _ctx_pausado(valores=valores))
    assert v == [] if pasa else "valor_vivo_desconocido" in codigos(v)


@pytest.mark.parametrize("status,pasa", [(None, False), ("ACTIVE", False), ("PAUSED", True)])
def test_subir_puja_fuera_de_activos_exige_pausada(limites_cop, status, pasa):
    valores = {} if status is None else {(PAUSADO, "status"): status}
    d = presupuesto(tipo="puja", operaciones=[operacion(id=PAUSADO, campo="bid_amount", de_esperado=None, a=5000)])
    v = comprobar(cargar_propuesta(d), limites_cop, _ctx_pausado(valores=valores))
    assert v == [] if pasa else "valor_vivo_desconocido" in codigos(v)


def test_bajar_presupuesto_fuera_de_activos_pasa_sin_status(limites_cop):
    d = presupuesto(operaciones=[operacion(id=PAUSADO, de_esperado=60000, a=50000)])
    v = comprobar(cargar_propuesta(d), limites_cop, _ctx_pausado(valores={(PAUSADO, "daily_budget"): 60000}))
    assert v == []


# --- I2 / M2: limite_ejecutor (resolución 22) --------------------------------------------------
def test_limite_ejecutor_moneda_de_la_cuenta(limites_cop, limites_cop_sin_offset):
    v = comprobar(cargar_propuesta(limite_ejecutor(CUENTA, "tope_gasto_diario_total", moneda="USD")),
                  limites_cop, ctx())
    assert codigos(v) == ["moneda_distinta"]
    v = comprobar(cargar_propuesta(limite_ejecutor(CUENTA, "tope_gasto_diario_total")), limites_cop_sin_offset, ctx())
    assert codigos(v) == ["moneda_no_configurada"]
    # Una clave entera no lleva moneda: el offset sin confirmar no la bloquea.
    assert comprobar(cargar_propuesta(limite_ejecutor("global", "paso_max_pct")), limites_cop_sin_offset, ctx()) == []


@pytest.mark.parametrize("a,pasa", [(100, True), (101, False)])
def test_limite_ejecutor_respeta_las_cotas_del_cargador(limites_cop, a, pasa):
    v = comprobar(cargar_propuesta(limite_ejecutor("global", "paso_max_pct", a=a)), limites_cop, ctx())
    assert v == [] if pasa else codigos(v) == ["limite_fuera_de_cota"]


def test_limite_cuenta_pasa(limites_cop):
    d = presupuesto(tipo="limite_cuenta", operaciones=[operacion(entidad="account", id=CUENTA, campo="spend_cap",
                                                                 de_esperado=None, a=500000)])
    assert comprobar(cargar_propuesta(d), limites_cop, ctx()) == []
