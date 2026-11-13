import json

from trovefy_ejecutor.auditoria import GENESIS, Auditoria, verificar_lineas


def _lineas(tmp_path, n=4):
    a = Auditoria(tmp_path / "a.jsonl")
    for i in range(n):
        a.anotar("transicion", id=f"P-20261112-00{i}", tipo="noop", de="recibida", a="enviada")
    return (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()


def test_cadena_entera_ok(tmp_path):
    assert verificar_lineas(_lineas(tmp_path)) is None


def test_acepta_dicts_y_bytes(tmp_path):
    ls = _lineas(tmp_path)
    assert verificar_lineas([json.loads(x) for x in ls]) is None
    assert verificar_lineas([x.encode() for x in ls]) is None


def test_tramo_que_continua(tmp_path):
    ls = _lineas(tmp_path)
    previa = json.loads(ls[1])["hash"]
    assert verificar_lineas(ls[2:], n0=3, hash_prev=previa) is None


def test_tramo_con_inicio_equivocado(tmp_path):
    ls = _lineas(tmp_path)
    assert verificar_lineas(ls[2:]) == "línea 1: cadena rota"
    assert verificar_lineas(ls[2:], n0=3, hash_prev=GENESIS) == "línea 1: cadena rota"


def test_linea_editada(tmp_path):
    ls = _lineas(tmp_path)
    ls[2] = ls[2].replace("enviada", "aceptada")
    assert verificar_lineas(ls) == "línea 3: cadena rota"


def test_linea_borrada_y_basura(tmp_path):
    ls = _lineas(tmp_path)
    assert verificar_lineas([ls[0], ls[2]]) == "línea 2: cadena rota"
    assert verificar_lineas([ls[0], "no json"]) == "línea 2: cadena rota"
    assert verificar_lineas([ls[0], "[1]"]) == "línea 2: cadena rota"


def test_vacia_ok():
    assert verificar_lineas([]) is None
