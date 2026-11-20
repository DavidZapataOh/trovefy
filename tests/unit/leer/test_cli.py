"""`trovefy leer` de punta a punta con instantáneas ficticias y el buzón en tmp_path (plan 23, Tarea 9)."""
import json
from datetime import datetime

import pytest
from trovefy import cli, leer_cli
from trovefy.caja.config import cargar_caja
from trovefy.fx import Cambio
from trovefy.montar.tanda import bloque_pais
from unit.montar.ejemplos import escribir_spool

from .ejemplos import (
    ANUNCIOS,
    CAMPANA,
    CONJUNTOS,
    PAIS,
    TRM,
    P,
    escribir_json,
    meta_adsets,
    utm,
    vault_test,
)

MANANA = datetime.fromisoformat("2026-11-20T07:30:00-05:00")
TARDE = datetime.fromisoformat("2026-11-20T16:00:00-05:00")
NOCHE = datetime.fromisoformat("2026-11-20T23:00:00-05:00")
BASE = ("--producto", P, "--pais", PAIS)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    v = vault_test(tmp_path)
    escribir_spool(tmp_path)
    monkeypatch.setattr(leer_cli, "_trm", lambda _v, _d: TRM)
    monkeypatch.setattr(leer_cli, "_cambio", lambda _v, _d: Cambio({"EUR": 1.0, "USD": 1.08}, "2026-11-19"))
    return v, tmp_path


def _filas(gastos_cop: list[str], presupuestos=None, estado="ACTIVE"):
    presupuestos = presupuestos or ["20000"] * len(gastos_cop)
    return meta_adsets([{"id": sid, "name": nombre, "daily_budget": pres, "effective_status": estado,
                         "insights": {"amount_spent": g, "omni_initiated_checkout": "0", "omni_purchase": "0",
                                      "link_click": "30", "landing_page_view": "20"}}
                        for (nombre, sid), g, pres in zip(CONJUNTOS.items(), gastos_cop, presupuestos, strict=True)])


def _importar(tmp, ahora, *, intradia=False, adsets=None, ventas=(), ventas_dia=None, dia=None):
    cache = tmp / "home" / ".cache" / "trovefy" / "leer" / P / PAIS
    args = ["leer", "importar", *BASE, "--ahora", ahora.isoformat(),
            "--meta-adset", str(escribir_json(cache / "meta-adset.json", adsets or _filas(["40000"] * 3))),
            "--utm-anuncio", str(escribir_json(cache / "utm-anuncio.json", utm(list(ventas))))]
    if intradia:
        args.append("--intradia")
    if dia is not None:
        args += ["--meta-dia", str(escribir_json(cache / "meta-dia.json", dia))]
    if ventas_dia is not None:
        args += ["--utm-dia", str(escribir_json(cache / "utm-dia.json", utm(list(ventas_dia))))]
    assert cli.main(args) == 0


def _entrada(tmp):
    return sorted((tmp / "spool" / "entrada").glob("P-*.json"))


def test_parte_25_sin_ventas_deposita_pausar_campana(entorno, capsys):
    v, tmp = entorno
    _importar(tmp, MANANA)  # 3 × 40.000 COP = US$ 30, 0 ventas
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()]) == 1
    [ruta] = _entrada(tmp)
    p = json.loads(ruta.read_text(encoding="utf-8"))
    assert p["tipo"] == "pausar" and p["prioridad"] == "alta" and p["operaciones"][0]["id"] == CAMPANA
    assert "C1 1:24:15" in p["motivo"] and p["origen"] == "/leer --parte"
    parte = (v / "wiki/analisis/partes/2026-11-20.md").read_text(encoding="utf-8")
    assert "| AD01 G1 mapa | mapa | 10,00 |" in parte and ruta.stem in parte
    assert "PI del píxel" not in parte or "desvío D1" in parte
    b = bloque_pais(v, P, PAIS)
    assert b["lectura"]["fiabilidad"] in ("media", "baja") and b["estado"] == "test"
    assert json.loads((v / "productos" / P / "trafico" / PAIS / "anuncios.json").read_text())[0]["nombre"] \
        == "AD01 G1 mapa"
    assert cargar_caja(v).tests[0].ventas == 0
    # misma lectura otra vez: la propuesta está pendiente, no se repite
    capsys.readouterr()
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()]) == 0
    assert len(_entrada(tmp)) == 1


def test_seco_no_deposita(entorno, capsys):
    v, tmp = entorno
    _importar(tmp, MANANA)
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat(), "--seco"]) == 1
    assert not _entrada(tmp) and "(seco) pausar" in capsys.readouterr().out
    assert not (v / "wiki/analisis/partes/2026-11-20.md").exists()


def test_stop_no_deposita_y_lo_dice(entorno, capsys):
    v, tmp = entorno
    (v / ".trovefy").mkdir(exist_ok=True)
    (v / ".trovefy" / "STOP").write_text("")
    _importar(tmp, MANANA)
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()]) == 1
    assert not _entrada(tmp) and "STOP" in capsys.readouterr().out


def test_intradia_no_mata_con_ventas(entorno):
    _, tmp = entorno
    ahora = datetime.fromisoformat("2026-11-23T10:00:00-05:00")  # > 72 h
    _importar(tmp, ahora, intradia=True, adsets=_filas(["200000"] * 3),
              ventas=[("AD03 G1 sueño", 2, 27.8)])  # ROAS muy bajo, pero intradía
    cli.main(["leer", "intradia", *BASE, "--ahora", ahora.isoformat()])
    for ruta in _entrada(tmp):  # los conjuntos sí se cortan (CPC); la campaña con ventas no
        p = json.loads(ruta.read_text(encoding="utf-8"))
        assert all(o["entidad"] != "campaign" for o in p["operaciones"])


def test_intradia_propone_x2_con_venta_nueva(entorno, capsys):
    v, tmp = entorno
    dia = meta_adsets([{"id": CONJUNTOS["AD03 G1 sueño"], "name": "AD03 G1 sueño", "daily_budget": "20000",
                        "insights": {"amount_spent": "20000"}}])
    _importar(tmp, TARDE, intradia=True, adsets=_filas(["10000", "10000", "20000"]),
              ventas=[("AD03 G1 sueño", 1, 13.9)], ventas_dia=[("AD03 G1 sueño", 1, 13.9)], dia=dia)
    assert cli.main(["leer", "intradia", *BASE, "--ahora", TARDE.isoformat()]) == 1
    [ruta] = _entrada(tmp)
    p = json.loads(ruta.read_text(encoding="utf-8"))
    op = p["operaciones"][0]
    assert p["tipo"] == "presupuesto" and op["id"] == CONJUNTOS["AD03 G1 sueño"]
    assert (op["de_esperado"], op["a"]) == (20000, 40000) and "S1 10:27" in p["motivo"]
    memoria = json.loads((v / "productos" / P / "trafico" / PAIS / "propuestas-leer.json").read_text())
    assert memoria["surf"]["2026-11-20"][CONJUNTOS["AD03 G1 sueño"]] == 1
    # la ronda siguiente sin venta nueva: no se toca
    capsys.readouterr()
    assert cli.main(["leer", "intradia", *BASE, "--ahora", TARDE.isoformat()]) == 0
    assert len(_entrada(tmp)) == 1


def test_base_a_las_23(entorno):
    _, tmp = entorno
    _importar(tmp, NOCHE, intradia=True, adsets=_filas(["10000"] * 3, ["20000", "40000", "80000"]))
    assert cli.main(["leer", "base", *BASE, "--ahora", NOCHE.isoformat()]) == 1
    [ruta] = _entrada(tmp)
    p = json.loads(ruta.read_text(encoding="utf-8"))
    assert p["tipo"] == "lote" and {o["a"] for o in p["operaciones"]} == {20000} and len(p["operaciones"]) == 2
    assert p["expira_en_min"] == 60


def test_estado_no_test_sale_2(tmp_path, capsys):
    vault_test(tmp_path, estado="listo")
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()]) == 2
    assert "/leer solo lee productos en test" in capsys.readouterr().err


def test_sin_lectura_sale_2(entorno, capsys):
    assert cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()]) == 2
    assert "trovefy leer importar" in capsys.readouterr().err


def test_economia_sin_comisiones_sale_1(tmp_path, capsys):
    vault_test(tmp_path, economia=False)
    assert cli.main(["leer", "economia", *BASE]) == 1
    out = capsys.readouterr().out
    assert "falta ruta_activa" in out and "US$ 25" in out


def test_preparar_dice_que_leer(entorno, capsys):
    assert cli.main(["leer", "preparar", *BASE, "--ahora", MANANA.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "ads_get_ad_entities nivel adset" in out and "impultienda_campanas_utm nivel anuncio" in out
    assert "2026-11-19..2026-11-19" in out


def test_estado_tras_ejecutar(entorno, capsys):
    from unit.montar.ejemplos import copia_ejecutor

    v, tmp = entorno
    _importar(tmp, MANANA)
    cli.main(["leer", "parte", *BASE, "--ahora", MANANA.isoformat()])
    [ruta] = _entrada(tmp)
    copia_ejecutor(v, ruta.stem, "pausar", "ejecutada")
    assert cli.main(["leer", "estado", *BASE, "--ahora", MANANA.isoformat()]) == 0
    assert bloque_pais(v, P, PAIS)["estado"] == "muerto" and "pasa a muerto" in capsys.readouterr().out
    assert ANUNCIOS  # ids ficticios del contrato 11
