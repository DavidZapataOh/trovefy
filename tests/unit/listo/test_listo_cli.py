"""Plan 20, Tarea 5: `trovefy listo <p-id> --pais XX [--para-activar]`."""

import pytest
from trovefy.cli import main
from trovefy.listo.veredicto import FuentesListo
from trovefy.vault import frontmatter

from .conftest import (
    AHORA,
    P,
    abrir_landing_falso,
    marcar_dominio,
    preparar_vault,
    spool_sano,
    trm_fijo,
    vault_con_caja,
)


@pytest.fixture
def vault_cli(tmp_path, monkeypatch):
    vault = preparar_vault(tmp_path)
    marcar_dominio(vault)
    vault_con_caja(vault)
    monkeypatch.setattr("trovefy.listo_cli._ahora", lambda: AHORA)
    return vault


@pytest.fixture
def fuentes_falsas_por_defecto(tmp_path, monkeypatch):
    fuentes = FuentesListo(spool=spool_sano(tmp_path), abrir_landing=abrir_landing_falso(), trm_de=trm_fijo)
    monkeypatch.setattr("trovefy.listo.veredicto.fuentes_por_defecto", lambda _v: fuentes)
    return fuentes


def _cli(vault, *extra):
    return main(["listo", P, "--pais", "ZZ", "--vault", str(vault), *extra])


def test_cli_verde_sale_0(vault_cli, fuentes_falsas_por_defecto, capsys):
    assert _cli(vault_cli) == 0
    out = capsys.readouterr().out
    assert "Estado de ZZ: con_checkout → listo" in out and "– creativos: no aplica hasta la fase 3" in out
    meta, _ = frontmatter.leer(vault_cli / "productos" / P / "PRODUCTO.md")
    assert meta["paises"]["ZZ"]["estado"] == "listo"


def test_cli_para_activar_sale_1_en_fase_2(vault_cli, fuentes_falsas_por_defecto):
    assert _cli(vault_cli, "--para-activar") == 1


def test_cli_sin_ejecutor_rojo_sin_traza(vault_cli, monkeypatch, capsys):
    # TROVEFY_SPOOL apunta a una carpeta inexistente (conftest) y la landing se mide con un abrir falso
    from trovefy.listo import veredicto

    real = veredicto.fuentes_por_defecto
    monkeypatch.setattr("trovefy.listo.veredicto.fuentes_por_defecto",
                        lambda v: FuentesListo(real(v).spool, abrir_landing_falso(), trm_fijo))
    assert _cli(vault_cli) == 1
    out = capsys.readouterr()
    assert "? ejecutor: no medido: el ejecutor aún no está instalado" in out.out and "Traceback" not in out.err
    assert "Lo que falta:" in out.out and "Estado de ZZ: con_checkout → con_checkout" in out.out


def test_cli_producto_inexistente_sale_2(tmp_path, capsys):
    assert main(["listo", P, "--pais", "ZZ", "--vault", str(tmp_path)]) == 2
    assert f"no existe productos/{P}/PRODUCTO.md" in capsys.readouterr().err


def test_cli_pais_invalido_sale_2(vault_cli, capsys):
    assert main(["listo", P, "--pais", "bg", "--vault", str(vault_cli)]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_con_excepcion_dice_que_no_es_verde(vault_cli, fuentes_falsas_por_defecto, capsys):
    from trovefy.checkout.cierre import registrar_excepcion

    ruta = vault_cli / "productos" / P / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("procesado: true", "procesado: false"))
    registrar_excepcion(vault_cli, P, "ZZ", "reembolso registrado", "Apruebo sin reembolso.", "se la queda", AHORA)
    assert _cli(vault_cli) == 0
    out = capsys.readouterr().out
    assert "! reembolso: excepción aprobada" in out and "no es verde" in out
    assert "Estado de ZZ: con_checkout → listo" in out and "pasa por tu excepción" in out


def test_skill_listo_existe():
    from pathlib import Path

    import yaml

    texto = (Path(__file__).resolve().parents[3] / "skills" / "listo" / "SKILL.md").read_text()
    meta = yaml.safe_load(texto.split("---")[1])
    assert meta["name"] == "listo" and "Bash(trovefy listo *)" in meta["allowed-tools"]
    assert "sudo" not in meta["allowed-tools"]
    cuerpo = texto.split("---", 2)[2]
    assert "trovefy checkout excepcion" in cuerpo and "no aplica hasta la fase 3" in cuerpo
