import traceback

import pytest
from trovefy_ejecutor.graph import ClienteGraph, ErrorGraph, ErrorRed

TOKEN = "EAAtokenSecreto123"


@pytest.mark.parametrize("cuerpo", [{"error": "x"}, {"error": {"code": "abc"}}, {"error": {}}, {"error": None}])
def test_200_con_error_malformado_es_error_red(respuesta_json, cuerpo):
    with pytest.raises(ErrorRed) as e:
        ClienteGraph(TOKEN, abrir=respuesta_json(200, cuerpo)).escribir("1", {"a": 1})
    assert e.value.motivo == "respuesta ilegible"


@pytest.mark.parametrize("cuerpo", [{"error": "x"}, {"error": {"code": "abc"}}, [1, 2], {"otro": 1}])
def test_http_con_error_malformado_es_http_n(respuesta_json, cuerpo):
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=respuesta_json(400, cuerpo)).leer("1", ["a"])
    assert (e.value.codigo, e.value.subcodigo, e.value.mensaje) == (400, None, "HTTP 400")


def test_lista_en_200_es_error_red(respuesta_json):
    with pytest.raises(ErrorRed):
        ClienteGraph(TOKEN, abrir=respuesta_json(200, [1])).leer("1", ["a"])


def test_fbtrace_id_limpio_y_acotado(respuesta_json):
    cuerpo = {"error": {"code": 100, "message": "m", "fbtrace_id": TOKEN + "z" * 200}}
    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=respuesta_json(400, cuerpo)).leer("1", ["a"])
    assert TOKEN not in e.value.fbtrace_id and len(e.value.fbtrace_id) <= 64
    assert TOKEN not in "".join(traceback.format_exception(e.value))


def test_fbtrace_id_redactado_en_constructor():
    assert "EAAxyz123456789012345" not in ErrorGraph(1, None, "m", "EAAxyz123456789012345" + "q" * 100).fbtrace_id
    assert len(ErrorGraph(1, None, "m", "x" * 500).fbtrace_id) == 64


def test_none_no_se_envia(respuesta_json):
    abrir = respuesta_json(200, {"success": True})
    c = ClienteGraph(TOKEN, abrir=abrir)
    with pytest.raises(ValueError):
        c.escribir("1", {"a": None})
    with pytest.raises(ValueError):
        c.crear("act_1", "ads", {"a": None})
    with pytest.raises(ValueError):
        c.listar("act_1", "ads", ["id"], {"f": None})
    assert not abrir.peticiones


@pytest.mark.parametrize("malo", ["123?x", "a/b", "../me", "", "a b", "x#y"])
def test_segmentos_validados(respuesta_json, malo):
    abrir = respuesta_json(200, {"id": "1"})
    c = ClienteGraph(TOKEN, abrir=abrir)
    with pytest.raises(ValueError):
        c.leer(malo, ["id"])
    with pytest.raises(ValueError):
        c.escribir(malo, {"a": 1})
    with pytest.raises(ValueError):
        c.crear(malo, "ads", {"a": 1})
    with pytest.raises(ValueError):
        c.crear("act_1", malo, {"a": 1})
    with pytest.raises(ValueError):
        c.listar("act_1", malo, ["id"])
    with pytest.raises(ValueError):
        c.subir_imagen(malo, b"x", "n.png")
    assert not abrir.peticiones


def test_segmentos_validos(respuesta_json):
    abrir = respuesta_json(200, {"id": "1"})
    c = ClienteGraph(TOKEN, abrir=abrir)
    c.leer("act_0000000000000000", ["id"])
    c.leer("120938", ["id"])
    c.crear("act_1", "ad_creatives", {"a": 1})
    assert len(abrir.peticiones) == 3


def test_httperror_se_cierra():
    import io
    import urllib.error

    cerrado = []

    class Cuerpo(io.BytesIO):
        def close(self):
            cerrado.append(1)
            super().close()

    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, Cuerpo(b"{}"))

    with pytest.raises(ErrorGraph):
        ClienteGraph(TOKEN, abrir=abrir).leer("1", ["a"])
    assert cerrado


def test_valueerror_del_transporte_no_es_conexion():
    def abrir(req, timeout=None):
        raise ValueError("bug local")

    with pytest.raises(ValueError):
        ClienteGraph(TOKEN, abrir=abrir).leer("1", ["a"])


@pytest.mark.parametrize("metodo", ["escribir", "crear"])
@pytest.mark.parametrize("fallo", ["5xx", "red"])
def test_escritura_sin_reintento(respuesta_json, metodo, fallo):
    n = []
    if fallo == "5xx":
        base = respuesta_json(503, {"error": {"code": 2, "message": "x"}})
        excepcion = ErrorGraph
    else:
        def base(req, timeout=None):
            raise TimeoutError("t")

        excepcion = ErrorRed

    def abrir(req, timeout=None):
        n.append(1)
        return base(req, timeout=timeout)

    c = ClienteGraph(TOKEN, abrir=abrir)
    with pytest.raises(excepcion):
        if metodo == "escribir":
            c.escribir("1", {"status": "PAUSED"})
        else:
            c.crear("act_1", "campaigns", {"name": "x"})
    assert len(n) == 1


def test_httperror_con_cuerpo_cortado_no_escapa_sin_envolver():
    import http.client
    import io
    import urllib.error

    cerrado = []

    class Cortado(io.BytesIO):
        def read(self, *a):
            raise http.client.IncompleteRead(b"{\"error\": " + TOKEN.encode(), 100)

        def close(self):
            cerrado.append(1)
            super().close()

    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, Cortado())

    with pytest.raises(ErrorGraph) as e:
        ClienteGraph(TOKEN, abrir=abrir).escribir("1", {"a": 1})
    assert (e.value.codigo, e.value.mensaje) == (500, "HTTP 500") and cerrado
    assert e.value.__cause__ is None and e.value.__suppress_context__
    assert TOKEN not in "".join(traceback.format_exception(e.value))
