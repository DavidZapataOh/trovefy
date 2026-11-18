"""Dataset guiado (plan 19, Tarea 7): lo crea el usuario en Events Manager; trovefy lo busca en la respuesta del MCP
de Meta (solo lectura) y le imprime la receta para su panel de Impultienda (R-d: Pixel ID y CAPI a mano)."""

import json
from pathlib import Path

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy.embudo.contexto import cargar_contexto
from trovefy.embudo.receta_texto import imprimir_receta
from trovefy.tienda.mcp import Catalogo, Herramienta, cargar_catalogo
from trovefy.tracking.dataset import (
    buscar_dataset,
    pixel_en_lectura_mcp,
    receta_tracking,
)

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "tracking"


def _json(nombre: str):
    return json.loads((FIX / nombre).read_text(encoding="utf-8"))


def test_busca_por_nombre_exacto():
    assert buscar_dataset(_json("datasets.json"), "SOMATIX ZZ") == ("1111111111111111", None)
    # Sin coincidencias aproximadas: «SOMATIX ZZ VIEJO» no es «SOMATIX ZZ», ni «somatix zz».
    ident, motivo = buscar_dataset(_json("datasets.json"), "somatix zz")
    assert ident is None and "ningún" in motivo


def test_respuesta_envuelta_del_mcp():
    envuelta = {"structuredContent": _json("datasets.json")}
    assert buscar_dataset(envuelta, "SOMATIX ZY") == ("3333333333333333", None)
    assert buscar_dataset(_json("datasets.json")["data"], "SOMATIX ZY") == ("3333333333333333", None)


def test_dos_con_el_mismo_nombre():
    datos = _json("datasets.json")
    datos["data"].append({"id": "6666666666666666", "name": "SOMATIX ZZ"})
    ident, motivo = buscar_dataset(datos, "SOMATIX ZZ")
    assert ident is None
    assert "1111111111111111" in motivo and "6666666666666666" in motivo


def test_ninguno():
    ident, motivo = buscar_dataset(_json("datasets-vacio.json"), "SOMATIX ZZ")
    assert ident is None and motivo.startswith("no medido")


def test_forma_rara_no_medido():
    for rara in (_json("datasets-forma-rara.json"), None, "texto", {"data": [{"id": "act_0000000000000000",
                                                                               "name": "SOMATIX ZZ"}]}):
        ident, motivo = buscar_dataset(rara, "SOMATIX ZZ")
        assert ident is None and motivo.startswith("no medido")


def test_pixel_en_lectura_mcp():
    leido = _json("mcp-tracking-leido.json")
    assert pixel_en_lectura_mcp(leido, "1111111111111111") is True
    assert pixel_en_lectura_mcp(leido, "7777777777777777") is False
    assert pixel_en_lectura_mcp({"tiendas": [{"id": "x", "nombre": "y"}]}, "1111111111111111") is None
    assert pixel_en_lectura_mcp("nada", "1111111111111111") is None


@pytest.fixture
def ctx(tmp_path):
    return cargar_contexto(vault_embudo(tmp_path), P, PAIS)


def test_receta_tracking_literal(ctx):
    pasos = receta_tracking(ctx, "SOMATIX ZZ", "1111111111111111", cargar_catalogo())
    texto = imprimir_receta("Tracking", pasos)
    for literal in ("https://business.facebook.com/events_manager2", "Conectar orígenes de datos",
                    "«SOMATIX ZZ»", "Generar identificador de acceso", "Meta / Tracking",
                    "https://impultienda.ar/login", "«1111111111111111»", "no lo pegues en el chat"):
        assert literal in texto, literal
    assert "app.impultienda.ar" not in texto
    # UTMify (R-d) también a mano; Clarity NO en la tienda: va tras el aviso de cookies de la landing.
    assert "UTMify" in texto and "Clarity" in texto and "aviso de cookies" in texto


def test_receta_sin_dataset_id_pide_el_id(ctx):
    texto = imprimir_receta("Tracking", receta_tracking(ctx, "SOMATIX ZZ", None, cargar_catalogo()))
    assert "trovefy tracking dataset" in texto


def _catalogo_con_pixel(prohibido: bool) -> Catalogo:
    h = Herramienta(nombre="impultienda_poner_pixel", descripcion="ESCRIBE el Pixel ID",
                    esquema={"type": "object", "properties": {"pixel_id": {"type": "string"}}},
                    clase="escritura", motivo="prueba",
                    parametros_prohibidos=("pixel_id",) if prohibido else ())
    return Catalogo({h.nombre: h}, fuente="prueba", fecha="2026-11-17", servidor="prueba", plan="Max", faltan=())


def test_receta_sin_pixel_id_si_hay_herramienta(ctx):
    con = imprimir_receta("T", receta_tracking(ctx, "SOMATIX ZZ", "1111111111111111", _catalogo_con_pixel(False)))
    assert "Meta Pixel ID" not in con
    assert "Generar identificador de acceso" in con
    sin = imprimir_receta("T", receta_tracking(ctx, "SOMATIX ZZ", "1111111111111111", _catalogo_con_pixel(True)))
    assert "Meta Pixel ID" in sin


def test_catalogo_real_no_tiene_escritura_de_pixel(ctx):
    # R-d: configurar_tracking es prohibida; el Pixel ID va en la receta.
    texto = imprimir_receta("T", receta_tracking(ctx, "SOMATIX ZZ", "1111111111111111", cargar_catalogo()))
    assert "Meta Pixel ID" in texto
