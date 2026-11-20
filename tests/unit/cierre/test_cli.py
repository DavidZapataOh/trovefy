"""`trovefy cierre` de punta a punta con instantáneas ficticias y el buzón en tmp_path (plan 24, Tarea 7)."""

import pytest
from trovefy import cierre_cli, cli
from unit.montar.ejemplos import escribir_spool

from .ejemplos import (
    CAMBIO,
    MANANA,
    NOCHE,
    STORE,
    TRM,
    campanas,
    escribir_json,
    fx,
    vault_cierre,
    venta,
    ventas_pagina,
)

CACHE = ("home", ".cache", "trovefy", "cierre", "2026-11-19")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    v = vault_cierre(tmp_path)
    escribir_spool(tmp_path)
    monkeypatch.setattr(cierre_cli, "_trm", lambda _v, _d: TRM)
    monkeypatch.setattr(cierre_cli, "_cambio", lambda _v, _d: CAMBIO)
    return v, tmp_path.joinpath(*CACHE)


def _lecturas(cache, ventas=None):
    escribir_json(cache / "cuentas.json", fx("ad_accounts.json"))
    escribir_json(cache / "meta-2026-11-19.json", campanas("2026-11-19"))
    escribir_json(cache / "meta-2026-11-18.json", campanas("2026-11-18", "40000"))
    pagina = ventas_pagina(ventas if ventas is not None else [venta("A"), venta("B", "7.90", post=True),
                                                              venta("ORD-0003")])
    escribir_json(cache / f"ventas-{STORE.replace('-', '')[:8]}-p1.json", pagina)


def _salida(capsys):
    return capsys.readouterr().out


def test_preparar_lista_llamadas_solo_lectura(entorno, capsys):
    assert cli.main(["cierre", "preparar", "--ahora", MANANA.isoformat()]) == 0
    out = _salida(capsys)
    assert "Cierre del 19/11/2026" in out and "act_…0000" in out and "act_0000000000000000" not in out
    assert "ads_get_ad_entities" in out and "impultienda_listar_ventas" in out and "ads_get_ad_accounts" in out
    assert out.count("meta-2026-11-") == 7 and "~/.cache/trovefy/cierre/2026-11-19/" in out
    for escritura in ("ads_update", "ads_create", "impultienda_ver_pago", "confirmar"):
        assert escritura not in out


def test_preparar_noche_es_hoy(entorno, capsys):
    assert cli.main(["cierre", "preparar", "--noche", "--ahora", NOCHE.isoformat()]) == 0
    assert "provisional" in _salida(capsys)


def test_calcular_sin_instantanea_sale_1(entorno, capsys):
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--ahora", MANANA.isoformat()]) == 1
    assert "falta la lectura obligatoria" in capsys.readouterr().err


def test_calcular_de_punta_a_punta(entorno, capsys):
    v, cache = entorno
    _lecturas(cache)
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--ahora", MANANA.isoformat()]) == 0
    out = _salida(capsys)
    # 99.200 COP / 4.000 = 24,80; bruto 13,90 + 7,90 EUR × 1,10 = 23,98; comisión 3 % + 2 × 0,30 = 1,32 → neto 22,66
    assert "Cierre del 19/11\nGasto Meta: 24,80\nNeto: 22,66\nGanancia: -2,14" in out
    assert "Mensaje del bot depositado: P-20261120-" in out
    meta = (v / "wiki/analisis/cierres/2026-11-19.md").read_text()
    assert "fiabilidad: alta" in meta and "ORD-0003" not in meta.split("informe:")[0].split("por_campana")[0]
    assert "2026-11-18,act_0000000000000000,120000000000000001,40000.00,COP" in (v / "ledger/gasto/2026-11.csv").read_text()
    assert "prueba" in (v / "ledger/ventas/2026-11.csv").read_text()
    assert "· cierre ·" in (v / "log.md").read_text()
    assert cli.main(["cierre", "ver"]) == 0 and "Ganancia: -2,14" in _salida(capsys)


def test_calcular_sin_comisiones_dice_motivo(entorno, tmp_path, capsys):
    v, cache = entorno
    import yaml
    ruta = v / "config" / "economia.yaml"
    datos = yaml.safe_load(ruta.read_text())
    datos["plataformas"]["whop"]["comision_pct"]["valor"] = None
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False))
    _lecturas(cache)
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--ahora", MANANA.isoformat(), "--sin-alerta"]) == 0
    out = _salida(capsys)
    assert "Gasto Meta: 24,80" in out and "Neto: — (falta la comisión de Whop)" in out


def test_stop_no_deposita(entorno, capsys):
    v, cache = entorno
    _lecturas(cache)
    (v / ".trovefy").mkdir(exist_ok=True)
    (v / ".trovefy" / "STOP").write_text("x")
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--ahora", MANANA.isoformat()]) == 0
    out = _salida(capsys)
    assert "no se depositó" in out and "STOP" in out


def test_rutina_registra_log(entorno, capsys):
    v, cache = entorno
    _lecturas(cache)
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--noche", "--rutina",
                     "--ahora", NOCHE.isoformat()]) == 0
    log = v / "rutinas/log/2026-11-19/cierre-noche.md"
    assert "Próximos movimientos" in log.read_text() and (v / "rutinas/log/2026-11-19/cierre-noche.ok").exists()


def test_rutina_sin_lecturas_sale_con_huecos(entorno, capsys):
    _v, _ = entorno
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--rutina", "--sin-alerta",
                     "--ahora", MANANA.isoformat()]) == 0
    out = _salida(capsys)
    assert "Gasto Meta: — (no medido: falta la lectura de Meta del 19/11)" in out and "fiabilidad baja" in out


def test_tiendas_y_esquema_y_prueba(entorno, tmp_path, capsys):
    v, cache = entorno
    (v / "config" / "cierre.yaml").unlink()
    ruta = escribir_json(cache / "tiendas.json", fx("listar_tiendas.json"))
    assert cli.main(["cierre", "tiendas", "--instantanea", str(ruta)]) == 0
    assert "→ p-0099-prueba-abc123 ZZ" in _salida(capsys)
    rv = escribir_json(cache / "v.json", fx("listar_ventas.json"))
    assert cli.main(["cierre", "esquema", "--instantanea", str(rv), "--ahora", MANANA.isoformat()]) == 0
    assert (v / "config/esquemas/impultienda-pedidos.yaml").exists()
    assert cli.main(["cierre", "prueba", "--tienda", STORE, "--orden", "ORD-0003", "--fuente", "usuario: «sí»"]) == 0
    assert "ORD-0003" in (v / "config/cierre.yaml").read_text()


def test_export_respaldo(entorno, capsys):
    _v, cache = entorno
    escribir_json(cache / "meta-2026-11-19.json", campanas("2026-11-19"))
    from .ejemplos import FIXTURES
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--export", str(FIXTURES / "export-ventas.csv"),
                     "--sin-alerta", "--ahora", MANANA.isoformat()]) == 0
    assert "fiabilidad media" in _salida(capsys)


def test_json_roto_es_error_de_uso(entorno, capsys):
    _, cache = entorno
    cache.mkdir(parents=True)
    (cache / "meta-2026-11-19.json").write_text("{roto")
    assert cli.main(["cierre", "calcular", "--dia", "2026-11-19", "--ahora", MANANA.isoformat()]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error:") and "Traceback" not in err
