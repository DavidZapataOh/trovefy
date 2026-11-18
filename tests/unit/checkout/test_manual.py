"""Respaldo manual guiado (plan 19, Tarea 12): la receta para el panel y su cierre con capturas o palabras."""
from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy import cli, navegador
from trovefy.checkout.manual import cerrar_manual, clave_captura, plan_manual
from trovefy.checkout.receta import Ajuste
from trovefy.embudo.contexto import cargar_contexto, ruta_pais
from trovefy.embudo.pegado import CLAVES, dicho, guardar_pegado, indice

AHORA = datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

PRECIO = Ajuste("producto.front.precio", "13.90", "mismo precio que la página", "S1 7:16", True)
PLANTILLA = Ajuste("checkout.plantilla", "Bambú", "plantilla de los vídeos", "V1 0:31:50", True)
EMAIL = Ajuste("emails.entrega", Path("/x/entrega.md"), "lo pegas tú", None, False)
MARKET = Ajuste("market.ZZ.moneda", "EUR", "un mercado propio", "V1 0:55:14", False)


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    return v, cargar_contexto(v, P, PAIS)


def _captura(v, ctx, clave, valores, tmp_path, n=0):
    origen = tmp_path / f"m{n}.png"
    origen.write_bytes(PNG)
    return guardar_pegado(v, ctx, clave, origen, valores, AHORA.replace(second=n))


@pytest.mark.parametrize(("ajuste", "clave"), [
    ("producto.front.precio", "ver-como"), ("market.ZZ.moneda", "market"), ("producto.front.titulo", "producto"),
    ("checkout.plantilla", "checkout"), ("tienda.nombre", "checkout"), ("postcompra.u1.pagina", "upsell-u1"),
    ("emails.entrega", "emails"), ("bump.activo", "bump"), ("downsell.x", "downsell"),
    ("tracking.pixel_id", "tracking-pixel"),
])
def test_clave_captura(ajuste, clave):
    assert clave_captura(ajuste) == clave
    assert clave in CLAVES


def test_manual_receta_y_capturas():
    texto = plan_manual([PLANTILLA, EMAIL, MARKET], producto=P, pais=PAIS)
    assert "https://impultienda.ar/login" in texto
    assert "app.impultienda.ar" not in texto
    assert "\n1. " in texto and "\n4. " in texto
    assert "Bambú" in texto
    assert "Capturas que hay que pegar" in texto
    for clave in ("checkout", "emails", "market"):
        assert (f"trovefy checkout evidencia --producto {P} --pais {PAIS} --clave {clave} --desde <captura>"
                in texto)


def test_manual_sin_ajustes():
    assert "Nada va a mano" in plan_manual([])


def test_dicho_no_vale_para_precio(zz, tmp_path):
    v, ctx = zz
    dicho(v, ctx, "ver-como", "Ya puse 13,90 €", AHORA)
    dicho(v, ctx, "emails", "Ya pegué el email de entrega", AHORA.replace(minute=1))
    idx = indice(v, ctx)
    precio = cerrar_manual(PRECIO, idx)
    assert precio.estado == "no_medido"
    assert "captura" in precio.detalle
    email = cerrar_manual(EMAIL, idx)
    assert (email.estado, email.fuente) == ("dicho", "dicho")


def test_captura_con_precio_cierra(zz, tmp_path):
    v, ctx = zz
    _captura(v, ctx, "ver-como", {"precio": "13,90 €"}, tmp_path)
    e = cerrar_manual(PRECIO, indice(v, ctx))
    assert (e.estado, e.fuente) == ("captura", "captura")
    assert e.evidencia.startswith("checkout/ZZ/evidencia/ver-como-")


def test_captura_con_otro_precio_falla(zz, tmp_path):
    v, ctx = zz
    _captura(v, ctx, "ver-como", {"precio": "12,64 €"}, tmp_path)
    assert cerrar_manual(PRECIO, indice(v, ctx)).estado == "falla"


def test_captura_sin_valores_no_cierra(zz, tmp_path):
    v, ctx = zz
    _captura(v, ctx, "checkout", {}, tmp_path)
    e = cerrar_manual(PLANTILLA, indice(v, ctx))
    assert e.estado == "no_medido"
    assert "--valor" in e.detalle


def test_captura_con_valor_distinto_falla(zz, tmp_path):
    v, ctx = zz
    _captura(v, ctx, "checkout", {"plantilla": "Coral"}, tmp_path)
    assert cerrar_manual(PLANTILLA, indice(v, ctx)).estado == "falla"
    _captura(v, ctx, "checkout", {"plantilla": "bambú"}, tmp_path, n=1)
    assert cerrar_manual(PLANTILLA, indice(v, ctx)).estado == "captura"


def test_sin_evidencia_no_medido(zz):
    v, ctx = zz
    e = cerrar_manual(EMAIL, indice(v, ctx))
    assert e.estado == "no_medido"
    assert "trovefy checkout evidencia" in e.detalle


def test_cli_manual_escribe_receta_sin_abrir_panel(zz, monkeypatch, capsys):
    v, ctx = zz
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(importlib.import_module("trovefy.checkout_cli"), "_ahora", lambda: AHORA)
    for nombre in ("sesion", "abrir", "capturar"):
        monkeypatch.setattr(navegador, nombre, lambda *a, **k: pytest.fail("abre el navegador"))
    assert cli.main(["checkout", "manual", "--producto", P, "--pais", PAIS]) == 0
    out = capsys.readouterr().out
    receta = (ruta_pais(ctx) / "RECETA-manual.md").read_text(encoding="utf-8")
    assert "https://impultienda.ar/login" in out and "Bambú" in receta
    assert "--clave checkout" in receta
