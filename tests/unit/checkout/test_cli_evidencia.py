"""`trovefy checkout evidencia` (plan 19, Tarea 6): registrar lo que pega el usuario, sin abrir ningún panel."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy import cli
from trovefy.embudo.contexto import cargar_contexto
from trovefy.embudo.pegado import indice

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TOKEN_FALSO = "EAA" + "Bq7" * 10


@pytest.fixture
def vault(tmp_path, monkeypatch):
    from trovefy import checkout_cli

    v = vault_embudo(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(checkout_cli, "_ahora",
                        lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")))
    return v


def _base(*extra: str) -> list[str]:
    return ["checkout", "evidencia", "--producto", P, "--pais", PAIS, *extra]


def test_cli_captura_con_valores(vault, tmp_path, capsys):
    origen = tmp_path / "c.png"
    origen.write_bytes(PNG)
    assert cli.main(_base("--clave", "ver-como", "--desde", str(origen), "--valor", "precio=13,90 €",
                          "--valor", "moneda=EUR")) == 0
    out = capsys.readouterr().out
    assert "checkout/ZZ/evidencia/ver-como-2026-11-17T120000.png" in out
    pegados = indice(vault, cargar_contexto(vault, P, PAIS))["ver-como"]
    assert pegados[0].valores == {"precio": "13,90 €", "moneda": "EUR"}


def test_cli_dicho(vault, capsys):
    assert cli.main(_base("--clave", "reembolso", "--dicho", "Ya lo reembolsé desde el panel")) == 0
    assert indice(vault, cargar_contexto(vault, P, PAIS))["reembolso"][0].tipo == "dicho"


def test_cli_desde_y_dicho_no_van_juntos(vault, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(_base("--clave", "reembolso", "--dicho", "x", "--desde", str(tmp_path / "c.png")))
    assert e.value.code == 2


def test_cli_valor_sin_desde(vault, capsys):
    assert cli.main(_base("--clave", "reembolso", "--dicho", "hecho", "--valor", "a=b")) == 2
    assert "--valor" in capsys.readouterr().err


def test_cli_valor_mal_escrito(vault, tmp_path, capsys):
    origen = tmp_path / "c.png"
    origen.write_bytes(PNG)
    assert cli.main(_base("--clave", "producto", "--desde", str(origen), "--valor", "precio")) == 2


def test_cli_secreto_sin_traza(vault, tmp_path, capsys):
    origen = tmp_path / "e.txt"
    origen.write_text(f"token {TOKEN_FALSO}", encoding="utf-8")
    assert cli.main(_base("--clave", "email-entrega", "--desde", str(origen))) == 2
    err = capsys.readouterr().err
    assert "secreto" in err and "Traceback" not in err and TOKEN_FALSO not in err


def test_cli_clave_desconocida(vault, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(_base("--clave", "token-capi", "--dicho", "x"))
    assert e.value.code == 2
