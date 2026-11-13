"""Servicio del ejecutor (plan 12, Tarea 5): desfase de reloj, barrido, recordatorios, cambio de límites,
latido, recuperación tras reinicio y ``servir()``.

Reutiliza la fixture ``montaje`` de la Tarea 4: todo en ``tmp_path``; Telegram y Graph en proceso.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from ejecutor.test_servicio import Montaje, _montaje, alerta, noop, pausar, presupuesto
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor.render import texto_ya_procesada
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


# == Barrido: caducidad, recordatorios y cola ======================================================

def test_caduca_y_edita(montaje):
    m = montaje
    d = presupuesto()
    del d["expira_en_min"]  # caduca a medianoche de la cuenta
    id = _enviar(m, d)
    m.reloj.avanzar(days=1)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "caducada" and m.graph.escrituras() == []
    msg = m.mensaje_de(id)
    assert msg["texto"].endswith("CADUCADA, no se ejecutó nada") and not msg["botones"]
    m.tg.tocar(id, "A", m.clave)  # «A» tardío
    m.ej.ciclo()
    assert m.textos()[-1] == texto_ya_procesada("caducada") and m.graph.escrituras() == []


def test_aceptada_que_caduca_sin_ejecutarse_es_fallida(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.reloj.avanzar(minutes=20)
    enviar, editar = m.tg.enviar, m.tg.editar
    m.tg.enviar = m.tg.editar = _sin_red
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "aceptada"
    m.tg.enviar, m.tg.editar = enviar, editar
    m.reloj.avanzar(hours=1)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "caducó antes de ejecutarse" in fila.datos["motivo"]
    assert m.graph.escrituras() == []


def _recordatorios(m: Montaje, id: str) -> list[dict]:
    mid = m.ej.almacen.obtener(id).message_id
    return [v for v in m.tg.mensajes.values() if v.get("responde_a") == mid and "Recordatorio" in v["texto"]]


def test_recordatorios_pausar_1h_y_3h(montaje):
    m = montaje
    d = pausar()
    del d["expira_en_min"]
    id = _enviar(m, d)
    m.reloj.avanzar(minutes=61)
    m.ej.ciclo()
    rec = _recordatorios(m, id)
    assert len(rec) == 1
    assert rec[0]["texto"] == f"Recordatorio: {id} sigue pendiente; el dinero sigue corriendo"
    m.ej.ciclo()
    assert len(_recordatorios(m, id)) == 1
    m.reloj.avanzar(hours=2)
    m.ej.ciclo()
    assert len(_recordatorios(m, id)) == 2
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "enviada" and len(fila.datos["recordatorios"]) == 2


def _noop(n: int) -> dict:
    d = noop(id=f"P-20261112-{n:03d}")
    del d["expira_en_min"]
    return d


def test_ritmo_sembrado_tras_reinicio(montaje):
    m = montaje
    for n in range(1, 6):
        _enviar(m, _noop(n))
    m.depositar(alerta())
    m.ej.ciclo()
    assert m.estado("P-20261112-010") == "ejecutada"
    m.ej.almacen.cerrar()
    m.ej = _otro(m)
    m.depositar(_noop(7))
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-007")
    assert fila.estado == "recibida" and fila.datos["en_cola"] is True


def test_cola_se_envia_en_resumen_y_el_toque_reescribe_solo_su_bloque(montaje):
    m = montaje
    for n in range(1, 7):
        _enviar(m, _noop(n))
    m.depositar(_noop(7))
    m.depositar(_noop(8))
    m.ej.ciclo()
    assert m.ej.almacen.obtener("P-20261112-008").datos["en_cola"] is True
    m.reloj.avanzar(minutes=61)
    m.ej.ciclo()
    f7, f8 = m.ej.almacen.obtener("P-20261112-007"), m.ej.almacen.obtener("P-20261112-008")
    assert f7.estado == f8.estado == "enviada" and f7.message_id == f8.message_id
    resumen = m.tg.mensajes[f7.message_id]
    assert resumen["texto"].startswith("En espera") and len(resumen["botones"]) == 2
    m.tg.tocar("P-20261112-008", "A", m.clave)
    m.ej.ciclo()
    assert m.estado("P-20261112-008") == "ejecutada" and m.estado("P-20261112-007") == "enviada"
    resumen = m.tg.mensajes[f7.message_id]
    bloques = resumen["texto"].split("\n\n")
    assert "P-20261112-007" in bloques[1] and "Caduca:" in bloques[1]
    assert "P-20261112-008" in bloques[2] and "Estado: EJECUTADA" in bloques[2]
    assert [[b.texto for b in fila] for fila in resumen["botones"]] == [["Aceptar 1", "Rechazar 1"]]
    assert any(t.startswith("P-20261112-008") and "EJECUTADA" in t for t in m.textos())
    n = len(m.tg.mensajes)
    m.reloj.avanzar(days=1)
    m.ej.ciclo()
    resumen = m.tg.mensajes[f7.message_id]
    assert m.estado("P-20261112-007") == "caducada" and "Estado: CADUCADA" in resumen["texto"].split("\n\n")[1]
    assert not resumen["botones"] and len(m.tg.mensajes) == n  # sin un mensaje aparte por la caducada


def test_alerta_en_cola_sale_cuando_el_ritmo_lo_permite(montaje):
    m = montaje
    for n in range(1, 7):
        _enviar(m, _noop(n))
    m.depositar(alerta())
    m.ej.ciclo()
    assert m.estado("P-20261112-010") == "recibida"
    m.reloj.avanzar(minutes=61)
    m.ej.ciclo()
    assert m.estado("P-20261112-010") == "ejecutada"
