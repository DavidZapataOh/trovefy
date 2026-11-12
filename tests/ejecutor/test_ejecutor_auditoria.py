import json

import pytest
from trovefy_ejecutor.auditoria import Auditoria, AuditoriaCorrupta, redactar, reparar


def llenar(tmp_path, n=3):
    a = Auditoria(tmp_path / "a.jsonl")
    for i in range(n):
        a.anotar("transicion", id=f"P-20261112-00{i}", tipo="noop", de="recibida", a="enviada")
    return a


def test_cadena_valida_y_redactada(tmp_path):
    a = llenar(tmp_path)
    linea = a.anotar(
        "error_graph",
        mensaje="token EAABsbCS1iHgBAZB0 y https://api.telegram.org/bot123456:AA-x_y/sendMessage",
    )
    assert "EAAB" not in json.dumps(linea) and "bot123456" not in json.dumps(linea)
    assert a.verificar()


def test_linea_editada(tmp_path):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    f.write_text(f.read_text().replace("enviada", "aceptada", 1))
    assert not Auditoria(f).verificar()


def test_linea_del_medio_borrada(tmp_path):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    ls = f.read_text().splitlines(keepends=True)
    f.write_text(ls[0] + ls[2])
    assert not Auditoria(f).verificar()


def test_cola_borrada_la_detecta_la_cabeza(tmp_path):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    ls = f.read_text().splitlines(keepends=True)
    f.write_text("".join(ls[:2]))
    assert not Auditoria(f).verificar()


def test_ultima_linea_a_medias_falla_cerrada_y_se_repara(tmp_path):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    with f.open("a") as h:
        h.write('{"n": 3, "evento": "trans')
    with pytest.raises(AuditoriaCorrupta):
        Auditoria(f)
    roto = reparar(f)
    a = Auditoria(f)
    primera = json.loads(f.read_text().splitlines()[0])
    assert roto.exists() and a.verificar() and primera["evento"] == "cadena_reanudada"
    assert primera["datos"]["archivo_anterior"] == roto.name
    assert len(primera["datos"]["hash_ultimo_valido"]) == 64


def test_eventos_de_la_resolucion_13(tmp_path):
    from trovefy_ejecutor.auditoria import EV_EJECUCION, EV_EMPAREJADO, EV_TRANSICION

    a = Auditoria(tmp_path / "a.jsonl")
    a.anotar(EV_TRANSICION, id="P-20261112-001", tipo="noop", de="enviada", a="aceptada")
    a.anotar(
        EV_EJECUCION, id="P-20261112-002", tipo="crear_estructura_pausada",
        validate_only=True, ok=True, detalle="",
    )
    with pytest.raises(ValueError, match="tipo"):
        a.anotar(EV_TRANSICION, id="P-20261112-001", de="enviada", a="aceptada")
    with pytest.raises(ValueError, match="chat_id"):
        a.anotar(EV_EMPAREJADO, user_id=1)
    assert a.verificar()


def test_redactar():
    assert redactar("x bot7000000001:AAH-abc_123 y EAAGm0PX4ZCps") == "x *** y ***"
    assert redactar("t 7000000001:" + "A" * 35 + " fin") == "t *** fin"


def test_vacio_reabrir_y_primer_fallo(tmp_path):
    f = tmp_path / "a.jsonl"
    assert Auditoria(f).verificar()
    a = llenar(tmp_path)
    assert Auditoria(f).verificar() and a.primer_fallo() is None
    f.write_text(f.read_text().replace("enviada", "aceptada", 1))
    assert "1" in Auditoria(f).primer_fallo()
    assert (f.stat().st_mode & 0o777) == 0o600


def test_reabrir_tras_truncar_cola_falla_cerrado(tmp_path):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    ls = f.read_text().splitlines(keepends=True)
    f.write_text("".join(ls[:2]))
    with pytest.raises(AuditoriaCorrupta):
        Auditoria(f).anotar("stop", activo=True)
    assert not Auditoria(f).verificar()
    reparar(f)
    assert Auditoria(f).verificar()


def test_hueco_benigno_entre_append_y_cabeza_se_cura(tmp_path):
    a = llenar(tmp_path, 2)
    cab = a.cabeza
    guardada = cab.read_text()
    a.anotar("stop", activo=True)
    cab.write_text(guardada)  # la caída ocurrió antes de escribir la cabeza
    b = Auditoria(tmp_path / "a.jsonl")
    b.anotar("stop", activo=False)
    assert b.verificar()
    assert len((tmp_path / "a.jsonl").read_text().splitlines()) == 4


@pytest.mark.parametrize("cual", [0, 1, 2])
def test_cadena_corrupta_bloquea_anotar(tmp_path, cual):
    llenar(tmp_path)
    f = tmp_path / "a.jsonl"
    ls = f.read_text().splitlines(keepends=True)
    ls[cual] = ls[cual].replace("enviada", "aceptada")
    f.write_text("".join(ls))
    with pytest.raises(AuditoriaCorrupta):
        Auditoria(f).anotar("stop", activo=True)


def _worker(ruta):
    a = Auditoria(ruta)
    for i in range(20):
        a.anotar("stop", activo=bool(i % 2))


def test_dos_procesos_concurrentes(tmp_path):
    import multiprocessing as mp

    f = tmp_path / "a.jsonl"
    Auditoria(f).anotar("stop", activo=True)
    ps = [mp.get_context("fork").Process(target=_worker, args=(f,)) for _ in range(2)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
        assert p.exitcode == 0
    assert len(f.read_text().splitlines()) == 41 and Auditoria(f).verificar()


def test_reparar_no_pisa_evidencia_ni_falla_sin_archivo(tmp_path):
    f = tmp_path / "a.jsonl"
    fijo = lambda: __import__("datetime").datetime(2026, 11, 12, tzinfo=__import__("datetime").UTC)
    r0 = reparar(f, fijo)  # no existe: no lanza
    assert Auditoria(f).verificar() and not r0.exists()
    r1 = reparar(f, fijo)
    r2 = reparar(f, fijo)
    assert r1 != r2 and r1.exists() and r2.exists()
