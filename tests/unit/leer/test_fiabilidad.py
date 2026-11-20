"""Fiabilidad del dato y validez de los pagos iniciados (plan 23, Tarea 5)."""
from dataclasses import replace

from trovefy.leer.fiabilidad import IC_NO_FIABLE, evaluar

from .ejemplos import U, conj, of

IC = {"eventos": {"InitiateCheckout": 3}}
SIN_IC = {"eventos": {"InitiateCheckout": None}}


def _of(**kw):
    c = conj(gasto="10", clics=400, visitas=300, pi=0)
    return of("10", conjuntos=[c], **kw)


def test_alta_con_todo_cuadrado():
    f = evaluar(_of(ventas=1, pixel=1, bruto="13.90"), IC, None, U)
    assert f.nivel == "alta" and f.pi_fiable and f.motivos == ()


def test_intradia_maximo_media():
    assert evaluar(_of(ventas=1, pixel=1, intradia=True), IC, None, U).nivel == "media"


def test_sin_tienda_baja():
    assert evaluar(_of(ventas=None, pixel=1), IC, None, U).nivel == "baja"


def test_diferencia_de_dos_baja_y_de_uno_media():
    assert evaluar(_of(ventas=3, pixel=1), IC, None, U).nivel == "baja"
    assert evaluar(_of(ventas=2, pixel=1), IC, None, U).nivel == "media"


def test_ic_no_verificado_pi_no_fiable():
    f = evaluar(_of(ventas=0, pixel=0), SIN_IC, None, U)
    assert not f.pi_fiable and IC_NO_FIABLE in f.motivos


def test_ic_aparece_en_meta_pi_fiable():
    o = _of(ventas=0, pixel=0)
    c = replace(o.conjuntos[0], metricas=replace(o.conjuntos[0].metricas, pi_pixel=2))
    assert evaluar(replace(o, conjuntos=(c,)), SIN_IC, None, U).pi_fiable


def test_zonas_distintas_media():
    assert evaluar(_of(ventas=1, pixel=1, zona="America/Argentina/Buenos_Aires"), IC, None, U).nivel == "media"


def test_pocos_clics_media():
    o = of("10", conjuntos=[conj(gasto="10", clics=50)], ventas=1, pixel=1)
    f = evaluar(o, IC, None, U)
    assert f.nivel == "media" and any("< 300" in m for m in f.motivos)
