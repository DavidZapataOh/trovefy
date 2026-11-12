from datetime import timedelta

import pytest
from fabricas import CUENTA, operacion, pausar, presupuesto
from trovefy_ejecutor.esquema import (
    PropuestaInvalida,
    cargar_propuesta,
    volcar_propuesta,
)
from trovefy_ejecutor.modelo import clase_de


def test_presupuesto_cop_valido():
    p = cargar_propuesta(presupuesto())
    assert p.clase == "gasto" and p.cuenta == CUENTA and p.operaciones[0].a == 26000
    assert p.creada.utcoffset() == timedelta(hours=-5)

def test_ida_y_vuelta():
    p = cargar_propuesta(presupuesto())
    assert cargar_propuesta(volcar_propuesta(p)) == p

@pytest.mark.parametrize("datos,motivo", [
    (presupuesto(color="rojo"), "campo no permitido: color"),
    (presupuesto(operaciones=[operacion(extra=1)]), "campo no permitido: extra"),
    (presupuesto(id="P-2026-1"), "id"), (presupuesto(id="P-20261112-000"), "id"),
    (presupuesto(id="P-20261112-004-R"), "id"), (presupuesto(version=2), "version"),
    (presupuesto(operaciones=[operacion(id=str(120245000000000100 + i)) for i in range(41)]), "40"),
    (presupuesto(tipo="borrar"), "tipo"), (presupuesto(creada="2026-11-12T14:05:00"), "zona"),
    (presupuesto(operaciones=[operacion(entidad="ad")]), "entidad"),
    (presupuesto(operaciones=[operacion(), operacion()]), "repetida"),
    (presupuesto(operaciones=[operacion(unidad="centavos")]), "unidad"),
])
def test_rechazos(datos, motivo):
    with pytest.raises(PropuestaInvalida, match=motivo) as e:
        cargar_propuesta(datos)
    assert e.value.motivo.startswith("esquema: ")

@pytest.mark.parametrize("a", [0, -1, 1.5, "26000", True, None])
def test_importe_entero_positivo(a):
    with pytest.raises(PropuestaInvalida, match="importe"):
        cargar_propuesta(presupuesto(operaciones=[operacion(a=a)]))

def test_pausar_no_lleva_moneda():
    assert cargar_propuesta(pausar()).operaciones[0].a == "PAUSED"
    with pytest.raises(PropuestaInvalida):
        cargar_propuesta(pausar(operaciones=[{**pausar()["operaciones"][0], "moneda": "COP"}]))

def test_noop_y_no_dict():
    assert cargar_propuesta({"version": 1, "id": "P-20261112-001", "tipo": "noop",
                             "creada": "2026-11-12T09:00:00-05:00", "origen": "/arranque"}).clase == "notificacion"
    with pytest.raises(PropuestaInvalida):
        cargar_propuesta([])

def test_clase_de():
    assert clase_de("limite_ejecutor") == "limite" and clase_de("crear_estructura_pausada") == "no_gasto"
    with pytest.raises(ValueError):
        clase_de("borrar")

def test_rangos_de_id():
    for n in ("001", "799", "800", "899", "900", "999"):
        cargar_propuesta(presupuesto(id=f"P-20261112-{n}"))

def test_cuenta_y_account():
    with pytest.raises(PropuestaInvalida, match="cuenta"):
        cargar_propuesta(presupuesto(cuenta="act_x"))
    # Resolución 22: el id de la operación es la cuenta CON act_ e igual a la de la propuesta.
    ok = presupuesto(tipo="limite_cuenta", operaciones=[operacion(entidad="account", id="act_0000000000000000",
                                                                  campo="spend_cap", de_esperado=None)])
    p = cargar_propuesta(ok)
    assert p.operaciones[0].de_esperado is None and p.operaciones[0].id == p.cuenta
    assert (p.operaciones[0].unidad, p.operaciones[0].moneda) == ("minima", "COP")
    for id_ in ("0000000000000000", "act_123", "123"):
        mal = presupuesto(tipo="limite_cuenta", operaciones=[operacion(entidad="account", id=id_,
                                                                       campo="spend_cap")])
        with pytest.raises(PropuestaInvalida, match="cuenta"):
            cargar_propuesta(mal)
    sin_moneda = presupuesto(tipo="limite_cuenta", operaciones=[
        {"entidad": "account", "id": "act_0000000000000000", "campo": "spend_cap", "de_esperado": None, "a": 1}])
    with pytest.raises(PropuestaInvalida, match="unidad"):
        cargar_propuesta(sin_moneda)

def _lim_ej(op: dict) -> dict:
    d = presupuesto(tipo="limite_ejecutor", operaciones=[{"entidad": "ejecutor", **op}])
    del d["cuenta"]
    return d

def test_limite_ejecutor_sin_cuenta():
    d = _lim_ej({"id": "global", "campo": "paso_max_pct", "de_esperado": 50, "a": 60})
    p = cargar_propuesta(d)
    assert p.clase == "limite" and p.cuenta is None
    for malo in ({"a": 0}, {"de_esperado": None}, {"de_esperado": 0}):
        with pytest.raises(PropuestaInvalida):
            cargar_propuesta(_lim_ej({"id": "global", "campo": "paso_max_pct", "de_esperado": 50, "a": 60} | malo))

def test_limite_ejecutor_unidad_y_moneda_segun_la_clave():
    cuenta = "act_0000000000000000"
    dinero = {"id": cuenta, "campo": "tope_gasto_diario_total", "de_esperado": 165000, "a": 150000}
    p = cargar_propuesta(_lim_ej(dinero | {"unidad": "minima", "moneda": "COP"}))
    assert (p.operaciones[0].unidad, p.operaciones[0].moneda) == ("minima", "COP")
    for falta in ({}, {"unidad": "minima"}, {"moneda": "COP"}, {"unidad": "centavos", "moneda": "COP"}):
        with pytest.raises(PropuestaInvalida, match="unidad|moneda"):
            cargar_propuesta(_lim_ej(dinero | falta))
    entera = {"id": "global", "campo": "paso_max_pct", "de_esperado": 50, "a": 60}
    for sobra in ({"unidad": "minima"}, {"moneda": "COP"}, {"unidad": "minima", "moneda": "COP"}):
        with pytest.raises(PropuestaInvalida, match="unidad y moneda"):
            cargar_propuesta(_lim_ej(entera | sobra))
    with pytest.raises(PropuestaInvalida, match="offset"):
        cargar_propuesta(_lim_ej({"id": cuenta, "campo": "offset", "de_esperado": 1, "a": 100}))

def test_agenda_y_lote():
    ag = presupuesto(tipo="agenda", operaciones=[
        {"entidad": "adset", "id": "1", "campo": "budget_schedules", "de_esperado": None, "a": None,
         "parametros": {"x": 1}}])
    assert cargar_propuesta(ag).operaciones[0].parametros["x"] == 1
    del ag["operaciones"][0]["parametros"]
    with pytest.raises(PropuestaInvalida, match="parametros"):
        cargar_propuesta(ag)
    lote = presupuesto(tipo="lote", operaciones=[operacion(), pausar()["operaciones"][0] | {"id": "2"}])
    assert cargar_propuesta(lote).clase == "gasto"

def test_inmutable():
    p = cargar_propuesta(presupuesto())
    with pytest.raises(TypeError):
        p.evidencia["x"] = 1


def test_estado_exacto_del_contrato():
    from typing import get_args

    from trovefy_ejecutor.modelo import Estado
    assert set(get_args(Estado)) == {"recibida", "enviada", "aceptada", "ejecutando", "ejecutada",
                                     "fallida", "discrepancia", "rechazada", "caducada", "obsoleta"}


@pytest.mark.parametrize("datos", [
    presupuesto(id="P-20261112-١٢٣"),
    presupuesto(cuenta="act_١٢٣"),
    presupuesto(operaciones=[operacion(id="١٢٣")]),
])
def test_ids_solo_digitos_ascii(datos):
    with pytest.raises(PropuestaInvalida):
        cargar_propuesta(datos)
