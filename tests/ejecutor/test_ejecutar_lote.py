"""Lotes op por op, tipos sin Meta y tipos no soportados (plan 11, tarea 5).

Almacén y auditoría reales en ``tmp_path`` (fixture ``entorno``). Nunca Graph real ni red.
"""
from __future__ import annotations

import dataclasses
import json

import pytest
from ejecutor.fabricas import alerta as alerta_dict
from ejecutor.fabricas_graph import propuesta
from ejecutor.falsos.graph_falso import CUENTA
from trovefy_ejecutor.ejecutar import (
    CAMPOS_POR_TIPO,
    NO_SOPORTADO_P07,
    TIPOS_SOPORTADOS,
    ejecutar,
)
from trovefy_ejecutor.esquema import REGLAS, cargar_propuesta
from trovefy_ejecutor.graph import ErrorGraph
from trovefy_ejecutor.modelo import TIPOS, Operacion

OPS = [{"entidad": "adset", "id": "s1", "campo": "daily_budget", "de_esperado": 20000, "a": 15000,
        "unidad": "minima", "moneda": "COP"},
       {"entidad": "adset", "id": "s2", "campo": "daily_budget", "de_esperado": 15000, "a": 10000,
        "unidad": "minima", "moneda": "COP"}]
PAUSAR_A1 = {"entidad": "ad", "id": "a1", "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}


def _reales(g):
    return [x for x in g.llamadas if x.metodo == "escribir" and not x.validate_only]


def _ejecuciones(aud):
    if not aud.ruta.exists():
        return []
    return [e["datos"] for e in (json.loads(x) for x in aud.ruta.read_text().splitlines())
            if e["evento"] == "ejecucion"]


def _noop():
    return cargar_propuesta({"version": 1, "id": "P-20261112-011", "tipo": "noop",
                             "creada": "2026-11-12T09:00:00-05:00", "origen": "/arranque"})


def _limite(**op):
    base = {"entidad": "ejecutor", "id": CUENTA, "campo": "tope_gasto_diario_total", "de_esperado": 200000,
            "a": 240000, "unidad": "minima", "moneda": "COP"}
    base.update(op)
    return cargar_propuesta({"version": 1, "id": "P-20261112-012", "tipo": "limite_ejecutor",
                             "creada": "2026-11-12T09:00:00-05:00", "origen": "/limites",
                             "motivo": "subir el tope diario", "operaciones": [base]})


# -- lote ----------------------------------------------------------------------------------
def test_lote_ok(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert (r.estado, r.parcial, r.error) == ("ejecutada", False, None)
    assert [o.estado for o in r.operaciones] == ["ejecutada"] * 3
    assert "3 de 3 aplicadas" in r.detalle
    assert [x.ruta for x in g.escrituras()] == ["s1", "s2", "a1"]


def test_lote_parcial(entorno):
    g, alm, aud = entorno
    # (adaptado) error en la escritura real: con ``errores`` fallaría ya en validate_only y s1 no
    # llegaría a escribirse; así se ve que s1 no se reintenta y que el lote sigue con s2.
    g.errores_reales["s1"] = ErrorGraph(100, None, "Invalid")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert r.estado == "fallida" and r.parcial and [o.estado for o in r.operaciones] == ["fallida", "ejecutada"]
    assert [x.ruta for x in g.escrituras()] == ["s1", "s2"]  # s1 no se reintenta
    assert "parcial: 1 de 2 aplicadas" in r.detalle and r.error == "otro"
    assert g.objetos["s1"]["daily_budget"] == "20000" and g.objetos["s2"]["daily_budget"] == "10000"


def test_lote_fallo_en_validate_only_sigue_con_el_resto(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(100, None, "Invalid")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.parcial) == ("fallida", True)
    assert [x.ruta for x in g.escrituras()] == ["s2"]


def test_lote_todas_fallidas_no_es_parcial(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(100, None, "Invalid")
    g.errores["s2"] = ErrorGraph(100, None, "Invalid")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.parcial) == ("fallida", False) and "0 de 2 aplicadas" in r.detalle
    assert g.escrituras() == []


def test_lote_con_una_op_desfasada_es_obsoleto(entorno):
    g, alm, aud = entorno
    g.cambiar("s2", daily_budget="16000")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert r.estado == "obsoleta" and g.escrituras() == []
    assert [x for x in g.llamadas if x.metodo == "escribir"] == []  # ni validate_only
    assert [o.estado for o in r.operaciones] == ["no_intentada", "no_intentada"]


def _posts_a(g, ruta):
    return [x for x in g.llamadas if x.metodo == "escribir" and x.ruta == ruta]


def test_token_caduca_a_mitad_del_lote(entorno):
    g, alm, aud = entorno
    # (adaptado) el token caduca justo después de que la relectura de s1 confirme el cambio; con
    # ``token_caduca_tras = 1`` a secas caducaría antes de esa relectura (ver el test siguiente).
    original = g.leer

    def leer(id, campos):
        salida = original(id, campos)
        if id == "s1" and g.escrituras():
            g.token_caduca_tras = 1
        return salida

    g.leer = leer
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["ejecutada", "fallida", "no_intentada"] and r.error == "token"
    assert len(g.escrituras()) == 1
    assert _posts_a(g, "a1") == []  # la restante ni se llama
    assert (r.estado, r.parcial) == ("fallida", True) and "parcial: 1 de 3 aplicadas" in r.detalle


def test_token_caduca_antes_de_releer_es_discrepancia(entorno):
    g, alm, aud = entorno
    g.token_caduca_tras = 1  # caduca tras la primera escritura real: su relectura ya falla
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["discrepancia", "fallida", "no_intentada"]
    assert (r.estado, r.error) == ("discrepancia", "token")
    assert len(g.escrituras()) == 1 and _posts_a(g, "a1") == []


def test_token_tras_otro_fallo_manda_token(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(100, None, "Invalid")
    g.errores["s2"] = ErrorGraph(190, 463, "token caducado")
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["fallida", "fallida", "no_intentada"] and r.error == "token"
    assert g.escrituras() == []


def test_stop_a_mitad_del_lote(entorno):
    g, alm, aud = entorno
    g.stop_tras = 1
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.parcial, r.error) == ("fallida", True, "stop")
    assert [o.estado for o in r.operaciones] == ["ejecutada", "no_intentada"] and len(g.escrituras()) == 1


def test_stop_tras_un_fallo_deja_el_resto_sin_intentar(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(100, None, "Invalid")
    g.stop_tras = 0
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert (r.estado, r.parcial, r.error) == ("fallida", True, "stop")
    assert [o.estado for o in r.operaciones] == ["fallida", "no_intentada", "no_intentada"]
    assert g.escrituras() == [] and _posts_a(g, "a1") == []


def test_lote_discrepancia_no_detiene_y_manda(entorno):
    g, alm, aud = entorno
    g.redondeo["s1"] = 15100
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.parcial) == ("discrepancia", True)
    assert [o.estado for o in r.operaciones] == ["discrepancia", "ejecutada"]
    assert "parcial: 1 de 2 aplicadas" in r.detalle and len(_reales(g)) == 2


def test_lote_discrepancia_y_fallida_es_discrepancia(entorno):
    g, alm, aud = entorno
    g.redondeo["s1"] = 15100
    g.errores["s2"] = ErrorGraph(100, None, "Invalid")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.parcial) == ("discrepancia", False) and "0 de 2 aplicadas" in r.detalle


def test_lote_no_activa(entorno):
    g, alm, aud = entorno
    g.cambiar("s1", status="PAUSED")
    op = {"entidad": "adset", "id": "s1", "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
    assert ejecutar(propuesta(tipo="lote", ops=[op]), g, alm, aud).estado == "fallida" and g.llamadas == []


def test_lote_activar_en_medio_rechaza_todo(entorno):
    g, alm, aud = entorno
    op = {"entidad": "ad", "id": "a1", "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
    r = ejecutar(propuesta(tipo="lote", ops=[OPS[0], op]), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


@pytest.mark.parametrize("op", [
    {"campo": "bid_amount", "de_esperado": 1500, "a": 1800},
    {"entidad": "campaign", "id": "c1", "campo": "spend_cap", "de_esperado": None, "a": 600000},
    {"entidad": "account", "id": CUENTA, "campo": "spend_cap", "de_esperado": 1000000, "a": 1200000},
    {"campo": "lifetime_budget", "de_esperado": 90000, "a": 100000},
])
def test_lote_solo_presupuesto_y_pausar(entorno, op):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="lote", ops=[OPS[1], op]), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


def test_lote_auditoria(entorno):
    g, alm, aud = entorno
    ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    ev = _ejecuciones(aud)
    assert [(e["validate_only"], e["ok"]) for e in ev] == [(True, True), (False, True)] * 2 + [(False, True)]
    assert all(e["tipo"] == "lote" for e in ev) and aud.verificar()


def test_formas_del_lote_dentro_del_esquema():
    assert CAMPOS_POR_TIPO["lote"] == CAMPOS_POR_TIPO["presupuesto"] | CAMPOS_POR_TIPO["pausar"]
    for entidad, campo in CAMPOS_POR_TIPO["lote"]:
        assert any(entidad in r.entidades and r.campo == campo for r in REGLAS["lote"]), (entidad, campo)
    # ningún campo de puja, spend_cap ni cuenta (el esquema de lote no los admite)
    assert not {c for _e, c in CAMPOS_POR_TIPO["lote"]} & {"bid_amount", "spend_cap"}


# -- tipos sin Meta ------------------------------------------------------------------------
def test_noop_no_toca_meta(entorno):
    g, alm, aud = entorno
    r = ejecutar(_noop(), g, alm, aud)
    assert r.estado == "ejecutada" and g.llamadas == []
    assert r.detalle == "circuito probado; nada cambió en Meta"
    ev = _ejecuciones(aud)
    assert len(ev) == 1 and (ev[0]["validate_only"], ev[0]["ok"], ev[0]["tipo"]) == (False, True, "noop")


def test_alerta_no_toca_meta(entorno):
    g, alm, aud = entorno
    r = ejecutar(cargar_propuesta(alerta_dict()), g, alm, aud)
    assert (r.estado, r.detalle) == ("ejecutada", "notificación; nada cambió en Meta") and g.llamadas == []
    assert len(_ejecuciones(aud)) == 1


def test_limite_ejecutor_devuelve_cambio(entorno):
    g, alm, aud = entorno
    r = ejecutar(_limite(), g, alm, aud)
    assert r.estado == "ejecutada" and g.llamadas == []
    assert r.cambio_limite == {"clave": "tope_gasto_diario_total", "id": CUENTA, "de": 200000, "a": 240000,
                               "moneda": "COP", "unidad": "minima"}
    ev = _ejecuciones(aud)
    assert len(ev) == 1 and (ev[0]["validate_only"], ev[0]["ok"]) == (False, True)


def test_limite_ejecutor_global_sin_moneda(entorno):
    g, alm, aud = entorno
    p = cargar_propuesta({"version": 1, "id": "P-20261112-013", "tipo": "limite_ejecutor",
                          "creada": "2026-11-12T09:00:00-05:00", "origen": "/limites", "motivo": "paso",
                          "operaciones": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct",
                                           "de_esperado": 20, "a": 25}]})
    r = ejecutar(p, g, alm, aud)
    assert r.cambio_limite == {"clave": "paso_max_pct", "id": "global", "de": 20, "a": 25}
    assert r.estado == "ejecutada" and g.llamadas == []


@pytest.mark.parametrize("cambios", [
    {"ops": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct", "de_esperado": 20, "a": 25}] * 2},
    {"ops": [{"entidad": "adset", "id": "s1", "campo": "daily_budget", "de_esperado": 20000, "a": 26000}]},
    {"ops": [{"entidad": "ejecutor", "id": "global", "campo": "offset", "de_esperado": 1, "a": 100}]},
    {"ops": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct", "de_esperado": 20, "a": 0}]},
    {"ops": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct", "de_esperado": 20, "a": "25"}]},
    {"ops": []},
])
def test_limite_ejecutor_malformado_falla_cerrado(entorno, cambios):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="limite_ejecutor", **cambios), g, alm, aud)
    assert r.estado == "fallida" and r.cambio_limite is None and g.llamadas == []


def test_limite_ejecutor_sin_auditoria_falla_cerrado(entorno):
    g, alm, aud = entorno
    aud.anotar("stop", activo=False)
    aud.cabeza.unlink()  # cadena inverificable: anotar falla
    r = ejecutar(_limite(), g, alm, aud)
    assert r.estado == "fallida" and r.cambio_limite is None


def test_noop_con_operaciones_falla_cerrado(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="noop"), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


# -- no soportados -------------------------------------------------------------------------
@pytest.mark.parametrize("tipo", ["agenda", "regla_meta"])
def test_agenda_y_regla_no_soportadas(entorno, tipo):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo=tipo), g, alm, aud)
    assert (r.estado, r.detalle) == ("fallida", "no soportado aún (P-07)") and g.llamadas == []
    assert r.error == "no_soportado" and r.detalle == NO_SOPORTADO_P07
    ev = _ejecuciones(aud)
    assert len(ev) == 1 and (ev[0]["validate_only"], ev[0]["ok"]) == (False, False)


def test_crear_estructura_pausada_lanza(entorno):
    g, alm, aud = entorno
    with pytest.raises(ValueError, match="montaje.montar"):
        ejecutar(propuesta(tipo="crear_estructura_pausada", ops=[]), g, alm, aud)
    assert g.llamadas == []


def test_tipos_soportados():
    assert TIPOS_SOPORTADOS == frozenset({"presupuesto", "pausar", "activar", "puja", "spend_cap", "limite_cuenta",
                                          "lote", "noop", "alerta", "limite_ejecutor"})
    assert TIPOS_SOPORTADOS <= TIPOS
    assert not TIPOS_SOPORTADOS & {"agenda", "regla_meta", "crear_estructura_pausada"}


# -- fix round 1 ---------------------------------------------------------------------------
PAUSAR_S1 = {"entidad": "adset", "id": "s1", "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}


@pytest.mark.parametrize("ops", [[PAUSAR_S1, OPS[0]], [OPS[0], PAUSAR_S1]], ids=["pausa_primero", "pausa_despues"])
def test_lote_pausa_y_presupuesto_misma_entidad(entorno, ops):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="lote", ops=ops), g, alm, aud)
    assert r.estado == "ejecutada" and r.nueva_propuesta is None
    assert not any(o.pausada_sin_pedir for o in r.operaciones)
    assert g.objetos["s1"]["status"] == "PAUSED" and g.objetos["s1"]["daily_budget"] == "15000"


def test_lote_forced_to_paused_sigue_detectandose(entorno):
    g, alm, aud = entorno
    g.forzar_pausa.add("s2")
    r = ejecutar(propuesta(tipo="lote", ops=[PAUSAR_A1, OPS[1]]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["ejecutada", "discrepancia"]
    assert r.operaciones[1].pausada_sin_pedir


def test_limite_meta_detiene_el_lote(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(17, 2446079, "limit")
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["fallida", "no_intentada", "no_intentada"]
    assert r.operaciones[1].detalle == "no se intentó: Meta pide frenar"
    assert _posts_a(g, "s2") == [] and _posts_a(g, "a1") == []
    assert (r.error, r.parcial) == ("limite_meta", False) and r.reintentable_desde is not None


def test_limite_meta_tras_una_aplicada_no_es_reintentable(entorno):
    g, alm, aud = entorno
    g.errores["s2"] = ErrorGraph(17, 2446079, "limit")
    r = ejecutar(propuesta(tipo="lote", ops=OPS + [PAUSAR_A1]), g, alm, aud)
    assert [o.estado for o in r.operaciones] == ["ejecutada", "fallida", "no_intentada"]
    assert (r.estado, r.error, r.parcial) == ("fallida", "limite_meta", True) and r.reintentable_desde is None
    assert _posts_a(g, "a1") == []


def test_lote_discrepancia_conserva_el_error_del_fallo(entorno):
    g, alm, aud = entorno
    g.redondeo["s1"] = 15100
    g.errores["s2"] = ErrorGraph(200, None, "Permissions error")
    r = ejecutar(propuesta(tipo="lote", ops=OPS), g, alm, aud)
    assert (r.estado, r.error) == ("discrepancia", "permiso")


def _audit_rota(aud):
    aud.anotar("stop", activo=False)
    aud.cabeza.unlink()


def test_noop_sin_auditoria_falla(entorno):
    g, alm, aud = entorno
    _audit_rota(aud)
    r = ejecutar(_noop(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "otro") and g.llamadas == []


def test_alerta_sin_auditoria_sigue_ejecutada(entorno):
    g, alm, aud = entorno
    _audit_rota(aud)
    assert ejecutar(cargar_propuesta(alerta_dict()), g, alm, aud).estado == "ejecutada"


def _limite_a_mano(**op):
    base = {"entidad": "ejecutor", "id": CUENTA, "campo": "tope_gasto_diario_total", "de_esperado": 200000,
            "a": 240000, "unidad": "minima", "moneda": "COP"}
    base.update(op)
    return dataclasses.replace(propuesta(tipo="limite_ejecutor"), operaciones=(Operacion(**base),))


@pytest.mark.parametrize("op", [
    {"id": "s1"},
    {"id": "act_"},
    {"id": "act_12x"},
    {"id": "act_1/../x"},
    {"unidad": None, "moneda": None},
    {"unidad": "centavos"},
    {"moneda": None},
    {"unidad": None},
    {"id": "global", "campo": "paso_max_pct", "de_esperado": 20, "a": 25},  # global con moneda/unidad
    {"id": "global", "campo": "paso_max_pct", "de_esperado": 20, "a": 25, "moneda": None},
    {"campo": "clave_inventada", "unidad": None, "moneda": None},
])
def test_limite_ejecutor_segunda_barrera(entorno, op):
    g, alm, aud = entorno
    r = ejecutar(_limite_a_mano(**op), g, alm, aud)
    assert r.estado == "fallida" and r.cambio_limite is None and g.llamadas == []


def test_limite_ejecutor_a_mano_valido(entorno):
    g, alm, aud = entorno
    r = ejecutar(_limite_a_mano(), g, alm, aud)
    assert r.estado == "ejecutada" and r.cambio_limite["moneda"] == "COP"
    r = ejecutar(_limite_a_mano(id="global", campo="paso_max_pct", de_esperado=20, a=25, unidad=None,
                                moneda=None), g, alm, aud)
    assert r.estado == "ejecutada" and r.cambio_limite == {"clave": "paso_max_pct", "id": "global", "de": 20, "a": 25}
