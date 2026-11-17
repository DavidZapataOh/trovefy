"""Contexto del producto-país y ruta de cobro (plan 19, Tarea 4; resoluciones 1, 6, 7, 14, 24).

Ruta Hotmart fuera («DESVÍOS RESUELTOS», cabecera del plan 19): la única ruta es Impultienda.
"""

from decimal import Decimal

import pytest
import yaml
from trovefy.embudo.contexto import (
    Contexto,
    EstadoIncorrecto,
    cargar_contexto,
    exigir_estado,
    ruta_de_cobro,
    ruta_pais,
)
from trovefy.vault.producto import EstadoInesperado

from embudo.ejemplos_embudo import PAIS, TIENDA, P, arranque, vault_embudo


def test_contexto_ficticio(tmp_path):
    v = vault_embudo(tmp_path)
    ctx = cargar_contexto(v, P, PAIS)
    assert isinstance(ctx, Contexto)
    assert (ctx.producto, ctx.pais, ctx.estado, ctx.idioma) == (P, PAIS, "con_landing", "bg")
    assert ctx.moneda == "EUR"
    assert ctx.piezas["front"].precio == Decimal("13.90")
    assert ctx.piezas["u1"].precio == Decimal("19.90")
    assert ctx.piezas["u1"].activo is True
    assert ctx.piezas["bump"].activo is False
    assert ctx.piezas["bump"].motivo_inactivo == "sin order bump (vídeos)"
    assert ctx.piezas["u2"].activo is False
    assert ctx.piezas["front"].pdf == v / "productos" / P / "entregable" / "prueba-bg-v1.pdf"
    assert ctx.piezas["u1"].titulo == "Сън без болка"
    assert ctx.tienda == TIENDA
    assert ctx.checkout_url == "https://prueba.impultienda.example/checkout"
    assert ctx.landing_url == TIENDA + "/"
    assert ctx.landing_hosting == "impultienda"
    assert ctx.ruta == "impultienda"


def test_precio_float_rechazado(tmp_path):
    pasos = {"front": {"precio": 13.9, "activo": True, "titulo": "x", "entregable": "x"}}
    v = vault_embudo(tmp_path, pasos=pasos)
    with pytest.raises(ValueError, match="precio sin comillas: escríbelo como texto"):
        cargar_contexto(v, P, PAIS)


def test_pdf_ausente_no_medido(tmp_path):
    v = vault_embudo(tmp_path, pdf_u1=False)
    ctx = cargar_contexto(v, P, PAIS)
    assert ctx.piezas["u1"].pdf is None
    assert "no medido: falta el PDF vigente de u1 (plan 17)" in ctx.motivos
    # Las piezas apagadas no piden PDF.
    assert not any("de u2" in m for m in ctx.motivos)


def test_pdf_fuera_de_entregable_no_cuenta(tmp_path):
    v = vault_embudo(tmp_path)
    ruta = v / "productos" / P / "PRODUCTO.md"
    texto = ruta.read_text(encoding="utf-8").replace("entregable/upsells/u1/u1-bg-v1.pdf", "../fuera.pdf")
    ruta.write_text(texto, encoding="utf-8")
    ctx = cargar_contexto(v, P, PAIS)
    assert ctx.piezas["u1"].pdf is None


def test_marca_es_nombre_local(tmp_path):
    v = vault_embudo(tmp_path)
    assert cargar_contexto(v, P, PAIS).marca == "Somatix"
    (v / "productos" / P / "BRANDBOOK.md").unlink()
    ctx = cargar_contexto(v, P, PAIS)
    assert ctx.marca is None
    assert any(m.startswith("no medido: falta nombre_local") for m in ctx.motivos)


def test_sin_tienda_ni_landing(tmp_path):
    v = vault_embudo(tmp_path, landing={})
    (v / "config" / "mercados.yaml").write_text(
        "ZZ: {idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo, tienda: null}\n",
        encoding="utf-8")
    ctx = cargar_contexto(v, P, PAIS)
    assert (ctx.tienda, ctx.checkout_url, ctx.landing_url, ctx.landing_hosting) == (None, None, None, None)
    assert any("tienda" in m for m in ctx.motivos)


def test_checkout_url_absoluto_de_landing(tmp_path):
    v = vault_embudo(tmp_path, landing={"hosting": "impultienda", "version": "v2", "url": TIENDA + "/",
                                        "checkout_url": TIENDA + "/checkout"})
    assert cargar_contexto(v, P, PAIS).checkout_url == TIENDA + "/checkout"


def test_ruta_impultienda():
    assert ruta_de_cobro(arranque({"09": "verificado", "10": "hecho"})) == "impultienda"
    assert ruta_de_cobro(arranque({"09": "hecho", "10": "verificado"})) == "impultienda"


def test_ruta_hotmart():
    # Fuera por «DESVÍOS RESUELTOS»: el paso 10b ya no abre una ruta.
    with pytest.raises(ValueError, match="Hotmart"):
        ruta_de_cobro(arranque({"09": "hecho", "10": "bloqueado", "10b": "hecho"}))


@pytest.mark.parametrize("pasos", [{"09": "hecho", "10": "pendiente"}, {"09": "pendiente", "10": "hecho"}, {}])
def test_sin_ruta(pasos):
    with pytest.raises(ValueError, match="cobro"):
        ruta_de_cobro(arranque(pasos))


def test_sin_ruta_en_el_contexto(tmp_path):
    v = vault_embudo(tmp_path, cobro={"09": "hecho", "10": "pendiente"})
    with pytest.raises(ValueError, match="cobro"):
        cargar_contexto(v, P, PAIS)


def test_arranque_roto(tmp_path):
    v = vault_embudo(tmp_path)
    (v / "config" / "arranque.yaml").write_text(yaml.safe_dump({"otra": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="arranque"):
        cargar_contexto(v, P, PAIS)


def test_estado_incorrecto(tmp_path):
    v = vault_embudo(tmp_path, estado="producido")
    ctx = cargar_contexto(v, P, PAIS)
    with pytest.raises(EstadoIncorrecto, match="producido") as exc:
        exigir_estado(ctx, "con_landing")
    assert isinstance(exc.value, EstadoInesperado)
    exigir_estado(ctx, ("producido", "con_landing"))  # no lanza


def test_ruta_pais(tmp_path):
    v = vault_embudo(tmp_path)
    assert ruta_pais(cargar_contexto(v, P, PAIS)) == v / "productos" / P / "checkout" / PAIS


def test_pais_sin_escalera(tmp_path):
    v = vault_embudo(tmp_path)
    with pytest.raises(ValueError, match="ZY"):
        cargar_contexto(v, P, "ZY")
