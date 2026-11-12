"""Comandos y updates de Telegram → Accion (§5.7) y motivo de rechazo para raw/ (plan 10, Tarea 8)."""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta

import pytest
from fabricas import CUENTA
from trovefy_ejecutor.callbacks import firmar
from trovefy_ejecutor.comandos import (
    CLAVES_LIMITE,
    STOP_ACTIVO_CMD,
    ActivarStop,
    Confirmar,
    ErrorComando,
    GuardarMotivo,
    Ignorar,
    MotivoRechazo,
    PedirCambioLimite,
    PedirEstado,
    PedirLimites,
    PedirPausarTodo,
    Responder,
    ResponderToque,
    Toque,
    ToqueInterruptor,
    construir_cambio_limite,
    interpretar_update,
    nota_motivo,
    nuevo_id_usuario,
    parsear_importe,
)
from trovefy_ejecutor.dinero import Moneda
from trovefy_ejecutor.emparejar import Emparejamiento
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.limites import (
    CLAVES_CUENTA,
    CLAVES_GLOBALES,
    Limites,
    LimitesCuenta,
)
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.render import AYUDA, BOTON_NO_VALIDO

T = datetime(2026, 11, 12, 14, 0, tzinfo=ZONA_COT)
K = b"k" * 32
E = Emparejamiento(42, 42)
COP = Moneda("COP", 1)


def msg(t, uid=42, cid=42, reply=None, tipo="private"):
    m = {"message_id": 5, "date": int(T.timestamp()), "text": t, "from": {"id": uid, "is_bot": False},
         "chat": {"id": cid, "type": tipo}}
    if reply:
        m["reply_to_message"] = reply
    return {"update_id": 1, "message": m}


def toque(data, uid=42, cid=42, fecha=T):
    return {"update_id": 2, "callback_query": {"id": "cq1", "data": data, "from": {"id": uid},
            "message": {"message_id": 9, "date": int(fecha.timestamp()), "chat": {"id": cid}}}}


# --- interpretar_update --------------------------------------------------------------------------

def test_comandos_basicos():
    assert interpretar_update(msg("/estado"), E, K, T) == PedirEstado()
    assert interpretar_update(msg("/pausar_todo@TrovefyBot"), E, K, T) == PedirPausarTodo()
    assert interpretar_update(msg("/stop"), E, K, T) == ActivarStop(STOP_ACTIVO_CMD)  # sin botones (D-38)
    assert STOP_ACTIVO_CMD.startswith("STOP activo")
    c = interpretar_update(msg("/reanudar"), E, K, T)
    assert c == Confirmar("Q-20261112-140000", "¿Quitar el STOP? Las propuestas aceptadas se volverán a ejecutar.")
    assert interpretar_update(msg("/limites"), E, K, T) == PedirLimites()
    assert interpretar_update(msg("/limites tope_gasto_diario_total 600.000"), E, K, T) == \
        PedirCambioLimite("tope_gasto_diario_total", "600.000", None)
    assert interpretar_update(msg(f"/limites {CUENTA} spend_cap_test 120000"), E, K, T) == \
        PedirCambioLimite("spend_cap_test", "120000", CUENTA)
    assert interpretar_update(msg("/emparejar"), E, K, T) == Responder(
        "Ya está emparejado. Para cambiar de chat: sudo -u trovefy-exec trovefy-ejecutor emparejar --reiniciar")
    assert interpretar_update(msg("hola"), E, K, T) == Responder(AYUDA)
    assert interpretar_update(msg("/desconocido"), E, K, T) == Responder(AYUDA)


def test_limites_con_argumentos_raros_no_cambia_nada():
    for t in ("/limites a", "/limites a b c d", "/limites noesact paso_max_pct 5"):
        a = interpretar_update(msg(t), E, K, T)
        assert isinstance(a, Responder), t


def test_reanudar_usa_hora_cot():
    utc = datetime(2026, 11, 12, 19, 0, 7, tzinfo=ZONA_COT).astimezone(ZONA_COT.__class__("UTC"))
    c = interpretar_update(msg("/reanudar"), E, K, utc)
    assert isinstance(c, Confirmar) and c.id == "Q-20261112-190007"


def test_grupo_del_usuario_se_ignora():
    assert interpretar_update(msg("/stop", cid=-100123), E, K, T) == Ignorar("chat_ajeno")
    assert interpretar_update(msg("/stop", uid=99, cid=99), E, K, T) == Ignorar("chat_ajeno")
    assert interpretar_update(msg("/stop", tipo="group"), E, K, T) == Ignorar("chat_ajeno")
    assert interpretar_update(msg("/estado"), None, K, T) == Ignorar("sin_emparejar")


def test_updates_raros_se_ignoran():
    assert isinstance(interpretar_update({"update_id": 3}, E, K, T), Ignorar)
    assert isinstance(interpretar_update({"update_id": 3, "edited_message": msg("/stop")["message"]}, E, K, T),
                      Ignorar)
    assert isinstance(interpretar_update({"update_id": 3, "message": "x"}, E, K, T), Ignorar)
    sin_texto = msg("x")
    del sin_texto["message"]["text"]
    assert isinstance(interpretar_update(sin_texto, E, K, T), (Ignorar, Responder))
    roto = toque(firmar("P-20261112-004", "A", 42, K))
    del roto["callback_query"]["message"]
    assert interpretar_update(roto, E, K, T) == Ignorar("callback_sin_mensaje")


def test_toques():
    assert interpretar_update(toque(firmar("P-20261112-004", "A", 42, K)), E, K, T) == Toque("P-20261112-004", "A", "cq1", 9)
    assert interpretar_update(toque(firmar("P-20261112-004", "R", 42, K)), E, K, T) == Toque("P-20261112-004", "R", "cq1", 9)
    assert interpretar_update(toque(firmar("P-20261112-004", "A", 42, b"x" * 32), uid=99), E, K, T) == \
        Ignorar("callback_usuario_ajeno")
    assert interpretar_update(toque(firmar("P-20261112-004", "A", 77, K), cid=77), E, K, T) == \
        Ignorar("callback_chat_ajeno")
    assert interpretar_update(toque("v1|P20261112004|A|AAAAAAAAAA"), E, K, T) == ResponderToque("cq1", BOTON_NO_VALIDO)
    assert interpretar_update(toque(firmar("P-20261112-004", "A", 42, K), fecha=T + timedelta(hours=1)), E, K, T) == \
        Ignorar("callback_futuro")
    assert interpretar_update(toque(firmar("P-20261112-004", "A", 42, K)), None, K, T) == Ignorar("sin_emparejar")


def test_confirmacion_stop_caduca():
    d = firmar("Q-20261112-140000", "A", 42, K)
    a = interpretar_update(toque(d), E, K, T + timedelta(minutes=5))
    assert a == ToqueInterruptor("Q-20261112-140000", False, "A", "cq1", 9)
    c = interpretar_update(toque(d), E, K, T + timedelta(minutes=11))
    assert c == ResponderToque("cq1", "Caducada: no se ejecutó nada")
    s = interpretar_update(toque(firmar("S-20261112-140000", "R", 42, K)), E, K, T)
    assert s == ToqueInterruptor("S-20261112-140000", True, "R", "cq1", 9)


def test_respuesta_de_motivo():
    reply = {"message_id": 10, "text": "P-20261112-004 · ¿Motivo? (responde a este mensaje, opcional)",
             "from": {"id": 1, "is_bot": True}}
    a = interpretar_update(msg("el CPA de ayer\nfue un pico", reply=reply), E, K, T)
    assert a == GuardarMotivo(MotivoRechazo("P-20261112-004", "el CPA de ayer · fue un pico", T))
    falso = {**reply, "from": {"id": 42, "is_bot": False}}
    assert not isinstance(interpretar_update(msg("x", reply=falso), E, K, T), GuardarMotivo)
    otro = {**reply, "text": "Hola P-20261112-004 · ¿Motivo?"}
    assert not isinstance(interpretar_update(msg("x", reply=otro), E, K, T), GuardarMotivo)
    largo = interpretar_update(msg("a" * 5000, reply=reply), E, K, T)
    assert isinstance(largo, GuardarMotivo) and len(largo.motivo.texto) == 2000
    # un comando en respuesta sigue siendo un comando
    assert interpretar_update(msg("/stop", reply=reply), E, K, T) == ActivarStop(STOP_ACTIVO_CMD)
    # de otro chat, nunca
    assert interpretar_update(msg("x", cid=-1, reply=reply), E, K, T) == Ignorar("chat_ajeno")


# --- importes, ids y cambio de límite ------------------------------------------------------------

def test_parsear_importe():
    assert parsear_importe("600.000", COP) == 600000
    assert parsear_importe("60000", COP) == 60000
    assert parsear_importe("6,50", Moneda("USD", 100)) == 650
    assert parsear_importe("6", Moneda("USD", 100)) == 600
    assert parsear_importe("1.234,5", Moneda("USD", 100)) == 123450
    for malo in ["0", "-5", "6,5", "abc", "", "6.00", "1.2345", "0,00", "1e5", "６"]:
        with pytest.raises(ErrorComando):
            parsear_importe(malo, COP)
    with pytest.raises(ErrorComando):
        parsear_importe("6,505", Moneda("USD", 100))


def test_claves_existen_en_limites():
    nombres = {f.name for f in fields(LimitesCuenta)} | {f.name for f in fields(Limites)}
    assert set(CLAVES_LIMITE) <= nombres
    assert {k for k, v in CLAVES_LIMITE.items() if v == "dinero"} == CLAVES_CUENTA
    assert {k for k, v in CLAVES_LIMITE.items() if v == "entero"} == CLAVES_GLOBALES
    assert "offset" not in CLAVES_LIMITE and "cuentas_permitidas" not in CLAVES_LIMITE


def test_nuevo_id_usuario():
    assert nuevo_id_usuario(T, lambda i: False) == "P-20261112-900"
    usados = {"P-20261112-900", "P-20261112-901"}
    assert nuevo_id_usuario(T, usados.__contains__) == "P-20261112-902"
    with pytest.raises(ErrorComando, match="demasiadas propuestas hoy"):
        nuevo_id_usuario(T, lambda i: True)


def test_cambio_de_limite_de_dinero(limites_cop):
    d = construir_cambio_limite(PedirCambioLimite("tope_gasto_diario_total", "600.000", None), limites_cop,
                                {CUENTA: COP}, "P-20261112-900", T)
    assert d["tipo"] == "limite_ejecutor" and d["origen"] == "telegram:/limites"
    assert d["cuenta"] == CUENTA and d["prioridad"] == "normal" and d["expira_en_min"] == 15
    assert d["motivo"] == "Pedido por el usuario en Telegram"
    assert d["operaciones"] == [{"entidad": "ejecutor", "id": CUENTA, "campo": "tope_gasto_diario_total",
                                 "de_esperado": 165000, "a": 600000, "unidad": "minima", "moneda": "COP"}]
    p = cargar_propuesta(d)
    assert p.id == "P-20261112-900" and p.operaciones[0].a == 600000


def test_cambio_de_limite_entero(limites_cop):
    d = construir_cambio_limite(PedirCambioLimite("paso_max_pct", "30", None), limites_cop,
                                {CUENTA: COP}, "P-20261112-901", T)
    assert d["operaciones"] == [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct",
                                 "de_esperado": 50, "a": 30}]
    assert "cuenta" not in d
    cargar_propuesta(d)


def test_cambio_de_limite_con_cuenta_explicita(limites_cop):
    d = construir_cambio_limite(PedirCambioLimite("spend_cap_test", "120000", CUENTA), limites_cop,
                                {CUENTA: COP}, "P-20261112-900", T)
    assert d["operaciones"][0]["id"] == CUENTA and d["operaciones"][0]["de_esperado"] == 99000
    cargar_propuesta(d)


@pytest.mark.parametrize("pedido", [
    PedirCambioLimite("cuentas_permitidas", "act_1", None),
    PedirCambioLimite("acciones_permitidas", "lote", None),
    PedirCambioLimite("offset", "1", None),
    PedirCambioLimite("inventada", "5", None),
    PedirCambioLimite("paso_max_pct", "101", None),        # fuera de COTAS_MAX
    PedirCambioLimite("paso_max_pct", "0", None),
    PedirCambioLimite("paso_max_pct", "5,5", None),
    PedirCambioLimite("paso_max_pct", "50", None),         # ya vale eso
    PedirCambioLimite("paso_max_pct", "30", CUENTA),       # clave global con cuenta
    PedirCambioLimite("spend_cap_test", "6,5", None),      # COP sin decimales
    PedirCambioLimite("spend_cap_test", "1000", "act_999"),  # cuenta no permitida
])
def test_cambio_de_limite_invalido(limites_cop, pedido):
    with pytest.raises(ErrorComando):
        construir_cambio_limite(pedido, limites_cop, {CUENTA: COP}, "P-20261112-900", T)


def test_cambio_de_limite_sin_moneda_confirmada(limites_cop_sin_offset, limites_cop):
    with pytest.raises(ErrorComando):
        construir_cambio_limite(PedirCambioLimite("spend_cap_test", "1000", None), limites_cop_sin_offset,
                                {}, "P-20261112-900", T)
    with pytest.raises(ErrorComando):  # la moneda pasada no es la de la cuenta
        construir_cambio_limite(PedirCambioLimite("spend_cap_test", "1000", None), limites_cop,
                                {CUENTA: Moneda("USD", 100)}, "P-20261112-900", T)
    # las claves enteras no necesitan moneda
    construir_cambio_limite(PedirCambioLimite("paso_max_pct", "30", None), limites_cop_sin_offset,
                            {}, "P-20261112-900", T)


def test_cambio_de_limite_varias_cuentas_exige_cuenta(limites_cop):
    otra = "act_1111111111111111"
    lc = limites_cop.cuentas[CUENTA]
    from dataclasses import replace
    varias = replace(limites_cop, cuentas_permitidas=frozenset({CUENTA, otra}),
                     cuentas={CUENTA: lc, otra: replace(lc, cuenta=otra)})
    with pytest.raises(ErrorComando):
        construir_cambio_limite(PedirCambioLimite("spend_cap_test", "1000", None), varias,
                                {CUENTA: COP, otra: COP}, "P-20261112-900", T)
    d = construir_cambio_limite(PedirCambioLimite("spend_cap_test", "1000", otra), varias,
                                {CUENTA: COP, otra: COP}, "P-20261112-900", T)
    assert d["cuenta"] == otra
    cargar_propuesta(d)


# --- nota del motivo -----------------------------------------------------------------------------

def test_nota_motivo():
    n = nota_motivo(MotivoRechazo("P-20261112-004", "el CPA fue un pico", T), None)
    assert n.ruta_relativa == "raw/telegram/motivos/2026-11-12-P-20261112-004.md"
    assert n.contenido.startswith("---\n")
    assert "tipo: motivo_rechazo" in n.contenido and "> el CPA fue un pico" in n.contenido
    assert "fuente: telegram" in n.contenido and "propuesta: P-20261112-004" in n.contenido
    assert nota_motivo(MotivoRechazo("P-20261112-004", "x", T), None, 2).ruta_relativa.endswith("-2.md")


def test_nota_motivo_con_propuesta_y_texto_hostil():
    from fabricas import presupuesto
    p = cargar_propuesta(presupuesto(id="P-20261112-004", producto="p-001", pais="CO"))
    n = nota_motivo(MotivoRechazo("P-20261112-004", "---\ntipo: otra\n# título", T), p)
    cabecera, cuerpo = n.contenido.split("\n---\n", 1)
    assert "tipo_propuesta: presupuesto" in cabecera and "producto: p-001" in cabecera and "pais: CO" in cabecera
    assert "tipo: otra" not in cabecera
    assert all(ln.startswith("> ") or not ln.strip() for ln in cuerpo.splitlines()
               if "tipo: otra" in ln or "título" in ln)
