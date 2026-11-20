"""Diagnóstico por etapa sin tocar la campaña (plan 23, Tarea 6; R-014)."""
from dataclasses import replace

from trovefy.leer.diagnostico import Hallazgo, diagnosticar, rechazados, renovar
from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import Veredicto

from .ejemplos import U, conj, of

F = Fiabilidad("alta", True, ())


def _of(clics=400, visitas=360, impresiones=20000, **kw):
    c = conj(gasto="30", clics=clics, visitas=visitas)
    c = replace(c, metricas=replace(c.metricas, impresiones=impresiones))
    return of("30", conjuntos=[c], **kw)


def test_trusa_checkout_1_de_8_no_alerta():  # 46 PI, 6 ventas: justo en la referencia (L2 19:15)
    hs = diagnosticar(_of(visitas=300, ventas=6, pi_tienda=46), F, U)
    assert not [h for h in hs if h.etapa == "checkout"]


def test_checkout_flojo_alerta():
    hs = diagnosticar(_of(visitas=300, ventas=2, pi_tienda=46), F, U)
    assert any(h.etapa == "checkout" and h.destino == "/checkout" and h.alerta for h in hs)


def test_pagina_pi_bajo_alerta_landing():
    hs = diagnosticar(_of(visitas=360, ventas=0, pi_tienda=20), F, U)
    assert any(h.etapa == "pagina" and h.destino == "/landing" and "C1 54:20" in h.texto for h in hs)


def test_llegada_baja_alerta_landing():
    hs = diagnosticar(_of(visitas=200, ventas=1, pi_tienda=60), F, U)
    assert any("falla la llegada" in h.texto for h in hs)


def test_ctr_bajo_alerta_creativos():
    hs = diagnosticar(_of(impresiones=40000, ventas=1, pi_tienda=80), F, U)  # 1 %
    assert any(h.destino == "/creativos" for h in hs)


def test_rechazos_de_pasarela_alerta_checkout():
    hs = diagnosticar(_of(ventas=1, pi_tienda=80, fallidos=2), F, U)
    assert any("rechazó 2 intentos" in h.texto for h in hs)


def test_poco_dato_sin_alerta():
    hs = diagnosticar(_of(clics=100, visitas=50, ventas=0, pi_tienda=1), F, U)
    assert hs and all(not h.alerta and "dato aún flojo" in h.texto for h in hs)


def test_nunca_propone_tocar_campana():
    hs = diagnosticar(_of(visitas=50, ventas=0, pi_tienda=1, fallidos=3), F, U)
    assert all(isinstance(h, Hallazgo) for h in hs)  # solo hallazgos: ningún Corte ni Surf


def test_rechazados_por_meta():
    o = _of(ventas=0)
    c = replace(o.conjuntos[0], estado_anuncio="DISAPPROVED")
    assert rechazados(replace(o, conjuntos=(c,)))[0].alerta


def test_renovar_con_angulo():
    o = _of(ventas=0)
    v = [Veredicto(o.conjuntos[0].adset_id, "AD01 G1 mapa", "APAGAR", "x")]
    assert renovar(o, v) == ["AD01 G1 mapa (mapa)"]
