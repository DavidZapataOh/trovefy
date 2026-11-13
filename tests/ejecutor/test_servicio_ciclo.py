"""Servicio del ejecutor (plan 12, Tarea 5): desfase de reloj, barrido, recordatorios, cambio de límites,
latido, recuperación tras reinicio y ``servir()``.

Reutiliza la fixture ``montaje`` de la Tarea 4: todo en ``tmp_path``; Telegram y Graph en proceso.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from ejecutor.test_servicio import Montaje, _montaje, presupuesto
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor.servicio import Ejecutor
from trovefy_ejecutor.telegram import ErrorRedTelegram


@pytest.fixture
def montaje(tmp_path):
    """La de la Tarea 4 (``test_servicio.montaje``)."""
    m = _montaje(tmp_path)
    try:
        yield m
    finally:
        m.ej.almacen.cerrar()
        _ejecutar._EMITIDOS.clear()


def _enviar(m: Montaje, d: dict) -> str:
    m.depositar(d)
    m.ej.ciclo()
    assert m.estado(d["id"]) == "enviada", m.ej.almacen.obtener(d["id"]).datos
    return d["id"]


def _otro(m: Montaje) -> Ejecutor:
    return Ejecutor(m.rutas, m.tg, m.graph, m.secretos, reloj=m.reloj, modo="simulado")


def _sin_red(*a, **k):
    raise ErrorRedTelegram("sin red")


# == Desfase de reloj ===============================================================================

def test_desfase_medido_con_un_envio_propio_bloquea(montaje):
    """Sin ningún mensaje del usuario: la fecha que devuelve Telegram al enviar la propuesta ya mide."""
    m = montaje
    m.tg._ahora = lambda: m.reloj() - timedelta(seconds=400)
    id = _enviar(m, presupuesto())
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "aceptada" and m.graph.escrituras() == []
    assert any("hwclock -s" in t for t in m.textos())


def test_desfase_se_persiste_y_sobrevive_al_reinicio(montaje):
    m = montaje
    m.tg._ahora = lambda: m.reloj() - timedelta(seconds=400)
    _enviar(m, presupuesto())
    guardado = json.loads(m.ej.almacen.leer_kv("desfase_reloj"))
    assert round(guardado["s"]) == 400
    nuevo = _otro(m)
    assert round(nuevo.desfase_s) == 400


def test_medida_vieja_no_vale_y_se_vuelve_a_medir(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.reloj.avanzar(minutes=20)  # la medida del envío tiene 20 min: no vale
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    medido = json.loads(m.ej.almacen.leer_kv("desfase_reloj"))["medido"]
    assert abs((datetime.fromisoformat(medido) - m.reloj()).total_seconds()) < 1


def test_sin_medida_fresca_no_ejecuta(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.reloj.avanzar(minutes=20)
    m.tg.tocar(id, "A", m.clave)
    m.tg.enviar = _sin_red
    m.tg.editar = _sin_red
    m.ej.ciclo()
    assert m.estado(id) == "aceptada" and m.graph.escrituras() == []
    assert m.eventos("reloj_sin_medida", id=id)
