import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from trovefy import caja_cli, cli
from trovefy.aprobaciones import fuentes
from trovefy.caja.config import iniciar_caja

ACT = "act_0000000000000000"
COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 9, 0, tzinfo=COT)
FIX = Path(__file__).resolve().parents[2] / "fixtures" / "trm" / "2026-11-11.json"


class _Resp(io.BytesIO):
    def geturl(self):
        return "https://www.datos.gov.co/resource/32sa-8pi3.json"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    spool = tmp_path / "spool"
    monkeypatch.setenv("TROVEFY_VAULT", str(vault))
    monkeypatch.setenv("TROVEFY_SPOOL", str(spool))
    monkeypatch.setattr(caja_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(
        "trovefy.trm._abrir_seguro", lambda url, timeout=15: _Resp(FIX.read_bytes())
    )
    return vault, spool


def con_caja(vault):
    iniciar_caja(vault, ACT, "COP")


def estado(spool, **meta):
    d = spool / "estado"
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(
        json.dumps({"cuenta": ACT, "currency": "COP", "offset": 1, "amount_spent": 0,
                    "spend_cap": 1000000, "fecha": "2026-11-12T13:00:00+00:00", **meta}),
        encoding="utf-8",
    )
    (d / "limites.json").write_text(
        json.dumps({"cuentas": {ACT: {"moneda": "COP", "offset": 1,
                                      "tope_gasto_diario_total": 5000000}}}),
        encoding="utf-8",
    )


def test_cli_ver_sin_caja_yaml(entorno, capsys):
    assert cli.main(["caja", "ver"]) == 2
    assert "trovefy caja iniciar" in capsys.readouterr().err


def test_cli_iniciar_y_ver(entorno, capsys):
    vault, _ = entorno
    assert cli.main(["caja", "iniciar", "--moneda", "COP"]) == 0
    assert (vault / "config" / "caja.yaml").is_file()
    assert cli.main(["caja", "iniciar"]) == 2  # nunca sobrescribe
    capsys.readouterr()
    assert cli.main(["caja", "ver"]) == 0
    out = capsys.readouterr().out
    assert "Caja: tests 280 de 280 (huecos: 9)" in out
    assert (vault / "wiki" / "analisis" / "caja.md").is_file()
    assert "· caja · ver caja" in (vault / "log.md").read_text(encoding="utf-8")


def test_cli_mover_y_anotar(entorno, capsys):
    vault, _ = entorno
    con_caja(vault)
    cita = 'muévele 50 de la reserva a tests, "ya" $50'
    assert cli.main(["caja", "mover", "--de", "reserva", "--a", "tests",
                     "--importe", "50", "--cita", cita]) == 0
    decision = vault / "decisiones" / "caja" / "2026-11-12-090000-mover.md"
    assert f"> {cita}\n" in decision.read_text(encoding="utf-8")
    assert cli.main(["caja", "mover", "--de", "reserva", "--a", "cobrado",
                     "--importe", "5", "--cita", "x"]) == 2
    assert cli.main(["caja", "anotar", "--importe", "10.50", "--moneda", "USD",
                     "--nota", "dominio"]) == 0
    capsys.readouterr()
    assert cli.main(["caja", "anotar", "--importe", "30", "--moneda", "USD", "--nota", "x"]) == 0
    assert "sobre Herramientas agotado: para y avisa" in capsys.readouterr().out


def test_cli_anotar_cop_sin_trm(entorno, monkeypatch, capsys):
    vault, _ = entorno
    con_caja(vault)
    monkeypatch.setattr("trovefy.trm._abrir_seguro", lambda url, timeout=15: (_ for _ in ()).throw(OSError()))
    assert cli.main(["caja", "anotar", "--importe", "1000", "--moneda", "COP", "--nota", "x"]) == 2
    assert "no medido: sin TRM vigente del 2026-11-12; no se anota" in capsys.readouterr().err


def test_cli_proponer_deposita(entorno, monkeypatch, capsys):
    vault, spool = entorno
    con_caja(vault)
    estado(spool)
    recogidas = []

    def falso(v, datos, ahora=None):
        recogidas.append(datos)
        return f"P-20261112-00{len(recogidas)}"

    monkeypatch.setattr(fuentes, "depositar", falso)
    assert cli.main(["caja", "proponer-limites"]) == 0
    assert any(d["tipo"] == "limite_cuenta" for d in recogidas)
    out = capsys.readouterr().out
    assert "P-20261112-001" in out


def test_cli_proponer_sin_estado_dice_no_medido(entorno, monkeypatch, capsys):
    vault, _ = entorno
    con_caja(vault)
    monkeypatch.setattr(fuentes, "depositar", lambda *a, **k: pytest.fail("no debe depositar"))
    assert cli.main(["caja", "proponer-limites"]) == 0
    assert "no medido" in capsys.readouterr().out


def test_cli_proponer_sin_buzon(entorno, monkeypatch, capsys):
    vault, spool = entorno
    con_caja(vault)
    estado(spool)
    monkeypatch.setitem(__import__("sys").modules, "trovefy.buzon", None)
    assert cli.main(["caja", "proponer-limites"]) == 1
    assert "el buzón aún no está instalado (plan 12)" in capsys.readouterr().err


def test_cli_iniciar_toma_la_moneda_de_la_decision_del_paso_06(entorno, capsys):
    from trovefy.arranque.estado import marcar_hecho
    from trovefy.caja.config import cargar_caja
    vault, _ = entorno
    marcar_hecho(vault, "06", datos={"act_id": "0000000000000000", "moneda": "COP", "zona": "America/Bogota"})
    assert cli.main(["caja", "iniciar"]) == 0
    assert cargar_caja(vault).cuenta == cargar_caja(vault).cuenta.__class__(ACT, "COP")
    assert "Moneda: COP (decisión del paso 06)" in capsys.readouterr().out


def test_cli_iniciar_sin_decision_ni_moneda(entorno, capsys):
    from trovefy.arranque.estado import marcar_hecho
    from trovefy.caja.config import cargar_caja
    vault, _ = entorno
    marcar_hecho(vault, "06", datos={"act_id": "0000000000000000"})
    assert cli.main(["caja", "iniciar"]) == 0
    assert cargar_caja(vault).cuenta.moneda is None
    assert "sin confirmar" in capsys.readouterr().out
