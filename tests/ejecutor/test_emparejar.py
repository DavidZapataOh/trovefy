import json
import os
import re
import stat
import threading
import time
from datetime import datetime, timedelta

import pytest
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.buzon import Buzon
from trovefy_ejecutor.emparejar import (
    MAX_FALLOS,
    CodigoPendiente,
    Emparejamiento,
    ejecutar_emparejamiento,
    guardar_emparejamiento,
    intentar_emparejar,
    leer_emparejamiento,
    nuevo_codigo,
)
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.telegram import ClienteTelegram

T = datetime(2026, 11, 12, 10, 0, tzinfo=ZONA_COT)


def msg(texto, uid=42, cid=42, tipo="private", bot=False):
    return {"update_id": 1, "message": {"text": texto, "from": {"id": uid, "is_bot": bot}, "chat": {"id": cid, "type": tipo}}}


def test_codigo_y_emparejado():
    p = nuevo_codigo(T)
    assert len(p.codigo) == 6 and p.codigo.isdigit()
    assert p.caduca == T + timedelta(minutes=10)
    assert intentar_emparejar(msg(f" {p.codigo} "), p, None, T) == Emparejamiento(42, 42)


def test_grupo_no_empareja():
    p = nuevo_codigo(T)
    assert intentar_emparejar(msg(p.codigo, cid=-100123, tipo="group"), p, None, T) == "no_privado"
    assert intentar_emparejar(msg(p.codigo, cid=-100123, tipo="channel"), p, None, T) == "no_privado"
    assert intentar_emparejar(msg(p.codigo, cid=43), p, None, T) == "no_privado"


def test_bot_y_no_mensaje():
    p = nuevo_codigo(T)
    assert intentar_emparejar(msg(p.codigo, bot=True), p, None, T) == "bot"
    assert intentar_emparejar({"update_id": 2, "callback_query": {}}, p, None, T) == "no_es_mensaje"
    assert intentar_emparejar({"update_id": 2, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}}}, p, None, T) == "no_es_mensaje"


def test_nunca_otro_despues():
    p = nuevo_codigo(T)
    assert intentar_emparejar(msg(p.codigo, uid=99, cid=99), p, Emparejamiento(42, 42), T) == "ya_emparejado"
    assert intentar_emparejar(msg(p.codigo), p, Emparejamiento(42, 42), T) == "ya_emparejado"


def test_caduca_y_se_agota():
    p = nuevo_codigo(T)
    assert intentar_emparejar(msg(p.codigo), p, None, T + timedelta(minutes=11)) == "caducado"
    for _ in range(MAX_FALLOS):
        assert intentar_emparejar(msg("000000" if p.codigo != "000000" else "111111"), p, None, T) == "codigo"
    assert p.fallos == MAX_FALLOS
    assert intentar_emparejar(msg(p.codigo), p, None, T) == "agotado"


def test_codigo_con_digitos_no_ascii_no_revienta():
    p = CodigoPendiente("123456", T + timedelta(minutes=10))
    assert intentar_emparejar(msg("١٢٣٤٥٦"), p, None, T) == "no_codigo"
    assert p.fallos == 0


def test_secretos(tmp_path):
    s = tmp_path / "secretos.env"
    s.write_text("TELEGRAM_BOT_TOKEN=123456:" + "A" * 35 + "\n")
    os.chmod(s, 0o600)
    assert leer_emparejamiento(s) is None
    guardar_emparejamiento(s, Emparejamiento(42, 42))
    assert leer_emparejamiento(s) == Emparejamiento(42, 42) and "TELEGRAM_BOT_TOKEN=" in s.read_text()
    assert stat.S_IMODE(s.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        guardar_emparejamiento(s, Emparejamiento(99, 99))
    assert leer_emparejamiento(s) == Emparejamiento(42, 42)


def _entorno(tmp_path):
    s = tmp_path / "secretos.env"
    s.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN_PRUEBA}\n")
    os.chmod(s, 0o600)
    return s, Almacen(tmp_path / "e.sqlite"), Auditoria(tmp_path / "a.jsonl"), Buzon(tmp_path / "buzon")


def test_flujo_con_el_falso(tmp_path):
    s, almacen, aud, buzon = _entorno(tmp_path)
    mostrado: list[str] = []
    with TelegramFalso() as tg:
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)

        def usuario():
            limite = time.monotonic() + 10
            while not mostrado and time.monotonic() < limite:
                time.sleep(0.02)
            c = re.search(r"\d{6}", mostrado[0]).group(0)
            malo = "000000" if c != "000000" else "111111"
            tg.meter_mensaje(malo, user_id=99, chat_id=99)  # extraño, código erróneo
            tg.meter_mensaje(c, user_id=7, chat_id=-100, chat_type="group")  # grupo con el código bueno
            time.sleep(0.3)
            tg.meter_mensaje(c, user_id=42, chat_id=42)

        h = threading.Thread(target=usuario)
        h.start()
        res = ejecutar_emparejamiento(
            cliente, almacen, s, mostrado.append, auditoria=aud, buzon=buzon,
            ahora=lambda: datetime.now(ZONA_COT),
        )
        h.join(timeout=15)
        enviados = [ll for ll in tg.llamadas if ll.metodo == "sendMessage"]
    assert res == Emparejamiento(42, 42)
    assert leer_emparejamiento(s) == res
    assert len(enviados) == 1 and enviados[0].params["chat_id"] == 42
    assert enviados[0].params["text"] == "Emparejado. Desde ahora solo este chat puede aprobar."
    assert mostrado[0].startswith("Código de emparejamiento: ") and "caduca en 10 min" in mostrado[0]
    codigo = re.search(r"\d{6}", mostrado[0]).group(0)
    crudo = (tmp_path / "a.jsonl").read_text()
    lineas = [json.loads(x) for x in crudo.splitlines()]
    assert [x["evento"] for x in lineas].count("emparejado") == 1
    assert [x["datos"]["motivo"] for x in lineas if x["evento"] == "emparejar_rechazado"] == ["codigo", "no_privado"]
    assert codigo not in crudo
    est = json.loads((tmp_path / "buzon/estado/emparejamiento.json").read_text())
    assert est["emparejado"] is True and "fecha" in est
    assert almacen.ultimo_update() >= 3


def test_caduca_sin_emparejar(tmp_path):
    s, almacen, aud, buzon = _entorno(tmp_path)
    reloj = {"t": T}

    def ahora():
        reloj["t"] += timedelta(seconds=59.5)
        return reloj["t"]

    with TelegramFalso() as tg:
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        res = ejecutar_emparejamiento(cliente, almacen, s, lambda _: None, auditoria=aud, buzon=buzon, ahora=ahora, minutos=1)
        assert not [ll for ll in tg.llamadas if ll.metodo == "sendMessage"]
    assert res is None and leer_emparejamiento(s) is None


def test_cola_vieja_y_charla_no_gastan_intentos(tmp_path):
    s, almacen, aud, buzon = _entorno(tmp_path)
    mostrado: list[str] = []
    with TelegramFalso() as tg:
        for i in range(5):  # un extraño encola 5 códigos ANTES de la emisión
            tg.meter_mensaje(f"00000{i}", user_id=99, chat_id=99)
        for u in tg._updates:
            u["message"]["date"] -= 1000
        tg.meter_mensaje("/start", user_id=42, chat_id=42)  # charla tras la emisión: se ignora
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)

        def usuario():
            limite = time.monotonic() + 10
            while not mostrado and time.monotonic() < limite:
                time.sleep(0.02)
            tg.meter_mensaje(re.search(r"\d{6}", mostrado[0]).group(0), user_id=42, chat_id=42)

        h = threading.Thread(target=usuario)
        h.start()
        res = ejecutar_emparejamiento(
            cliente, almacen, s, mostrado.append, auditoria=aud, buzon=buzon,
            ahora=lambda: datetime.now(ZONA_COT),
        )
        h.join(timeout=15)
    assert res == Emparejamiento(42, 42)
    eventos = [json.loads(x) for x in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert not [x for x in eventos if x["evento"] == "emparejar_rechazado"]


def test_cinco_codigos_malos_tras_emitir_agotan():
    p = nuevo_codigo(T)
    m = msg("000000" if p.codigo != "000000" else "111111")
    m["message"]["date"] = int(T.timestamp()) + 1
    for _ in range(MAX_FALLOS):
        assert intentar_emparejar(m, p, None, T) == "codigo"
    bueno = msg(p.codigo)
    bueno["message"]["date"] = int(T.timestamp()) + 1
    assert intentar_emparejar(bueno, p, None, T) == "agotado"
    viejo = msg(p.codigo)
    viejo["message"]["date"] = int(T.timestamp()) - 100
    assert intentar_emparejar(viejo, nuevo_codigo(T), None, T) == "antiguo"


def test_fallo_al_confirmar_se_avisa_y_audita(tmp_path):
    s, almacen, aud, buzon = _entorno(tmp_path)
    mostrado: list[str] = []
    with TelegramFalso() as tg:
        tg.fallar("sendMessage", veces=1, codigo=403)
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)

        def usuario():
            limite = time.monotonic() + 10
            while not mostrado and time.monotonic() < limite:
                time.sleep(0.02)
            tg.meter_mensaje(re.search(r"\d{6}", mostrado[0]).group(0), user_id=42, chat_id=42)

        h = threading.Thread(target=usuario)
        h.start()
        res = ejecutar_emparejamiento(
            cliente, almacen, s, mostrado.append, auditoria=aud, buzon=buzon,
            ahora=lambda: datetime.now(ZONA_COT),
        )
        h.join(timeout=15)
    assert res == Emparejamiento(42, 42) and leer_emparejamiento(s) == res
    assert "Emparejado, pero no se pudo confirmar en Telegram." in mostrado
    eventos = [json.loads(x) for x in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert any(x["datos"].get("motivo") == "confirmacion_no_enviada" for x in eventos)


def test_ya_emparejado_no_muestra_codigo(tmp_path):
    s, almacen, aud, _ = _entorno(tmp_path)
    guardar_emparejamiento(s, Emparejamiento(42, 42))
    mostrado: list[str] = []
    with TelegramFalso() as tg:
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        with pytest.raises(ValueError, match="ya emparejado"):
            ejecutar_emparejamiento(cliente, almacen, s, mostrado.append, auditoria=aud,
                                    ahora=lambda: datetime.now(ZONA_COT))
        assert not tg.llamadas
    assert mostrado == []


def test_par_a_medias(tmp_path):
    s, almacen, aud, _ = _entorno(tmp_path)
    s.write_text(s.read_text() + "TELEGRAM_USER_ID=42\n")
    with TelegramFalso() as tg:
        cliente = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        with pytest.raises(ValueError, match="a medias"):
            ejecutar_emparejamiento(cliente, almacen, s, lambda _: None, auditoria=aud,
                                    ahora=lambda: datetime.now(ZONA_COT))
        assert not tg.llamadas


def test_guardar_par_en_una_escritura(tmp_path, monkeypatch):
    from trovefy_ejecutor import secretos as sec
    s, *_ = _entorno(tmp_path)
    llamadas = []
    orig = sec._guardar_bloqueado
    monkeypatch.setattr(sec, "_guardar_bloqueado", lambda *a: (llamadas.append(a), orig(*a))[1])
    guardar_emparejamiento(s, Emparejamiento(42, 42))
    assert len(llamadas) == 1
    assert set(llamadas[0][1]) == {"TELEGRAM_USER_ID", "TELEGRAM_CHAT_ID"}
