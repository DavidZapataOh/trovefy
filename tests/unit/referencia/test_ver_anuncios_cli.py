from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest
from trovefy import ver_anuncios_cli as cli
from trovefy.referencia import watch
from trovefy.vault.frontmatter import escribir as fm_escribir

PLANTILLA = Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml"
P = "p-0001-prueba"


def _args(**kw):
    base = {"accion": "ver", "producto": P, "pais": "RO", "page_id": None, "top": None, "desde_mcp": None, "sin_navegador": True}
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_CACHE_REFERENCIA", str(tmp_path / "cache"))
    v = tmp_path / "vault"
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    (v / "config").mkdir(parents=True)
    shutil.copy(PLANTILLA, v / "config/umbrales.yaml")
    fm_escribir(v / f"productos/{P}/PRODUCTO.md", {"id": P, "oferta_id": "o-001"}, "# P\n")
    fm_escribir(v / "wiki/ofertas/o-001.md", {"oferta_id": "o-001", "page_ids": ["800000000001"], "paises": {"RO": {"c8": 3}}}, "# o\n")
    return v


def test_cli_comprobar_sale_0_sin_whisperx(monkeypatch, capsys):
    monkeypatch.setattr(watch, "comprobar_entorno", lambda: watch.Entorno(None, None, True, False, "WhisperX no instalado"))
    assert cli._ejecutar(argparse.Namespace(accion="comprobar")) == 0
    out = capsys.readouterr().out
    assert "ffmpeg: falta" in out and "sudo apt install ffmpeg" in out


def test_cli_lote_invalido_sale_2(vault, tmp_path, monkeypatch, capsys):
    from trovefy.referencia import orquestador

    monkeypatch.setattr(orquestador, "comprobar_entorno", lambda: watch.Entorno(None, None, True, False, ""))
    malo = tmp_path / "lote.json"
    malo.write_text("no es json")
    assert cli._ejecutar(_args(desde_mcp=str(malo))) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_producto_sin_producto_md_sale_2(vault, capsys):
    assert cli._ejecutar(_args(producto="p-0009-no")) == 2
    assert "auditar" in capsys.readouterr().err


def test_cli_anotar_invalido_sale_2(vault, tmp_path, capsys):
    r = tmp_path / "a.json"
    r.write_text(json.dumps({"no": "lista"}))
    assert cli._ejecutar(_args(accion="anotar", desde=str(r))) == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("cambio", [{"producto": "../x"}, {"pais": "MEX"}, {"pais": "M1"}, {"top": 0}])
def test_cli_valida_argumentos(vault, capsys, cambio):
    assert cli._ejecutar(_args(**cambio)) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_ctrl_c_es_interrumpida(vault, monkeypatch, capsys):
    from trovefy.referencia import orquestador

    def corta(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(orquestador, "ver", corta)
    assert cli._ejecutar(_args()) == 3
    err = capsys.readouterr().err
    assert "INTERRUMPIDA" in err and "Traceback" not in err


def test_cli_ayuda_pagina_original(capsys):
    p = argparse.ArgumentParser()
    cli._configurar(p)
    with pytest.raises(SystemExit):
        p.parse_args(["ver", "--help"])
    assert "original_page_id" in capsys.readouterr().out
