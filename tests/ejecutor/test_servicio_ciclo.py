"""Servicio del ejecutor (plan 12, Tarea 5): desfase de reloj, barrido, recordatorios, cambio de límites,
latido, recuperación tras reinicio y ``servir()``.

Reutiliza la fixture ``montaje`` de la Tarea 4: todo en ``tmp_path``; Telegram y Graph en proceso.
"""
from __future__ import annotations

import dataclasses
import json
import os
import signal
import sqlite3
import stat
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfoNotFoundError

import pytest
import yaml
from ejecutor.test_servicio import (
    CUENTA,
    S1,
    S2,
    T0,
    TOKEN_META,
    TOKEN_TG,
    Montaje,
    _creada,
    _montaje,
    alerta,
    estructura,
    lote,
    noop,
    pausar,
    presupuesto,
)
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor import servicio
from trovefy_ejecutor.auditoria import AuditoriaCorrupta
from trovefy_ejecutor.candado import MENSAJE_OTRO, candado
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.limites import LimitesInvalidos
from trovefy_ejecutor.render import texto_ya_procesada
from trovefy_ejecutor.servicio import Ejecutor
from trovefy_ejecutor.stop import activar_stop, stop_activo
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


# == Recuperación tras reinicio ====================================================================

def _dejar_en(m: Montaje, d: dict, estado: str) -> str:
    """Propuesta enviada de verdad y llevada a mano a ``aceptada`` o ``ejecutando`` (caída del proceso)."""
    id = _enviar(m, d)
    assert m.ej.almacen.transicion(id, "enviada", "aceptada", callback_id="1")
    if estado == "ejecutando":
        assert m.ej.almacen.transicion(id, "aceptada", "ejecutando")
    return id


def _reiniciar(m: Montaje) -> Ejecutor:
    m.ej.almacen.cerrar()
    m.ej = _otro(m)
    return m.ej


def test_reinicio_en_ejecutando_no_reescribe(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(de=20000, a=26000), "ejecutando")
    m.graph.objetos[S1]["daily_budget"] = "26000"  # la escritura llegó a Meta antes de la caída
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "ejecutada" and m.graph.escrituras() == []
    assert "relectura tras reinicio" in fila.datos["detalle"]
    assert "EJECUTADA" in m.mensaje_de(id)["texto"]


def test_reinicio_en_ejecutando_sin_cambio_es_fallida(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(de=20000, a=26000), "ejecutando")
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "no se reintenta" in fila.datos["detalle"]
    assert m.graph.escrituras() == [] and "FALLÓ" in m.mensaje_de(id)["texto"]


def test_reinicio_lote_a_medias_es_discrepancia(montaje):
    m = montaje
    id = _dejar_en(m, lote(), "ejecutando")
    m.graph.objetos[S1]["daily_budget"] = "15000"  # la primera sí, la segunda no
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "discrepancia" and m.graph.escrituras() == []
    assert "no se cambió nada" not in m.mensaje_de(id)["texto"]


def test_reinicio_lote_entero_aplicado_es_ejecutada(montaje):
    m = montaje
    id = _dejar_en(m, lote(), "ejecutando")
    m.graph.objetos[S1]["daily_budget"] = "15000"
    m.graph.objetos[S2]["daily_budget"] = "10000"
    _reiniciar(m).recuperar()
    assert m.estado(id) == "ejecutada" and m.graph.escrituras() == []


def test_reinicio_sin_poder_leer_es_discrepancia(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "ejecutando")
    m.graph.red_al_leer = True
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "discrepancia" and "estado desconocido tras reinicio" in fila.datos["detalle"]


def test_reinicio_montaje_en_ejecutando_es_discrepancia(montaje):
    m = montaje
    p = cargar_propuesta(estructura())
    m.ej.almacen.registrar(p)
    assert m.ej.almacen.transicion(p.id, "recibida", "ejecutando")
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(p.id)
    assert fila.estado == "discrepancia" and "puede haberse creado algo" in fila.datos["detalle"]
    assert m.graph.escrituras() == []
    assert any("revisa Ads Manager" in t for t in m.textos())


def test_reinicio_noop_en_ejecutando_es_fallida(montaje):
    m = montaje
    id = _dejar_en(m, noop(), "ejecutando")
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "interrumpida" in fila.datos["detalle"]


@pytest.mark.parametrize("ya_escrito", [True, False])
def test_reinicio_limite_ejecutor_en_ejecutando(montaje, ya_escrito):
    m = montaje
    id = _dejar_en(m, _limite_global(), "ejecutando")
    if ya_escrito:
        m.limites(1, paso_max_pct=40)
    _reiniciar(m).recuperar()
    assert m.estado(id) == ("ejecutada" if ya_escrito else "fallida")


def test_reinicio_aceptada_se_ejecuta_con_todas_las_comprobaciones(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "aceptada")
    _reiniciar(m).recuperar()  # la medida del envío (kv) aún es fresca
    assert m.estado(id) == "ejecutada" and len(m.graph.escrituras()) == 1


def test_reinicio_aceptada_con_stop_no_ejecuta(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "aceptada")
    activar_stop(m.rutas, "prueba", T0)
    _reiniciar(m).recuperar()
    assert m.estado(id) == "fallida" and m.graph.escrituras() == []


def test_reinicio_aceptada_obsoleta_no_ejecuta(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "aceptada")
    m.graph.cambiar(S1, daily_budget=21000)
    _reiniciar(m).recuperar()
    assert m.estado(id) == "obsoleta" and m.graph.escrituras() == []


def test_reinicio_sin_medida_de_reloj_no_ejecuta(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "aceptada")
    m.reloj.avanzar(minutes=20)
    m.tg.enviar = m.tg.editar = _sin_red
    _reiniciar(m).recuperar()
    assert m.estado(id) == "aceptada" and m.graph.escrituras() == []


def test_reinicio_con_recibida_a_medias_la_despacha_otra_vez(montaje):
    m = montaje
    p = cargar_propuesta(presupuesto())
    m.ej.almacen.registrar(p)  # caída entre registrar y despachar
    _reiniciar(m).recuperar()
    assert m.estado(p.id) == "enviada" and m.graph.escrituras() == []


def test_reinicio_aceptada_caducada_es_fallida(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(), "aceptada")
    m.reloj.avanzar(hours=1)
    _reiniciar(m).recuperar()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "caducó antes de ejecutarse" in fila.datos["motivo"]
    assert m.graph.escrituras() == []


# == Latido y archivos de estado ===================================================================

def _estado_json(m: Montaje, nombre: str) -> dict:
    return json.loads((m.rutas.spool / "estado" / f"{nombre}.json").read_text())


def test_latido_y_estado(montaje):
    m = montaje
    m.ej.ciclo()
    lat = _estado_json(m, "latido")
    assert lat["modo"] == "simulado" and lat["version"] and lat["fecha"].startswith("2026-11-12")
    assert lat["stop"] is False and lat["pendientes"] == 0 and lat["vault"] == "ok"
    assert lat["telegram"] in ("ok", "sin red") and isinstance(lat["avisos"], list) and "reloj_desfase_s" in lat
    assert _estado_json(m, "stop") == {"activo": False, "motivo": None, "fecha": None}
    emp = _estado_json(m, "emparejamiento")
    assert emp["emparejado"] is True and set(emp) == {"emparejado", "fecha"} and "42" not in json.dumps(emp)
    lim = _estado_json(m, "limites")
    assert lim["cuentas"][CUENTA]["tope_gasto_diario_total"] == 165000 and lim["paso_max_pct"] == 50
    for nombre in ("latido", "stop", "emparejamiento", "limites"):
        assert stat.S_IMODE((m.rutas.spool / "estado" / f"{nombre}.json").stat().st_mode) == 0o640
    crudo = "".join(p.read_text() for p in (m.rutas.spool / "estado").iterdir())
    assert TOKEN_META not in crudo and TOKEN_TG not in crudo


def test_latido_como_mucho_cada_30_s_y_stop(montaje):
    m = montaje
    m.ej.ciclo()
    primero = _estado_json(m, "latido")["fecha"]
    activar_stop(m.rutas, "prueba", T0)
    m.reloj.avanzar(seconds=10)
    m.ej.ciclo()
    assert _estado_json(m, "latido")["fecha"] == primero
    m.reloj.avanzar(seconds=21)
    m.ej.ciclo()
    lat, st = _estado_json(m, "latido"), _estado_json(m, "stop")
    assert lat["fecha"] != primero and lat["stop"] is True
    assert st["activo"] is True and st["motivo"] == "prueba" and st["fecha"] == T0.isoformat()


def test_limites_json_solo_cuando_cambia_limites_yaml(montaje):
    m = montaje
    m.ej.ciclo()
    ruta = m.rutas.spool / "estado" / "limites.json"
    ruta.unlink()
    m.reloj.avanzar(seconds=31)
    m.ej.ciclo()
    assert not ruta.exists()
    m.limites(1, paso_max_pct=45)
    m.reloj.avanzar(seconds=31)
    m.ej.ciclo()
    assert json.loads(ruta.read_text())["paso_max_pct"] == 45


def test_sin_red_en_el_latido_y_el_barrido_sigue(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.ej.espera_red_s = 0
    m.tg.obtener_updates = _sin_red
    m.reloj.avanzar(hours=1)
    m.ej.ciclo()
    m.reloj.avanzar(seconds=31)
    m.ej.ciclo()
    assert _estado_json(m, "latido")["telegram"] == "sin red"
    assert m.estado(id) == "caducada"


def test_aviso_de_reloj_en_el_latido(montaje):
    m = montaje
    m.tg._ahora = lambda: m.reloj() - timedelta(seconds=400)
    id = _enviar(m, presupuesto())
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    m.reloj.avanzar(seconds=31)
    m.ej.ciclo()
    lat = _estado_json(m, "latido")
    assert any("hwclock -s" in a for a in lat["avisos"]) and round(lat["reloj_desfase_s"]) == 400


def test_token_caducado_se_comprueba_y_se_borra_al_renovarse(montaje):
    m = montaje
    m.graph.token_caduca_tras = 0
    m.depositar(presupuesto())
    m.ej.ciclo()
    assert m.ej.almacen.leer_kv("token_caducado")
    m.ej.ciclo()  # recién marcado: la primera comprobación espera 10 min
    assert not (m.rutas.spool / "estado" / "meta.json").exists()
    m.reloj.avanzar(minutes=10)
    m.ej.ciclo()  # primera comprobación: sigue caducado
    meta = _estado_json(m, "meta")
    assert meta["validate_only"]["ok"] is False and meta["cuenta"] == CUENTA
    m.graph.token_caduca_tras = None  # el usuario renueva el token
    m.reloj.avanzar(minutes=5)
    m.ej.ciclo()
    assert m.ej.almacen.leer_kv("token_caducado")  # aún no toca (cada 10 min)
    m.reloj.avanzar(minutes=6)
    m.ej.ciclo()
    assert m.ej.almacen.leer_kv("token_caducado") is None
    assert _estado_json(m, "meta")["validate_only"]["ok"] is True
    assert any("token de Meta renovado" in t for t in m.textos())
    assert m.graph.escrituras() == []  # comprobar-meta solo usa validate_only


def test_token_caducado_se_comprueba_al_arrancar(montaje):
    m = montaje
    m.ej.almacen.poner_kv("token_caducado", T0.isoformat())
    _reiniciar(m).ciclo()
    assert m.ej.almacen.leer_kv("token_caducado") is None


# == servir() ======================================================================================

def _secretos(m: Montaje, **sin) -> None:
    pares = {"META_TOKEN": TOKEN_META, "TELEGRAM_BOT_TOKEN": TOKEN_TG, "HMAC_CLAVE": m.clave.hex(),
             "TELEGRAM_USER_ID": "42", "TELEGRAM_CHAT_ID": "42", "CLAUDE_UID": str(os.geteuid())}
    for k in sin:
        pares.pop(k)
    m.rutas.secretos.write_text("".join(f"{k}={v}\n" for k, v in pares.items()))
    os.chmod(m.rutas.secretos, 0o600)


def _servir(m: Montaje, parar: threading.Event | None = None, **kw) -> int:
    return servicio.servir(m.rutas, parar=parar or threading.Event(), fabrica=lambda s: (m.tg, m.graph),
                           reloj=m.reloj, **kw)


def test_servir_sin_emparejar_devuelve_4(montaje, capsys):
    m = montaje
    _secretos(m, TELEGRAM_CHAT_ID=1, TELEGRAM_USER_ID=1)
    assert _servir(m) == 4
    assert "trovefy-ejecutor emparejar" in capsys.readouterr().err


def test_servir_secretos_inseguros_devuelve_2(montaje):
    m = montaje
    _secretos(m)
    os.chmod(m.rutas.secretos, 0o644)
    assert _servir(m) == 2


def test_servir_limites_invalidos_devuelve_2(montaje):
    m = montaje
    _secretos(m)
    m.rutas.limites.write_text("version: 1\n")
    assert _servir(m) == 2


def test_servir_sin_tzdata_devuelve_2(montaje, monkeypatch, capsys):
    m = montaje
    _secretos(m)

    def sin_zona(nombre):
        raise ZoneInfoNotFoundError(nombre)

    monkeypatch.setattr(servicio, "ZoneInfo", sin_zona)
    assert _servir(m) == 2
    assert "tzdata" in capsys.readouterr().err


def test_servir_con_otro_ejecutor_devuelve_3(montaje, capsys):
    m = montaje
    _secretos(m)
    with candado(m.rutas.base.with_suffix(".lock")):
        assert _servir(m) == 3
    assert MENSAJE_OTRO in capsys.readouterr().err


def test_sqlite_roto_no_ejecuta(montaje, monkeypatch, capsys):
    m = montaje
    _secretos(m)
    id = _dejar_en(m, presupuesto(), "aceptada")

    def rota(self, *a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(Almacen, "transicion", rota)
    assert _servir(m) == 1
    assert m.graph.escrituras() == [] and m.estado(id) == "aceptada"
    assert TOKEN_META not in capsys.readouterr().err


def test_servir_recupera_y_atiende_hasta_parar(montaje):
    m = montaje
    _secretos(m)
    id = _dejar_en(m, presupuesto(), "aceptada")
    m.depositar(noop())
    parar = threading.Event()
    original = m.tg.obtener_updates

    def y_parar(*a, **k):
        parar.set()
        return original(*a, **k)

    m.tg.obtener_updates = y_parar
    assert _servir(m, parar) == 0
    assert m.estado(id) == "ejecutada" and len(m.graph.escrituras()) == 1  # recuperar
    assert m.estado("P-20261112-001") == "enviada"  # un ciclo completo
    for nombre in ("estado", "procesadas"):
        assert (m.rutas.spool / nombre).is_dir()
    assert (m.rutas.spool / "estado" / "latido.json").exists()


def test_sigterm_termina_el_ciclo_y_sale_limpio(montaje):
    m = montaje
    _secretos(m)
    m.depositar(noop())
    original = m.tg.obtener_updates

    def con_sigterm(*a, **k):
        os.kill(os.getpid(), signal.SIGTERM)  # llega en mitad del ciclo
        return original(*a, **k)

    m.tg.obtener_updates = con_sigterm
    previo = signal.getsignal(signal.SIGTERM)
    assert _servir(m) == 0
    assert m.estado("P-20261112-001") == "enviada"  # el ciclo en curso terminó
    assert signal.getsignal(signal.SIGTERM) is previo


def test_servir_crea_estado_y_procesadas_con_setgid(tmp_path, monkeypatch):
    m = _montaje(tmp_path / "otro")
    try:
        spool = tmp_path / "spool_nuevo"
        m.rutas = dataclasses.replace(m.rutas, spool=spool)
        _secretos(m)
        parar = threading.Event()
        parar.set()  # sale tras recuperar, sin ciclos
        assert _servir(m, parar) == 0
        for nombre in ("estado", "procesadas"):
            assert stat.S_IMODE((spool / nombre).stat().st_mode) == 0o2750
    finally:
        m.ej.almacen.cerrar()


# == Fix round 1 ===================================================================================

def test_servir_comprueba_el_token_antes_de_recuperar(montaje):
    """Token renovado + reinicio: la bandera se comprueba con el token recién cargado antes de recuperar."""
    m = montaje
    _secretos(m)
    id = _dejar_en(m, presupuesto(), "aceptada")
    m.ej.almacen.poner_kv("token_caducado", T0.isoformat())
    parar = threading.Event()
    parar.set()  # solo recuperar
    assert _servir(m, parar) == 0
    assert m.estado(id) == "ejecutada" and len(m.graph.escrituras()) == 1
    assert m.ej.almacen.leer_kv("token_caducado") is None


def test_buzon_roto_no_impide_atender_stop(montaje):
    m = montaje

    def rota():
        raise PermissionError("entrada/ sin permiso")

    m.ej.buzon.nuevas = rota
    m.tg.escribir("/stop")
    m.ej.ciclo()
    m.ej.ciclo()
    assert stop_activo(m.rutas)


def test_desfase_de_un_mensaje_entrante_es_solo_una_pista(montaje):
    """Un mensaje con fecha rara (p. ej. reenviado o retrasado) no bloquea si una medida propia dice que
    el reloj va bien; y nunca autoriza por sí sola."""
    m = montaje
    id = _enviar(m, presupuesto())
    m.ej.desfase_s = None  # sin medida propia
    m.ej._desfase_medido = None
    m.tg.escribir("hola")  # su fecha (= reloj) daría desfase 0
    m.tg.enviar = m.tg.editar = _sin_red  # y no se puede medir de verdad
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "aceptada" and m.graph.escrituras() == []


def test_mensaje_entrante_desfasado_vuelve_a_medir_antes_de_bloquear(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    viejo = m.tg._ahora
    m.tg._ahora = lambda: m.reloj() - timedelta(seconds=400)
    m.tg.user_id = 99  # de otro usuario: se ignora sin responder, pero su fecha se mide
    m.tg.escribir("hola")  # pista: 400 s
    m.tg.user_id = 42
    m.tg._ahora = viejo  # pero el servidor, al editar, da la hora buena
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    assert m.eventos("transicion", id=id, de="aceptada", a="ejecutando")


def test_medir_ahora_con_edicion_sin_cambios_cae_a_un_mensaje(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.reloj.avanzar(minutes=20)
    editar = m.tg.editar

    def sin_cambios(chat, mid, texto, botones=None):
        if "comprobando la hora" in texto:
            return None  # «message is not modified»: sin fecha
        return editar(chat, mid, texto, botones)

    m.tg.editar = sin_cambios
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    assert any("comprobando la hora" in t for t in m.textos())


def test_id_duplicado_identico_refleja_el_estado_real(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.depositar(presupuesto())  # Claude reenvía el mismo archivo
    m.ej.ciclo()
    res = json.loads((m.rutas.spool / "procesadas" / f"{id}-2.resultado.json").read_text())
    assert res["estado"] == "enviada" and m.estado(id) == "enviada"
    assert not m.eventos("validacion_rechazada", id=id)


def test_auditoria_corrupta_para_el_servicio(montaje, monkeypatch):
    m = montaje

    def rota(*a, **k):
        raise AuditoriaCorrupta("cadena rota")

    m.depositar(presupuesto())
    monkeypatch.setattr(m.ej.auditoria, "anotar", rota)
    with pytest.raises(AuditoriaCorrupta):
        m.ej.ingerir()
    m.tg.escribir("/stop")
    with pytest.raises(AuditoriaCorrupta):
        m.ej.atender_updates()


def test_reinicio_compara_valores_normalizados(montaje):
    m = montaje
    id = _dejar_en(m, presupuesto(de=20000, a=26000), "ejecutando")
    m.graph.objetos[S1]["daily_budget"] = "26000"
    vv_original = servicio.valores_vivos

    def como_texto(p, g, **k):  # Meta devuelve el importe como texto
        vv = vv_original(p, g, **k)
        ent = {k2: dict(v) for k2, v in vv.entidades.items()}
        ent[S1]["daily_budget"] = "26000"
        return dataclasses.replace(vv, entidades=ent)

    monkeypatch_vv = pytest.MonkeyPatch()
    monkeypatch_vv.setattr(servicio, "valores_vivos", como_texto)
    try:
        _reiniciar(m).recuperar()
    finally:
        monkeypatch_vv.undo()
    assert m.estado(id) == "ejecutada"


def test_auditoria_corrupta_al_servir_sale_5(montaje, capsys):
    """Auditoría corrupta = código 5 (RestartPreventExitStatus): no se reinicia en bucle; SQLite sigue en 1."""
    m = montaje
    _secretos(m)
    with m.rutas.auditoria.open("ab") as f:
        f.write(b'{"n": 99, "roto"')  # última línea incompleta
    assert _servir(m) == 5
    err = capsys.readouterr().err
    assert "trovefy-ejecutor auditoria reparar" in err
    assert m.graph.escrituras() == []
