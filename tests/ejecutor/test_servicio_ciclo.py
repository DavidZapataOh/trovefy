"""Servicio del ejecutor (plan 12, Tarea 5): desfase de reloj, barrido, recordatorios, cambio de límites,
latido, recuperación tras reinicio y ``servir()``.

Reutiliza la fixture ``montaje`` de la Tarea 4: todo en ``tmp_path``; Telegram y Graph en proceso.
"""
from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta

import pytest
import yaml
from ejecutor.test_servicio import (
    CUENTA,
    Montaje,
    _creada,
    _montaje,
    alerta,
    noop,
    pausar,
    presupuesto,
)
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor import servicio
from trovefy_ejecutor.limites import LimitesInvalidos
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


def _yaml(m: Montaje) -> dict:
    return yaml.safe_load(m.rutas.limites.read_text())


def _limite_global(id: str = "P-20261112-006", de: int = 50, a: int = 40) -> dict:
    return {"version": 1, "id": id, "tipo": "limite_ejecutor", "creada": _creada(), "origen": "/limites",
            "motivo": "más pasos",
            "operaciones": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct",
                             "de_esperado": de, "a": a}]}


def test_cambio_de_limite_aceptado(montaje):
    m = montaje
    m.tg.escribir("/limites tope_gasto_diario_total 600.000")
    m.ej.ciclo()
    id = "P-20261112-900"
    assert m.estado(id) == "enviada"
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    assert _yaml(m)["cuentas"][CUENTA]["tope_gasto_diario_total"] == 600000
    assert stat.S_IMODE(m.rutas.limites.stat().st_mode) == 0o600
    assert m.ej.limites.cuentas[CUENTA].tope_gasto_diario_total == 600000
    assert m.eventos("limite_cambiado", clave="tope_gasto_diario_total", de=165000, a=600000, id=CUENTA)
    copia = json.loads((m.rutas.spool / "estado" / "limites.json").read_text())
    assert copia["cuentas"][CUENTA]["tope_gasto_diario_total"] == 600000
    assert "paginas_permitidas" not in copia["cuentas"][CUENTA]
    assert [p.name for p in m.rutas.limites.parent.iterdir() if p.name.startswith(".")] == []


def test_cambio_de_limite_global(montaje):
    m = montaje
    id = _enviar(m, _limite_global())
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada" and _yaml(m)["paso_max_pct"] == 40
    assert _yaml(m)["cuentas"][CUENTA]["offset"] == 1  # lo demás, intacto


def test_limite_que_cambio_desde_la_propuesta_es_fallida(montaje, monkeypatch):
    """Entre la validación y la escritura alguien edita limites.yaml: no se pisa su cambio."""
    m = montaje
    id = _enviar(m, _limite_global())
    original = servicio.ejecutar

    def y_alguien_edita(*a, **k):
        r = original(*a, **k)
        m.limites(1, paso_max_pct=45)
        return r

    monkeypatch.setattr(servicio, "ejecutar", y_alguien_edita)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "el límite cambió desde la propuesta" in fila.datos["detalle"]
    assert _yaml(m)["paso_max_pct"] == 45 and not m.eventos("limite_cambiado")


def test_limites_resultante_invalido_no_toca_el_archivo(montaje, monkeypatch):
    m = montaje
    antes = m.rutas.limites.read_bytes()

    def rechaza(ruta, **k):
        raise LimitesInvalidos("forzado")

    monkeypatch.setattr(servicio, "cargar_limites", rechaza)
    with pytest.raises(LimitesInvalidos):
        m.ej._aplicar_cambio_limite({"clave": "paso_max_pct", "id": "global", "de": 50, "a": 40}, None)
    assert m.rutas.limites.read_bytes() == antes
    assert [p.name for p in m.rutas.limites.parent.iterdir() if p.name.startswith(".")] == []


@pytest.mark.parametrize("cambio", [
    {"clave": "offset", "id": CUENTA, "de": 1, "a": 100},
    {"clave": "tope_gasto_diario_total", "id": CUENTA, "de": 165000, "a": 1, "moneda": "USD", "unidad": "minima"},
    {"clave": "tope_gasto_diario_total", "id": CUENTA, "de": 1, "a": 2, "moneda": "COP", "unidad": "minima"},
    {"clave": "paso_max_pct", "id": CUENTA, "de": 50, "a": 40},
    {"clave": "tope_gasto_diario_total", "id": "act_1", "de": 1, "a": 2, "moneda": "COP", "unidad": "minima"},
    {"clave": "paso_max_pct", "id": "global", "de": 50, "a": "40"},
])
def test_cambio_de_limite_invalido_lanza_sin_tocar(montaje, cambio):
    m = montaje
    antes = m.rutas.limites.read_bytes()
    with pytest.raises((ValueError, KeyError, LimitesInvalidos)):
        m.ej._aplicar_cambio_limite(cambio, cambio["id"] if cambio["id"] != "global" else None)
    assert m.rutas.limites.read_bytes() == antes


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
