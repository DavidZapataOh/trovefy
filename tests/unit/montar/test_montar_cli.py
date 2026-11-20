"""`trovefy montar preparar|validar|depositar|registrar|activar` de punta a punta, con un ejecutor simulado que solo
copia resultados al vault (plan 22, Tareas 8, 9 y 13). Nunca Meta ni el buzón real."""
from __future__ import annotations

import json

import pytest
import yaml
from trovefy import cli, montar_cli
from trovefy.caja.config import cargar_caja
from trovefy.listo import GATES
from trovefy.listo.gates import Gate
from trovefy.listo.veredicto import InformeListo
from trovefy.vault import frontmatter

from .ejemplos import AHORA, PAIS, TRM, P, copia_ejecutor, escribir_spool, ids_montaje


def _informe(*_a, **_k):
    return InformeListo(P, PAIS, AHORA, tuple(Gate(g, "ok", "ok") for g in GATES), "BE 10 USD", True)


@pytest.fixture
def entorno(vault_zz, tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_VAULT", str(vault_zz))
    spool = escribir_spool(tmp_path)
    monkeypatch.setattr(montar_cli, "_evaluar_listo", _informe)
    monkeypatch.setattr(montar_cli, "_fuentes", lambda v: None)
    monkeypatch.setattr(montar_cli, "_trm", lambda v, d: TRM)
    monkeypatch.setattr(montar_cli, "_ahora", lambda: AHORA)
    return vault_zz, spool


def _main(*args):
    return cli.main(["montar", *args])


def _ids(*extra):
    return ["--producto", P, "--pais", PAIS, *extra]


def _entrada(spool):
    return sorted((spool / "entrada").glob("P-*.json"))


def _trafico(vault):
    meta, _ = frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")
    return meta["paises"][PAIS]


def test_preparar_escribe_y_no_deposita(entorno, capsys):
    vault, spool = entorno
    assert _main("preparar", *_ids("--tanda", "t1")) == 0
    assert not _entrada(spool)
    out = capsys.readouterr().out
    assert "Todo se crea en PAUSED" in out and "PRUEBA ZZ | G1 | ABO | 20-11-26" in out
    d = json.loads((vault / "productos" / P / "trafico" / PAIS / "MONTAJE-t1.json").read_text())
    assert len(d["estructura"]["conjuntos"]) == 5 and d["huella"]


def test_bloqueo_sale_1_con_motivos(entorno, monkeypatch, capsys):
    monkeypatch.setattr(montar_cli, "_evaluar_listo", lambda *a: InformeListo(
        P, PAIS, AHORA, tuple(Gate(g, "falla" if g == "caja" else "ok", "0 huecos") for g in GATES), "BE", True))
    assert _main("preparar", *_ids("--tanda", "t1")) == 1
    assert "caja: 0 huecos" in capsys.readouterr().out


def test_validar_deposita_solo_validar(entorno):
    _vault, spool = entorno
    _main("preparar", *_ids("--tanda", "t1"))
    assert _main("validar", *_ids("--tanda", "t1")) == 0
    d = json.loads(_entrada(spool)[0].read_text())
    assert d["solo_validar"] is True and d["origen"] == "/montar" and d["tipo"] == "crear_estructura_pausada"
    assert _main("validar", *_ids("--tanda", "t1")) == 0  # idempotente
    assert len(_entrada(spool)) == 1


def test_validar_rechaza_tanda_cambiada(entorno, capsys):
    vault, _ = entorno
    _main("preparar", *_ids("--tanda", "t1"))
    d = json.loads((vault / "productos" / P / "trafico" / PAIS / "MONTAJE-t1.json").read_text())
    medio = vault / d["estructura"]["medios"][0]["ruta"]
    medio.write_bytes(medio.read_bytes() + b"\x00")
    assert _main("validar", *_ids("--tanda", "t1")) == 2
    assert "la tanda cambió" in capsys.readouterr().err


def test_depositar_sin_validacion_falla(entorno):
    _main("preparar", *_ids("--tanda", "t1"))
    assert _main("depositar", *_ids("--tanda", "t1")) == 2


def _validado(vault, spool):
    _main("preparar", *_ids("--tanda", "t1"))
    _main("validar", *_ids("--tanda", "t1"))
    vid = _entrada(spool)[0].stem
    copia_ejecutor(vault, vid, "crear_estructura_pausada", "ejecutada", detalle="solo validar: ok")
    return vid


def test_depositar_rechaza_huella_vieja(entorno, capsys):
    vault, spool = entorno
    _validado(vault, spool)
    ruta = vault / "productos" / P / "trafico" / PAIS / "MONTAJE-t1.json"
    d = json.loads(ruta.read_text())
    d["estructura"]["campana"]["nombre"] = "otro"
    ruta.write_text(json.dumps(d))
    assert _main("depositar", *_ids("--tanda", "t1")) == 2
    assert "cambió a mano" in capsys.readouterr().err


def test_depositar_es_idempotente(entorno, capsys):
    vault, spool = entorno
    _validado(vault, spool)
    assert _main("depositar", *_ids("--tanda", "t1")) == 0
    assert _main("depositar", *_ids("--tanda", "t1")) == 0
    assert "ya depositado" in capsys.readouterr().out
    assert len(_entrada(spool)) == 2
    d = json.loads(_entrada(spool)[1].read_text())
    assert "solo_validar" not in d and all("status" not in c for c in d["conjuntos"])
    assert _trafico(vault)["trafico"]["montaje"] == _entrada(spool)[1].stem


def test_depositar_con_stop_no_escribe(entorno):
    vault, spool = entorno
    _validado(vault, spool)
    (vault / ".trovefy").mkdir(exist_ok=True)
    (vault / ".trovefy" / "STOP").write_text("stop")
    assert _main("depositar", *_ids("--tanda", "t1")) == 1
    assert len(_entrada(spool)) == 1


def test_validacion_fallida_por_spend_cap_explica_d1(entorno, capsys):
    vault, spool = entorno
    _main("preparar", *_ids("--tanda", "t1"))
    _main("validar", *_ids("--tanda", "t1"))
    copia_ejecutor(vault, _entrada(spool)[0].stem, "crear_estructura_pausada", "fallida",
                   detalle="validate_only rechazado: spend_cap below minimum")
    assert _main("depositar", *_ids("--tanda", "t1")) == 1
    assert "D1" in capsys.readouterr().out


def _montado(vault, spool, monkeypatch=None):
    _validado(vault, spool)
    _main("depositar", *_ids("--tanda", "t1"))
    mid = _entrada(spool)[1].stem
    d = json.loads(_entrada(spool)[1].read_text())
    nombres = [c["nombre"] for c in d["conjuntos"]]
    copia_ejecutor(vault, mid, "crear_estructura_pausada", "ejecutada", ids=ids_montaje(nombres),
                   detalle="montaje en PAUSED completado; la relectura confirma")
    return mid, nombres


def test_registrar_montaje_y_activacion(entorno):
    vault, spool = entorno
    mid, nombres = _montado(vault, spool)
    assert _main("registrar", *_ids()) == 0
    b = _trafico(vault)
    assert b["estado"] == "montado" and b["trafico"]["campana"]["id"] == "9000001"
    assert set(b["trafico"]["conjuntos"]) == set(nombres)
    hist = vault / "productos" / P / b["trafico"]["historico"]
    assert hist.is_file() and "act_0000000000000000" not in hist.read_text()
    copia_ejecutor(vault, "P-20261120-801", "activar", "ejecutada",
                   texto=f"Por qué: Activar campaña X (creada en PAUSED, montaje {mid})")
    assert _main("registrar", "--pendientes") == 0
    b = _trafico(vault)
    assert b["estado"] == "test" and b["trafico"]["activado"]
    t = cargar_caja(vault).tests
    assert len(t) == 1 and t[0].campana_id == "9000001" and t[0].presupuesto_diario == 2500
    assert _main("registrar", *_ids()) == 0  # idempotente
    assert _trafico(vault)["estado"] == "test"


def test_rechazar_escribe_veto_y_no_avanza(entorno):
    vault, spool = entorno
    mid, _ = _montado(vault, spool)
    _main("registrar", *_ids())
    copia_ejecutor(vault, "P-20261120-801", "activar", "rechazada", texto=f"montaje {mid}")
    motivo = vault / "raw" / "telegram" / "motivos" / "2026-11-20-P-20261120-801.md"
    motivo.parent.mkdir(parents=True, exist_ok=True)
    frontmatter.escribir(motivo, {"tipo": "motivo_rechazo"}, "\nMotivo:\n\n> el AD03 tiene el texto cortado\n")
    _main("registrar", *_ids())
    b = _trafico(vault)
    assert b["estado"] == "montado"
    veto = vault / b["trafico"]["veto"]
    assert "el AD03 tiene el texto cortado" in veto.read_text()


def test_caducada_avisa_y_activar_de_claude(entorno, capsys):
    vault, spool = entorno
    mid, _ = _montado(vault, spool)
    _main("registrar", *_ids())
    assert _main("activar", *_ids()) == 1  # aún no caducó
    copia_ejecutor(vault, "P-20261120-801", "activar", "caducada", texto=f"montaje {mid}")
    _main("registrar", *_ids())
    assert "trovefy montar activar" in capsys.readouterr().out
    assert _main("activar", *_ids()) == 0
    d = json.loads(_entrada(spool)[-1].read_text())
    assert d["tipo"] == "activar" and d["origen"] == "/montar" and len(d["operaciones"]) == 11
    assert len(d["evidencia"]["anuncios"]) == 5


def test_parcial_no_avanza(entorno, capsys):
    vault, spool = entorno
    _validado(vault, spool)
    _main("depositar", *_ids("--tanda", "t1"))
    mid = _entrada(spool)[1].stem
    copia_ejecutor(vault, mid, "crear_estructura_pausada", "fallida", parcial=True,
                   ids={"campana": "9000001", "conjuntos": {}, "anuncios": {}, "creativos": {}, "medios": {}},
                   detalle="conjunto AD02: Meta lo rechazó")
    _main("registrar", *_ids())
    b = _trafico(vault)
    assert b["estado"] == "listo" and b["trafico"]["montaje_estado"] == "fallida"
    assert "estado parcial" in capsys.readouterr().out
    assert _main("depositar", *_ids("--tanda", "t1")) == 0  # mismo montaje: ya depositado


def test_excepcion_exige_mensaje_del_usuario(entorno, monkeypatch, capsys):
    monkeypatch.setattr(montar_cli, "_hay_terminal", lambda: False)
    assert _main("excepcion", *_ids("--gate", "reembolso", "--cita", "sí", "--motivo", "x")) == 2
    monkeypatch.setattr(montar_cli, "_hay_terminal", lambda: True)
    assert _main("excepcion", *_ids("--gate", "reembolso", "--cita", "sí, actívalo", "--motivo", "x")) == 0
    assert _main("excepcion", *_ids("--gate", "compra", "--cita", "sí", "--motivo", "x")) == 2


def test_estado(entorno, capsys):
    vault, spool = entorno
    _montado(vault, spool)
    _main("registrar", *_ids())
    assert _main("estado", *_ids()) == 0
    out = capsys.readouterr().out
    assert "estado montado" in out and "…0001" in out


# --- renovación (Tarea 13) ---------------------------------------------------------------------------------------


def _activo(vault, spool):
    mid, nombres = _montado(vault, spool)
    _main("registrar", *_ids())
    copia_ejecutor(vault, "P-20261120-801", "activar", "ejecutada", texto=f"montaje {mid}")
    _main("registrar", *_ids())
    return nombres


def _tanda_renovacion(vault):
    """t2 de renovación: las reservas AD06 y AD07 de t1 con uso renovacion, cerrada y vigente."""
    import csv
    import hashlib
    import io
    import shutil

    from trovefy.creativos.manifest import CABECERA
    from trovefy.vault.producto import actualizar_producto

    t1 = vault / "productos" / P / "creativos" / PAIS / "t1"
    t2 = t1.parent / "t2"
    t2.mkdir()
    filas = []
    for f in csv.DictReader((t1 / "manifest.csv").read_text().splitlines()):
        if f["id"] in ("AD06", "AD07"):
            for col in ("archivo", "miniatura"):
                origen = vault / f[col]
                destino = t2 / origen.relative_to(t1)
                destino.parent.mkdir(parents=True, exist_ok=True)
                if not destino.exists():
                    shutil.copy2(origen, destino)
                f[col] = destino.relative_to(vault).as_posix()
            f["uso"], f["nombre"] = "renovacion", f["nombre"].replace(" G1 ", " G2 ")
            filas.append(f)
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=CABECERA, lineterminator="\n")
    w.writeheader()
    for f in filas:
        w.writerow(f)
    (t2 / "manifest.csv").write_text(s.getvalue())
    sha = hashlib.sha256(s.getvalue().encode()).hexdigest()
    actualizar_producto(vault, P, {"paises": {PAIS: {"creativos": {"vigente": "t2", "tandas": {"t2": {
        "cerrada": AHORA.isoformat(), "manifest_sha256": sha}}}}}}, [], "/t", AHORA)


def test_renovacion_en_la_misma_campana(entorno, monkeypatch):
    vault, spool = entorno
    _activo(vault, spool)
    _tanda_renovacion(vault)
    import trovefy.montar.tanda as tanda_mod

    monkeypatch.setattr(tanda_mod, "_aprobada", lambda *a: (True, None))
    assert _main("renovacion", *_ids("--tanda", "t2")) == 0
    assert _main("renovacion", *_ids("--tanda", "t2", "--paso", "validar")) == 0
    vid = _entrada(spool)[-1].stem
    d = json.loads(_entrada(spool)[-1].read_text())
    assert d["campana_existente"] == "9000001" and len(d["conjuntos"]) == 2
    assert all(c["daily_budget"] == 20000 for c in d["conjuntos"])
    assert d["conjuntos"][0]["nombre"].startswith("AD06 G2 ")
    copia_ejecutor(vault, vid, "crear_estructura_pausada", "ejecutada")
    assert _main("renovacion", *_ids("--tanda", "t2", "--paso", "depositar")) == 0
    mid = _entrada(spool)[-1].stem
    nombres = [c["nombre"] for c in json.loads(_entrada(spool)[-1].read_text())["conjuntos"]]
    ids = ids_montaje(nombres)
    ids["campana"] = None
    copia_ejecutor(vault, mid, "crear_estructura_pausada", "ejecutada", ids=ids)
    copia_ejecutor(vault, "P-20261120-802", "activar", "ejecutada", texto=f"montaje {mid}")
    _main("registrar", *_ids())
    b = _trafico(vault)
    assert len(b["trafico"]["conjuntos"]) == 7
    assert cargar_caja(vault).tests[0].presupuesto_diario == 3500


def test_plazo_vencido_no_renueva(entorno, monkeypatch, capsys):
    vault, spool = entorno
    _activo(vault, spool)
    _tanda_renovacion(vault)
    import datetime as dt

    import trovefy.montar.tanda as tanda_mod

    monkeypatch.setattr(tanda_mod, "_aprobada", lambda *a: (True, None))
    monkeypatch.setattr("trovefy.montar.precondiciones.DIAS_DATASET", 30)
    monkeypatch.setattr(montar_cli, "_ahora", lambda: AHORA + dt.timedelta(days=9))
    monkeypatch.setattr(montar_cli, "_trm", lambda v, d: TRM.__class__(TRM.cop_por_usd, d, d))
    escribir_spool(vault, AHORA + dt.timedelta(days=9))
    assert _main("renovacion", *_ids("--tanda", "t2")) == 1
    assert "plazo del test" in capsys.readouterr().out


def test_sin_tanda_cerrada_no_deposita(entorno, capsys):
    vault, spool = entorno
    _activo(vault, spool)
    _tanda_renovacion(vault)
    assert _main("renovacion", *_ids("--tanda", "t2")) == 1  # el gate creativos real no la da por revisada
    assert "no está aprobada" in capsys.readouterr().out


def test_techo_agotado_no_renueva(entorno, monkeypatch, capsys):
    vault, spool = entorno
    _activo(vault, spool)
    _tanda_renovacion(vault)
    import trovefy.montar.tanda as tanda_mod

    monkeypatch.setattr(tanda_mod, "_aprobada", lambda *a: (True, None))
    led = vault / "ledger" / "gasto"
    led.mkdir(parents=True)
    (led / "2026-11.csv").write_text("fecha,cuenta,campana,gasto,moneda\n2026-11-20,act_0000000000000000,9000001,"
                                     "100.00,USD\n")
    assert _main("renovacion", *_ids("--tanda", "t2")) == 1
    assert "techo del test" in capsys.readouterr().out


def test_caja_yaml_valida(entorno):
    vault, _ = entorno
    assert yaml.safe_load((vault / "config" / "caja.yaml").read_text())["cuenta"]["id"]
