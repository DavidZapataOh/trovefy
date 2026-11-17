import io
import json
import urllib.error

import pytest
from trovefy.apimart.http import (
    BASE_POR_DEFECTO,
    ClaveRechazada,
    Credenciales,
    ErrorServidor,
    Limitado,
    RespuestaInesperada,
    SinClave,
    SinRed,
    SinSaldo,
    leer_credenciales,
    pedir_json,
)

from .ayudas import CLAVE, escribir_env


def test_credenciales_no_muestran_la_clave(tmp_path):
    c = leer_credenciales(escribir_env(tmp_path, "APIMART_API_KEY=sk-prueba-123"))
    assert "sk-prueba" not in repr(c) and "sk-prueba" not in str(c)
    assert c.base == "https://api.apimart.ai" == BASE_POR_DEFECTO
    assert repr(c) == "Credenciales(base='https://api.apimart.ai', clave=***)"


def test_base_propia_https(tmp_path):
    c = leer_credenciales(escribir_env(tmp_path, f"APIMART_API_KEY={CLAVE}\nAPIMART_BASE_URL=https://otra.example/"))
    assert c.base == "https://otra.example"


def test_base_http_rechazada(tmp_path):
    with pytest.raises(SinClave) as e:
        leer_credenciales(escribir_env(tmp_path, f"APIMART_API_KEY={CLAVE}\nAPIMART_BASE_URL=http://evil"))
    assert "https" in e.value.motivo and CLAVE not in str(e.value)


def test_env_ausente(tmp_path):
    with pytest.raises(SinClave) as e:
        leer_credenciales(tmp_path / "no.env")
    assert "no existe" in e.value.motivo and e.value.arreglos


def test_env_no_0600(tmp_path):
    with pytest.raises(SinClave) as e:
        leer_credenciales(escribir_env(tmp_path, f"APIMART_API_KEY={CLAVE}", 0o644))
    assert "600" in e.value.motivo and "chmod 600" in e.value.arreglos[0]
    assert CLAVE not in str(e.value)


def test_sin_clave_en_env(tmp_path):
    with pytest.raises(SinClave) as e:
        leer_credenciales(escribir_env(tmp_path, "OTRA=1"))
    assert "APIMART_API_KEY" in e.value.motivo


def test_clave_con_caracteres_raros(tmp_path):
    with pytest.raises(SinClave) as e:
        leer_credenciales(escribir_env(tmp_path, "APIMART_API_KEY=sk-ñ-raro"))
    assert "raros" in e.value.motivo


def _cred():
    return Credenciales("https://api.apimart.ai", CLAVE)


@pytest.mark.parametrize(
    "codigo,cuerpo,error",
    [
        (401, {"error": {"code": 401, "message": CLAVE, "type": "authentication_error"}}, ClaveRechazada),
        (403, {"error": {"code": 403, "type": "permission_error"}}, ClaveRechazada),
        (402, {"error": {"code": 402, "type": "payment_required"}}, SinSaldo),
        (400, {"error": {"code": 400, "type": "payment_required"}}, SinSaldo),
        (429, {"error": {"code": 429, "type": "rate_limit_error"}}, Limitado),
        (503, {"error": {"code": 503, "type": "service_unavailable"}}, ErrorServidor),
        (500, b"<html>roto</html>", ErrorServidor),
        (400, {"error": {"code": 400, "message": f"size raro {CLAVE}", "type": "invalid_request_error"}},
         RespuestaInesperada),
    ],
)
def test_errores_mapeados(respuesta_json, codigo, cuerpo, error):
    abrir = respuesta_json(codigo, cuerpo)
    with pytest.raises(error) as e:
        pedir_json(_cred(), "POST", "/v1/images/generations", {"model": "x"}, abrir=abrir)
    assert CLAVE not in str(e.value) and "Bearer" not in str(e.value)


def test_payment_required_con_200(respuesta_json):
    abrir = respuesta_json(200, {"error": {"code": 402, "type": "payment_required"}})
    with pytest.raises(SinSaldo):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=abrir)


def test_json_roto(respuesta_json):
    with pytest.raises(RespuestaInesperada):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=respuesta_json(200, b"{roto"))


def test_respuesta_de_mas_de_1_mb(respuesta_json):
    grande = json.dumps({"x": "a" * (1 << 20)}).encode()
    with pytest.raises(RespuestaInesperada):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=respuesta_json(200, grande))


@pytest.mark.parametrize("exc", [urllib.error.URLError("caída"), TimeoutError(), ConnectionResetError()])
def test_sin_red(exc):
    def abrir(req, timeout=None):
        raise exc

    with pytest.raises(SinRed):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=abrir)


def test_peticion_con_clave_y_json(respuesta_json):
    abrir = respuesta_json(200, {"ok": 1})
    assert pedir_json(_cred(), "POST", "/v1/images/generations", {"n": 1}, abrir=abrir, timeout=7) == {"ok": 1}
    req, timeout = abrir.peticiones[0]
    assert req.full_url == "https://api.apimart.ai/v1/images/generations" and req.get_method() == "POST"
    assert req.headers["Authorization"] == f"Bearer {CLAVE}" and timeout == 7
    assert json.loads(req.data) == {"n": 1}


def test_sin_credenciales_va_sin_clave(respuesta_json):
    abrir = respuesta_json(200, {"ok": 1})
    pedir_json(None, "GET", "/api/pricing/model?model=x", abrir=abrir, base="https://api.apimart.ai")
    assert "Authorization" not in abrir.peticiones[0][0].headers


def test_respuesta_que_no_es_mapa(respuesta_json):
    with pytest.raises(RespuestaInesperada):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=respuesta_json(200, [1, 2]))


def test_http_error_lee_cuerpo_acotado():
    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b"no json"))

    with pytest.raises(SinSaldo):
        pedir_json(_cred(), "GET", "/v1/tasks/x", abrir=abrir)
