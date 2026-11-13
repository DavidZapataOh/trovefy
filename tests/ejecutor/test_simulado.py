"""Modo simulado: Telegram y Graph en proceso (plan 12, tarea 3). Sin red, sin hilos, sin token."""
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from ejecutor.fabricas_graph import propuesta
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.callbacks import firmar, verificar
from trovefy_ejecutor.ejecutar import ejecutar
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.graph import ClienteGraph, ErrorGraph
from trovefy_ejecutor.render import botones_propuesta
from trovefy_ejecutor.simulado import GraphSimulado, TelegramSimulado
from trovefy_ejecutor.telegram import ClienteTelegram
from trovefy_ejecutor.vivo import valores_vivos

K = b"k" * 32
PID = "P-20261112-001"
T = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


def test_tocar_genera_callback_firmado():
    t = TelegramSimulado()
    mid = t.enviar(42, f"{PID} · PRUEBA", botones_propuesta(PID, 42, K))
    cb = t.tocar(PID, "A", K)
    (u,) = t.obtener_updates(offset=0, timeout_s=0)
    cq = u["callback_query"]
    assert cq["id"] == cb and cq["from"]["id"] == 42 and cq["message"]["message_id"] == mid
    assert cq["data"] == firmar(PID, "A", 42, K) and cq["message"]["chat"]["id"] == 42
    emp = SimpleNamespace(chat_id=42, user_id=42)
    assert verificar(cq["data"], 42, 42, emp, K) == (PID, "A")


def test_updates_respetan_offset_y_fecha_del_reloj():
    t = TelegramSimulado(ahora=lambda: T)
    t.enviar(42, PID, botones_propuesta(PID, 42, K))
    t.tocar(PID, "R", K)
    t.escribir("/estado")
    ups = t.obtener_updates(0)
    assert [u["update_id"] for u in ups] == [1, 2]
    assert [u["update_id"] for u in t.obtener_updates(2)] == [2]
    assert t.obtener_updates(3) == []
    assert ups[0]["callback_query"]["message"]["date"] == int(T.timestamp())
    assert ups[1]["message"]["text"] == "/estado" and ups[1]["message"]["date"] == int(T.timestamp())


def test_tocar_con_usuario_ajeno_y_data_manipulada():
    t = TelegramSimulado()
    t.enviar(42, PID, botones_propuesta(PID, 42, K))
    t.tocar(PID, "A", K, user_id=7, data="basura")
    (u,) = t.obtener_updates(0)
    assert u["callback_query"]["from"]["id"] == 7 and u["callback_query"]["data"] == "basura"


def test_tocar_sin_mensaje_falla():
    with pytest.raises(KeyError):
        TelegramSimulado().tocar(PID, "A", K)


def test_editar_responder_y_escribir_respondiendo():
    t = TelegramSimulado()
    mid = t.enviar(42, "uno", None, sonido=False)
    assert t.mensajes[mid] == {"chat_id": 42, "texto": "uno", "botones": None, "sonido": False}
    t.editar(42, mid, "dos", None)
    assert t.mensajes[mid]["texto"] == "dos"
    t.responder_callback("1", "hecho")
    assert t.respuestas_callback == [("1", "hecho")]
    t.escribir("123456", responde_a=mid)
    assert t.obtener_updates(0)[0]["message"]["reply_to_message"]["message_id"] == mid


def test_simulado_fecha_y_respuesta():
    reloj = [T]
    t = TelegramSimulado(ahora=lambda: reloj[0])
    mid = t.enviar(42, "uno")
    assert t.tomar_fecha() == int(T.timestamp()) and t.tomar_fecha() is None
    otro = t.enviar(42, "dos", responde_a=mid)
    assert t.mensajes[otro]["responde_a"] == mid
    t.tomar_fecha()
    t.editar(42, mid, "tres")
    assert t.tomar_fecha() == int(T.timestamp())


def test_telegram_misma_interfaz_que_cliente():
    for nombre in ("obtener_updates", "enviar", "editar", "responder_callback", "tomar_fecha"):
        real = inspect.signature(getattr(ClienteTelegram, nombre))
        sim = inspect.signature(getattr(TelegramSimulado, nombre))
        assert list(real.parameters) == list(sim.parameters), nombre
        assert [p.kind for p in real.parameters.values()] == [p.kind for p in sim.parameters.values()], nombre


def test_graph_misma_interfaz_que_cliente():
    for nombre in ("leer", "listar", "buscar", "escribir", "crear", "subir_imagen", "subir_video", "cuenta"):
        real = inspect.signature(getattr(ClienteGraph, nombre))
        sim = inspect.signature(getattr(GraphSimulado, nombre))
        assert list(real.parameters) == list(sim.parameters), nombre
        assert [p.kind for p in real.parameters.values()] == [p.kind for p in sim.parameters.values()], nombre


def test_graph_validate_only_no_cambia():
    g = GraphSimulado()
    assert g.escribir("s1", {"daily_budget": 1}, validate_only=True) == {"success": True}
    assert g.escrituras == [] and g.leer("s1", ["daily_budget"])["daily_budget"] == "20000"
    g.escribir("s1", {"daily_budget": 26000})
    assert g.leer("s1", ["daily_budget"])["daily_budget"] == "26000"
    assert [e[0] for e in g.escrituras] == ["escribir"]


def test_cuenta_cop():
    c = GraphSimulado().cuenta("act_0000000000000000")
    assert (c.currency, c.offset, c.timezone_name, c.account_status) == ("COP", 1, "America/Bogota", 1)
    assert c.spend_cap and c.amount_spent is not None
    assert GraphSimulado(moneda="USD").cuenta("act_0000000000000000").offset == 100


def test_listar_mundo_coherente():
    g = GraphSimulado()
    cuenta = "act_0000000000000000"
    campos = ["status", "effective_status", "daily_budget", "lifetime_budget", "campaign_id"]
    (s,) = g.listar("c1", "adsets", campos)
    assert s["id"] == "s1" and s["daily_budget"] == "20000" and s["campaign_id"] == "c1"
    assert [x["id"] for x in g.listar(cuenta, "adsets", campos, limite=100)] == ["s1"]
    assert [x["id"] for x in g.listar(cuenta, "campaigns", campos)] == ["c1"]
    assert g.listar(cuenta, "adsets", campos, filtros={"effective_status": ["PAUSED"]}) == []
    assert g.leer("c1", ["account_id"])["account_id"] == "0000000000000000"


def test_crear_campana_exige_presupuesto_y_errores():
    g = GraphSimulado()
    with pytest.raises(ErrorGraph):
        g.crear("act_0000000000000000", "campaigns", {"name": "x"})
    with pytest.raises(ErrorGraph):
        g.leer("nope", ["status"])
    with pytest.raises(ValueError):
        g.leer("s1/../x", ["status"])
    with pytest.raises(ValueError):
        g.escribir("s1", {"daily_budget": None})
    r = g.crear("act_0000000000000000", "campaigns", {"name": "x", "is_adset_budget_sharing_enabled": False,
                                                       "status": "PAUSED"}, validate_only=True)
    assert r == {"success": True} and g.escrituras == []
    nuevo = g.crear("act_0000000000000000", "campaigns", {"name": "x", "is_adset_budget_sharing_enabled": False,
                                                           "status": "PAUSED"})["id"]
    assert g.leer(nuevo, ["effective_status"])["effective_status"] == "PAUSED"
    assert len(g.escrituras) == 1


def test_montaje_soporte(tmp_path):
    g = GraphSimulado()
    h = g.subir_imagen("act_0000000000000000", b"png", "a.png")
    assert len(h) == 32
    vid = g.subir_video("act_0000000000000000", b"vid", "v.mp4")
    assert g.leer(vid, ["status"])["status"]["video_status"] == "ready"
    th = g.leer(vid, ["thumbnails{uri,is_preferred}"])["thumbnails"]["data"]
    assert th[0]["uri"].startswith("https://")
    assert g.buscar("otro", "x", ["key"]) == []
    assert [e[0] for e in g.escrituras] == ["subir_imagen", "subir_video"]


def test_repr_sin_secretos():
    assert "token" not in repr(GraphSimulado()).lower() and "token" not in repr(TelegramSimulado()).lower()


def test_ejecutar_extremo_a_extremo(tmp_path):
    g = GraphSimulado()
    alm = Almacen(tmp_path / "estado.db")
    try:
        aud = Auditoria(tmp_path / "auditoria.jsonl")
        p = propuesta()
        vv = valores_vivos(p, g, ahora=lambda: T)
        assert vv.entidades["s1"]["daily_budget"] == 20000
        r = ejecutar(p, g, alm, aud, ahora=lambda: T)
        assert r.estado == "ejecutada" and r.operaciones[0].despues == 26000
        assert g.escrituras == [("escribir", "s1", {"daily_budget": 26000})]
    finally:
        alm.cerrar()


# -- ronda de fidelidad 1 ---------------------------------------------------------------
def test_editar_inexistente_error_telegram():
    from trovefy_ejecutor.telegram import ErrorTelegram
    with pytest.raises(ErrorTelegram) as e:
        TelegramSimulado().editar(42, 99, "x")
    assert e.value.codigo == 400


def test_largo_maximo_en_enviar_y_editar():
    t = TelegramSimulado()
    with pytest.raises(ValueError):
        t.enviar(42, "x" * 4097)
    mid = t.enviar(42, "ok")
    with pytest.raises(ValueError):
        t.editar(42, mid, "x" * 4097)


def test_importe_no_entero_error_graph():
    g = GraphSimulado()
    with pytest.raises(ErrorGraph) as e:
        g.escribir("s1", {"daily_budget": "abc"})
    assert e.value.codigo == 100
    with pytest.raises(ErrorGraph):
        g.escribir("s1", {"daily_budget": 1.5})


def test_status_refleja_effective_status():
    g = GraphSimulado()
    g.escribir("s1", {"status": "PAUSED"})
    assert g.leer("s1", ["effective_status"])["effective_status"] == "PAUSED"


def test_crear_pone_cuenta_y_padres():
    g = GraphSimulado()
    nuevo = g.crear("c1", "adsets", {"name": "n", "status": "PAUSED"})["id"]
    o = g.leer(nuevo, ["account_id", "campaign_id"])
    assert o["account_id"] == "0000000000000000" and o["campaign_id"] == "c1"
    ad = g.crear("s1", "ads", {"name": "n"})["id"]
    assert g.leer(ad, ["adset_id", "account_id"])["adset_id"] == "s1"
    camp = g.crear("act_0000000000000000", "campaigns", {"name": "c", "is_adset_budget_sharing_enabled": False})["id"]
    assert g.leer(camp, ["account_id"])["account_id"] == "0000000000000000"


def test_listar_filtro_str_normalizado():
    g = GraphSimulado()
    cu = "act_0000000000000000"
    assert [x["id"] for x in g.listar(cu, "adsets", ["id"], filtros={"effective_status": "ACTIVE"})] == ["s1"]
    assert g.listar(cu, "adsets", ["id"], filtros={"effective_status": "ACTI"}) == []
    assert [x["id"] for x in g.listar(cu, "adsets", ["id"], filtros={"effective_status": '["ACTIVE"]'})] == ["s1"]
