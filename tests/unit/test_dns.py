import pytest
from trovify.dns import SinRed, consultar, normalizar


def r(tipo, data, nombre="kits-docentes.com."):
    return {"name": nombre, "type": tipo, "data": data}


def test_dominio_normalizado():
    for d in ["Kits-Docentes.com", "https://www.kits-docentes.com/", "kits-docentes.com.", "www.KITS-docentes.com/landing"]:
        assert normalizar(d) == "kits-docentes.com"


@pytest.mark.parametrize("malo", ["", "localhost", "192.168.1.1", "a b.com", "-x.com", "x..com", "user@x.com", "https://", "x.com:99999", "x_y.com", "x.c om", "x.com\n", "x\x00.com"])
def test_dominio_invalido(malo):
    with pytest.raises(ValueError):
        normalizar(malo)


def test_consulta_doh(respuesta_json):
    ns = {"Status": 0, "Answer": [r(2, "ada.ns.cloudflare.com."), r(2, "bob.ns.cloudflare.com.")]}
    abrir = respuesta_json(200, ns)
    assert consultar("kits-docentes.com", "NS", abrir=abrir) == ["ada.ns.cloudflare.com.", "bob.ns.cloudflare.com."]
    req, timeout = abrir.peticiones[0]
    assert req.full_url == "https://cloudflare-dns.com/dns-query?name=kits-docentes.com&type=NS"
    assert req.get_header("Accept") == "application/dns-json" and timeout == 10


def test_sin_respuesta_es_lista_vacia(respuesta_json):
    assert consultar("x.com", "TXT", abrir=respuesta_json(200, {"Status": 3})) == []
    assert consultar("x.com", "TXT", abrir=respuesta_json(200, {"Status": 0})) == []


def test_error_de_red(respuesta_json):
    with pytest.raises(SinRed):
        consultar("x.com", "NS", abrir=respuesta_json(503, {}))

    def roto(req, timeout=None):
        raise TimeoutError

    with pytest.raises(SinRed):
        consultar("x.com", "NS", abrir=roto)
    with pytest.raises(SinRed):
        consultar("x.com", "NS", abrir=respuesta_json(200, b"no json"))


def test_consulta_valida_entradas(respuesta_json):
    with pytest.raises(ValueError):
        consultar("x.com&y=1", "NS", abrir=respuesta_json(200, {}))
    with pytest.raises(ValueError):
        consultar("x.com", "MX", abrir=respuesta_json(200, {}))


def test_cadena_cname_no_cuenta(respuesta_json):
    cuerpo = {"Status": 0, "Answer": [
        r(5, "pepe.ns.cloudflare.com.", "kits-docentes.com."),
        r(2, "ns1.ajeno.com.", "otro.com."),
        r(16, "\"x\"", "kits-docentes.com."),
        r(2, "ada.ns.cloudflare.com.", "KITS-docentes.com."),
    ]}
    assert consultar("kits-docentes.com", "NS", abrir=respuesta_json(200, cuerpo)) == ["ada.ns.cloudflare.com."]


@pytest.mark.parametrize("status", [1, 2, 5, None, "0", True])
def test_status_no_medido(respuesta_json, status):
    cuerpo = {"Answer": [r(2, "ada.ns.cloudflare.com.")]}
    if status is not None:
        cuerpo["Status"] = status
    with pytest.raises(SinRed):
        consultar("kits-docentes.com", "NS", abrir=respuesta_json(200, cuerpo))


def test_excepciones_raras_son_sin_red(respuesta_json):
    import http.client

    def roto(req, timeout=None):
        raise http.client.IncompleteRead(b"")

    with pytest.raises(SinRed):
        consultar("x.com", "NS", abrir=roto)
    with pytest.raises(SinRed):
        consultar("x.com", "NS", abrir=respuesta_json(200, b"[" * 100000))
