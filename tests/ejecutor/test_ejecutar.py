"""Ejecución de una operación contra el Graph falso (plan 11, tarea 4).

Almacén y auditoría reales en ``tmp_path`` (fixture ``entorno``). Nunca Graph real ni red.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from ejecutor.fabricas_graph import PROPUESTA_BASE, propuesta
from ejecutor.falsos.graph_falso import CUENTA
from trovefy_ejecutor.ejecutar import CAMPOS_POR_TIPO, ejecutar, siguiente_id
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.graph import ErrorGraph

T = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)  # 15:00 en Bogotá


def _reloj():
    return T


def _reales(g):
    """Escrituras reales intentadas (llegaron al cliente)."""
    return [x for x in g.llamadas if x.metodo == "escribir" and not x.validate_only]


def _posts(g):
    return [x for x in g.llamadas if x.metodo == "escribir"]


def _eventos(aud):
    return [json.loads(x) for x in aud.ruta.read_text().splitlines()] if aud.ruta.exists() else []


def _ejecuciones(aud):
    return [e["datos"] for e in _eventos(aud) if e["evento"] == "ejecucion"]


# -- casos felices -------------------------------------------------------------------------
def test_presupuesto_ok(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert r.estado == "ejecutada" and r.operaciones[0].despues == 26000
    assert r.operaciones[0].antes == 20000 and r.operaciones[0].pedido == 26000
    assert [x.validate_only for x in _posts(g)] == [True, False]
    assert alm.ultimo_cambio("s1", "daily_budget") == T and aud.verificar()
    assert g.objetos["s1"]["daily_budget"] == "26000"


def test_puja_registra_bid_amount(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="puja", op={"campo": "bid_amount", "de_esperado": 1500, "a": 1800}),
                 g, alm, aud, ahora=_reloj)
    assert r.estado == "ejecutada"
    assert alm.ultimo_cambio("s1", "bid_amount") is not None
    assert alm.ultimo_cambio("s1", "daily_budget") is None


def test_cop_offset_1(entorno):
    g, alm, aud = entorno
    ejecutar(propuesta(), g, alm, aud)
    assert g.escrituras()[0].datos == {"daily_budget": 26000}  # COP: sin multiplicar por 100


def test_pausar_ok(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="pausar", op={"campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}),
                 g, alm, aud, ahora=_reloj)
    assert r.estado == "ejecutada" and g.objetos["s1"]["status"] == "PAUSED"
    assert r.operaciones[0].despues == "PAUSED" and r.nueva_propuesta is None
    assert alm.ultimo_cambio("s1", "status") is None  # status no tiene regla de cadencia


def test_activar_ok(entorno):
    g, alm, aud = entorno
    g.cambiar("s1", status="PAUSED", effective_status="PAUSED")
    r = ejecutar(propuesta(tipo="activar", op={"campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}),
                 g, alm, aud, ahora=_reloj)
    assert r.estado == "ejecutada" and g.objetos["s1"]["status"] == "ACTIVE"
    assert g.escrituras()[0].datos == {"status": "ACTIVE"}


def test_puja_ok(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="puja", op={"campo": "bid_amount", "de_esperado": 1500, "a": 1700}),
                 g, alm, aud, ahora=_reloj)
    assert (r.estado, r.operaciones[0].despues) == ("ejecutada", 1700)
    assert g.escrituras()[0].datos == {"bid_amount": 1700}


def test_spend_cap_campana_ok(entorno):
    g, alm, aud = entorno
    g.cambiar("c1", spend_cap="500000")
    r = ejecutar(propuesta(tipo="spend_cap", op={"entidad": "campaign", "id": "c1", "campo": "spend_cap",
                                                 "de_esperado": 500000, "a": 600000}),
                 g, alm, aud, ahora=_reloj)
    assert (r.estado, r.operaciones[0].despues) == ("ejecutada", 600000)
    assert alm.ultimo_cambio("c1", "spend_cap") is None


def test_limite_cuenta_ok(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="limite_cuenta", op={"entidad": "account", "id": CUENTA, "campo": "spend_cap",
                                                     "de_esperado": 1000000, "a": 1200000}),
                 g, alm, aud, ahora=_reloj)
    assert (r.estado, r.operaciones[0].despues) == ("ejecutada", 1200000)
    assert g.escrituras()[0].ruta == CUENTA and g.cuentas[CUENTA]["spend_cap"] == "1200000"


# -- precondición y forma ------------------------------------------------------------------
def test_cambio_manual_obsoleta(entorno):
    g, alm, aud = entorno
    g.cambiar("s1", daily_budget="22000")
    r = ejecutar(propuesta(), g, alm, aud)
    assert r.estado == "obsoleta" and "22000" in r.detalle and _posts(g) == []
    ev = _ejecuciones(aud)
    assert len(ev) == 1 and (ev[0]["validate_only"], ev[0]["ok"]) == (False, False)


def test_active_solo_en_activar(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="pausar", op={"campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}),
                 g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []
    ev = _ejecuciones(aud)
    assert len(ev) == 1 and (ev[0]["validate_only"], ev[0]["ok"]) == (False, False)


def test_campo_fuera_del_tipo_no_llama(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="puja", op={"entidad": "campaign", "id": "c1", "campo": "bid_amount",
                                            "de_esperado": None, "a": 1000}), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


def test_importe_no_entero_no_escribe(entorno):
    g, alm, aud = entorno
    for malo in (26000.0, "26000", True, 0, -5):
        r = ejecutar(propuesta(op={"a": malo}), g, alm, aud)
        assert r.estado == "fallida", malo
    assert g.llamadas == []


def test_unidad_no_minima_no_escribe(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(op={"unidad": "centavos"}), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


def test_tipo_no_soportado(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(tipo="agenda"), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "no_soportado") and g.llamadas == []


def test_campos_por_tipo():
    assert CAMPOS_POR_TIPO["puja"] == {("adset", "bid_amount")}
    assert CAMPOS_POR_TIPO["limite_cuenta"] == {("account", "spend_cap")}
    assert CAMPOS_POR_TIPO["presupuesto"] == {("adset", "daily_budget"), ("campaign", "daily_budget")}
    assert CAMPOS_POR_TIPO["pausar"] == CAMPOS_POR_TIPO["activar"] == {
        ("campaign", "status"), ("adset", "status"), ("ad", "status")}


# -- moneda --------------------------------------------------------------------------------
def test_moneda_distinta_no_escribe(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(op={"moneda": "USD"}), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "moneda") and g.escrituras() == [] and _posts(g) == []


def test_moneda_sin_offset_no_escribe(entorno):
    g, alm, aud = entorno
    g.cuentas[CUENTA]["currency"] = "XXX"
    r = ejecutar(propuesta(op={"moneda": "XXX"}), g, alm, aud)
    assert r.error == "moneda" and "offset" in r.detalle and _posts(g) == []


# -- lectura que falla ----------------------------------------------------------------------
def test_entidad_ajena_no_escribe(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(op={"id": "x9"}), g, alm, aud)
    assert r.estado == "fallida" and "fuera de la cuenta" in r.detalle and _posts(g) == []


def test_red_al_leer_no_escribe(entorno):
    g, alm, aud = entorno
    g.red_al_leer = True
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "red") and _posts(g) == []


def test_lectura_incompleta_no_escribe(entorno):
    g, alm, aud = entorno
    g.objetos["s2"]["daily_budget"] = "abc"  # importe ilegible en algo que gasta
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "otro") and _posts(g) == []


def test_lectura_incompleta_por_red(entorno):
    g, alm, aud = entorno
    g.tam_pagina = 0  # el listado de conjuntos nunca termina: listado incompleto
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "red") and _posts(g) == []


def test_id_invalido_no_escribe(entorno):
    g, alm, aud = entorno
    r = ejecutar(propuesta(op={"id": "s1/../x"}), g, alm, aud)
    assert r.estado == "fallida" and _posts(g) == []


def test_token_caducado(entorno):
    g, alm, aud = entorno
    g.token_caduca_tras = 0
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "token") and _posts(g) == []


# -- STOP ----------------------------------------------------------------------------------
def test_stop_no_intenta(entorno):
    g, alm, aud = entorno
    g.stop_tras = 0
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error, r.parcial) == ("fallida", "stop", True) and g.escrituras() == []
    assert r.operaciones[0].estado == "no_intentada"
    assert alm.ultimo_cambio("s1", "daily_budget") is None


def test_stop_deja_el_resto_no_intentado(entorno):
    g, alm, aud = entorno
    g.stop_tras = 1
    r = ejecutar(propuesta(tipo="pausar", ops=[
        {"campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"},
        {"id": "s2", "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"},
        {"entidad": "ad", "id": "a1", "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"},
    ]), g, alm, aud)
    assert (r.estado, r.error, r.parcial) == ("fallida", "stop", True)
    assert [o.estado for o in r.operaciones] == ["ejecutada", "no_intentada", "no_intentada"]
    assert len(g.escrituras()) == 1


# -- errores de Meta y de red al escribir ---------------------------------------------------
def test_error_meta_en_validate_only_no_escribe(entorno):
    g, alm, aud = entorno
    g.errores["s1"] = ErrorGraph(17, 2446079, "limit")
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert (r.estado, r.error) == ("fallida", "limite_meta") and r.reintentable_desde == T + timedelta(hours=1)
    assert _reales(g) == []


def test_error_meta_no_reintenta(entorno):
    g, alm, aud = entorno
    g.errores_reales["s1"] = ErrorGraph(17, 2446079, "limit")
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert (r.estado, r.error) == ("fallida", "limite_meta") and r.reintentable_desde == T + timedelta(hours=1)
    assert len(_reales(g)) == 1 and "17" in r.detalle
    assert g.objetos["s1"]["daily_budget"] == "20000"


def test_error_permiso_al_escribir(entorno):
    g, alm, aud = entorno
    g.errores_reales["s1"] = ErrorGraph(200, None, "Permissions error")
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error, r.reintentable_desde) == ("fallida", "permiso", None) and len(_reales(g)) == 1


def test_red_tras_escribir_relee_y_confirma(entorno):
    g, alm, aud = entorno
    g.red_tras_escribir.add("s1")
    r = ejecutar(propuesta(), g, alm, aud)
    assert r.estado == "ejecutada" and "relectura" in r.detalle and len(g.escrituras()) == 1
    assert len(_reales(g)) == 1


def test_red_tras_escribir_sin_relectura_es_discrepancia(entorno):
    g, alm, aud = entorno
    g.red_tras_escribir.add("s1")
    g.al_escribir = lambda: setattr(g, "red_al_leer", True)  # la red cae del todo tras enviar
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and len(g.escrituras()) == 1 and len(_reales(g)) == 1
    assert "estado desconocido" in r.detalle
    assert alm.ultimo_cambio("s1", "daily_budget") == T  # pudo cambiar: cuenta para la cadencia


def test_red_y_no_se_aplico_es_fallida_red(entorno):
    g, alm, aud = entorno
    original = g.escribir

    def escribir_perdido(id, datos, *, validate_only=False):
        if validate_only:
            return original(id, datos, validate_only=True)
        g.llamadas.append(type(g.llamadas[0])("escribir", id, dict(datos), False))
        from trovefy_ejecutor.graph import ErrorRed
        raise ErrorRed("timeout")  # la petición nunca llegó a Meta

    g.escribir = escribir_perdido
    r = ejecutar(propuesta(), g, alm, aud)
    assert (r.estado, r.error) == ("fallida", "red") and "no se aplicó" in r.detalle
    assert len(_reales(g)) == 1 and alm.ultimo_cambio("s1", "daily_budget") is None


def test_meta_redondea_es_discrepancia(entorno):
    g, alm, aud = entorno
    g.redondeo["s1"] = 26100
    r = ejecutar(propuesta(), g, alm, aud)
    assert r.estado == "discrepancia" and r.operaciones[0].despues == 26100 and len(_reales(g)) == 1
    assert r.nueva_propuesta is None


# -- forced_to_paused -> Reactivar -------------------------------------------------------------
NUM = "120245000000000101"


def _con_numerico(g):
    g.objetos[NUM] = dict(g.objetos["s1"])
    g.hijos[NUM] = ("adsets", {CUENTA, "c1"})


def test_forced_to_paused_genera_reactivar(entorno):
    g, alm, aud = entorno
    _con_numerico(g)
    g.forzar_pausa.add(NUM)
    r = ejecutar(propuesta(op={"id": NUM}), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and len(g.escrituras()) == 1
    nueva = cargar_propuesta(r.nueva_propuesta)
    assert nueva.tipo == "activar" and nueva.operaciones[0].a == "ACTIVE"
    assert nueva.operaciones[0].de_esperado == "PAUSED" and nueva.operaciones[0].id == NUM
    assert re.fullmatch(r"P-\d{8}-8\d{2}", nueva.id) and nueva.id == "P-20261112-800"
    assert nueva.origen == "trovefy-ejecutor" and nueva.cuenta == CUENTA and nueva.pais == "BG"
    assert "status_forced_to_paused" in nueva.motivo and "P-20261112-004" in nueva.motivo
    assert alm.ultimo_cambio(NUM, "daily_budget") == T


def test_forced_to_paused_sin_numero_libre(entorno):
    g, alm, aud = entorno
    _con_numerico(g)
    g.forzar_pausa.add(NUM)
    from trovefy_ejecutor import ejecutar as mod
    mod._EMITIDOS.update(f"P-20261112-{n}" for n in range(800, 900))
    r = ejecutar(propuesta(op={"id": NUM}), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and r.nueva_propuesta is None
    assert "sin número libre 800–899 hoy: crea la propuesta a mano" in r.detalle


def test_siguiente_id_salta_ocupados(entorno):
    _g, alm, _aud = entorno
    alm.registrar(cargar_propuesta(dict(PROPUESTA_BASE, id="P-20261112-800")))
    assert siguiente_id(alm, T) == "P-20261112-801" and siguiente_id(alm, T) == "P-20261112-802"
    assert siguiente_id(alm, datetime(2026, 11, 13, 3, 0, tzinfo=UTC)).startswith("P-20261112-")  # aún 12 en COT


def test_siguiente_id_agotado(entorno):
    _g, alm, _aud = entorno
    from trovefy_ejecutor import ejecutar as mod
    mod._EMITIDOS.update(f"P-20261112-{n}" for n in range(800, 900))
    assert siguiente_id(alm, T) is None


# -- auditoría -----------------------------------------------------------------------------
def test_auditoria_ejecucion(entorno):
    g, alm, aud = entorno
    ejecutar(propuesta(), g, alm, aud)
    ej = _ejecuciones(aud)
    assert [(e["validate_only"], e["ok"]) for e in ej][:2] == [(True, True), (False, True)]
    assert len(ej) == 3 and (ej[2]["validate_only"], ej[2]["ok"]) == (False, True)
    assert all(e["tipo"] == "presupuesto" and e["id"] == propuesta().id for e in ej)
    assert "s1" in ej[1]["detalle"] and "26000" in ej[1]["detalle"] and "daily_budget" in ej[1]["detalle"]
    assert aud.verificar()


def test_auditoria_sin_token_ni_url(entorno):
    g, alm, aud = entorno
    secreto = "EAAB" + "x" * 30
    g.errores_reales["s1"] = ErrorGraph(100, None, f"bad https://graph.facebook.com/?access_token={secreto}")
    r = ejecutar(propuesta(), g, alm, aud)
    crudo = aud.ruta.read_text()
    assert secreto not in crudo and secreto not in r.detalle


def test_auditoria_rota_antes_de_escribir_no_escribe(entorno):
    g, alm, aud = entorno
    aud.anotar("stop", activo=False)
    aud.cabeza.unlink()  # cadena inverificable: anotar falla
    r = ejecutar(propuesta(), g, alm, aud)
    assert r.estado == "fallida" and _reales(g) == []


# -- fix round 1 ---------------------------------------------------------------------------
def test_campos_por_tipo_nunca_mas_abierto_que_el_esquema():
    from trovefy_ejecutor.esquema import REGLAS
    for tipo, pares in CAMPOS_POR_TIPO.items():
        for entidad, campo in pares:
            assert any(entidad in r.entidades and r.campo == campo for r in REGLAS[tipo]), (tipo, entidad, campo)


def test_lifetime_budget_no_soportado(entorno):
    g, alm, aud = entorno
    g.cambiar("s1", lifetime_budget="90000")
    r = ejecutar(propuesta(op={"campo": "lifetime_budget", "de_esperado": 90000, "a": 100000}), g, alm, aud)
    assert r.estado == "fallida" and g.llamadas == []


def _error_real_aplicado(g, aplicar: bool):
    """La escritura real devuelve ErrorGraph; con ``aplicar`` Meta la aplicó igualmente."""
    original = g.escribir

    def escribir(id, datos, *, validate_only=False):
        if validate_only:
            return original(id, datos, validate_only=True)
        if aplicar:
            original(id, datos)
        else:
            g.llamadas.append(type(g.llamadas[0])("escribir", id, dict(datos), False))
        raise ErrorGraph(17, 2446079, "limit")

    g.escribir = escribir


def test_error_meta_real_pero_aplicado_es_discrepancia(entorno):
    g, alm, aud = entorno
    _error_real_aplicado(g, aplicar=True)
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and len(_reales(g)) == 1
    assert alm.ultimo_cambio("s1", "daily_budget") == T


def test_error_meta_real_no_aplicado_relee_y_falla(entorno):
    g, alm, aud = entorno
    _error_real_aplicado(g, aplicar=False)
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert (r.estado, r.error) == ("fallida", "limite_meta") and r.reintentable_desde == T + timedelta(hours=1)
    assert len(_reales(g)) == 1 and alm.ultimo_cambio("s1", "daily_budget") is None
    assert [x.metodo for x in g.llamadas].count("leer") >= 3  # cuenta + s1 + relectura


def test_error_meta_real_sin_relectura_registra_y_falla(entorno):
    g, alm, aud = entorno
    g.errores_reales["s1"] = ErrorGraph(17, 2446079, "limit")
    original = g.escribir

    def escribir(id, datos, *, validate_only=False):
        try:
            return original(id, datos, validate_only=validate_only)
        finally:
            if not validate_only:
                g.red_al_leer = True

    g.escribir = escribir
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert (r.estado, r.error) == ("fallida", "limite_meta") and len(_reales(g)) == 1
    assert alm.ultimo_cambio("s1", "daily_budget") == T


def test_reactivar_que_revienta_no_escapa(entorno):
    g, alm, aud = entorno
    _con_numerico(g)
    g.forzar_pausa.add(NUM)

    def roto(_id):
        raise RuntimeError("sqlite caído")

    alm.obtener = roto
    r = ejecutar(propuesta(op={"id": NUM}), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and r.nueva_propuesta is None and "crea la propuesta a mano" in r.detalle
    assert len(_ejecuciones(aud)) == 3 and len(_reales(g)) == 1


def test_relectura_sin_status_es_discrepancia(entorno):
    g, alm, aud = entorno
    g.al_escribir = lambda: g.objetos["s1"].pop("status")
    r = ejecutar(propuesta(), g, alm, aud)
    assert r.estado == "discrepancia" and len(_reales(g)) == 1


# --- final review: spend_cap de cuenta en moneda con offset ≠ 1 (P-21) ------------------------------

def test_limite_cuenta_en_usd_no_escribe(entorno):
    g, alm, aud = entorno
    g.cuentas["act_usd"]["spend_cap"] = "5000"
    r = ejecutar(propuesta(tipo="limite_cuenta", cuenta="act_usd",
                           op={"entidad": "account", "id": "act_usd", "campo": "spend_cap",
                               "de_esperado": 5000, "a": 6000, "moneda": "USD"}), g, alm, aud, ahora=_reloj)
    assert r.estado == "fallida" and r.error == "moneda"
    assert "spend_cap de cuenta con offset ≠ 1 sin confirmar la unidad (P-21)" in r.detalle
    assert _posts(g) == [] and g.cuentas["act_usd"]["spend_cap"] == "5000"


def test_spend_cap_de_campana_en_usd_sigue_igual(entorno):
    g, alm, aud = entorno
    g.objetos["cu"] = {"account_id": "usd", "status": "ACTIVE", "effective_status": "ACTIVE", "spend_cap": "5000"}
    r = ejecutar(propuesta(tipo="spend_cap", cuenta="act_usd",
                           op={"entidad": "campaign", "id": "cu", "campo": "spend_cap",
                               "de_esperado": 5000, "a": 6000, "moneda": "USD"}), g, alm, aud, ahora=_reloj)
    assert r.estado == "ejecutada" and g.objetos["cu"]["spend_cap"] == "6000"


# --- final review: error ambiguo en la escritura real y relectura imposible --------------------------


def _cae_la_red_tras_escribir(g):
    original = g.escribir

    def escribir(id, datos, *, validate_only=False):
        try:
            return original(id, datos, validate_only=validate_only)
        finally:
            if not validate_only:
                g.red_al_leer = True

    g.escribir = escribir


@pytest.mark.parametrize("err", [ErrorGraph(2, None, "Service temporarily unavailable"),
                                 ErrorGraph(500, None, "HTTP 500")])
def test_error_ambiguo_sin_relectura_es_discrepancia(entorno, err):
    g, alm, aud = entorno
    g.errores_reales["s1"] = err
    _cae_la_red_tras_escribir(g)
    r = ejecutar(propuesta(), g, alm, aud, ahora=_reloj)
    assert r.estado == "discrepancia" and len(_reales(g)) == 1
    assert f"estado desconocido: Meta devolvió un error ambiguo ({err.codigo}) y no se pudo releer" in r.detalle
    assert alm.ultimo_cambio("s1", "daily_budget") == T

