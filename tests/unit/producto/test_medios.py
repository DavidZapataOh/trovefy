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


# --- ronda de revisión de la Tarea 1 -------------------------------------------------------------


def test_manifiesto_rechaza_enlace(tmp_path):
    raiz = tmp_path / "entregable"
    _medio(raiz)
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(DATOS)
    os.chmod(fuera, 0o640)
    (raiz / "medios" / "enlace.png").symlink_to(fuera)
    with pytest.raises(ValueError, match="enlace"):
        registrar_medio(raiz, "enlace", "enlace.png", SHA, "propio")
    assert leer_manifiesto(raiz) == {}


def test_manifiesto_rechaza_modo_no_0640(tmp_path):
    raiz = tmp_path / "entregable"
    _medio(raiz)
    os.chmod(raiz / "medios" / "portada.png", 0o644)
    with pytest.raises(ValueError, match="640"):
        registrar_medio(raiz, "portada", "portada.png", SHA, "propio")
    assert leer_manifiesto(raiz) == {}


def test_manifiesto_rechaza_no_regular(tmp_path):
    raiz = tmp_path / "entregable"
    (raiz / "medios").mkdir(parents=True)
    os.mkfifo(raiz / "medios" / "tubo.png", 0o640)
    with pytest.raises(ValueError, match="regular"):
        registrar_medio(raiz, "tubo", "tubo.png", SHA, "propio")


def _vault_con_enlace(tmp_path, enlazado):
    """Vault con ``productos/p/entregable`` y ``enlazado`` (relativo al entregable o él mismo) como enlace."""
    vault = tmp_path / "vault"
    entregable = vault / "productos" / "p-0042-respira" / "entregable"
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    if enlazado == "entregable":
        entregable.parent.mkdir(parents=True)
        entregable.symlink_to(fuera, target_is_directory=True)
    else:
        entregable.mkdir(parents=True)
        (entregable / enlazado).symlink_to(fuera, target_is_directory=True)
    return vault, entregable, fuera


@pytest.mark.parametrize("enlazado", ["medios", "entregable"])
def test_medio_rechaza_padre_enlazado(tmp_path, enlazado):
    vault, entregable, fuera = _vault_con_enlace(tmp_path, enlazado)
    with pytest.raises(ValueError, match="enlace"):
        escribir_medio(entregable / "medios" / "portada.png", DATOS, base=vault)
    assert list(fuera.rglob("*")) == []


@pytest.mark.parametrize("enlazado", ["medios", "entregable"])
def test_manifiesto_rechaza_padre_enlazado(tmp_path, enlazado):
    _vault, entregable, fuera = _vault_con_enlace(tmp_path, enlazado)
    (fuera / "portada.png").write_bytes(DATOS)
    os.chmod(fuera / "portada.png", 0o640)
    if enlazado == "entregable":
        (fuera / "medios").mkdir()
        os.replace(fuera / "portada.png", fuera / "medios" / "portada.png")
    antes = sorted(p.name for p in fuera.rglob("*"))
    with pytest.raises(ValueError, match="enlace"):
        registrar_medio(entregable, "portada", "portada.png", SHA, "propio")
    assert sorted(p.name for p in fuera.rglob("*")) == antes  # sin medios.json ni temporales


def test_medio_reemplaza_enlace_final_sin_seguirlo(tmp_path):
    vault = tmp_path / "vault"
    medios = vault / "entregable" / "medios"
    medios.mkdir(parents=True)
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"intacto")
    (medios / "portada.png").symlink_to(fuera)
    escribir_medio(medios / "portada.png", DATOS, base=vault)
    assert not (medios / "portada.png").is_symlink()
    assert (medios / "portada.png").read_bytes() == DATOS
    assert fuera.read_bytes() == b"intacto"


def test_medio_fuera_de_la_base(tmp_path):
    with pytest.raises(ValueError, match="fuera"):
        escribir_medio(tmp_path / "otro" / "x.png", DATOS, base=tmp_path / "vault")


def _manifiesto_crudo(raiz, datos):
    (raiz / "medios").mkdir(parents=True, exist_ok=True)
    (raiz / "medios" / "medios.json").write_text(json.dumps(datos), encoding="utf-8")


@pytest.mark.parametrize("entrada", [
    {"archivo": "../../etc/passwd", "sha256": SHA, "origen": "propio"},
    {"archivo": "portada.png", "sha256": "abc", "origen": "propio"},
    {"archivo": "portada.png", "sha256": SHA, "origen": "web"},
    {"sha256": SHA, "origen": "propio"},
    {"archivo": "medios.json", "sha256": SHA, "origen": "propio"},
    {"archivo": "portada.png", "sha256": SHA, "origen": "propio", "coste": 0.5},
])
def test_leer_manifiesto_valida_entradas(tmp_path, entrada):
    raiz = tmp_path / "entregable"
    _manifiesto_crudo(raiz, {"portada": entrada})
    with pytest.raises(ValueError):
        leer_manifiesto(raiz)


def test_leer_manifiesto_valida_ids(tmp_path):
    raiz = tmp_path / "entregable"
    _manifiesto_crudo(raiz, {"../x": {"archivo": "portada.png", "sha256": SHA, "origen": "propio"}})
    with pytest.raises(ValueError, match="id"):
        leer_manifiesto(raiz)


def test_leer_manifiesto_verificar(tmp_path):
    raiz = tmp_path / "entregable"
    _medio(raiz)
    registrar_medio(raiz, "portada", "portada.png", SHA, "propio")
    assert leer_manifiesto(raiz, verificar=True)["portada"]["sha256"] == SHA
    escribir_medio(raiz / "medios" / "portada.png", b"cambiado")
    assert leer_manifiesto(raiz)["portada"]["sha256"] == SHA  # sin verificar no se relee el archivo
    with pytest.raises(ValueError, match="sha256"):
        leer_manifiesto(raiz, verificar=True)
    (raiz / "medios" / "portada.png").unlink()
    (raiz / "medios" / "portada.png").symlink_to(tmp_path / "fuera.png")
    with pytest.raises(ValueError, match="enlace"):
        leer_manifiesto(raiz, verificar=True)


@pytest.mark.parametrize("extra", [
    {"coste_usd": 0.0085},
    {"detalle": {"coste": 1.5}},
    {"lista": [1, 2.0]},
])
def test_manifiesto_rechaza_float(tmp_path, extra):
    raiz = tmp_path / "entregable"
    sha = _medio(raiz)
    with pytest.raises(ValueError, match="float|Decimal"):
        registrar_medio(raiz, "portada", "portada.png", sha, "propio", **extra)
    assert leer_manifiesto(raiz) == {}


def test_manifiesto_tipo_no_serializable_es_valueerror(tmp_path):
    raiz = tmp_path / "entregable"
    sha = _medio(raiz)
    with pytest.raises(ValueError, match="no se puede guardar"):
        registrar_medio(raiz, "portada", "portada.png", sha, "propio", raro=object())
    assert leer_manifiesto(raiz) == {}


@pytest.mark.parametrize("archivo", ["medios.json", "portada.gif", "portada.svg", "portada", "nota.txt"])
def test_manifiesto_rechaza_archivo_no_medio(tmp_path, archivo):
    raiz = tmp_path / "entregable"
    _medio(raiz, archivo)
    with pytest.raises(ValueError, match="archivo|medios.json"):
        registrar_medio(raiz, "portada", archivo, SHA, "propio")


@pytest.mark.parametrize("archivo", ["a.png", "b.jpg", "c.jpeg", "d.webp", "e.pdf"])
def test_manifiesto_admite_extensiones(tmp_path, archivo):
    raiz = tmp_path / "entregable"
    _medio(raiz, archivo)
    registrar_medio(raiz, "m", archivo, SHA, "propio")
    assert leer_manifiesto(raiz, verificar=True)["m"]["archivo"] == archivo


def test_carpeta_segura_es_publica_con_alias_privado():
    """Ruling de la Tarea 13: ``carpeta_segura`` es pública; ``_carpeta_segura`` queda como alias."""
    from trovefy.pdf import render
    from trovefy.producto import medios

    assert medios._carpeta_segura is medios.carpeta_segura
    assert render.carpeta_segura is medios.carpeta_segura
