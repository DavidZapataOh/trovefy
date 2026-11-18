"""`trovefy tracking preparar|dataset|tienda|capi|utm` (plan 19, Tarea 7)."""

import importlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, TIENDA, P, vault_embudo
from trovefy import cli
from trovefy.tracking.modelo import PLANTILLA_UTM
from trovefy.tracking.salida import leer_tracking

from tracking.test_publico import _abrir, _html

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "tracking"
TOKEN_FALSO = "EAA" + "Bq7" * 10


@pytest.fixture
def vault(tmp_path, monkeypatch):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    v = vault_embudo(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(tracking_cli, "_ahora",
                        lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("America/Bogota")))
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({}))
    return v


def _cmd(*args: str) -> list[str]:
    return ["tracking", *args, "--producto", P, "--pais", PAIS]


def _preparar_y_dataset(vault) -> None:
    assert cli.main(_cmd("preparar")) == 0
    assert cli.main([*_cmd("dataset"), "--instantanea", str(FIX / "datasets.json")]) == 0


def test_preparar(vault, capsys):
    assert cli.main(_cmd("preparar")) == 0
    out = capsys.readouterr().out
    assert "SOMATIX ZZ" in out and "Generar identificador de acceso" in out
    t = leer_tracking(vault, P, PAIS)
    assert t.estado == "pendiente" and t.dataset_nombre == "SOMATIX ZZ" and t.dataset_id is None
    assert t.emisores["Purchase"] == "impultienda"


def test_preparar_no_guarda_token(vault, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([*_cmd("preparar"), "--token", TOKEN_FALSO])
    assert e.value.code == 2
    assert cli.main(_cmd("preparar")) == 0
    for archivo in vault.rglob("*"):
        if archivo.is_file():
            assert "EAA" not in archivo.read_text(encoding="utf-8", errors="ignore"), archivo


def test_preparar_estado_incorrecto(tmp_path, monkeypatch, capsys):
    v = vault_embudo(tmp_path, estado="auditado")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    assert cli.main(_cmd("preparar")) == 2
    assert "auditado" in capsys.readouterr().err


def test_preparar_no_pisa_lo_hecho(vault, capsys):
    _preparar_y_dataset(vault)
    assert cli.main(_cmd("preparar")) == 0
    assert leer_tracking(vault, P, PAIS).dataset_id == "1111111111111111"


def test_dataset(vault, capsys):
    _preparar_y_dataset(vault)
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.dataset_id) == ("dataset", "1111111111111111")
    assert "1111111111111111" in capsys.readouterr().out


def test_dataset_sin_preparar(vault, capsys):
    assert cli.main([*_cmd("dataset"), "--instantanea", str(FIX / "datasets.json")]) == 2
    assert "preparar" in capsys.readouterr().err


def test_dataset_no_encontrado(vault, capsys):
    assert cli.main(_cmd("preparar")) == 0
    assert cli.main([*_cmd("dataset"), "--instantanea", str(FIX / "datasets-vacio.json")]) == 1
    assert "no medido" in capsys.readouterr().out
    assert leer_tracking(vault, P, PAIS).estado == "pendiente"


def test_tienda_ok_configurado(vault, monkeypatch, capsys):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    _preparar_y_dataset(vault)
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({TIENDA + "/": _html("tienda-con-pixel.html"),
                                                        TIENDA + "/checkout": _html("tienda-con-pixel.html")}))
    assert cli.main(_cmd("tienda")) == 0
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.pixel_publico) == ("configurado", "ok")


def test_pixel_no_visto_y_mcp_coincide_configurado(vault, monkeypatch, capsys):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    _preparar_y_dataset(vault)
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({TIENDA + "/": _html("tienda-sin-pixel.html"),
                                                        TIENDA + "/checkout": _html("tienda-sin-pixel.html")}))
    assert cli.main([*_cmd("tienda"), "--instantanea-mcp", str(FIX / "mcp-tracking-leido.json")]) == 0
    t = leer_tracking(vault, P, PAIS)
    assert (t.estado, t.pixel_publico, t.pixel_config) == ("configurado", "no_visto", "mcp")


def test_tienda_otro_pixel_es_problema(vault, monkeypatch, capsys):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    _preparar_y_dataset(vault)
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({TIENDA + "/": _html("tienda-dos-pixeles.html"),
                                                        TIENDA + "/checkout": _html("tienda-dos-pixeles.html")}))
    assert cli.main(_cmd("tienda")) == 1
    out = capsys.readouterr().out
    assert "la tienda carga otro píxel (5555555555555555): quítalo (V1 0:31:50)" in out
    t = leer_tracking(vault, P, PAIS)
    assert t.estado == "dataset" and t.pixel_publico == "otro"


def test_tienda_sin_datos_no_medido(vault, capsys):
    _preparar_y_dataset(vault)
    assert cli.main(_cmd("tienda")) == 1
    assert "no medido" in capsys.readouterr().out
    assert leer_tracking(vault, P, PAIS).estado == "dataset"


def test_tienda_mcp_contradice(vault, monkeypatch, capsys):
    tracking_cli = importlib.import_module("trovefy.tracking_cli")

    _preparar_y_dataset(vault)
    datos = json.loads((FIX / "mcp-tracking-leido.json").read_text(encoding="utf-8"))
    datos["structuredContent"]["tiendas"][0]["tracking"]["pixels"][0]["pixel_id"] = "7777777777777777"
    ruta = vault.parent / "mcp.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(tracking_cli, "_abrir", _abrir({TIENDA + "/": _html("tienda-con-pixel.html"),
                                                        TIENDA + "/checkout": _html("tienda-con-pixel.html")}))
    assert cli.main([*_cmd("tienda"), "--instantanea-mcp", str(ruta)]) == 1
    assert "1111111111111111" in capsys.readouterr().out
    assert leer_tracking(vault, P, PAIS).estado == "dataset"


def test_tienda_sin_dataset(vault, capsys):
    assert cli.main(_cmd("preparar")) == 0
    assert cli.main(_cmd("tienda")) == 2
    assert "dataset" in capsys.readouterr().err


def test_capi_dicho_no_es_visto(vault, capsys):
    _preparar_y_dataset(vault)
    assert cli.main([*_cmd("capi"), "--dicho", "Ya pegué el token y le di a Guardar"]) == 0
    t = leer_tracking(vault, P, PAIS)
    assert t.capi == "dicho"
    assert t.estado == "dataset"  # decirlo no lo verifica: solo la Tarea 8 lo sube a visto_en_meta
    assert any("evidencia/tracking-pixel-" in e for e in t.evidencia)


def test_capi_con_token_no_se_guarda(vault, capsys):
    _preparar_y_dataset(vault)
    assert cli.main([*_cmd("capi"), "--dicho", f"el token es {TOKEN_FALSO}"]) == 2
    err = capsys.readouterr().err
    assert "secreto" in err and TOKEN_FALSO not in err
    assert leer_tracking(vault, P, PAIS).capi is None


def test_utm(vault, capsys):
    assert cli.main(["tracking", "utm"]) == 0
    assert capsys.readouterr().out.strip() == PLANTILLA_UTM


def test_instantanea_ilegible(vault, capsys):
    assert cli.main(_cmd("preparar")) == 0
    ruta = vault.parent / "rota.json"
    ruta.write_text("{no es json", encoding="utf-8")
    assert cli.main([*_cmd("dataset"), "--instantanea", str(ruta)]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_ejecutor_registrado_sin_dataset(vault, capsys):
    # Tarea 9: `trovefy tracking ejecutor` despacha a trovefy.tracking.ejecutor.
    assert cli.main(_cmd("preparar")) == 0
    capsys.readouterr()
    assert cli.main(_cmd("ejecutor")) == 2
    assert "falta el dataset" in capsys.readouterr().err


def test_ejecutor_registrado_sin_pagina(vault, capsys):
    _preparar_y_dataset(vault)
    capsys.readouterr()
    assert cli.main(_cmd("ejecutor")) == 2
    assert "página de Facebook" in capsys.readouterr().err


def test_ejecutor_sale_en_la_ayuda(vault, capsys):
    with pytest.raises(SystemExit):
        cli.main(["tracking", "--help"])
    assert "ejecutor" in capsys.readouterr().out
