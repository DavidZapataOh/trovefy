import socket

import pytest
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from trovefy_ejecutor.telegram import (
    Boton,
    ClienteTelegram,
    ErrorRedTelegram,
    ErrorTelegram,
)


def test_enviar_editar_y_updates():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        mid = c.enviar(42, "hola *x*", [[Boton("Aceptar", "v1|P20261112004|A|abcdefghij")]], sonido=False)
        m = tg.mensajes[mid]
        assert m["texto"] == "hola *x*" and m["sonido"] is False
        assert "parse_mode" not in tg.llamadas[-1].params
        c.editar(42, mid, "EJECUTANDO…")
        assert tg.mensajes[mid]["botones"] == []
        c.editar(42, mid, "EJECUTANDO…")  # «not modified» no es error
        tg.meter_mensaje("/estado", user_id=42, chat_id=42)
        ups = c.obtener_updates(0, timeout_s=0)
        assert ups[0]["message"]["text"] == "/estado"
        assert c.obtener_updates(ups[0]["update_id"] + 1, timeout_s=0) == []


def test_responder_callback():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        cq = tg.meter_toque("v1|P20261112004|A|abcdefghij", user_id=42, chat_id=42, message_id=1)
        c.responder_callback(cq, "Recibido")
        assert tg.llamadas[-1].metodo == "answerCallbackQuery"


@pytest.mark.parametrize("base", ["http://api.telegram.org", "https://evil.example", "http://10.0.0.1:80"])
def test_base_no_permitida(base):
    with pytest.raises(ValueError):
        ClienteTelegram(TOKEN_PRUEBA, base)


def test_token_invalido_no_aparece_en_el_error():
    with pytest.raises(ValueError) as e:
        ClienteTelegram("123:corto", "https://api.telegram.org")
    assert "corto" not in str(e.value)


def test_validaciones_de_telegram():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        with pytest.raises(ErrorTelegram) as e:
            c.enviar(1, "x" * 4097)
        assert e.value.codigo == 400
        with pytest.raises(ErrorTelegram):
            c.enviar(1, "x", [[Boton("a", "d" * 65)]])
        with pytest.raises(ErrorTelegram):
            c.editar(1, 999, "x")


def test_token_erroneo_da_401_sin_token():
    with TelegramFalso() as tg:
        otro = "999999:" + "B" * 35
        c = ClienteTelegram(otro, tg.base)
        with pytest.raises(ErrorTelegram) as e:
            c.enviar(1, "x")
        assert e.value.codigo == 401
        assert otro not in str(e.value) and otro not in repr(e.value)


def test_429_expone_retry_after():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        tg.fallar("sendMessage", veces=1, codigo=429, retry_after=7)
        with pytest.raises(ErrorTelegram) as e:
            c.enviar(1, "x")
        assert e.value.codigo == 429 and e.value.retry_after == 7
        assert c.enviar(1, "x")


def test_corte_de_conexion_es_error_de_red_sin_token():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        tg.cortar("sendMessage")
        with pytest.raises(ErrorRedTelegram) as e:
            c.enviar(1, "x")
        assert TOKEN_PRUEBA not in e.value.motivo and TOKEN_PRUEBA not in str(e.value)
        assert len(tg.mensajes) == 1  # Telegram lo recibió pero no contestó


def test_base_inalcanzable_no_filtra_token():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    c = ClienteTelegram(TOKEN_PRUEBA, f"http://127.0.0.1:{puerto}")
    with pytest.raises(ErrorRedTelegram) as e:
        c.enviar(1, "x")
    assert TOKEN_PRUEBA not in str(e.value) and TOKEN_PRUEBA not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_repr_del_cliente_sin_token():
    c = ClienteTelegram(TOKEN_PRUEBA, "https://api.telegram.org")
    assert TOKEN_PRUEBA not in repr(c) and "AAAA" not in repr(c)
