import json
import os
import stat
from datetime import date, datetime, timedelta, timezone

import pytest
from trovefy.buzon import (
    CupoAgotado,
    IdDuplicado,
    StopActivo,
    depositar,
    estado,
    nuevo_id,
)
from trovefy.cli import main
from trovefy_ejecutor.esquema import PropuestaInvalida

COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 10, tzinfo=COT)


def noop_sin_id(**c):
    d = {"tipo": "noop", "origen": "/probar", "motivo": "prueba"}
    d.update(c)
    return d


@pytest.fixture
def spool(tmp_path):
    s = tmp_path / "spool"
    (s / "entrada").mkdir(parents=True)
    (s / "procesadas").mkdir()
    (s / "estado").mkdir()
    return s


def test_depositar_genera_id_y_escribe_atomico(spool, tmp_path):
    (spool / "procesadas/P-20261112-004.json").write_text("{}")
    ruta = depositar(noop_sin_id(), spool=spool, vault=tmp_path / "v", ahora=AHORA)
    assert ruta.name == "P-20261112-005.json" and json.loads(ruta.read_text())["id"] == "P-20261112-005"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o640
    assert not list((spool / "entrada").glob(".*"))


def test_ids_del_ejecutor_no_cuentan(spool):
    (spool / "procesadas/P-20261112-801.json").write_text("{}")
    assert nuevo_id(spool, date(2026, 11, 12)) == "P-20261112-001"


def test_cupo_agotado(spool):
    (spool / "entrada/P-20261112-799.json").write_text("{}")
    with pytest.raises(CupoAgotado):
        nuevo_id(spool, date(2026, 11, 12))


def test_unidad_centavos_se_rechaza(spool, tmp_path):
    d = noop_sin_id(tipo="presupuesto", cuenta="act_0000000000000000", motivo="x",
                    operaciones=[{"entidad": "adset", "id": "1", "campo": "daily_budget",
                                  "de_esperado": 1, "a": 2, "unidad": "centavos", "moneda": "COP"}])
    with pytest.raises(PropuestaInvalida, match="minima"):
        depositar(d, spool=spool, vault=tmp_path / "v", ahora=AHORA)
    assert not list((spool / "entrada").iterdir())


def test_depositar_con_stop(spool, tmp_path):
    v = tmp_path / "v"
    (v / ".trovefy").mkdir(parents=True)
    (v / ".trovefy/STOP").write_text("")
    with pytest.raises(StopActivo):
        depositar(noop_sin_id(), spool=spool, vault=v, ahora=AHORA)
    assert not list((spool / "entrada").iterdir())


def test_depositar_invalida(spool, tmp_path):
    with pytest.raises(PropuestaInvalida):
        depositar(noop_sin_id(extra=1), spool=spool, vault=tmp_path / "v", ahora=AHORA)
    assert not list((spool / "entrada").iterdir())


def test_id_de_claude_duplicado_o_fuera_de_rango(spool, tmp_path):
    kw = {"spool": spool, "vault": tmp_path / "v", "ahora": AHORA}
    depositar(noop_sin_id(id="P-20261112-010"), **kw)
    with pytest.raises(IdDuplicado):
        depositar(noop_sin_id(id="P-20261112-010"), **kw)
    with pytest.raises(PropuestaInvalida):
        depositar(noop_sin_id(id="P-20261112-850"), **kw)


def test_no_sigue_enlaces_simbolicos(spool, tmp_path):
    objetivo = tmp_path / "otro.json"
    (spool / "entrada/.P-20261112-001.json.tmp").symlink_to(objetivo)
    with pytest.raises(OSError):
        depositar(noop_sin_id(), spool=spool, vault=tmp_path / "v", ahora=AHORA)
    assert not objetivo.exists()


def test_estado_latido_viejo(spool):
    (spool / "estado/latido.json").write_text(json.dumps(
        {"fecha": (AHORA - timedelta(minutes=10)).isoformat(), "version": "1", "modo": "real"}))
    (spool / "estado/meta.json").write_text("{roto")
    (spool / "entrada/P-20261112-001.json").write_text("{}")
    e = estado(spool, AHORA)
    assert e["latido_viejo"] is True and e["pendientes"] == 1 and e["meta"] is None


def test_estado_sin_latido_es_viejo(spool):
    assert estado(spool, AHORA)["latido_viejo"] is True


def test_cli_lee_de_stdin(spool, tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("TROVEFY_SPOOL", str(spool))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "v"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(noop_sin_id())))
    assert main(["buzon", "depositar", "-"]) == 0
    assert "P-" in capsys.readouterr().out
    assert len(list((spool / "entrada").glob("P-*.json"))) == 1


def test_cli_stop_codigo_3_e_invalida_1(spool, tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("TROVEFY_SPOOL", str(spool))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "v"))
    monkeypatch.setattr("sys.stdin", io.StringIO("{no json"))
    assert main(["buzon", "depositar", "-"]) == 1
    (tmp_path / "v/.trovefy").mkdir(parents=True)
    (tmp_path / "v/.trovefy/STOP").write_text("")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(noop_sin_id())))
    assert main(["buzon", "depositar", "-"]) == 3


def test_cli_estado_no_imprime_chat_id(spool, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TROVEFY_SPOOL", str(spool))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "v"))
    (spool / "estado/emparejamiento.json").write_text(json.dumps({"emparejado": True, "fecha": "x", "chat_id": 987654321}))
    assert main(["buzon", "estado"]) == 0
    salida = capsys.readouterr().out
    assert "987654321" not in salida and "ejecutor parado" in salida
    assert os.environ["TROVEFY_SPOOL"] == str(spool)
