"""Relectura por el MCP (plan 19, Tarea 11): lo pedido frente a lo releído, normalizado; nunca un verde falso."""
from __future__ import annotations

import json

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy.checkout.operaciones import Operacion, Plan
from trovefy.checkout.relectura import (
    NO_GUARDADA,
    instantanea,
    leer_respuestas,
    pendiente_panel,
    releer,
    valores_de,
)
from trovefy.embudo.contexto import cargar_contexto
from trovefy.tienda.mcp import cargar_catalogo

from .mcp_falso import STORE, URL_FIRMADA, fixture
from .test_receta import _preparar

CATALOGO = cargar_catalogo()


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v)
    return cargar_contexto(v, P, PAIS), emails
MERCADO = "00000000-0000-4000-8000-000000000003"
TOKEN_FALSO = "EAA" + "Bq7" * 10


def _plan(*ops: Operacion) -> Plan:
    return Plan(operaciones=list(ops), manuales=[], ya_estan=[], huella="h", huella_catalogo="c")


def _op(n: int, herramienta: str, argumentos: dict, ajuste: str, lectura: str | None = None) -> Operacion:
    return Operacion(n=n, ajustes=(ajuste,), herramienta=herramienta, argumentos=argumentos, lectura=lectura,
                     clave=f"k{n}")


def _inst(ctx, **cambios):
    lecturas = {"impultienda_listar_tiendas": fixture("listar_tiendas.json"),
                "impultienda_listar_productos": fixture("listar_productos.json"),
                "impultienda_ver_markets": fixture("ver_markets.json"),
                "impultienda_ver_postcompra": fixture("ver_postcompra.json"), **cambios}
    inst, avisos = instantanea(ctx, lecturas)
    return inst, avisos


PRECIO = {"store_id": STORE, "market_id": MERCADO, "precio": 13.9, "precio_original": None}


def test_precio_distinto_es_discrepancia(zz):
    ctx, _ = zz
    inst, _ = _inst(ctx)
    plan = _plan(_op(1, "impultienda_precio_por_pais", PRECIO, "producto.front.precio"))
    bien = {"modo": "aplicado", "precio_fijo": {"precio": "13,90", "precio_original": None}}
    mal = {"modo": "aplicado", "precio_fijo": {"precio": 14.0, "precio_original": None}}
    [r] = releer(plan, inst, {1: bien}, ctx=ctx)
    assert r.estado == "ok" and r.igual is True
    [r] = releer(plan, inst, {1: mal}, ctx=ctx)
    assert r.estado == "distinto" and r.igual is False and r.leido == 14.0
    tachado = {"modo": "aplicado", "precio_fijo": {"precio": 13.9, "precio_original": 29.9}}
    assert releer(plan, inst, {1: tachado}, ctx=ctx)[0].estado == "distinto"  # sin precio tachado (D-01)


def test_relectura_por_lectura(zz):
    ctx, _ = zz
    plan = _plan(_op(1, "impultienda_configurar_tienda", {"store_id": STORE, "nombre": "Somatix"}, "tienda.nombre",
                     "impultienda_listar_tiendas"))
    tiendas = fixture("listar_tiendas.json")
    inst, _ = _inst(ctx)
    assert releer(plan, inst, {1: {"aplicado": ["nombre"]}}, ctx=ctx)[0].estado == "distinto"
    tiendas["tiendas"][0]["nombre"] = "  SOMATIX "
    inst, _ = _inst(ctx, impultienda_listar_tiendas=tiendas)
    assert releer(plan, inst, {1: {"aplicado": ["nombre"]}}, ctx=ctx)[0].estado == "ok"
    # Sin lectura de la tienda: no medido, nunca verde.
    assert releer(plan, {}, {1: {"aplicado": ["nombre"]}}, ctx=ctx)[0].estado == "no_medido"


def test_solo_se_releen_las_aplicadas(zz):
    ctx, _ = zz
    plan = _plan(_op(1, "impultienda_configurar_tienda", {"store_id": STORE, "nombre": "Somatix"}, "tienda.nombre"))
    assert releer(plan, _inst(ctx)[0], {}, ctx=ctx) == []


def test_pendiente_aprobar_en_panel(zz):
    ctx, _ = zz
    plan = _plan(_op(1, "impultienda_configurar_tienda", {"store_id": STORE, "nombre": "Somatix"}, "tienda.nombre"))
    [r] = releer(plan, _inst(ctx)[0], {1: fixture("pendiente-aprobar.json")}, ctx=ctx)
    assert r.estado == "pendiente_aprobar_panel" and r.enlace == "https://impultienda.ar/panel/cambios/aprobar"
    assert pendiente_panel({"ok": True}) is None
    assert pendiente_panel("El cambio quedó pendiente de Aprobar en el panel") == ""


def test_respuesta_con_token_no_se_guarda(zz, tmp_path):
    ctx, _ = zz
    con_token = json.loads(json.dumps(fixture("respuesta-con-token.json")).replace("__TOKEN__", TOKEN_FALSO))
    plan = _plan(_op(1, "impultienda_configurar_tienda", {"store_id": STORE, "nombre": "Somatix"}, "tienda.nombre"))
    [r] = releer(plan, _inst(ctx)[0], {1: con_token}, ctx=ctx)
    assert r.estado == "no_medido" and r.evidencia == NO_GUARDADA and r.leido is None
    # Al leer el archivo: no se usa ni se guarda.
    ruta = tmp_path / "r.json"
    ruta.write_text(json.dumps({"llamadas": [{"herramienta": "impultienda_configurar_tienda",
                                              "argumentos": {"store_id": STORE, "nombre": "Somatix"},
                                              "respuesta": con_token}]}), encoding="utf-8")
    [resp], guardable = leer_respuestas(ruta, CATALOGO)
    assert resp.respuesta is None and resp.secreto
    assert TOKEN_FALSO not in guardable and NO_GUARDADA in guardable


def test_url_firmada_redactada_y_ruta_conservada(tmp_path):
    ruta = tmp_path / "r.json"
    respuesta = {"modo": "subir", "url_subida": URL_FIRMADA, "ruta": "entregables/0001/0002/prueba.pdf"}
    ruta.write_text(json.dumps({"llamadas": [{"herramienta": "mcp__impultienda__impultienda_cargar_entregable",
                                              "argumentos": {"store_id": STORE}, "respuesta": respuesta}]}),
                    encoding="utf-8")
    [resp], guardable = leer_respuestas(ruta, CATALOGO)
    assert resp.herramienta == "impultienda_cargar_entregable"
    assert "X-Amz-Signature" not in json.dumps(resp.respuesta) and "X-Amz-Signature" not in guardable
    assert resp.respuesta["ruta"] == "entregables/0001/0002/prueba.pdf"


def test_formato_desconocido_no_medido(zz):
    ctx, _ = zz
    plan = _plan(_op(1, "impultienda_configurar_checkout", {"store_id": STORE, "pedir_telefono": True},
                     "checkout.campos"),
                 _op(2, "impultienda_disenar_checkout", {"store_id": STORE, "minutos_timer_bump": 0},
                     "checkout.temporizador"))
    rs = releer(plan, _inst(ctx)[0], {1: {"raro": 1}, 2: {"aplicado": "sí"}}, ctx=ctx)
    assert [r.estado for r in rs] == ["no_medido", "no_medido"]
    rs = releer(plan, _inst(ctx)[0], {1: {"aplicado": ["pedir_telefono"]},
                                      2: {"aplicado": {"timer_bump": 0}}}, ctx=ctx)
    assert [r.estado for r in rs] == ["ok", "ok"]


def test_error_del_conector_es_distinto(zz):
    ctx, _ = zz
    plan = _plan(_op(1, "impultienda_activar_markets", {"store_id": STORE, "activar": True}, "market.ZZ.activo"))
    [r] = releer(plan, _inst(ctx)[0], {1: {"error": "la tienda no está en Multidivisa"}}, ctx=ctx)
    assert r.estado == "distinto" and "Multidivisa" in r.evidencia


def test_valores_de_las_lecturas(zz):
    ctx, _ = zz
    inst, avisos = _inst(ctx)
    assert avisos == []
    valores = valores_de(ctx, inst)
    assert valores["<store_id>"] == STORE and "<market_id>" not in valores
    tiendas = fixture("listar_tiendas.json")
    tiendas["tiendas"][1]["url"] = "https://prueba.impultienda.example"
    inst, avisos = _inst(ctx, impultienda_listar_tiendas=tiendas)
    assert "<store_id>" not in valores_de(ctx, inst) and "no encuentro una sola tienda" in avisos[0]


def test_codigo_de_subida_no_se_guarda(tmp_path):
    ruta = tmp_path / "r.json"
    respuesta = {"link": "https://impultienda.ar/subir/c0d1g0s3cr3t0l4rg0abcdef123456", "codigo": "abc123def456",
                 "vence": "30 min"}
    ruta.write_text(json.dumps({"llamadas": [{"herramienta": "impultienda_link_subida_recursos",
                                              "argumentos": {"store_id": STORE}, "respuesta": respuesta}]}),
                    encoding="utf-8")
    [resp], guardable = leer_respuestas(ruta, CATALOGO)
    assert "abc123def456" not in guardable and "c0d1g0s3cr3t0" not in guardable
    assert resp.respuesta["vence"] == "30 min" and resp.respuesta["codigo"] != "abc123def456"


def test_confirmar_pdf_sin_uploaded_no_medido(zz):
    ctx, _ = zz
    args = {"store_id": STORE, "tipo": "ebook", "item_id": "00000000-0000-4000-8000-000000000002",
            "modo": "confirmar", "ruta": "r"}
    plan = _plan(_op(1, "impultienda_cargar_entregable", args, "producto.front.entregable"))
    [r] = releer(plan, _inst(ctx)[0], {1: {"guardado": "r"}}, ctx=ctx)
    assert r.estado == "no_medido"  # «generated» no prueba que el PDF propio esté: nunca verde
