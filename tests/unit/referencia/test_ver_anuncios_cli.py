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
    malo = tmp_path / "cache" / P / "mcp" / "lote.json"
    malo.parent.mkdir(parents=True)
    malo.write_text("no es json")
    assert cli._ejecutar(_args(desde_mcp=str(malo))) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "JSON" in err


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


def test_cli_lote_fuera_de_la_cache_sale_2(vault, tmp_path, monkeypatch, capsys):
    from trovefy.referencia import orquestador

    llamado = []
    monkeypatch.setattr(orquestador, "ver", lambda *a, **kw: llamado.append(1))
    fuera = tmp_path / "lote-fuera.json"
    fuera.write_text("{}")
    assert cli._ejecutar(_args(desde_mcp=str(fuera))) == 2
    err = capsys.readouterr().err
    assert "caché" in err and "Traceback" not in err and llamado == []


def test_cli_lote_con_enlace_que_sale_de_la_cache_sale_2(vault, tmp_path, monkeypatch, capsys):
    import os

    from trovefy.referencia import orquestador

    monkeypatch.setattr(orquestador, "ver", lambda *a, **kw: pytest.fail("no debe leer"))
    fuera = tmp_path / "lote-fuera.json"
    fuera.write_text("{}")
    mcp = tmp_path / "cache" / P / "mcp"
    mcp.mkdir(parents=True)
    os.symlink(fuera, mcp / "lote-x.json")
    assert cli._ejecutar(_args(desde_mcp=str(mcp / "lote-x.json"))) == 2


def test_cli_parada_sin_desde_mcp(vault, monkeypatch, capsys):
    from types import SimpleNamespace

    from trovefy.referencia import orquestador

    ref = SimpleNamespace(producto=P, pais="RO", fecha="2026-11-13", fichas=[], via="mcp", completo=False,
                          via_medios=None, motivos=[])
    r = SimpleNamespace(ref=ref, trabajo=[], parada="Meta ya bloqueó hoy; vuelve mañana", tipo_parada="meta",
                        avisos=[], busquedas_hoy=None)
    monkeypatch.setattr(orquestador, "ver", lambda *a, **kw: r)
    assert cli._ejecutar(_args()) == 1
    err = capsys.readouterr().err
    assert "PARADA" in err and "--desde-mcp" not in err


def test_cli_siguiente_paso_con_ruta_del_analisis(vault, monkeypatch, capsys):
    from types import SimpleNamespace

    from trovefy.referencia import orquestador

    ref = SimpleNamespace(producto=P, pais="RO", fecha="2026-11-13", fichas=[], via="mcp", completo=False,
                          via_medios=None, motivos=[])
    r = SimpleNamespace(ref=ref, trabajo=[], parada=None, tipo_parada=None, avisos=[], busquedas_hoy=None)
    monkeypatch.setattr(orquestador, "ver", lambda *a, **kw: r)
    assert cli._ejecutar(_args()) == 0
    assert f"--desde data/referencia/analisis-{P}.json" in capsys.readouterr().out
