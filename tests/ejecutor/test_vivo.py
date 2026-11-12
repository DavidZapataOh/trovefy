from datetime import UTC, datetime

import pytest
from ejecutor.falsos.graph_falso import mundo_basico
from fabricas_graph import CUENTA, propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.graph import ErrorGraph, ErrorRed
from trovefy_ejecutor.limites import comprobar, contexto_para
from trovefy_ejecutor.vivo import (
    CAMPOS_IMPORTE,
    CAMPOS_LECTURA,
    EntidadAjena,
    LecturaIncompleta,
    valores_vivos,
)

T = datetime(2026, 11, 12, 19, 5, tzinfo=UTC)
ACTIVAR = {"campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}


def pausado(g, *ids):
    for i in ids:
        g.cambiar(i, status="PAUSED", effective_status="PAUSED")


def test_valores_vivos_presupuesto():
    g = mundo_basico()
    vv = valores_vivos(propuesta(), g, ahora=lambda: T)
    op = propuesta().operaciones[0]
    assert vv.valor(op) == 20000 and vv.leido_en == T and vv.cuenta.currency == "COP"
    assert vv.suma_diaria_activa == 35000 and vv.status("s1") == "ACTIVE"
    assert dict(vv.presupuestos_activos) == {"s1": 20000, "s2": 15000}  # c1 es ABO: sin presupuesto propio
    assert g.escrituras() == []


def test_presupuestos_activos_excluye_pausados():
    g = mundo_basico()
    pausado(g, "s2")
    vv = valores_vivos(propuesta(), g)
    assert dict(vv.presupuestos_activos) == {"s1": 20000} and vv.suma_diaria_activa == 20000


def test_effective_status_distinto_de_active_no_gasta():
    g = mundo_basico()
    g.cambiar("s2", effective_status="CAMPAIGN_PAUSED")
    assert dict(valores_vivos(propuesta(), g).presupuestos_activos) == {"s1": 20000}


def test_campana_cbo_cuenta_y_lifetime_no():
    g = mundo_basico()
    g.cambiar("c1", daily_budget="50000", lifetime_budget="900000")
    g.cambiar("s2", lifetime_budget="700000")
    vv = valores_vivos(propuesta(), g)
    assert dict(vv.presupuestos_activos) == {"c1": 50000, "s1": 20000, "s2": 15000}
    assert vv.suma_diaria_activa == 85000


def test_suma_solo_en_tipos_de_gasto():
    g = mundo_basico()
    p = propuesta(tipo="pausar", op={"campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"})
    vv = valores_vivos(p, g)
    assert vv.suma_diaria_activa is None and dict(vv.presupuestos_activos) == {}
    assert not [c for c in g.llamadas if c.metodo == "listar"]


def test_entidad_de_otra_cuenta():
    g = mundo_basico()
    with pytest.raises(EntidadAjena) as e:
        valores_vivos(propuesta(op={"id": "x9"}), g)
    assert e.value.entidad_id == "x9" and e.value.cuenta_viva == "act_999"
    assert g.escrituras() == []


def test_entidad_account_exige_la_cuenta_de_la_propuesta():
    g = mundo_basico()
    ok = propuesta(op={"entidad": "account", "id": CUENTA, "campo": "spend_cap", "de_esperado": 1000000,
                       "a": 900000})
    assert valores_vivos(ok, g).valor(ok.operaciones[0]) == 1000000
    mal = propuesta(op={"entidad": "account", "id": "act_usd", "campo": "spend_cap"})
    with pytest.raises(EntidadAjena) as e:
        valores_vivos(mal, g)
    assert e.value.cuenta_viva is None


def test_errores_de_red_y_graph_se_propagan():
    g = mundo_basico()
    g.red_al_leer = True
    with pytest.raises(ErrorRed):
        valores_vivos(propuesta(), g)
    with pytest.raises(ErrorGraph):
        valores_vivos(propuesta(op={"id": "nope"}), mundo_basico())


def test_obsoleta_da_motivo():
    g = mundo_basico()
    g.cambiar("s1", daily_budget="22000")
    assert valores_vivos(propuesta(), g).obsoleta(propuesta()) == "s1 daily_budget: esperado 20000, vivo 22000"
    assert valores_vivos(propuesta(), mundo_basico()).obsoleta(propuesta()) is None


def test_obsoleta_status_y_ausente():
    g = mundo_basico()
    p = propuesta(op={"campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"})
    assert "esperado PAUSED, vivo ACTIVE" in valores_vivos(p, g).obsoleta(p)
    p2 = propuesta(op={"campo": "lifetime_budget", "de_esperado": 5, "a": 6})
    assert "vivo None" in valores_vivos(p2, g).obsoleta(p2)


@pytest.mark.parametrize("malo", ["20000.5", "-5", "abc"])
def test_presupuesto_ilegible_o_negativo_de_algo_que_gasta_falla_cerrado(malo):
    g = mundo_basico()
    g.objetos["s1"]["daily_budget"] = malo
    with pytest.raises(LecturaIncompleta) as e:
        valores_vivos(propuesta(), g)
    assert "s1" in str(e.value) and malo not in str(e.value)


def test_invariante_suma_igual_a_presupuestos_activos():
    vv = valores_vivos(propuesta(), mundo_basico())
    assert vv.suma_diaria_activa == sum(vv.presupuestos_activos.values())
    for v in vv.valores_para_limites().values():
        assert not isinstance(v, float)


@pytest.mark.parametrize("eff,gasta", [("ACTIVE", True), ("IN_PROCESS", True), ("WITH_ISSUES", True),
                                       ("PENDING_REVIEW", True), ("PREAPPROVED", True),
                                       ("PENDING_BILLING_INFO", True), ("PAUSED", False),
                                       ("CAMPAIGN_PAUSED", False), ("ADSET_PAUSED", False),
                                       ("DELETED", False), ("ARCHIVED", False), ("DISAPPROVED", False)])
def test_que_cuenta_como_gastando(eff, gasta):
    g = mundo_basico()
    g.cambiar("s2", effective_status=eff)
    assert ("s2" in valores_vivos(propuesta(), g).presupuestos_activos) is gasta


def test_status_propio_pausado_no_gasta_aunque_effective_diga_active():
    g = mundo_basico()
    g.cambiar("s2", status="PAUSED")
    assert "s2" not in valores_vivos(propuesta(), g).presupuestos_activos


def test_listado_se_pide_con_limit_y_filtra_estados():
    g = mundo_basico()
    valores_vivos(propuesta(), g)
    ls = [c for c in g.llamadas if c.metodo == "listar"]
    assert ls and all(c.datos["limite"] == 500 for c in ls)
    assert "DISAPPROVED" not in ls[0].datos["filtros"]["effective_status"]
    assert "IN_PROCESS" in ls[0].datos["filtros"]["effective_status"]


def _con_muchos_conjuntos(g, n=25):
    for i in range(n):
        g.objetos[f"w{i}"] = {"account_id": "0000000000000000", "status": "ACTIVE", "effective_status": "ACTIVE",
                              "daily_budget": "1000", "campaign_id": "c1"}
        g.hijos[f"w{i}"] = ("adsets", {CUENTA, "c1"})


def test_listado_truncado_falla_cerrado():
    g = mundo_basico()
    _con_muchos_conjuntos(g)
    g.tam_pagina = 1
    with pytest.raises(ErrorRed, match="listado incompleto"):
        valores_vivos(propuesta(), g)


def test_listado_multipagina_completo_se_suma_entero():
    g = mundo_basico()
    _con_muchos_conjuntos(g)
    g.tam_pagina = 500
    vv = valores_vivos(propuesta(), g)
    assert vv.suma_diaria_activa == 35000 + 25000 and len(vv.presupuestos_activos) == 27


def test_listado_de_hijos_de_campana_truncado_falla_cerrado():
    g = mundo_basico()
    _con_muchos_conjuntos(g)
    pausado(g, "c1")
    g.tam_pagina = 1
    p = propuesta(tipo="activar", op={"entidad": "campaign", "id": "c1", **ACTIVAR})
    with pytest.raises(ErrorRed, match="listado incompleto"):
        valores_vivos(p, g)


def test_presupuesto_al_activar():
    g = mundo_basico()
    pausado(g, "s1")
    p = propuesta(tipo="activar", op=ACTIVAR)
    assert valores_vivos(p, g).presupuesto_al_activar(p) == 20000
    pausado(g, "c1")  # padre en PAUSED y fuera de p
    assert valores_vivos(p, g).presupuesto_al_activar(p) == 0
    assert g.escrituras() == []


def test_presupuesto_al_activar_ya_activo_o_otro_tipo():
    g = mundo_basico()
    p = propuesta(tipo="activar", op=ACTIVAR)  # s1 ya está ACTIVE: no empieza nada nuevo
    assert valores_vivos(p, g).presupuesto_al_activar(p) == 0
    q = propuesta()
    assert valores_vivos(q, g).presupuesto_al_activar(q) == 0


def test_activar_campana_cuenta_sus_conjuntos_y_se_atribuye_una_vez():
    g = mundo_basico()
    pausado(g, "c1", "s1", "s2")
    p = propuesta(tipo="activar", ops=[
        {"entidad": "campaign", "id": "c1", **ACTIVAR},
        {"entidad": "adset", "id": "s1", **ACTIVAR},
    ])
    vv = valores_vivos(p, g)
    # s2 queda PAUSED (fuera de p): solo s1 gasta; se atribuye a la primera op (la campaña)
    assert vv.presupuesto_al_activar(p) == 20000
    assert vv.presupuesto_al_activar_por_id(p) == {"c1": 20000, "s1": 0}
    p2 = propuesta(tipo="activar", ops=[
        {"entidad": "campaign", "id": "c1", **ACTIVAR},
        {"entidad": "adset", "id": "s1", **ACTIVAR},
        {"entidad": "adset", "id": "s2", **ACTIVAR},
    ])
    vv2 = valores_vivos(p2, g)
    por_id = vv2.presupuesto_al_activar_por_id(p2)
    assert por_id == {"c1": 35000, "s1": 0, "s2": 0}
    assert sum(por_id.values()) == vv2.presupuesto_al_activar(p2) == 35000


def test_activar_campana_cbo():
    g = mundo_basico()
    g.cambiar("c1", daily_budget="50000", status="PAUSED", effective_status="PAUSED")
    g.objetos["s1"].pop("daily_budget")
    g.objetos["s2"].pop("daily_budget")
    p = propuesta(tipo="activar", op={"entidad": "campaign", "id": "c1", **ACTIVAR})
    assert valores_vivos(p, g).presupuesto_al_activar_por_id(p) == {"c1": 50000}


def test_activar_anuncio_lee_padres_y_no_suma():
    g = mundo_basico()
    pausado(g, "a1")
    p = propuesta(tipo="activar", op={"entidad": "ad", "id": "a1", **ACTIVAR})
    vv = valores_vivos(p, g)
    assert vv.presupuesto_al_activar_por_id(p) == {"a1": 0} and vv.presupuesto_al_activar(p) == 0
    assert vv.status("s1") == "ACTIVE" and vv.status("c1") == "ACTIVE"


def test_una_lectura_por_entidad():
    g = mundo_basico()
    valores_vivos(propuesta(tipo="pausar", op={"campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}), g)
    assert [c.ruta for c in g.llamadas if c.metodo == "leer"].count("s1") == 1
    g2 = mundo_basico()
    pausado(g2, "s1")
    valores_vivos(propuesta(tipo="activar", ops=[{**ACTIVAR}, {"entidad": "adset", "id": "s1", **ACTIVAR}]), g2)
    assert [c.ruta for c in g2.llamadas if c.metodo == "leer"].count("s1") == 1
    assert g2.escrituras() == []


def test_campos_de_lectura():
    assert CAMPOS_LECTURA["campaign"] == ("id", "account_id", "status", "effective_status", "daily_budget",
                                          "lifetime_budget", "spend_cap")
    assert CAMPOS_LECTURA["adset"] == ("id", "account_id", "status", "effective_status", "daily_budget",
                                       "lifetime_budget", "bid_amount", "campaign_id")
    assert CAMPOS_LECTURA["ad"] == ("id", "account_id", "status", "effective_status", "adset_id", "campaign_id")
    assert CAMPOS_LECTURA["account"] == ("id", "currency", "spend_cap", "account_status", "amount_spent")
    assert CAMPOS_IMPORTE == {"daily_budget", "lifetime_budget", "bid_amount", "spend_cap"}


def test_valores_para_limites():
    g = mundo_basico()
    vv = valores_vivos(propuesta(), g)
    v = vv.valores_para_limites()
    assert v[("s1", "daily_budget")] == 20000 and v[("s1", "bid_amount")] == 1500
    assert v[("s1", "status")] == "ACTIVE" and v[("s1", "effective_status")] == "ACTIVE"
    assert v[(CUENTA, "currency")] == "COP" and v[(CUENTA, "spend_cap")] == 1000000


# --- integración con limites.comprobar (Ruling del ledger) ---------------------------------------

def _violaciones(g, limites, tmp_path):
    p = propuesta(tipo="puja", op={"campo": "bid_amount", "de_esperado": 1500, "a": 2000})
    vv = valores_vivos(p, g, ahora=lambda: T)
    a = Almacen(tmp_path / "e.sqlite")
    try:
        ctx = contexto_para(p, a, ahora=T, stop=False, valores=vv.valores_para_limites(),
                            presupuestos_activos=vv.presupuestos_activos,
                            presupuesto_al_activar=vv.presupuesto_al_activar_por_id(p))
    finally:
        a.cerrar()
    return [x.split(":")[0] for x in comprobar(p, limites, ctx)]


def test_comprobar_deja_subir_puja_de_conjunto_pausado(limites_cop, tmp_path):
    g = mundo_basico()
    pausado(g, "s1")
    assert "valor_vivo_desconocido" not in _violaciones(g, limites_cop, tmp_path)


def test_comprobar_rechaza_subir_puja_de_conjunto_activo_fuera_de_activos(limites_cop, tmp_path):
    g = mundo_basico()
    g.objetos["s1"].pop("daily_budget")  # ACTIVE sin presupuesto propio (CBO): no figura en presupuestos_activos
    assert "valor_vivo_desconocido" in _violaciones(g, limites_cop, tmp_path)


def _activar_violaciones(g, p, limites, tmp_path):
    vv = valores_vivos(p, g, ahora=lambda: T)
    a = Almacen(tmp_path / "e.sqlite")
    try:
        ctx = contexto_para(p, a, ahora=T, stop=False, valores=vv.valores_para_limites(),
                            presupuestos_activos=vv.presupuestos_activos,
                            presupuesto_al_activar=vv.presupuesto_al_activar_por_id(p))
    finally:
        a.cerrar()
    return vv, [x.split(":")[0] for x in comprobar(p, limites, ctx)]


def test_activar_sin_presupuesto_diario_positivo_no_se_sabe(limites_cop, tmp_path):
    g = mundo_basico()
    pausado(g, "s1")
    g.objetos["s1"].pop("daily_budget")
    g.objetos["s1"]["lifetime_budget"] = "900000"
    p = propuesta(tipo="activar", op=ACTIVAR)
    vv, cods = _activar_violaciones(g, p, limites_cop, tmp_path)
    assert vv.presupuesto_al_activar_por_id(p) == {} and vv.presupuesto_al_activar(p) is None
    assert "valor_vivo_desconocido" in cods


def test_activar_conjunto_sin_ningun_presupuesto_ni_padre_con_presupuesto(limites_cop, tmp_path):
    g = mundo_basico()
    pausado(g, "s1")
    g.objetos["s1"].pop("daily_budget")
    p = propuesta(tipo="activar", op=ACTIVAR)
    vv, cods = _activar_violaciones(g, p, limites_cop, tmp_path)
    assert vv.presupuesto_al_activar(p) is None and "valor_vivo_desconocido" in cods


def test_activar_con_presupuesto_conocido_no_da_desconocido(limites_cop, tmp_path):
    g = mundo_basico()
    pausado(g, "s1")
    p = propuesta(tipo="activar", op=ACTIVAR)
    vv, cods = _activar_violaciones(g, p, limites_cop, tmp_path)
    assert vv.presupuesto_al_activar(p) == 20000 and "valor_vivo_desconocido" not in cods


def test_gasto_nuevo_sin_op_propia_se_carga_a_la_primera_activacion():
    g = mundo_basico()
    pausado(g, "a1")
    g.cambiar("s1", effective_status="DISAPPROVED")  # ACTIVE pero no gasta hoy; activar el anuncio lo arranca
    p = propuesta(tipo="activar", op={"entidad": "ad", "id": "a1", **ACTIVAR})
    vv = valores_vivos(p, g)
    assert vv.presupuesto_al_activar_por_id(p) == {"a1": 20000}
    assert vv.presupuesto_al_activar(p) == 20000


@pytest.mark.parametrize("eff", ["IN_PROCESS", "WITH_ISSUES"])
def test_conjunto_en_proceso_o_con_problemas_ya_cuenta_como_gastando(eff):
    g = mundo_basico()
    pausado(g, "a1")
    g.cambiar("s1", effective_status=eff)
    p = propuesta(tipo="activar", op={"entidad": "ad", "id": "a1", **ACTIVAR})
    assert valores_vivos(p, g).presupuesto_al_activar_por_id(p) == {"a1": 0}


def test_conjunto_bajo_cbo_con_problemas_no_suma_dos_veces():
    g = mundo_basico()
    pausado(g, "a1")
    g.cambiar("c1", daily_budget="50000", effective_status="WITH_ISSUES")
    g.objetos["s1"].pop("daily_budget")
    g.cambiar("s1", effective_status="WITH_ISSUES")
    p = propuesta(tipo="activar", op={"entidad": "ad", "id": "a1", **ACTIVAR})
    assert valores_vivos(p, g).presupuesto_al_activar_por_id(p) == {"a1": 0}


def test_cbo_no_gasta_hoy_se_carga_a_la_activacion():
    g = mundo_basico()
    pausado(g, "a1")
    g.cambiar("c1", daily_budget="50000", effective_status="DISAPPROVED")
    g.objetos["s1"].pop("daily_budget")
    p = propuesta(tipo="activar", op={"entidad": "ad", "id": "a1", **ACTIVAR})
    assert valores_vivos(p, g).presupuesto_al_activar_por_id(p) == {"a1": 50000}
