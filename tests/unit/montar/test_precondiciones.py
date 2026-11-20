"""Precondiciones de «Activar» antes de depositar (plan 22, Tarea 4)."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from trovefy.listo import GATES
from trovefy.listo.gates import Gate
from trovefy.listo.veredicto import InformeListo, listo_para_activar
from trovefy.montar.precondiciones import (
    comprobar,
    excepciones_para_activar,
    registrar_excepcion_activar,
)
from trovefy.vault import frontmatter
from trovefy.vault.producto import actualizar_producto

from .ejemplos import AHORA, PAIS, P


def informe(**estados) -> InformeListo:
    gates = tuple(Gate(g, estados.get(g, "ok"), f"{g}: {estados.get(g, 'ok')}") for g in GATES)
    return InformeListo(P, PAIS, AHORA, gates, "BE 10 USD · CPA de equilibrio 8 USD", True)


def _comprobar(vault, inf=None, **kw):
    inf = inf or informe()
    return comprobar(vault, P, PAIS, AHORA, None, evaluar=lambda *_a: inf, **kw)


def test_todo_ok(vault_zz):
    pre = _comprobar(vault_zz)
    assert pre.ok, pre.bloqueos


def test_excepcion_no_admitida_bloquea(vault_zz):
    pre = _comprobar(vault_zz, informe(reembolso="excepcion"))
    assert not pre.ok and any("reembolso" in b and "no admitida" in b for b in pre.bloqueos)


def test_excepcion_admitida_pasa(vault_zz):
    registrar_excepcion_activar(vault_zz, P, PAIS, "reembolso", "sí, activa aunque no reembolsé la prueba",
                                "la compra de prueba no se reembolsó", AHORA)
    assert set(excepciones_para_activar(vault_zz, P, PAIS)) == {"reembolso"}
    pre = _comprobar(vault_zz, informe(reembolso="excepcion"))
    assert pre.ok, pre.bloqueos


def test_gate_no_admisible_rechazado(vault_zz):
    with pytest.raises(ValueError, match="no se admite para activar"):
        registrar_excepcion_activar(vault_zz, P, PAIS, "compra", "sí", "x", AHORA)


def test_be_no_medido_bloquea(vault_zz):
    pre = _comprobar(vault_zz, replace(informe(), be_medido=False, economia="no medido: falta ESCALERA.md"))
    assert not pre.ok and any("ruta_activa" in b for b in pre.bloqueos)


def test_sin_hueco_bloquea(vault_zz):
    assert not _comprobar(vault_zz, informe(caja="falla")).ok


def test_stop_bloquea(vault_zz):
    assert not _comprobar(vault_zz, informe(stop="falla")).ok


def test_dataset_json_viejo_imprime_sudo(vault_zz):
    pre = _comprobar(vault_zz)
    assert pre.ok
    lejos = AHORA + timedelta(days=9)
    pre = comprobar(vault_zz, P, PAIS, lejos, None, evaluar=lambda *_a: informe())
    assert any("sudo -u trovefy-exec" in b and "comprobar-dataset 1111111111111111" in b for b in pre.bloqueos)


def test_montaje_vivo_bloquea(vault_zz):
    actualizar_producto(vault_zz, P, {"paises": {PAIS: {"trafico": {"montaje": "P-20261120-002"}}}}, [], "/t", AHORA)
    pre = _comprobar(vault_zz)
    assert any("montaje en curso" in b for b in pre.bloqueos)
    frontmatter.escribir(vault_zz / "propuestas" / "P-20261120-002.md", {"estado": "ejecutada"}, "x\n")
    assert any("ya hay una campaña montada" in b for b in _comprobar(vault_zz).bloqueos)


def test_estado_no_listo_bloquea(vault_zz):
    actualizar_producto(vault_zz, P, {"paises": {PAIS: {"trafico": {"activar": "P-20261120-801"}}}}, [], "/t", AHORA)
    from trovefy.vault.producto import avanzar_estado

    avanzar_estado(vault_zz, P, PAIS, "listo", "montado", "x", "/montar", AHORA)
    assert any("solo monta desde listo" in b for b in _comprobar(vault_zz).bloqueos)
    frontmatter.escribir(vault_zz / "propuestas" / "P-20261120-801.md", {"estado": "rechazada"}, "x\n")
    pre = _comprobar(vault_zz)
    assert not any("solo monta desde listo" in b for b in pre.bloqueos)


def test_para_activar_sin_admitidas_igual_que_antes():
    assert listo_para_activar(informe())
    assert not listo_para_activar(informe(reembolso="excepcion"))
    assert listo_para_activar(informe(reembolso="excepcion"), frozenset({"reembolso"}))
    assert not listo_para_activar(informe(creativos="no_aplica"), frozenset({"creativos"}))
