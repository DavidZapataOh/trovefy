import http.server
import json
import os
import threading
import urllib.error

import pytest
from trovify.arranque.verificadores import REGISTRO
from trovify.arranque.verificadores.apimart import consultar_saldo, verificar_apimart
from trovify.secretos import PermisosInseguros, leer_env

CLAVE = "sk-" + "x" * 30
EXACTO = "en una terminal de Ubuntu (WSL) aparte: `mkdir -p ~/.config/trovify` y luego `install -m 600 /dev/null ~/.config/trovify/claude.env`"


def env(tmp_path, modo=0o600, extra=""):
    f = tmp_path / "claude.env"
    f.write_text(f"# comentario\nAPIMART_API_KEY={CLAVE}\nAPIMART_BASE_URL=http://127.0.0.1:9\n{extra}")
    os.chmod(f, modo)
    return f


def todo(r, vault):
    ev = "".join((vault / e).read_text() for e in r.evidencia if (vault / e).is_file())
    return " | ".join([r.motivo, *r.evidencia, *r.arreglos, *r.lineas, json.dumps(r.datos), ev])


SALDO = {"success": True, "remain_balance": 10.5, "remain_credits": 105, "used_balance": 2.3, "used_credits": 23, "unlimited_quota": False}


def test_leer_env_parsea_y_quita_comillas(tmp_path):
    f = tmp_path / "a.env"
    f.write_text('\n# c\nA="uno"\nB=\'dos\'\nC=tres=cuatro\n')
    os.chmod(f, 0o600)
    assert leer_env(f) == {"A": "uno", "B": "dos", "C": "tres=cuatro"}


def test_leer_env_permisos_abiertos(tmp_path):
    with pytest.raises(PermisosInseguros) as e:
        leer_env(env(tmp_path, 0o644))
    assert CLAVE not in str(e.value) and "644" in str(e.value)


def test_env_con_permisos_abiertos_falla(tmp_path):
    r = verificar_apimart(tmp_path, env(tmp_path, 0o644), abrir=lambda *a, **k: 1 / 0)
    assert r.ok is False and "chmod 600" in r.arreglos[0]
    assert CLAVE not in todo(r, tmp_path)


def test_env_inexistente_explica_como_crearlo(tmp_path):
    r = verificar_apimart(tmp_path, tmp_path / "no.env", abrir=lambda *a, **k: 1 / 0)
    assert r.ok is False and r.arreglos[0] == EXACTO


def test_sin_clave_en_env(tmp_path):
    f = tmp_path / "c.env"
    f.write_text("OTRA=1\n")
    os.chmod(f, 0o600)
    r = verificar_apimart(tmp_path, f, abrir=lambda *a, **k: 1 / 0)
    assert r.ok is False and "APIMART_API_KEY" in r.motivo


def test_sin_red_no_medido(tmp_path):
    def sin_red(*a, **k):
        raise urllib.error.URLError("sin red")

    r = verificar_apimart(tmp_path, env(tmp_path), abrir=sin_red)
    assert r.ok is None and r.motivo.startswith("no medido: sin red")


def test_timeout_no_medido(tmp_path):
    def lento(*a, **k):
        raise TimeoutError

    assert verificar_apimart(tmp_path, env(tmp_path), abrir=lento).ok is None


def test_clave_rechazada(tmp_path, respuesta_json):
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(401, {"success": False, "message": CLAVE}))
    assert r.ok is False and "clave rechazada" in r.motivo
    assert CLAVE not in todo(r, tmp_path)


def test_respuesta_inesperada(tmp_path, respuesta_json):
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(200, {"hola": 1}))
    assert r.ok is None and r.motivo == "no medido: respuesta inesperada"


def test_json_invalido_inesperado(tmp_path, respuesta_json):
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(200, b"<html>"))
    assert r.ok is None and r.motivo == "no medido: respuesta inesperada"


def test_saldo_ok(tmp_path, respuesta_json):
    abrir = respuesta_json(200, SALDO)
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=abrir)
    assert r.ok is True and r.evidencia
    datos = json.loads((tmp_path / r.evidencia[0]).read_text())
    assert datos["saldo"] == 10.5 and datos["moneda"] == "USD (inferida)" and datos["fecha"] and datos["creditos"] == 105
    assert set(datos) == {"saldo", "creditos", "moneda", "fecha"}
    assert "inferida" in r.motivo and r.datos["moneda"] == "USD (inferida)"
    req, timeout = abrir.peticiones[0]
    assert timeout == 15 and req.full_url == "http://127.0.0.1:9/v1/balance"
    assert req.get_header("Authorization") == f"Bearer {CLAVE}" and CLAVE not in req.full_url
    assert CLAVE not in todo(r, tmp_path)


def test_cuota_ilimitada_es_ok_sin_saldo_numerico(tmp_path, respuesta_json):
    cuerpo = {**SALDO, "unlimited_quota": True}
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(200, cuerpo))
    assert r.ok is True and "USD" not in r.motivo
    assert json.loads((tmp_path / r.evidencia[0]).read_text())["moneda"] is None


def test_consultar_saldo_devuelve_dict(respuesta_json):
    assert consultar_saldo("http://127.0.0.1:9", CLAVE, abrir=respuesta_json(200, SALDO))["saldo"] == 10.5


def test_registrado_como_16():
    assert REGISTRO["16"] is verificar_apimart


def test_success_false_con_200(tmp_path, respuesta_json):
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(200, {"success": False, "message": "x"}))
    assert r.ok is None and r.motivo == "no medido: respuesta inesperada"


def test_3xx_es_inesperada(tmp_path, respuesta_json):
    r = verificar_apimart(tmp_path, env(tmp_path), abrir=respuesta_json(302, {}))
    assert r.ok is None and r.motivo == "no medido: respuesta inesperada"


@pytest.mark.parametrize("base", ["http://example.com", "file:///etc/passwd", "ftp://example.com", "https://", "nada"])
def test_base_no_https_rechazada(tmp_path, respuesta_json, base):
    f = tmp_path / "c.env"
    f.write_text(f"APIMART_API_KEY={CLAVE}\nAPIMART_BASE_URL={base}\n")
    os.chmod(f, 0o600)
    r = verificar_apimart(tmp_path, f, abrir=lambda *a, **k: 1 / 0)
    assert r.ok is False and r.motivo == "APIMART_BASE_URL debe ser https"
    assert "example.com" not in todo(r, tmp_path) and "passwd" not in todo(r, tmp_path)


def test_env_enlace_simbolico_rechazado(tmp_path):
    real = env(tmp_path)
    enlace = tmp_path / "enlace.env"
    enlace.symlink_to(real)
    r = verificar_apimart(tmp_path, enlace, abrir=lambda *a, **k: 1 / 0)
    assert r.ok is False and "enlace simbólico" in r.motivo and CLAVE not in todo(r, tmp_path)


def test_env_directorio_y_no_utf8(tmp_path):
    d = tmp_path / "d.env"
    d.mkdir()
    assert verificar_apimart(tmp_path, d, abrir=None).ok is False
    f = tmp_path / "b.env"
    f.write_bytes(b"\xff\xfe\x00")
    os.chmod(f, 0o600)
    r = verificar_apimart(tmp_path, f, abrir=None)
    assert r.ok is False and r.motivo.startswith("no se pudo leer")


def test_redireccion_no_reenvia_la_clave(tmp_path):
    vistos: list[str | None] = []

    class Destino(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            vistos.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    destino = http.server.HTTPServer(("127.0.0.1", 0), Destino)
    url_destino = f"http://127.0.0.1:{destino.server_port}/v1/balance"

    class Origen(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", url_destino)
            self.end_headers()

        def log_message(self, *a):
            pass

    origen = http.server.HTTPServer(("127.0.0.1", 0), Origen)
    for srv in (destino, origen):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        f = tmp_path / "r.env"
        f.write_text(f"APIMART_API_KEY={CLAVE}\nAPIMART_BASE_URL=http://127.0.0.1:{origen.server_port}\n")
        os.chmod(f, 0o600)
        r = verificar_apimart(tmp_path, f)  # abridor real por defecto
    finally:
        origen.shutdown()
        destino.shutdown()
    assert r.ok is None and r.motivo == "no medido: respuesta inesperada"
    assert vistos == []
