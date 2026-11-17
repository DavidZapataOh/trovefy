import json
from datetime import datetime, timedelta, timezone

import pytest
from trovefy.apimart.http import Credenciales, RespuestaInesperada
from trovefy.apimart.subidas import RUTA_CACHE, subir

from .ayudas import CLAVE, FIXTURES, fixture

CRED = Credenciales("https://api.apimart.ai", CLAVE)
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=timezone(timedelta(hours=-5)))


def explota(*_a, **_k):
    raise AssertionError("no debía subir nada")


def test_subida_cacheada_60h(tmp_path, respuesta_json):
    abrir = respuesta_json(200, fixture("subida-imagen.json"))
    url = subir(CRED, FIXTURES / "png-1x1.png", tmp_path, abrir, T0)
    assert url == "https://cdn.example/uploads/reference.png"
    req = abrir.peticiones[0][0]
    assert req.full_url == "https://api.apimart.ai/v1/uploads/images?retention_days=3"
    assert req.headers["Authorization"] == f"Bearer {CLAVE}"
    assert req.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="png-1x1.png"' in req.data and fixture("png-1x1.png") in req.data
    # a las 59 h no llama
    assert subir(CRED, FIXTURES / "png-1x1.png", tmp_path, explota, T0 + timedelta(hours=59)) == url
    # a las 61 h vuelve a subir
    otra = respuesta_json(200, {**fixture("subida-imagen.json"), "url": "https://cdn.example/uploads/b.png"})
    assert subir(CRED, FIXTURES / "png-1x1.png", tmp_path, otra, T0 + timedelta(hours=61)) == \
        "https://cdn.example/uploads/b.png"
    cache = json.loads((tmp_path / RUTA_CACHE).read_text())
    assert next(iter(cache.values()))["url"] == "https://cdn.example/uploads/b.png"


def test_subida_sin_url_https(tmp_path, respuesta_json):
    with pytest.raises(RespuestaInesperada):
        subir(CRED, FIXTURES / "png-1x1.png", tmp_path, respuesta_json(200, {"url": "http://x/y.png"}), T0)
    assert not (tmp_path / RUTA_CACHE).exists()


def test_subida_solo_imagenes(tmp_path):
    otra = tmp_path / "nota.txt"
    otra.write_text("hola")
    with pytest.raises(ValueError):
        subir(CRED, otra, tmp_path, explota, T0)


def test_ahora_sin_zona(tmp_path):
    with pytest.raises(ValueError):
        subir(CRED, FIXTURES / "png-1x1.png", tmp_path, explota, datetime(2026, 11, 14))


def test_cache_rota_se_rehace(tmp_path, respuesta_json):
    (tmp_path / RUTA_CACHE).parent.mkdir(parents=True)
    (tmp_path / RUTA_CACHE).write_text("{roto")
    url = subir(CRED, FIXTURES / "png-1x1.png", tmp_path, respuesta_json(200, fixture("subida-imagen.json")), T0)
    assert url.startswith("https://")
