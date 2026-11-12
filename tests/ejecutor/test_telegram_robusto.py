import io
import traceback
import urllib.error

import pytest
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from trovefy_ejecutor.telegram import (
    ClienteTelegram,
    ErrorRedTelegram,
    ErrorTelegram,
    largo_telegram,
)


class Reloj:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def ahora(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(s)
        self.t += s


def cliente(tg, r):
    return ClienteTelegram(TOKEN_PRUEBA, tg.base, dormir=r.dormir, reloj=r.ahora)


def _cadena(exc):
    visto = []
    while exc is not None and exc not in visto:
        visto.append(exc)
        yield exc
        exc = exc.__cause__ or exc.__context__


def _texto_total(exc):
    partes = ["".join(traceback.format_exception(exc))]
    for e in _cadena(exc):
        partes += [str(e), repr(e)]
    return "".join(partes)


def test_429_respeta_retry_after():
    with TelegramFalso() as tg:
        r = Reloj()
        tg.fallar("sendMessage", veces=2, codigo=429, retry_after=7)
        cliente(tg, r).enviar(42, "x")
        assert r.esperas[:2] == [7, 7] and len(tg.mensajes) == 1


def test_429_se_agota_a_los_tres_intentos():
    with TelegramFalso() as tg:
        r = Reloj()
        tg.fallar("sendMessage", veces=5, codigo=429, retry_after=2)
        with pytest.raises(ErrorTelegram) as e:
            cliente(tg, r).enviar(42, "x")
        assert e.value.codigo == 429 and e.value.retry_after == 2
        assert [x.metodo for x in tg.llamadas].count("sendMessage") == 3


def test_429_con_espera_absurda_se_rinde():
    with TelegramFalso() as tg:
        r = Reloj()
        tg.fallar("sendMessage", veces=1, codigo=429, retry_after=3600)
        with pytest.raises(ErrorTelegram) as e:
            cliente(tg, r).enviar(42, "x")
        assert e.value.retry_after == 3600 and tg.mensajes == {}


def test_429_en_updates_reintenta_y_en_callback_no():
    with TelegramFalso() as tg:
        r = Reloj()
        c = cliente(tg, r)
        tg.fallar("getUpdates", veces=1, codigo=429, retry_after=3)
        assert c.obtener_updates(0, timeout_s=0) == []
        assert r.esperas == [3]
        tg.fallar("answerCallbackQuery", veces=1, codigo=429, retry_after=3)
        with pytest.raises(ErrorTelegram):
            c.responder_callback("1")
        assert [x.metodo for x in tg.llamadas].count("answerCallbackQuery") == 1


def test_un_mensaje_por_segundo_por_chat():
    with TelegramFalso() as tg:
        r = Reloj()
        c = cliente(tg, r)
        c.enviar(42, "a")
        c.enviar(42, "b")
        c.enviar(7, "c")
        assert sum(r.esperas) == pytest.approx(1.0)


def test_red_caida_no_reintenta():
    with TelegramFalso() as tg:
        tg.cortar("sendMessage")
        with pytest.raises(ErrorRedTelegram):
            cliente(tg, Reloj()).enviar(42, "x")
        assert [x.metodo for x in tg.llamadas].count("sendMessage") == 1


def test_token_nunca_en_errores():
    with TelegramFalso(token="999:" + "B" * 35) as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base)
        with pytest.raises(ErrorTelegram) as e:
            c.enviar(42, "x")
        todo = _texto_total(e.value)
        assert TOKEN_PRUEBA not in todo and "bot123456" not in todo and e.value.codigo == 401


class _CuerpoRoto(io.BytesIO):
    def read(self, *a):
        raise ConnectionResetError("corte leyendo el cuerpo")


@pytest.mark.parametrize("fallo", [ConnectionResetError, __import__("http.client").client.IncompleteRead])
def test_fallo_leyendo_cuerpo_de_error_no_arrastra_la_url(fallo):
    class Cuerpo(io.BytesIO):
        def read(self, *a):
            raise fallo(b"") if fallo.__name__ == "IncompleteRead" else fallo("corte")

    def abrir(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, Cuerpo())

    c = ClienteTelegram(TOKEN_PRUEBA, "http://127.0.0.1:9", abrir=abrir)
    with pytest.raises(ErrorRedTelegram) as e:
        c.enviar(42, "x")
    for x in _cadena(e.value):
        assert not isinstance(x, urllib.error.HTTPError)
    todo = _texto_total(e.value)
    assert TOKEN_PRUEBA not in todo and "bot123456" not in todo


def test_error_de_red_sin_contexto_con_url():
    def abrir(req, timeout):
        raise urllib.error.URLError("fallo " + req.full_url)

    c = ClienteTelegram(TOKEN_PRUEBA, "http://127.0.0.1:9", abrir=abrir)
    with pytest.raises(ErrorRedTelegram) as e:
        c.enviar(42, "x")
    assert e.value.__context__ is None
    assert TOKEN_PRUEBA not in _texto_total(e.value)


def test_rechaza_texto_largo():
    with TelegramFalso() as tg:
        c = cliente(tg, Reloj())
        with pytest.raises(ValueError):
            c.enviar(42, "😀" * 2049)
        with pytest.raises(ValueError):
            c.editar(42, 1, "😀" * 2049)
        assert tg.llamadas == []
        c.enviar(42, "😀" * 2048)


def test_largo_telegram_cuenta_utf16():
    assert largo_telegram("a😀") == 3


def test_base_con_digitos_unicode_rechazada():
    with pytest.raises(ValueError):
        ClienteTelegram(TOKEN_PRUEBA, "http://127.0.0.1:٨٠")
