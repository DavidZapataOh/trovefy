"""CLI trovefy-ejecutor (plan 12, tarea 7). Todo en tmp_path: sin red, sin HOME real, sin systemd."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ejecutor.falsos.graph_falso import CUENTA, mundo_basico
from trovefy_ejecutor import cli, instalacion
from trovefy_ejecutor.candado import candado
from trovefy_ejecutor.cli import main
from trovefy_ejecutor.comprobar_meta import comprobar_meta, informe_a_dict
from trovefy_ejecutor.config import rutas_por_defecto
from trovefy_ejecutor.secretos import cargar_secretos, guardar_secretos

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
TOKEN_META = "fakemeta_" + "x1y2z3" * 4
TOKEN_BOT = "123456:" + "B" * 35
HMAC = "ab" * 32


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_EJECUTOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.delenv("TROVEFY_VAULT", raising=False)
    r = rutas_por_defecto()
    r.secretos.parent.mkdir(parents=True)
    r.base.parent.mkdir(parents=True)
    guardar_secretos(r.secretos, {"META_TOKEN": TOKEN_META, "TELEGRAM_BOT_TOKEN": TOKEN_BOT, "HMAC_CLAVE": HMAC})
    os.chmod(r.secretos, 0o600)
    r.limites.write_text(PLANTILLA.read_text())
    os.chmod(r.limites, 0o600)
    return r


def _sin_tokens(cap) -> None:
    for t in (TOKEN_META, TOKEN_BOT, HMAC):
        assert t not in cap.out + cap.err


def test_simular_sale_0(tmp_path, capsys):
    assert main(["simular", "--raiz", str(tmp_path)]) == 0
    assert "callback falsificado" in capsys.readouterr().out


def test_simular_sin_raiz(capsys):
    assert main(["simular"]) == 0
    lineas = capsys.readouterr().out.splitlines()
    assert lineas and all(ln.startswith("OK ") for ln in lineas)


def test_emparejar_con_servicio_en_marcha(mundo, capsys):
    with candado(mundo.base.with_suffix(".lock")):
        assert main(["emparejar"]) == 3
    c = capsys.readouterr()
    assert "sudo systemctl stop trovefy-ejecutor" in c.out + c.err


def test_emparejar_reiniciar_tambien_bajo_candado(mundo):
    guardar_secretos(mundo.secretos, {"TELEGRAM_USER_ID": "7", "TELEGRAM_CHAT_ID": "7"})
    with candado(mundo.base.with_suffix(".lock")):
        assert main(["emparejar", "--reiniciar"]) == 3
    assert cargar_secretos(mundo.secretos).telegram_user_id == 7  # no se tocó


def test_emparejar_ya_emparejado_sin_traza(mundo, capsys):
    guardar_secretos(mundo.secretos, {"TELEGRAM_USER_ID": "5551234", "TELEGRAM_CHAT_ID": "5551234"})
    assert main(["emparejar"]) == 2
    c = capsys.readouterr()
    assert "ya emparejado" in c.err and "Traceback" not in c.err
    assert "5551234" not in c.out + c.err
    _sin_tokens(c)


def test_emparejar_reiniciar_borra_ids_y_llama(mundo, monkeypatch, capsys):
    guardar_secretos(mundo.secretos, {"TELEGRAM_USER_ID": "7", "TELEGRAM_CHAT_ID": "7"})
    vistos = {}

    def falso(cliente, almacen, secretos, mostrar, **kw):
        vistos["s"] = cargar_secretos(secretos)
        mostrar("Código de emparejamiento: 123456")

    monkeypatch.setattr(cli, "ejecutar_emparejamiento", falso)
    assert main(["emparejar", "--reiniciar"]) == 1  # sin emparejar al final
    assert vistos["s"].telegram_user_id is None and vistos["s"].telegram_chat_id is None
    assert vistos["s"].meta_token == TOKEN_META  # lo demás intacto
    c = capsys.readouterr()
    assert "hwclock" in c.err
    _sin_tokens(c)


def test_comprobar_meta_escribe_meta_json_y_fija_offset(mundo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: mundo_basico())
    assert main(["comprobar-meta"]) == 0
    meta = json.loads((mundo.spool / "estado" / "meta.json").read_text())
    esperado = informe_a_dict(comprobar_meta(mundo_basico(), CUENTA))
    meta.pop("fecha"), esperado.pop("fecha")
    assert meta == esperado
    assert "offset: 1" in mundo.limites.read_text()
    eventos = [json.loads(ln) for ln in mundo.auditoria.read_text().splitlines()]
    assert any("limite_cambiado" in json.dumps(e) for e in eventos)
    _sin_tokens(capsys.readouterr())


def test_comprobar_meta_offset_distinto_no_se_toca(mundo, monkeypatch, capsys):
    mundo.limites.write_text(mundo.limites.read_text().replace("offset: null", "offset: 1", 1))
    os.chmod(mundo.limites, 0o600)
    monkeypatch.setitem(instalacion.OFFSETS_META, "COP", 100)  # Meta "cambia" de criterio: no se pisa
    antes = mundo.limites.read_bytes()
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: mundo_basico())
    assert main(["comprobar-meta"]) == 1
    assert mundo.limites.read_bytes() == antes
    assert "offset distinto del instalado" in capsys.readouterr().err


def test_comprobar_meta_error_no_filtra_token(mundo, monkeypatch, capsys):
    g = mundo_basico()

    def mal(act):
        raise RuntimeError(TOKEN_META)

    g.cuenta = mal
    monkeypatch.setattr(cli, "ClienteGraph", lambda token: g)
    assert main(["comprobar-meta"]) == 1
    _sin_tokens(capsys.readouterr())


def test_servir_sin_emparejar_sale_4(mundo, capsys):
    assert main(["servir", "--graph-simulado"]) == 4
    _sin_tokens(capsys.readouterr())


def test_limites_sin_configurar_y_con_offset(mundo, capsys):
    assert main(["limites"]) == 0
    assert "sin configurar (P-21)" in capsys.readouterr().out
    assert (mundo.spool / "estado" / "limites.json").exists()
    mundo.limites.write_text(mundo.limites.read_text().replace("offset: null", "offset: 1", 1))
    os.chmod(mundo.limites, 0o600)
    assert main(["limites"]) == 0
    assert "165.000 COP" in capsys.readouterr().out


def test_limites_ilegibles_sale_2(mundo, capsys):
    mundo.limites.write_text("esto: [no")
    assert main(["limites"]) == 2
    _sin_tokens(capsys.readouterr())


def test_estado_no_imprime_ids_ni_secretos(mundo, capsys):
    guardar_secretos(mundo.secretos, {"TELEGRAM_USER_ID": "5551234", "TELEGRAM_CHAT_ID": "5551234"})
    assert main(["estado"]) == 0
    c = capsys.readouterr()
    assert "STOP" in c.out and "latido" in c.out and "auditor" in c.out
    assert "5551234" not in c.out + c.err
    _sin_tokens(c)


def test_estado_muestra_stop(mundo, capsys):
    mundo.stop.write_text("{}")
    assert main(["estado"]) == 0
    assert "STOP: ACTIVO" in capsys.readouterr().out


@pytest.mark.parametrize("orden", [["emparejar"], ["comprobar-meta"], ["servir"], ["estado"], ["limites"]])
def test_secretos_rotos_sin_traza_ni_tokens(mundo, orden, capsys):
    mundo.secretos.write_text(f"META_TOKEN={TOKEN_META}\nTELEGRAM_BOT_TOKEN={TOKEN_BOT}\nXX\n")
    os.chmod(mundo.secretos, 0o600)
    main(orden)
    c = capsys.readouterr()
    assert "Traceback" not in c.err
    _sin_tokens(c)


def test_help_no_filtra(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    _sin_tokens(capsys.readouterr())


def test_no_importa_trovefy():
    codigo = ("import sys, trovefy_ejecutor.cli, trovefy_ejecutor.servicio, trovefy_ejecutor.simulado, "
              "trovefy_ejecutor.instalacion;"
              "print(any(m == 'trovefy' or m.startswith('trovefy.') for m in sys.modules))")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "False"
