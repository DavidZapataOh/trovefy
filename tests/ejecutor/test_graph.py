import json
import traceback
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest
from trovefy_ejecutor import dinero
from trovefy_ejecutor.graph import (
    OFFSETS_META,
    ClienteGraph,
    DetenidoPorStop,
    ErrorGraph,
    ErrorRed,
    InfoCuenta,
    clasificar,
)

TOKEN = "EAAtokenSecreto123"


class _R:
    status = 200

    def __init__(self, d):
        self.d = json.dumps(d).encode()

    def read(self, *_):
        return self.d

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_token_solo_en_cabecera(respuesta_json):
    abrir = respuesta_json(200, {"id": "1", "status": "ACTIVE"})
    ClienteGraph(TOKEN, abrir=abrir).leer("120", ["status"])
    req, timeout = abrir.peticiones[0]
    assert req.full_url == "https://graph.facebook.com/v25.0/120?fields=status"
    assert req.get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in req.full_url and "access_token" not in req.full_url and timeout == 20


def test_escribir_validate_only(respuesta_json):
    abrir = respuesta_json(200, {"success": True})
    ClienteGraph(TOKEN, abrir=abrir).escribir("120", {"daily_budget": 26000}, validate_only=True)
    req, timeout = abrir.peticiones[0]
    cuerpo = req.data.decode()
    assert req.get_method() == "POST" and "daily_budget=26000" in cuerpo
    assert "execution_options=%5B%22validate_only%22%5D" in cuerpo and TOKEN not in cuerpo and timeout == 30
    assert req.get_header("Content-type") == "application/x-www-form-urlencoded"


def test_escribir_sin_validate_only_y_json_anidado(respuesta_json):
    abrir = respuesta_json(200, {"success": True})
    ClienteGraph(TOKEN, abrir=abrir).escribir("120", {"targeting": {"a": [1]}, "status": "PAUSED"})
    cuerpo = parse_qs(abrir.peticiones[0][0].data.decode())
    assert "execution_options" not in cuerpo
    assert json.loads(cuerpo["targeting"][0]) == {"a": [1]} and cuerpo["status"] == ["PAUSED"]


def test_crear_url(respuesta_json):
    abrir = respuesta_json(200, {"id": "9"})
    r = ClienteGraph(TOKEN, abrir=abrir).crear("act_1", "campaigns", {"name": "x"}, validate_only=True)
    req, _ = abrir.peticiones[0]
    assert r == {"id": "9"} and req.full_url == "https://graph.facebook.com/v25.0/act_1/campaigns"
    assert "validate_only" in req.data.decode()


def test_error_meta_redactado(respuesta_json):
    abrir = respuesta_json(400, {"error": {"code": 190, "error_subcode": 463,
                                           "message": f"Token {TOKEN} expirado", "fbtrace_id": "x"}})
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=abrir).leer("120", ["status"])
    assert (e.value.codigo, e.value.subcodigo) == (190, 463)
    assert TOKEN not in str(e.value) and clasificar(e.value) == "token"


def test_error_sin_rastro_del_token(respuesta_json):
    abrir = respuesta_json(400, {"error": {"code": 100, "message": "malo EAAxyz123456789012345"}})
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=abrir).leer("120", ["status"])
    texto = "".join(traceback.format_exception(e.value)) + repr(e.value) + repr(ClienteGraph(TOKEN))
    assert TOKEN not in texto and "EAAxyz" not in texto
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_mensaje_truncado_y_str():
    e = ErrorGraph(100, None, "a" * 1000, "tr")
    assert len(e.mensaje) <= 300 and str(e) == f"Meta 100/-: {e.mensaje}"
    assert str(ErrorGraph(17, 2446079, "lim")) == "Meta 17/2446079: lim"


def test_http_sin_json(respuesta_json):
    abrir = respuesta_json(502, b"<html>bad gateway</html>")
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=abrir).leer("1", ["a"])
    assert (e.value.codigo, e.value.subcodigo, e.value.mensaje) == (502, None, "HTTP 502")


def test_200_con_error_es_error_graph(respuesta_json):
    abrir = respuesta_json(200, {"error": {"code": 200, "message": "permiso"}})
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=abrir).escribir("1", {"a": 1})
    assert clasificar(e.value) == "permiso"


def test_red_caida_es_error_red():
    def abrir(req, timeout=None):
        raise TimeoutError("timed out " + req.full_url)

    with pytest.raises(ErrorRed) as e:
        ClienteGraph(TOKEN, abrir=abrir).escribir("120", {"status": "PAUSED"})
    assert e.value.__cause__ is None and e.value.__context__ is None
    assert "graph.facebook.com" not in "".join(traceback.format_exception_only(e.value))
    assert TOKEN not in "".join(traceback.format_exception(e.value))


def test_urlerror_y_json_ilegible(respuesta_json):
    def abrir(req, timeout=None):
        raise urllib.error.URLError(f"fallo {req.full_url}")

    with pytest.raises(ErrorRed):
        ClienteGraph(TOKEN, abrir=abrir).leer("1", ["a"])
    with pytest.raises(ErrorRed):
        ClienteGraph(TOKEN, abrir=respuesta_json(200, b"no json")).leer("1", ["a"])


def test_respuesta_demasiado_grande(respuesta_json):
    with pytest.raises(ErrorRed):
        ClienteGraph(TOKEN, abrir=respuesta_json(200, b" " * (5 * 1024 * 1024 + 10))).leer("1", ["a"])


def test_cuenta_cop(respuesta_json):
    abrir = respuesta_json(200, {"currency": "COP", "timezone_name": "America/Bogota",
                                 "spend_cap": "1000000", "amount_spent": "250000", "account_status": 1,
                                 "id": "act_0000000000000000"})
    info = ClienteGraph(TOKEN, abrir=abrir).cuenta("act_0000000000000000")
    assert info == InfoCuenta("COP", 1, "America/Bogota", 1000000, 1, 250000)


def test_cuenta_sin_tope_ni_gastado(respuesta_json):
    abrir = respuesta_json(200, {"currency": "USD", "timezone_name": "UTC", "spend_cap": "0", "account_status": 1})
    info = ClienteGraph(TOKEN, abrir=abrir).cuenta("act_1")
    assert info.spend_cap is None and info.amount_spent is None and info.offset == 100
    fields = parse_qs(urlparse(abrir.peticiones[0][0].full_url).query)["fields"][0]
    assert fields == "currency,timezone_name,spend_cap,account_status,amount_spent"


def test_moneda_fuera_de_tabla(respuesta_json):
    abrir = respuesta_json(200, {"currency": "XXX", "timezone_name": "UTC", "account_status": 1})
    assert ClienteGraph(TOKEN, abrir=abrir).cuenta("act_1").offset is None
    assert OFFSETS_META["USD"] == 100 and OFFSETS_META["COP"] == 1


def test_tabla_offsets():
    for k, v in {"EUR": 100, "BGN": 100, "CLP": 1, "JPY": 1, "VND": 1, "KRW": 1}.items():
        assert OFFSETS_META[k] == v
    assert all(OFFSETS_META[k] == v for k, v in dinero.OFFSETS_OFICIALES.items())


def test_clasificar():
    assert clasificar(ErrorGraph(17, 2446079, "User request limit reached")) == "limite_meta"
    assert clasificar(ErrorGraph(100, None, "Invalid parameter")) == "otro"
    assert clasificar(ErrorGraph(102, None, "s")) == "token"
    assert clasificar(ErrorGraph(80004, None, "s")) == "limite_meta"
    assert clasificar(ErrorGraph(10, None, "s")) == "permiso"
    assert clasificar(ErrorGraph(299, None, "s")) == "permiso"
    assert clasificar(ErrorGraph(300, None, "s")) == "otro"


def test_solo_https():
    with pytest.raises(ValueError):
        ClienteGraph(TOKEN, base="http://graph.facebook.com")


def test_detenido_por_stop():
    assert issubclass(DetenidoPorStop, Exception)


def test_listar_pagina_con_cursor():
    paginas = [
        {"data": [{"id": "1"}], "paging": {"cursors": {"after": "CUR1"}, "next": "https://evil.example/x"}},
        {"data": [{"id": "2"}], "paging": {"cursors": {"after": "CUR2"}}},
    ]
    vistas = []

    def abrir(req, timeout=None):
        vistas.append(req.full_url)
        return _R(paginas[len(vistas) - 1])

    r = ClienteGraph(TOKEN, abrir=abrir).listar("act_1", "campaigns", ["id"], {"limit": 1})
    assert r == [{"id": "1"}, {"id": "2"}] and len(vistas) == 2
    assert "after" not in vistas[0] and "after=CUR1" in vistas[1]
    assert all(v.startswith("https://graph.facebook.com/v25.0/act_1/campaigns?") for v in vistas)


def test_listar_max_paginas_falla_cerrado():
    pagina = {"data": [{"id": "1"}], "paging": {"cursors": {"after": "C"}, "next": "x"}}
    with pytest.raises(ErrorRed, match="listado incompleto"):
        ClienteGraph(TOKEN, abrir=lambda req, timeout=None: _R(pagina)).listar("a", "b", ["id"], max_paginas=3)


def test_listar_next_sin_cursor_falla_cerrado():
    pagina = {"data": [{"id": "1"}], "paging": {"next": "x"}}
    with pytest.raises(ErrorRed, match="listado incompleto"):
        ClienteGraph(TOKEN, abrir=lambda req, timeout=None: _R(pagina)).listar("a", "b", ["id"])


def test_listar_envia_limit():
    vistas = []

    def abrir(req, timeout=None):
        vistas.append(req.full_url)
        return _R({"data": []})

    ClienteGraph(TOKEN, abrir=abrir).listar("a", "b", ["id"], limite=500)
    assert "limit=500" in vistas[0]


def test_subir_imagen(respuesta_json):
    abrir = respuesta_json(200, {"images": {"x.png": {"hash": "abc123"}}})
    h = ClienteGraph(TOKEN, abrir=abrir).subir_imagen("act_1", b"\x89PNG", "x.png")
    req, timeout = abrir.peticiones[0]
    assert h == "abc123" and req.full_url.endswith("/v25.0/act_1/adimages") and timeout == 120
    assert parse_qs(req.data.decode())["bytes"] == ["iVBORw=="]


def test_subir_video(respuesta_json, tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"datos")
    abrir = respuesta_json(200, {"id": "777"})
    assert ClienteGraph(TOKEN, abrir=abrir).subir_video("act_1", v) == "777"
    req, timeout = abrir.peticiones[0]
    assert req.full_url.endswith("/v25.0/act_1/advideos") and timeout == 120
    assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="source"' in req.data and b"datos" in req.data and TOKEN.encode() not in req.data


def test_subir_video_grande(respuesta_json, tmp_path):
    v = tmp_path / "v.mp4"
    with v.open("wb") as f:
        f.truncate(100 * 1024 * 1024 + 1)
    abrir = respuesta_json(200, {"id": "1"})
    with pytest.raises(ValueError, match="vídeo > 100 MB"):
        ClienteGraph(TOKEN, abrir=abrir).subir_video("act_1", v)
    assert not abrir.peticiones


def test_sin_redirecciones():
    from trovefy_ejecutor.graph import _SinRedireccion

    assert _SinRedireccion().redirect_request(None, None, 302, "", {}, "https://x") is None
