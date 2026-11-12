"""Integración con el Telegram falso (§7 fila «Ejecutor»): piezas del plan 10 + Almacen y Auditoria reales.

``despachar`` y ``ciclo`` son un ayudante solo de test: aplican la tabla de la Tarea 8 y sirven de
especificación ejecutable para el servicio del plan 12. Sin Meta: «ejecutar» una A es pasar por
EJECUTANDO a EJECUTADA con una relectura fija.
"""
from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from ejecutor.datos_telegram import noop
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from trovefy_ejecutor.auditoria import EV_CALLBACK_INVALIDO, EV_TRANSICION, Auditoria
from trovefy_ejecutor.callbacks import firmar
from trovefy_ejecutor.comandos import (
    Accion,
    GuardarMotivo,
    Ignorar,
    ResponderToque,
    Toque,
    interpretar_update,
    nota_motivo,
)
from trovefy_ejecutor.dinero import Moneda
from trovefy_ejecutor.emparejar import Emparejamiento
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.render import (
    PREGUNTA_MOTIVO,
    RECIBIDO,
    DatosRender,
    Desenlace,
    botones_propuesta,
    render_propuesta,
    render_resultado,
    texto_ya_procesada,
)
from trovefy_ejecutor.telegram import ClienteTelegram, ErrorRedTelegram, ErrorTelegram

ID = "P-20261112-001"
ID2 = "P-20261112-002"
K = b"k" * 32
USUARIO = 42
T = datetime(2026, 11, 12, 14, 7, tzinfo=ZONA_COT)
VIVO = DatosRender(Moneda("COP", 1), T, T.replace(hour=14, minute=37), {})
RELECTURA = "sin cambios (prueba)"


@dataclass
class Entorno:
    tg: TelegramFalso
    alm: Almacen
    aud: Auditoria
    mid: int
    cliente: ClienteTelegram
    pausas: list[float]
    motivos: list
    sig: int = 0  # offset de getUpdates

    def __iter__(self):
        return iter((self.tg, self.alm, self.aud, self.mid))


def enviar_propuesta(e_tg, alm, cliente, datos) -> int:
    p = cargar_propuesta(datos)
    alm.registrar(p)
    assert alm.transicion(p.id, "recibida", "enviada")
    mid = cliente.enviar(USUARIO, render_propuesta(p, VIVO), botones_propuesta(p.id, USUARIO, K))
    alm.guardar_mensaje(p.id, USUARIO, mid)
    return mid


@pytest.fixture
def entorno(tmp_path: Path):
    with TelegramFalso() as tg:
        pausas: list[float] = []
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base, dormir=pausas.append)
        alm = Almacen(tmp_path / "e.sqlite")
        aud = Auditoria(tmp_path / "a.jsonl")
        mid = enviar_propuesta(tg, alm, cliente, noop())
        yield Entorno(tg, alm, aud, mid, cliente, pausas, [])
        alm.cerrar()


def despachar(e: Entorno, accion: Accion, update: dict | None = None) -> None:
    """Tabla de la Tarea 8 para lo que cubre este archivo. La callback query se responde SIEMPRE antes
    de cualquier transición o edición."""
    if isinstance(accion, Ignorar):
        evento = EV_CALLBACK_INVALIDO if accion.motivo.startswith("callback_") else "mensaje_ignorado"
        e.aud.anotar(evento, motivo=accion.motivo)
    elif isinstance(accion, ResponderToque):
        e.aud.anotar(EV_CALLBACK_INVALIDO, motivo=accion.motivo)
        e.cliente.responder_callback(accion.callback_id, accion.texto)
    elif isinstance(accion, Toque):
        fila = e.alm.obtener(accion.id)
        if fila is None:
            e.cliente.responder_callback(accion.callback_id, "Botón no válido: no se hizo nada")
        elif fila.estado != "enviada":
            e.cliente.responder_callback(accion.callback_id, texto_ya_procesada(fila.estado))
        else:
            e.cliente.responder_callback(accion.callback_id, RECIBIDO)  # antes de transicionar
            texto = e.tg.mensajes[accion.message_id]["texto"]
            if accion.accion == "A":
                if e.alm.transicion(accion.id, "enviada", "aceptada"):
                    e.aud.anotar(EV_TRANSICION, id=accion.id, tipo=fila.tipo, de="enviada", a="aceptada")
                    assert e.alm.transicion(accion.id, "aceptada", "ejecutando")
                    e.cliente.editar(USUARIO, accion.message_id, texto + "\n\nEJECUTANDO…")
                    assert e.alm.transicion(accion.id, "ejecutando", "ejecutada", relectura=RELECTURA)
                    e.aud.anotar(EV_TRANSICION, id=accion.id, tipo=fila.tipo, de="ejecutando", a="ejecutada")
                    e.cliente.editar(USUARIO, accion.message_id,
                                     render_resultado(texto, Desenlace("ejecutada", T, relectura=RELECTURA)))
            elif e.alm.transicion(accion.id, "enviada", "rechazada"):
                e.aud.anotar(EV_TRANSICION, id=accion.id, tipo=fila.tipo, de="enviada", a="rechazada")
                e.cliente.editar(USUARIO, accion.message_id,
                                 render_resultado(texto, Desenlace("rechazada", T)))
                e.cliente.enviar(USUARIO, PREGUNTA_MOTIVO.format(id=accion.id))
    elif isinstance(accion, GuardarMotivo):
        fila = e.alm.obtener(accion.motivo.id)
        e.motivos.append(nota_motivo(accion.motivo, fila.propuesta if fila else None))
    else:  # pragma: no cover - fuera del alcance de este archivo
        raise TypeError(f"acción no cubierta: {accion!r}")


def ciclo(e: Entorno) -> None:
    """obtener_updates → interpretar_update → despachar, hasta vaciar la cola."""
    while True:
        ups = e.cliente.obtener_updates(e.sig, timeout_s=0)
        if not ups:
            return
        for u in ups:
            e.sig = u["update_id"] + 1
            accion = interpretar_update(u, Emparejamiento(USUARIO, USUARIO), K, datetime.now(ZONA_COT))
            despachar(e, accion, u)


def respuestas(tg: TelegramFalso) -> list[str]:
    return [ll.params.get("text", "") for ll in tg.llamadas if ll.metodo == "answerCallbackQuery"]


def last_answer(tg: TelegramFalso) -> str:
    return respuestas(tg)[-1]


def ediciones(tg: TelegramFalso) -> list:
    return [ll for ll in tg.llamadas if ll.metodo == "editMessageText"]


def test_aceptar_noop(entorno):
    tg, alm, aud, mid = entorno
    cq = tg.meter_toque(firmar(ID, "A", 42, K), 42, 42, mid)
    ciclo(entorno)
    resp = next(ll for ll in tg.llamadas if ll.metodo == "answerCallbackQuery")
    assert resp.params["text"] == "Recibido" and resp.t - tg.entregado_en(cq) < 1.0
    assert resp.params["callback_query_id"] == cq
    assert tg.mensajes[mid]["texto"].endswith("EJECUTADA 14:07 · relectura OK: sin cambios (prueba)")
    assert tg.mensajes[mid]["botones"] == [] and alm.obtener(ID).estado == "ejecutada"
    # la respuesta salió antes que cualquier edición
    metodos = [ll.metodo for ll in tg.llamadas]
    assert metodos.index("answerCallbackQuery") < metodos.index("editMessageText")
    assert aud.verificar() is True


def test_doble_toque(entorno):
    tg, alm, _aud, mid = entorno
    d = firmar(ID, "A", 42, K)
    tg.meter_toque(d, 42, 42, mid)
    tg.meter_toque(d, 42, 42, mid)
    ciclo(entorno)
    textos = [ll.params["text"] for ll in tg.llamadas if ll.metodo == "answerCallbackQuery"]
    assert textos == ["Recibido", "Ya procesada (ejecutada)"]
    assert len(ediciones(tg)) == 2  # EJECUTANDO… y EJECUTADA, una sola vez
    assert alm.historial(ID)[-1][1] == "ejecutada"


def test_toque_tardio(entorno):
    tg, alm, _aud, mid = entorno
    alm.transicion(ID, "enviada", "caducada")
    tg.meter_toque(firmar(ID, "A", 42, K), 42, 42, mid)
    ciclo(entorno)
    assert last_answer(tg) == "Caducada: no se ejecutó nada" and alm.obtener(ID).estado == "caducada"
    assert ediciones(tg) == []


def test_rechazar_pide_motivo_y_lo_guarda(entorno):
    tg, alm, _aud, mid = entorno
    tg.meter_toque(firmar(ID, "R", 42, K), 42, 42, mid)
    ciclo(entorno)
    assert tg.mensajes[mid]["texto"].endswith("RECHAZADA 14:07") and tg.mensajes[mid]["botones"] == []
    assert alm.obtener(ID).estado == "rechazada"
    pregunta = max(tg.mensajes)
    assert tg.mensajes[pregunta]["texto"] == PREGUNTA_MOTIVO.format(id=ID)
    tg.meter_mensaje("Ya tengo demasiados anuncios en ese país", 42, 42, reply_to=pregunta)
    ciclo(entorno)
    assert len(entorno.motivos) == 1
    nota = entorno.motivos[0]
    assert nota.ruta_relativa == f"raw/telegram/motivos/{datetime.now(ZONA_COT).date().isoformat()}-{ID}.md"
    assert nota.ruta_relativa.endswith(f"-{ID}.md") and nota.ruta_relativa.startswith("raw/telegram/motivos/")
    assert "> Ya tengo demasiados anuncios en ese país" in nota.contenido
    assert f"propuesta: {ID}" in nota.contenido


def test_firma_falsa_y_usuario_ajeno(entorno):
    tg, alm, aud, mid = entorno
    buena = firmar(ID, "A", 42, K)
    falsa = buena[:-1] + ("b" if buena[-1] != "b" else "c")
    tg.meter_toque(falsa, 42, 42, mid)
    tg.meter_toque(buena, 99, 42, mid)
    ciclo(entorno)
    assert ediciones(tg) == [] and alm.obtener(ID).estado == "enviada"
    lineas = [json.loads(ln) for ln in Path(aud.ruta).read_text().splitlines()]
    inv = [ln for ln in lineas if ln["evento"] == "callback_invalido"]
    assert [ln["datos"]["motivo"] for ln in inv] == ["callback_firma", "callback_usuario_ajeno"]
    assert aud.verificar() is True


def test_429_en_mitad_de_la_edicion(entorno):
    tg, alm, _aud, mid = entorno
    tg.fallar("editMessageText", veces=1, codigo=429, retry_after=1)
    tg.meter_toque(firmar(ID, "A", 42, K), 42, 42, mid)
    ciclo(entorno)
    assert 1 in entorno.pausas  # durmió retry_after (falso) y reintentó
    assert len(ediciones(tg)) == 3  # 429 + EJECUTANDO… + EJECUTADA
    assert tg.mensajes[mid]["texto"].endswith("EJECUTADA 14:07 · relectura OK: sin cambios (prueba)")
    assert alm.obtener(ID).estado == "ejecutada"


def test_mensaje_fantasma(entorno):
    tg, alm, _aud, _mid = entorno
    p2 = cargar_propuesta(noop(id=ID2))
    alm.registrar(p2)
    antes = set(tg.mensajes)
    tg.cortar("sendMessage")
    with pytest.raises(ErrorRedTelegram):
        entorno.cliente.enviar(USUARIO, render_propuesta(p2, VIVO), botones_propuesta(ID2, USUARIO, K))
    fantasma = next(iter(set(tg.mensajes) - antes))  # el falso sí lo creó aunque cortó la conexión
    assert alm.obtener(ID2).estado == "recibida" and alm.obtener(ID2).message_id is None
    tg.meter_toque(firmar(ID2, "A", 42, K), 42, 42, fantasma)
    ciclo(entorno)
    assert last_answer(tg) == "Aún no enviada: no se hizo nada"
    assert alm.obtener(ID2).estado == "recibida" and ediciones(tg) == []


def test_token_fuera_de_todo(entorno, caplog, tmp_path):
    tg, _alm, _aud, mid = entorno
    caplog.set_level(logging.DEBUG)
    buena = firmar(ID, "A", 42, K)
    tg.meter_toque(buena[:-1] + "x", 42, 42, mid)
    tg.meter_toque(buena, 42, 42, mid)
    ciclo(entorno)
    tg.cortar("sendMessage")
    with pytest.raises(ErrorRedTelegram) as exc:
        entorno.cliente.enviar(USUARIO, "x")
    tg.fallar("editMessageText", veces=3, codigo=429, retry_after=1)  # agota los reintentos
    with pytest.raises(ErrorTelegram) as exc2:
        entorno.cliente.editar(USUARIO, mid, "otro texto")
    for exc_ in (exc, exc2):
        assert exc_.value.__cause__ is None and exc_.value.__suppress_context__ is True
        assert TOKEN_PRUEBA not in str(exc_.value) and TOKEN_PRUEBA not in repr(exc_.value)
        assert TOKEN_PRUEBA not in "".join(traceback.format_exception(exc_.value))
    assert TOKEN_PRUEBA not in (tmp_path / "a.jsonl").read_text()
    assert TOKEN_PRUEBA not in caplog.text and TOKEN_PRUEBA not in repr(entorno.cliente)


def test_toque_de_mensaje_inaccesible(entorno):
    tg, alm, aud, mid = entorno
    antes = len(ediciones(tg))
    tg.meter_toque(firmar(ID, "A", 42, K), 42, 42, mid)
    tg._updates[-1]["callback_query"]["message"]["date"] = 0  # Telegram: mensaje de más de 48 h
    ciclo(entorno)
    assert alm.obtener(ID).estado == "enviada" and len(ediciones(tg)) == antes
    assert respuestas(tg) == []
    lineas = [json.loads(ln) for ln in Path(aud.ruta).read_text().splitlines()]
    assert [ln["datos"]["motivo"] for ln in lineas] == ["callback_sin_fecha"]
