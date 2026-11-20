"""Criterio de salida de la fase 3 (plan 24, Tarea 12). La auditoría se escribe con la clase real del ejecutor y se
copia por días como hace el ejecutor en ``ledger/auditoria/``."""
import json
from datetime import datetime

import pytest
from trovefy import cli
from trovefy.cierre.criterio import comprobar
from trovefy.vault import frontmatter
from trovefy_ejecutor.auditoria import Auditoria

from .ejemplos import CAMPANA, escribir_json

AHORA = datetime.fromisoformat("2026-11-21T09:00:00-05:00")
ACT = "P-20261117-002"
CB = "cb-0123456789abcdef"


def _escribir(tmp_path, eventos, quitar=None):
    """``eventos``: [(hora ISO, evento, datos)]. ``quitar``: (día, índices) de la copia a omitir (hueco)."""
    ruta = tmp_path / "datos" / "auditoria.jsonl"
    for hora, evento, datos in eventos:
        Auditoria(ruta, reloj=lambda h=hora: datetime.fromisoformat(h)).anotar(evento, **datos)
    v = tmp_path / "vault"
    carpeta = v / "ledger" / "auditoria"
    carpeta.mkdir(parents=True, exist_ok=True)
    por_dia: dict[str, list[str]] = {}
    for ln in ruta.read_text(encoding="utf-8").splitlines():
        ts = datetime.fromisoformat(json.loads(ln)["ts"]).astimezone(AHORA.tzinfo)
        por_dia.setdefault(ts.date().isoformat(), []).append(ln)
    for dia, lineas in por_dia.items():
        if quitar and quitar[0] == dia:
            lineas = [x for i, x in enumerate(lineas) if i not in quitar[1]]
        (carpeta / f"{dia}.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return v


def _cierres(v, dias=("2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21")):
    for d in dias:
        frontmatter.escribir(v / "wiki/analisis/cierres" / f"{d}.md",
                             {"tipo": "cierre", "fecha": d, "momentos": {"manana": {"alerta_id": f"P-{d.replace('-', '')}-001"}}},
                             "\n# c\n")


def _aceptar(hora, id_, tipo):
    return [(hora, "transicion", {"id": id_, "tipo": tipo, "de": "recibida", "a": "enviada"}),
            (hora, "transicion", {"id": id_, "tipo": tipo, "de": "enviada", "a": "aceptada", "callback_id": CB})]


def _base(extra=()):
    return [
        ("2026-11-17T15:00:00-05:00", "ejecucion", {"id": "P-20261117-001", "tipo": "crear_estructura_pausada",
                                                     "validate_only": False, "ok": True,
                                                     "detalle": f"creado (queda en PAUSED): campaña {CAMPANA}"}),
        *_aceptar("2026-11-17T22:00:00-05:00", ACT, "activar"),
        ("2026-11-18T00:05:00-05:00", "ejecucion", {"id": ACT, "tipo": "activar", "validate_only": False, "ok": True,
                                                     "detalle": f"campaña {CAMPANA} activa"}),
        *extra,
    ]


ACTIVIDAD = {"data": [{"event_time": "2026-11-18T00:05:30-05:00", "event_type": "Estado de la campaña",
                       "object_id": CAMPANA, "actor_name": "Trovefy ejecutor"}]}


def test_pasa_con_tres_dias_y_aceptar(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v)
    r = comprobar(v, AHORA, ACTIVIDAD)
    assert r.pasa, r.motivos
    assert [w["tipo"] for w in r.escrituras] == ["activar"] and r.escrituras[0]["aceptar"].startswith("cb-01234")


def test_escritura_de_gasto_sin_aceptar_falla(tmp_path):
    v = _escribir(tmp_path, _base([("2026-11-19T10:00:00-05:00", "ejecucion", {
        "id": "P-20261119-003", "tipo": "presupuesto", "validate_only": False, "ok": True, "detalle": "x"})]))
    _cierres(v)
    r = comprobar(v, AHORA, ACTIVIDAD)
    assert not r.pasa and r.sin_aceptar == ["P-20261119-003"]


def test_estructura_pausada_sin_botones_cuenta(tmp_path):
    v = _escribir(tmp_path, _base([("2026-11-20T20:10:00-05:00", "ejecucion", {
        "id": "P-20261120-004", "tipo": "crear_estructura_pausada", "validate_only": False, "ok": True,
        "detalle": "creado (queda en PAUSED, no se borra nada): conjuntos 130000000000000009"})]))
    _cierres(v)
    act = {"data": [*ACTIVIDAD["data"], {"event_time": "2026-11-20T20:11:00-05:00", "event_type": "Creación",
                                         "object_id": "130000000000000009", "actor_name": "Trovefy ejecutor"}]}
    r = comprobar(v, AHORA, act)
    assert r.pasa, r.motivos


def test_hueco_en_cadena_falla(tmp_path):
    extra = [*_aceptar("2026-11-19T09:00:00-05:00", "P-20261119-001", "pausar"),
             ("2026-11-19T09:05:00-05:00", "ejecucion", {"id": "P-20261119-001", "tipo": "pausar",
                                                         "validate_only": False, "ok": True, "detalle": "x"}),
             ("2026-11-20T09:00:00-05:00", "transicion", {"id": "P-20261120-009", "tipo": "noop", "de": "recibida",
                                                          "a": "enviada"})]
    v = _escribir(tmp_path, _base(extra), quitar=("2026-11-19", {2}))
    _cierres(v)
    r = comprobar(v, AHORA, ACTIVIDAD)
    assert not r.pasa and any("hueco" in m for m in r.motivos)


def test_dia_sin_cierre_falla(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v, ("2026-11-18", "2026-11-20", "2026-11-21"))
    r = comprobar(v, AHORA, ACTIVIDAD)
    assert not r.pasa and r.dias_sin_cierre == ["2026-11-19"]


def test_menos_de_72h_dice_cuanto_falta(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v)
    r = comprobar(v, datetime.fromisoformat("2026-11-20T09:00:00-05:00"), ACTIVIDAD)
    assert not r.pasa and any(m.startswith("faltan 16 h") for m in r.motivos)


def test_sin_activacion_no_pasa(tmp_path):
    v = _escribir(tmp_path, _base()[:1])
    assert "aún no se activó" in comprobar(v, AHORA, ACTIVIDAD).motivos[0]


def test_cambio_manual_en_meta_falla(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v)
    act = {"data": [*ACTIVIDAD["data"], {"event_time": "2026-11-19T15:00:00-05:00", "event_type": "Presupuesto",
                                         "object_id": "130000000000000001", "actor_name": "Persona"}]}
    r = comprobar(v, AHORA, act)
    assert not r.pasa and r.fuera_de_trovefy[0]["objeto"] == "130000000000000001"


def test_cambio_de_meta_por_spend_cap_no_cuenta(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v)
    act = {"data": [*ACTIVIDAD["data"], {"event_time": "2026-11-20T18:00:00-05:00",
                                         "event_type": "Límite de gasto alcanzado", "object_id": "130000000000000001",
                                         "actor_name": "Meta"}]}
    r = comprobar(v, AHORA, act)
    assert r.pasa and len(r.de_meta) == 1


def test_actividad_forma_rara_no_medido(tmp_path):
    v = _escribir(tmp_path, _base())
    _cierres(v)
    r = comprobar(v, AHORA, {"cosa": 1})
    assert not r.pasa and any("forma del registro" in m for m in r.motivos)
    assert not comprobar(v, AHORA, None).pasa


def test_test_muerto_antes_de_3_dias(tmp_path):
    extra = [*_aceptar("2026-11-18T19:00:00-05:00", "P-20261118-005", "pausar"),
             ("2026-11-18T19:01:00-05:00", "ejecucion", {"id": "P-20261118-005", "tipo": "pausar",
                                                         "validate_only": False, "ok": True,
                                                         "detalle": f"campaña {CAMPANA} pausada (US$ 25 sin ventas)"})]
    v = _escribir(tmp_path, _base(extra))
    _cierres(v)
    act = {"data": [*ACTIVIDAD["data"], {"event_time": "2026-11-18T19:01:30-05:00", "event_type": "Estado",
                                         "object_id": CAMPANA, "actor_name": "Trovefy ejecutor"}]}
    r = comprobar(v, AHORA, act)
    assert r.pasa and [w["tipo"] for w in r.escrituras] == ["activar", "pausar"]


@pytest.mark.parametrize("pasa", [True, False])
def test_cli_criterio(tmp_path, monkeypatch, capsys, pasa):
    v = _escribir(tmp_path, _base())
    _cierres(v) if pasa else _cierres(v, ())
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    ruta = escribir_json(tmp_path / "home/.cache/trovefy/cierre/criterio/actividad.json", ACTIVIDAD)
    codigo = cli.main(["cierre", "criterio", "--actividad", str(ruta), "--ahora", AHORA.isoformat()])
    assert codigo == (0 if pasa else 1)
    out = capsys.readouterr().out
    assert ("PASA" if pasa else "NO PASA") in out
    texto = (v / "wiki/analisis/fase-3-criterio.md").read_text()
    assert "| " + ACT in texto and "act_0000000000000000" not in texto
