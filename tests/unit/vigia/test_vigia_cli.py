import json
from datetime import datetime, timedelta, timezone

import pytest
from trovefy import cli
from trovefy.aprobaciones import fuentes
from trovefy.aprobaciones.fuentes import BuzonNoDisponible
from trovefy.vigia import comprobaciones as c

COT = timezone(timedelta(hours=-5))


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    spool = tmp_path / "spool"
    (spool / "estado").mkdir(parents=True)
    viejo = datetime(2020, 1, 1, tzinfo=COT).isoformat()
    (spool / "estado" / "latido.json").write_text(json.dumps({"fecha": viejo, "avisos": []}))
    monkeypatch.setenv("TROVEFY_VAULT", str(vault))
    monkeypatch.setattr(c, "fuentes_por_defecto", lambda: c.Fuentes(
        spool=spool, unidades=tmp_path / "u", ruta_env=tmp_path / "no.env",
        uso_disco=lambda p: (100 << 30, 1 << 30, 99 << 30)))
    return vault


def test_cli_rutina_registra_log(entorno, monkeypatch, capsys):
    depositos = []
    monkeypatch.setattr(fuentes, "depositar", lambda v, d, ahora=None: depositos.append(d) or "P-20261112-001")
    assert cli.main(["vigia", "--rutina"]) == 0
    logs = list((entorno / "rutinas" / "log").glob("*/vigia.md"))
    assert len(logs) == 1 and "latido" in logs[0].read_text()
    assert len(depositos) == 1 and depositos[0]["tipo"] == "alerta"
    assert "latido" in capsys.readouterr().out


def test_cli_sin_buzon_no_falla(entorno, monkeypatch, capsys):
    def sin(*_a, **_k):
        raise BuzonNoDisponible("el buzón aún no está instalado (plan 12)")

    monkeypatch.setattr(fuentes, "depositar", sin)
    assert cli.main(["vigia"]) == 0
    assert "no medido: aviso por Telegram (el buzón aún no está instalado (plan 12))" in capsys.readouterr().out


def test_cli_sin_alerta_no_deposita(entorno, monkeypatch):
    def no(*_a, **_k):
        raise AssertionError("no debe depositar")

    monkeypatch.setattr(fuentes, "depositar", no)
    assert cli.main(["vigia", "--sin-alerta"]) == 0
