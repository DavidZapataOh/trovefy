"""CLI ``trovefy-ejecutor permitir`` y ``comprobar-dataset`` (plan 19, Tarea 9). Sin red: Graph falso."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from trovefy_ejecutor import cli
from trovefy_ejecutor.cli import main
from trovefy_ejecutor.config import rutas_por_defecto
from trovefy_ejecutor.graph import ErrorGraph, ErrorRed
from trovefy_ejecutor.limites import cargar_limites
from trovefy_ejecutor.permitidos import comprobar_dataset
from trovefy_ejecutor.secretos import guardar_secretos

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
CUENTA = "act_0000000000000000"
DATASET = "1111111111111111"
PAGINA = "2222222222222222"
TOKEN_META = "fakemeta_" + "x1y2z3" * 4
AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_EJECUTOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.delenv("TROVEFY_VAULT", raising=False)
    r = rutas_por_defecto()
    r.secretos.parent.mkdir(parents=True)
    r.base.parent.mkdir(parents=True)
    guardar_secretos(r.secretos, {"META_TOKEN": TOKEN_META, "TELEGRAM_BOT_TOKEN": "123456:" + "B" * 35,
                                  "HMAC_CLAVE": "ab" * 32})
    os.chmod(r.secretos, 0o600)
    r.limites.write_text(PLANTILLA.read_text())
    os.chmod(r.limites, 0o600)
    return r


class GraphFalso:
    def __init__(self, respuesta=None, error: Exception | None = None):
        self.respuesta = respuesta
        self.error = error
        self.leidos: list[tuple[str, list[str]]] = []

    def leer(self, id: str, campos):
        self.leidos.append((id, list(campos)))
        if self.error is not None:
            raise self.error
        return self.respuesta


def _auditoria(r) -> list[dict]:
    return [json.loads(ln) for ln in r.auditoria.read_text().splitlines()]


def test_cli_permitir_audita(mundo, capsys):
    assert main(["permitir", "--dataset", DATASET]) == 0
    assert "añadido" in capsys.readouterr().out
    assert DATASET in cargar_limites(mundo.limites).cuentas[CUENTA].datasets_permitidos
    eventos = [e for e in _auditoria(mundo) if "limite_cambiado" in json.dumps(e)]
    assert len(eventos) == 1
    texto = json.dumps(eventos[0])
    assert '"clave": "datasets_permitidos"' in texto and f'"a": "{DATASET}"' in texto and '"de": null' in texto


def test_cli_permitir_pagina_y_ya_estaba(mundo, capsys):
    assert main(["permitir", "--pagina", PAGINA, "--cuenta", CUENTA]) == 0
    assert main(["permitir", "--pagina", PAGINA]) == 0
    salida = capsys.readouterr().out
    assert "añadido" in salida and "ya estaba" in salida
    assert PAGINA in cargar_limites(mundo.limites).cuentas[CUENTA].paginas_permitidas
    assert len([e for e in _auditoria(mundo) if "paginas_permitidas" in json.dumps(e)]) == 1


def test_cli_permitir_id_invalido(mundo, capsys):
    antes = mundo.limites.read_bytes()
    assert main(["permitir", "--dataset", "12ab"]) == 2
    assert mundo.limites.read_bytes() == antes
    assert not mundo.auditoria.exists()


def test_cli_permitir_cuenta_ajena(mundo, capsys):
    antes = mundo.limites.read_bytes()
    assert main(["permitir", "--dataset", DATASET, "--cuenta", "act_1234"]) == 2
    assert mundo.limites.read_bytes() == antes


def test_cli_permitir_exige_uno(mundo):
    with pytest.raises(SystemExit):
        main(["permitir"])
    with pytest.raises(SystemExit):
        main(["permitir", "--dataset", DATASET, "--pagina", PAGINA])


def test_comprobar_dataset_graph_falso(mundo, monkeypatch, capsys):
    main(["permitir", "--dataset", DATASET])
    main(["permitir", "--pagina", PAGINA])
    g = GraphFalso({"id": DATASET, "name": "PRUEBA ZZ"})
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: g)
    assert main(["comprobar-dataset", DATASET]) == 0
    d = json.loads((mundo.spool / "estado" / "dataset.json").read_text())
    assert d["dataset_id"] == DATASET and d["nombre"] == "PRUEBA ZZ"
    assert d["lectura_ok"] is True and d["en_limites"] is True and d["pagina_en_limites"] is True
    assert d["motivo"] is None and d["fecha"]
    assert g.leidos == [(DATASET, ["id", "name"])]
    assert TOKEN_META not in capsys.readouterr().out


def test_comprobar_dataset_fuera_de_limites_sale_1(mundo, monkeypatch):
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: GraphFalso({"id": DATASET, "name": "PRUEBA ZZ"}))
    assert main(["comprobar-dataset", DATASET]) == 1
    d = json.loads((mundo.spool / "estado" / "dataset.json").read_text())
    assert d["lectura_ok"] is True and d["en_limites"] is False and d["pagina_en_limites"] is False


def test_comprobar_dataset_sin_acceso(mundo, monkeypatch, capsys):
    error = ErrorGraph(100, 33, f"Unsupported get request. token {TOKEN_META}")
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: GraphFalso(error=error))
    assert main(["comprobar-dataset", DATASET]) == 1
    d = json.loads((mundo.spool / "estado" / "dataset.json").read_text())
    assert d["lectura_ok"] is False and d["nombre"] is None
    assert d["motivo"] and "100" in d["motivo"] and TOKEN_META not in d["motivo"]
    c = capsys.readouterr()
    assert TOKEN_META not in c.out + c.err


def test_comprobar_dataset_funcion():
    lim = cargar_limites(PLANTILLA, exigir_0600=False)
    d = comprobar_dataset(GraphFalso(error=ErrorRed("timeout")), DATASET, lim, CUENTA, AHORA)
    assert d == {"fecha": AHORA.isoformat(), "dataset_id": DATASET, "nombre": None, "lectura_ok": False,
                 "motivo": d["motivo"], "en_limites": False, "pagina_en_limites": False}
    assert "conexión" in d["motivo"]
    otro = comprobar_dataset(GraphFalso({"id": "9999", "name": "X"}), DATASET, lim, CUENTA, AHORA)
    assert otro["lectura_ok"] is False
    with pytest.raises(ValueError):
        comprobar_dataset(GraphFalso({}), "act_1", lim, CUENTA, AHORA)


def test_comprobar_dataset_id_invalido(mundo, monkeypatch):
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: GraphFalso({"id": DATASET}))
    assert main(["comprobar-dataset", "12ab"]) == 2
    assert not (mundo.spool / "estado" / "dataset.json").exists()
