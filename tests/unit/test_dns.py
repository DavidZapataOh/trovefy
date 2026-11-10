import pytest
from trovify.dns import SinRed, consultar, normalizar


def test_dominio_normalizado():
    for d in ["Kits-Docentes.com", "https://www.kits-docentes.com/", "kits-docentes.com.", "www.KITS-docentes.com/landing"]:
        assert normalizar(d) == "kits-docentes.com"


@pytest.mark.parametrize("malo", ["", "localhost", "192.168.1.1", "a b.com", "-x.com", "x..com", "user@x.com", "https://", "x.com:99999", "x_y.com", "x.c om"])
def test_dominio_invalido(malo):
    with pytest.raises(ValueError):
        normalizar(malo)


def test_consulta_doh(respuesta_json):
    ns = {"Answer": [{"data": "ada.ns.cloudflare.com."}, {"data": "bob.ns.cloudflare.com."}]}
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
