import hashlib
import json
import os
import stat
from decimal import Decimal

import pytest
from trovefy.producto.medios import (
    MODO_MEDIO,
    escribir_medio,
    leer_manifiesto,
    registrar_medio,
)

DATOS = b"\x89PNG\r\n\x1a\nfalso"
SHA = hashlib.sha256(DATOS).hexdigest()


def test_medio_0640(tmp_path):
    r = tmp_path / "entregable" / "medios" / "portada.png"
    sha = escribir_medio(r, DATOS)
    assert MODO_MEDIO == 0o640
    assert stat.S_IMODE(os.stat(r).st_mode) == 0o640
    assert sha == SHA and r.read_bytes() == DATOS
    assert [p.name for p in r.parent.iterdir()] == ["portada.png"]  # sin temporales


def test_medio_sobrescribe_y_conserva_0640(tmp_path):
    r = tmp_path / "x.pdf"
    r.write_bytes(b"viejo")
    os.chmod(r, 0o644)
    escribir_medio(r, b"nuevo")
    assert r.read_bytes() == b"nuevo" and stat.S_IMODE(os.stat(r).st_mode) == 0o640


def _medio(raiz, nombre="portada.png", datos=DATOS):
    return escribir_medio(raiz / "medios" / nombre, datos)


def test_manifiesto_registra(tmp_path):
    raiz = tmp_path / "entregable"
    assert leer_manifiesto(raiz) == {}
    sha = _medio(raiz)
    registrar_medio(raiz, "portada", "portada.png", sha, "apimart", task_id="t-1", coste_usd=Decimal("0.0085"))
    sha2 = _medio(raiz, "foto.png", b"otra")
    registrar_medio(raiz, "foto", "foto.png", sha2, "propio")
    m = leer_manifiesto(raiz)
    assert m["portada"] == {"archivo": "portada.png", "sha256": SHA, "origen": "apimart", "task_id": "t-1",
                            "coste_usd": "0.0085"}
    assert m["foto"]["origen"] == "propio"
    assert json.loads((raiz / "medios" / "medios.json").read_text(encoding="utf-8")) == m
    # volver a registrar el mismo id lo reemplaza
    registrar_medio(raiz, "portada", "portada.png", sha, "propio")
    assert leer_manifiesto(raiz)["portada"] == {"archivo": "portada.png", "sha256": SHA, "origen": "propio"}


@pytest.mark.parametrize(("id_", "archivo", "sha", "origen", "error"), [
    ("portada", "portada.png", SHA, "web", "origen"),
    ("portada", "../portada.png", SHA, "apimart", "archivo"),
    ("portada", "sub/portada.png", SHA, "apimart", "archivo"),
    ("Portada X", "portada.png", SHA, "apimart", "id"),
    ("portada", "portada.png", "0" * 64, "apimart", "sha256"),
    ("portada", "portada.png", "abc", "apimart", "sha256"),
    ("portada", "falta.png", SHA, "apimart", "no existe"),
])
def test_manifiesto_rechaza(tmp_path, id_, archivo, sha, origen, error):
    raiz = tmp_path / "entregable"
    _medio(raiz)
    with pytest.raises(ValueError, match=error):
        registrar_medio(raiz, id_, archivo, sha, origen)
    assert leer_manifiesto(raiz) == {}


def test_manifiesto_rechaza_secretos(tmp_path):
    raiz = tmp_path / "entregable"
    sha = _medio(raiz)
    with pytest.raises(ValueError, match="secreto"):
        registrar_medio(raiz, "portada", "portada.png", sha, "apimart", nota="sk-" + "a" * 48)
    assert leer_manifiesto(raiz) == {}


def test_manifiesto_ilegible(tmp_path):
    raiz = tmp_path / "entregable"
    (raiz / "medios").mkdir(parents=True)
    (raiz / "medios" / "medios.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="medios.json"):
        leer_manifiesto(raiz)
