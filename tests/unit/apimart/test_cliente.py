import http.client
import io
import traceback
import urllib.error
from decimal import Decimal

import pytest
from trovefy.apimart.cliente import (
    MAX_REFERENCIAS,
    PROPORCIONES,
    PROPORCIONES_4K,
    PeticionImagen,
    PeticionInvalida,
    cuerpo_envio,
    descargar,
    enviar,
    esperar,
    formato_imagen,
    validar,
)
from trovefy.apimart.http import (
    ClaveRechazada,
    Credenciales,
    RespuestaInesperada,
    SinRed,
    SinSaldo,
)

from .ayudas import CLAVE, fixture

CRED = Credenciales("https://api.apimart.ai", CLAVE)
PNG = fixture("png-1x1.png")


class _Resp:
    def __init__(self, codigo, cuerpo):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def secuencia(*respuestas):
    """`abrir` que devuelve las respuestas en orden (dict → JSON 200; excepción → se lanza)."""
    import json

    pendientes = list(respuestas)
    peticiones = []

    def abrir(req, timeout=None):
        peticiones.append(req)
        r = pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]
        if isinstance(r, BaseException):
            raise r
        return _Resp(200, json.dumps(r).encode())

    abrir.peticiones = peticiones
    return abrir


def pet(**k):
    base = {"id": "portada", "pieza": "principal", "prompt": "una portada limpia", "proporcion": "2:3",
            "resolucion": "1k"}
    return PeticionImagen(**{**base, **k})


def test_proporciones_de_la_documentacion():
    assert len(PROPORCIONES) == 15 and "1:1" in PROPORCIONES and "9:21" in PROPORCIONES
    assert set(PROPORCIONES_4K) == set(PROPORCIONES) and MAX_REFERENCIAS == 15


def test_cuerpo_n_entero_y_sin_refs():
    cuerpo = cuerpo_envio(pet(), "gpt-image-2", [])
    assert cuerpo["n"] == 1 and type(cuerpo["n"]) is int and "image_urls" not in cuerpo
    assert cuerpo == {"model": "gpt-image-2", "prompt": "una portada limpia", "n": 1, "size": "2:3",
                      "resolution": "1k"}


def test_cuerpo_con_refs():
    cuerpo = cuerpo_envio(pet(referencias=("logo",)), "gpt-image-2", ["https://cdn.example/a.png"])
    assert cuerpo["image_urls"] == ["https://cdn.example/a.png"]


@pytest.mark.parametrize("proporcion", ["3:5", "auto", "1881x836"])
def test_4k_en_proporcion_no_admitida(proporcion):
    with pytest.raises(PeticionInvalida):
        validar(pet(proporcion=proporcion, resolucion="4k"), {})


@pytest.mark.parametrize("proporcion", PROPORCIONES)
def test_4k_en_las_15(proporcion):
    validar(pet(proporcion=proporcion, resolucion="4k"), {})


@pytest.mark.parametrize(
    "cambio",
    [{"resolucion": "8k"}, {"prompt": ""}, {"prompt": "   "}, {"prompt": "x" * 4001}, {"id": "Mal_Id"},
     {"id": "x" * 41}, {"pieza": "otra"}, {"pieza": "landing-zz"}, {"proporcion": "7:7"}],
)
def test_peticion_invalida(cambio):
    with pytest.raises(PeticionInvalida):
        validar(pet(**cambio), {})


def test_referencia_ajena_rechazada():
    manifiesto = {"logo": {"origen": "propio"}, "rara": {"origen": "competidor"}}
    validar(pet(referencias=("logo",)), manifiesto)
    with pytest.raises(PeticionInvalida):
        validar(pet(referencias=("foto-del-competidor",)), manifiesto)
    with pytest.raises(PeticionInvalida):
        validar(pet(referencias=("rara",)), manifiesto)


def test_demasiadas_referencias():
    manifiesto = {f"r{i}": {"origen": "propio"} for i in range(16)}
    validar(pet(referencias=tuple(f"r{i}" for i in range(15))), manifiesto)
    with pytest.raises(PeticionInvalida):
        validar(pet(referencias=tuple(manifiesto)), manifiesto)


def test_enviar_devuelve_task_id(respuesta_json):
    abrir = respuesta_json(200, fixture("generacion-enviada.json"))
    assert enviar(CRED, cuerpo_envio(pet(), "gpt-image-2", []), abrir) == "task_01KPQ7J7DWB7QZ3WCEK3YVPBRA"
    req = abrir.peticiones[0][0]
    assert req.full_url == "https://api.apimart.ai/v1/images/generations" and req.get_method() == "POST"


@pytest.mark.parametrize("cuerpo", [{"code": 200, "data": []}, {"data": [{"status": "submitted"}]}, {},
                                    {"data": [{"task_id": "../../x"}]}])
def test_enviar_sin_task_id(respuesta_json, cuerpo):
    with pytest.raises(RespuestaInesperada):
        enviar(CRED, {"model": "x"}, respuesta_json(200, cuerpo))


def test_enviar_sin_saldo(respuesta_json):
    with pytest.raises(SinSaldo):
        enviar(CRED, {"model": "x"}, respuesta_json(402, {"error": {"type": "payment_required"}}))


def test_backoff_5_6_72_hasta_15():
    esperas = []
    abrir = secuencia(*[fixture("tarea-en-proceso.json")] * 9, fixture("tarea-completada.json"))
    e = esperar(CRED, "task_01KA040M0HP1GJWBJYZMKX1XS1", abrir, dormir=esperas.append, reloj=lambda: 0)
    assert esperas == [5, 6, 7.2, 8.64, 10.368, 12.4416, 14.92992, 15, 15]
    assert len(abrir.peticiones) == 10
    assert abrir.peticiones[0].full_url == "https://api.apimart.ai/v1/tasks/task_01KA040M0HP1GJWBJYZMKX1XS1"
    assert abrir.peticiones[0].headers["Authorization"] == f"Bearer {CLAVE}"
    assert e.estado == "completada" and e.url.startswith("https://upload.apimart.ai/f/image/")
    assert e.coste_real_usd == Decimal("0.15") and e.motivo is None


def test_coste_en_creditos_si_no_hay_usd():
    datos = fixture("tarea-completada.json")
    del datos["data"]["cost"]
    e = esperar(CRED, "t-1", secuencia(datos), dormir=lambda s: None, reloj=lambda: 0)
    assert e.coste_real_usd == Decimal("0.15")


def test_sin_coste_es_none():
    datos = fixture("tarea-completada.json")
    del datos["data"]["cost"], datos["data"]["credits_cost"]
    assert esperar(CRED, "t-1", secuencia(datos), dormir=lambda s: None, reloj=lambda: 0).coste_real_usd is None


def test_sondeo_agotado_queda_pendiente():
    t = iter(range(0, 10_000, 100))
    e = esperar(CRED, "t-1", secuencia(fixture("tarea-en-proceso.json")), dormir=lambda s: None,
                reloj=lambda: next(t))
    assert e.estado == "pendiente" and e.task_id == "t-1" and e.url is None
    assert e.motivo == "sin resultado en 600 s; se reanuda con --reanudar"


@pytest.mark.parametrize("exc", [urllib.error.URLError("caída"), TimeoutError()])
def test_red_caida_al_sondear_es_pendiente(exc):
    e = esperar(CRED, "t-1", secuencia(exc), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "pendiente" and "reanudar" in e.motivo


def test_red_caida_un_momento_se_recupera():
    abrir = secuencia(TimeoutError(), fixture("tarea-completada.json"))
    assert esperar(CRED, "t-1", abrir, dormir=lambda s: None, reloj=lambda: 0).estado == "completada"


def test_servidor_caido_al_sondear_es_pendiente(respuesta_json):
    e = esperar(CRED, "t-1", respuesta_json(503, {}), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "pendiente"


def test_clave_rechazada_al_sondear_es_pendiente(respuesta_json):
    e = esperar(CRED, "t-1", respuesta_json(401, {}), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "pendiente" and CLAVE not in e.motivo


def test_fallida_con_motivo():
    e = esperar(CRED, "t-1", secuencia(fixture("tarea-fallida.json")), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "fallida" and "content policy violation" in e.motivo and e.url is None


def test_completada_sin_url_es_fallida():
    datos = fixture("tarea-completada.json")
    datos["data"]["result"] = {"images": []}
    e = esperar(CRED, "t-1", secuencia(datos), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "fallida" and e.coste_real_usd == Decimal("0.15")


def test_task_id_mal_escrito():
    with pytest.raises(ValueError):
        esperar(CRED, "../balance", secuencia({}), dormir=lambda s: None, reloj=lambda: 0)


def test_descarga_sin_cabecera_authorization(respuesta_json):
    abrir = respuesta_json(200, PNG)
    assert descargar("https://upload.apimart.ai/f/image/x.png", abrir) == PNG
    req = abrir.peticiones[0][0]
    assert "Authorization" not in req.headers and req.get_header("Authorization") is None
    assert formato_imagen(PNG) == "png"


def test_descarga_no_imagen(respuesta_json):
    with pytest.raises(RespuestaInesperada):
        descargar("https://upload.apimart.ai/x.png", respuesta_json(200, b"<html>no</html>"))


def test_descarga_http_rechazada(respuesta_json):
    abrir = respuesta_json(200, PNG)
    for url in ("http://upload.apimart.ai/x.png", "file:///etc/passwd", "ftp://x/y.png", "https:///x"):
        with pytest.raises(RespuestaInesperada):
            descargar(url, abrir)
    assert abrir.peticiones == []


def test_descarga_demasiado_grande(respuesta_json):
    with pytest.raises(RespuestaInesperada):
        descargar("https://upload.apimart.ai/x.png", respuesta_json(200, PNG), max_bytes=10)


def test_descarga_sin_red():
    def abrir(req, timeout=None):
        raise urllib.error.URLError("caída")

    with pytest.raises(SinRed):
        descargar("https://upload.apimart.ai/x.png", abrir)


def test_descarga_404_es_inesperada():
    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b""))

    with pytest.raises(RespuestaInesperada):
        descargar("https://upload.apimart.ai/x.png", abrir)


def test_clave_rechazada_existe():
    assert issubclass(ClaveRechazada, Exception)


# --- ronda de revisión de las Tareas 2–5 ------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://127.0.0.1/x.png", "https://[::1]/x.png", "https://10.0.0.8/x.png", "https://169.254.169.254/x.png",
    "https://192.168.1.10/x.png", "https://localhost/x.png", "https://algo.localhost/x.png",
    "https://intranet/x.png", "https://2130706433/x.png", "https://0x7f.0.0.1/x.png", "https://servidor.local/x.png",
])
def test_descarga_rechaza_hosts_no_publicos(respuesta_json, url):
    abrir = respuesta_json(200, PNG)
    with pytest.raises(RespuestaInesperada):
        descargar(url, abrir)
    assert abrir.peticiones == []


def test_url_de_resultado_con_ip_es_fallida():
    datos = fixture("tarea-completada.json")
    datos["data"]["result"]["images"][0]["url"] = ["https://127.0.0.1/x.png"]
    e = esperar(CRED, "t-1", secuencia(datos), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "fallida" and e.url is None


def test_url_de_resultado_publica_vale():
    datos = fixture("tarea-completada.json")
    e = esperar(CRED, "t-1", secuencia(datos), dormir=lambda s: None, reloj=lambda: 0)
    assert e.estado == "completada" and e.url.startswith("https://upload.apimart.ai/")


@pytest.mark.parametrize("exc", [http.client.BadStatusLine(CLAVE), http.client.IncompleteRead(CLAVE.encode())])
def test_descarga_http_exception_es_sin_red(exc):
    def abrir(req, timeout=None):
        raise exc

    with pytest.raises(SinRed) as info:
        descargar("https://upload.apimart.ai/x.png", abrir)
    assert CLAVE not in "".join(traceback.format_exception(info.value))
