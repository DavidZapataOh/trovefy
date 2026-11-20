"""CLI `trovefy creativos` (plan 21): el camino de la tanda con APIMart falso y sin gastar nada."""

import os
from decimal import Decimal

import pytest
import yaml
from trovefy import cli, creativos_cli
from trovefy.creativos import coste
from trovefy.creativos.contexto import ruta_tanda

from .ejemplos import AHORA, PAIS, P, brief_ok, crear_vault, guion_video
from .falsos import CLAVE, explota
from .test_manifest import cerrada


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    env = tmp_path / "home" / ".config" / "trovefy" / "claude.env"
    env.parent.mkdir(parents=True)
    env.write_text(f"APIMART_API_KEY={CLAVE}\n", encoding="utf-8")
    os.chmod(env, 0o600)
    monkeypatch.setattr(creativos_cli, "RUTA_ENV", env)
    monkeypatch.setattr(creativos_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(creativos_cli, "_abrir", explota)
    monkeypatch.setattr(creativos_cli, "_abrir_publico", explota)
    return tmp_path


def _vault(entorno, monkeypatch, **kw):
    vault = crear_vault(entorno / "v", **kw)
    monkeypatch.setenv("TROVEFY_VAULT", str(vault))
    return vault


def _correr(*args):
    return cli.main(["creativos", *args])


BASE = ("--producto", P, "--pais", PAIS)


def test_nueva_brief_y_coste_sin_medir(entorno, monkeypatch, capsys):
    vault = _vault(entorno, monkeypatch)
    assert _correr("nueva", *BASE) == 0
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    (carpeta / "brief.yaml").write_text(yaml.safe_dump(brief_ok(), allow_unicode=True), encoding="utf-8")
    assert _correr("brief", *BASE, "--tanda", "t1") == 0
    (carpeta / "guiones").mkdir()
    for n, f in ((2, "broll_voz"), (3, "ugc"), (5, "claymation"), (6, "3d"), (7, "scroll_pdf"), (8, "zoom_lento"),
                 (10, "scroll_pdf")):
        (carpeta / "guiones" / f"AD{n:02d}.yaml").write_text(yaml.safe_dump(guion_video(f), allow_unicode=True),
                                                             encoding="utf-8")
    capsys.readouterr()
    assert _correr("coste", *BASE, "--tanda", "t1") == 1  # precios de APIMart sin medir
    out = capsys.readouterr().out
    assert "no medido: precio de clips" in out and "no medido: precio de voz de APIMart" in out
    assert _correr("aprobar-coste", *BASE, "--tanda", "t1", "--cita", "sí") == 2  # no se aprueba lo no medido


def test_estado_producido_primero_listo(entorno, monkeypatch, capsys):
    _vault(entorno, monkeypatch, estado="producido")
    assert _correr("nueva", *BASE) == 1
    assert "primero /listo" in capsys.readouterr().err


def test_tope_y_aprobar_coste(entorno, monkeypatch, capsys):
    vault = _vault(entorno, monkeypatch)
    _correr("nueva", *BASE)
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    (carpeta / "brief.yaml").write_text(yaml.safe_dump(brief_ok(), allow_unicode=True), encoding="utf-8")
    assert _correr("tope", *BASE, "--tanda", "t1", "--usd", "5", "--cita", "con 5 basta") == 0
    from trovefy.creativos.config import cargar_config
    assert coste.tope_vigente(vault, P, PAIS, "t1", cargar_config(vault)) == Decimal(5)
    # sin escenas ni guiones de vídeo escritos todavía, lo que hay que pagar es solo lo escrito: nada
    assert _correr("estado", *BASE, "--tanda", "t1") == 0
    assert "Coste aprobado: no" in capsys.readouterr().out


def test_escenas_sin_aprobar_no_llama(entorno, monkeypatch, capsys):
    vault = _vault(entorno, monkeypatch)
    _correr("nueva", *BASE)
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    (carpeta / "brief.yaml").write_text(yaml.safe_dump(brief_ok(), allow_unicode=True), encoding="utf-8")
    (carpeta / "escenas.yaml").write_text(yaml.safe_dump([{"id": "e01", "prompt": "x", "proporcion": "4:5"}]),
                                          encoding="utf-8")
    from trovefy.apimart.precios import Precio
    monkeypatch.setattr(creativos_cli, "_precio_imagen",
                        lambda *_a: Precio("gpt-image-2", "1k", Decimal("0.0085"), "p", AHORA.date()))
    assert _correr("escenas", *BASE, "--tanda", "t1") == 1
    assert "aprobar-coste" in capsys.readouterr().out


def test_cerrar_rehacer_y_estado(entorno, monkeypatch, capsys):
    vault, *_ = cerrada(entorno / "c")
    monkeypatch.setenv("TROVEFY_VAULT", str(vault))
    assert _correr("rehacer", *BASE, "--tanda", "t1", "--ad", "AD03", "--motivo", "la letra se corta") == 0
    assert _correr("cerrar", *BASE, "--tanda", "t1") == 1  # AD03 no cambió desde el veto
    assert "no cambió desde el veto" in capsys.readouterr().out
    assert _correr("renovar", *BASE) == 1  # el país sigue en listo: la renovación es con el test vivo
    capsys.readouterr()

