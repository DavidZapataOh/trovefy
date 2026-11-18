"""Plan de una etapa del MCP y su resumen en seco (plan 19, Tarea 11): funciones puras, sin MCP."""
from __future__ import annotations

import dataclasses
import re
from decimal import Decimal
from pathlib import Path

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy.checkout.operaciones import (
    REGLAS,
    normalizar,
    pagina_html,
    planificar,
    resumen_en_seco,
)
from trovefy.checkout.receta import OpcionesReceta, ajustes_de_checkout
from trovefy.checkout.relectura import estado_nuevo, instantanea, valores_de
from trovefy.embudo.contexto import cargar_contexto
from trovefy.tienda.mcp import (
    Catalogo,
    cargar_catalogo,
    huella_catalogo,
    huella_plan,
    violaciones,
)

from .mcp_falso import FRONT, STORE, fixture
from .test_receta import MAX, _preparar

CATALOGO = cargar_catalogo()


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v)
    return cargar_contexto(v, P, PAIS), emails
MERCADO = "00000000-0000-4000-8000-000000000003"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _lecturas(**cambios) -> dict:
    lecturas = {"impultienda_listar_tiendas": fixture("listar_tiendas.json"),
                "impultienda_listar_productos": fixture("listar_productos.json"),
                "impultienda_ver_markets": fixture("ver_markets.json"),
                "impultienda_ver_postcompra": fixture("ver_postcompra.json")}
    lecturas.update(cambios)
    return lecturas


def _estado(ctx, lecturas: dict | None = None, **extra) -> dict:
    est = estado_nuevo()
    inst, _ = instantanea(ctx, lecturas or _lecturas())
    est.update(instantanea=inst, valores=valores_de(ctx, inst), lecturas_completas=True, **extra)
    return est


def _con_mercado(paises: list[str]) -> dict:
    m = fixture("ver_markets.json")
    m["mercados"].append({"id": MERCADO, "nombre": "ZZ EUR", "moneda": "EUR", "es_default": False,
                          "paises": [{"codigo": p, "nombre": p} for p in paises], "precios_fijos": 0, "avisos": []})
    return m


def _catalogo_con(prohibidas: set[str]) -> Catalogo:
    hs = {n: (dataclasses.replace(h, clase="prohibida", motivo="prueba") if n in prohibidas else h)
          for n, h in CATALOGO.items()}
    return Catalogo(hs, fuente=CATALOGO.fuente, fecha=CATALOGO.fecha, servidor=CATALOGO.servidor,
                    plan=CATALOGO.plan, faltan=CATALOGO.faltan)


def _plan(zz, catalogo=CATALOGO, estado=None):
    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    return ctx, aj, planificar(ctx, aj, catalogo, estado if estado is not None else _estado(ctx))


# --- normalizar ---------------------------------------------------------------------------------------------------


def test_relectura_normaliza_precio():
    assert normalizar("precio", "13,90 €") == normalizar("precio", "EUR 13.9") == Decimal("13.90")
    assert normalizar("precio", 13.9) == normalizar("precio", "13.90") == Decimal("13.90")
    assert normalizar("precio", "1.234,50 лв.") == Decimal("1234.50")
    assert normalizar("precio", "14.00") != normalizar("precio", "13,90")
    assert normalizar("precio", "gratis") is None and normalizar("precio", True) is None


def test_normalizar_otros():
    assert normalizar("texto", "  Спокойно   ТЯЛО ") == normalizar("texto", "спокойно тяло")
    assert normalizar("bool", "Sí") is True and normalizar("bool", "no") is False and normalizar("bool", "x") is None
    assert normalizar("archivo", Path("/a/b/Prueba-BG-v1.PDF")) == "prueba-bg-v1.pdf"
    assert normalizar("lista", ["zz", "AA"]) == ["AA", "ZZ"]
    with pytest.raises(ValueError):
        normalizar("otro", 1)


# --- planificar ---------------------------------------------------------------------------------------------------


def test_plan_solo_escrituras_permitidas(zz):
    _, _, plan = _plan(zz)
    assert plan.operaciones
    for op in plan.operaciones:
        h = CATALOGO[op.herramienta]
        assert h.clase == "escritura" and op.herramienta in REGLAS
        assert violaciones(h, op.argumentos) == [], op
        assert op.argumentos.get("confirmar") in (None, False) and "token" not in op.argumentos
    assert plan.huella == huella_plan([{"herramienta": o.herramienta, "argumentos": o.argumentos}
                                       for o in plan.operaciones])
    assert plan.huella_catalogo == huella_catalogo(CATALOGO)


def test_primera_etapa_con_ids_de_las_lecturas(zz):
    _, _, plan = _plan(zz)
    assert all(op.argumentos["store_id"] == STORE for op in plan.operaciones)
    sube = next(o for o in plan.operaciones if o.herramienta == "impultienda_cargar_entregable")
    assert sube.argumentos["item_id"] == FRONT and sube.argumentos["modo"] == "subir"
    # Lo que espera a un id que da una escritura de esta etapa va después.
    esperan = {e.herramienta for e in plan.pendientes}
    assert {"impultienda_precio_por_pais", "impultienda_crear_funnel_postcompra"} <= esperan
    vista = next(o for o in plan.operaciones if o.solo_vista_previa)
    assert vista.argumentos == {"store_id": STORE, "posicion": "abajo", "bloques": [], "confirmar": False}
    assert not vista.dos_pasos


def test_ajuste_sin_herramienta_va_a_mano(zz):
    _, _, plan = _plan(zz, _catalogo_con({"impultienda_precio_por_pais"}))
    manuales = {a.clave for a in plan.manuales}
    assert {"producto.front.precio", "postcompra.u1.precio", "emails.entrega", "checkout.plantilla"} <= manuales
    assert "es prohibida" in plan.motivos_manuales["producto.front.precio"]
    assert all(o.herramienta != "impultienda_precio_por_pais" for o in plan.operaciones)
    assert all(e.herramienta != "impultienda_precio_por_pais" for e in plan.pendientes)


def test_reaplicar_no_reescribe_lo_igual(zz):
    ctx, _ = zz
    tiendas = fixture("listar_tiendas.json")
    tiendas["tiendas"][0].update(nombre="Somatix", idioma="bg")
    markets = _con_mercado(["ZZ"])
    markets["markets_activo"] = True
    productos = fixture("listar_productos.json")
    productos["productos"][0]["titulo"] = "Спокойно тяло"
    est = _estado(ctx, _lecturas(impultienda_listar_tiendas=tiendas, impultienda_ver_markets=markets,
                                 impultienda_listar_productos=productos))
    _, _, plan = _plan(zz, estado=est)
    ya = {a.clave for a in plan.ya_estan}
    assert {"tienda.nombre", "checkout.idioma", "market.ZZ.activo", "market.ZZ.moneda", "market.ZZ.paises",
            "producto.front.titulo"} <= ya
    nombres = {o.herramienta for o in plan.operaciones}
    assert not nombres & {"impultienda_configurar_tienda", "impultienda_cambiar_idioma", "impultienda_activar_markets",
                          "impultienda_configurar_mercado", "impultienda_asignar_paises",
                          "impultienda_editar_producto"}
    # Lo ya aplicado y releído «ok» tampoco se repite: con todo hecho, cero operaciones.
    hechas = {}
    for _ in range(6):
        if not plan.operaciones:
            break
        hechas |= {o.clave: {"estado": "ok", "etapa": 1} for o in plan.operaciones}
        _, _, plan = _plan(zz, estado={**est, "hechas": hechas, "valores": {
            **est["valores"], "<item_id:u1>": "u1", "<ruta:front>": "r", "<ruta:u1>": "r",
            "<bloques:abajo>": [], "<url:mockup>": "https://cdn.ejemplo.test/m.webp", "<oferta_id:u1>": "o"}})
    assert plan.operaciones == []


def test_mercado_existente_sin_el_pais_usa_asignar(zz):
    ctx, _ = zz
    _, _, plan = _plan(zz, estado=_estado(ctx, _lecturas(impultienda_ver_markets=_con_mercado([]))))
    nombres = [o.herramienta for o in plan.operaciones]
    assert "impultienda_configurar_mercado" not in nombres
    asignar = next(o for o in plan.operaciones if o.herramienta == "impultienda_asignar_paises")
    assert asignar.argumentos["market_id"] == MERCADO and asignar.argumentos["paises"] == ["ZZ"]


def test_upsell_ya_creado_no_se_duplica(zz):
    ctx, _ = zz
    productos = fixture("listar_productos.json")
    productos["productos"].append({"id": "00000000-0000-4000-8000-0000000000u1".replace("u1", "11"),
                                   "titulo": "Сън без болка", "tipo": "upsell", "precio": 19.9,
                                   "solo_post_compra": True, "estado_generacion": "draft"})
    _, _, plan = _plan(zz, estado=_estado(ctx, _lecturas(impultienda_listar_productos=productos)))
    assert all(o.herramienta != "impultienda_crear_producto" for o in plan.operaciones)
    assert "postcompra.u1.titulo" in {a.clave for a in plan.ya_estan}
    # Y su precio entra ya en esta etapa si se conoce el mercado.


def test_funnel_existente_usa_agregar(zz):
    ctx, _ = zz
    post = fixture("ver_postcompra.json")
    post["funnels"] = [{"funnel_id": "f", "nombre": "otro"}]
    est = _estado(ctx, _lecturas(impultienda_ver_postcompra=post))
    est["valores"]["<item_id:u1>"] = "00000000-0000-4000-8000-000000000011"
    est["hechas"] = {}
    _, _, plan = _plan(zz, estado=est)
    todos = [o.herramienta for o in plan.operaciones] + [e.herramienta for e in plan.pendientes]
    assert "impultienda_crear_funnel_postcompra" not in todos
    assert "impultienda_agregar_oferta_postcompra" in todos


# --- resumen en seco ----------------------------------------------------------------------------------------------


def test_resumen_en_seco_sin_ids_de_herramienta(zz):
    ctx, _ = zz
    _, _, plan = _plan(zz, estado=_estado(ctx, _lecturas(impultienda_ver_markets=_con_mercado(["ZZ"]))))
    texto = resumen_en_seco(plan, ctx)
    assert "impultienda_" not in texto and not UUID.search(texto) and "<" not in texto
    assert "Poner el precio del producto «Спокойно тяло» en 13,90 EUR" in texto
    assert "Poner el nombre de la tienda: «Somatix»" in texto
    assert "(primero verás una vista previa)" in texto
    assert "## Irá a mano" in texto and "Plantilla" in texto
    assert "## En las etapas siguientes" in texto
    # H3: la frase de aprobación va atada a este plan (etapa y huella), sin afirmaciones genéricas.
    frase = f"sí, aplica la etapa {plan.etapa} ({plan.huella[:4]})"
    assert f"«{frase}»" in texto and f'--cita "{frase}"' in texto
    assert "sí, dale" not in texto


# --- M2: `aplicado` se compara por valores ------------------------------------------------------------------------


def test_aplicado_por_valores_no_por_numero_de_claves():
    pedido = {"store_id": STORE, "minutos_timer_bump": 0}
    releer = REGLAS["impultienda_disenar_checkout"].releer
    assert releer(pedido, None, {"aplicado": {"minutos_timer_bump": 0}})[2] == "ok"
    assert releer(pedido, None, {"aplicado": {"minutos_timer_bump": 7}})[2] == "distinto"
    # Mismo número de claves, pero otra columna: no se sabe → no medido (antes salía «ok»).
    assert releer(pedido, None, {"aplicado": {"timer": 7}})[2] == "no_medido"
    assert releer(pedido, None, {"aplicado": {}})[2] == "no_medido"
    assert releer(pedido, None, {"otra": 1})[2] == "no_medido"
    campos = {"store_id": STORE, "pedir_telefono": True, "color_boton_pagar": "#16a34a"}
    rcampos = REGLAS["impultienda_configurar_checkout"].releer
    assert rcampos(campos, None, {"aplicado": {"pedir_telefono": True, "color_boton_pagar": "#16A34A"}})[2] == "ok"
    assert rcampos(campos, None, {"aplicado": {"pedir_telefono": False, "color_boton_pagar": "#16a34a"}})[2] \
        == "distinto"


# --- página del upsell --------------------------------------------------------------------------------------------


def test_pagina_html_escapa_y_pone_botones():
    md = ("<!-- guion: gracias -->\n## Благодаря\n\nТекст <script>alert(1)</script> & повече.\n\n"
          "[[aceptar: Да, искам го]]\n[[rechazar: Не, благодаря]]\n")
    html = pagina_html(md)
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html
    assert '<button type="button" data-pp-accept>Да, искам го</button>' in html
    assert "data-pp-decline" in html and "<h2>Благодаря</h2>" in html and "guion" not in html
    assert pagina_html("## Solo texto\n\n[[aceptar: Sí]]\n") is None


def test_aplicado_con_los_nombres_reales_del_conector():
    """Respuestas reales del conector (BG, 2026-11-18): `configurar_checkout` confirma columnas del panel
    (`checkout_fields`, …) y `disenar_checkout` devuelve `{checkout_bump_timer_minutes: 0}`."""
    rcampos = REGLAS["impultienda_configurar_checkout"].releer
    campos = {"store_id": STORE, "pedir_nombre": True, "pedir_apellido": False, "pedir_telefono": True}
    assert rcampos(campos, None, {"aplicado": ["checkout_fields"]})[2] == "ok"
    assert rcampos({"store_id": STORE, "ocultar_barra_compradores": True}, None,
                   {"aplicado": ["checkout_hide_social_proof"]})[2] == "ok"
    assert rcampos({"store_id": STORE, "resumen_posicion": "top"}, None,
                   {"aplicado": ["checkout_summary_position"]})[2] == "ok"
    assert rcampos({"store_id": STORE, "color_boton_pagar": "#16a34a"}, None,
                   {"aplicado": ["checkout_pay_button_color"]})[2] == "ok"
    # Una columna que no corresponde sigue siendo «distinto».
    assert rcampos({"store_id": STORE, "color_boton_pagar": "#16a34a"}, None,
                   {"aplicado": ["checkout_fields"]})[2] == "distinto"
    rdis = REGLAS["impultienda_disenar_checkout"].releer
    pedido = {"store_id": STORE, "minutos_timer_bump": 0}
    assert rdis(pedido, None, {"aplicado": {"checkout_bump_timer_minutes": 0}})[2] == "ok"
    assert rdis(pedido, None, {"aplicado": {"checkout_bump_timer_minutes": 5}})[2] == "distinto"


# --- U1 al precio de la escalera ----------------------------------------------------------------------------------


def test_descuento_de_u1_se_corrige_si_el_funnel_lo_puso(zz):
    from .test_relectura import U1, _postcompra

    ctx, _ = zz
    est = _estado(ctx, _lecturas(impultienda_ver_postcompra=_postcompra("15%")))
    est["valores"]["<item_id:u1>"] = U1
    _, _, plan = _plan(zz, estado=est)
    op = next(o for o in plan.operaciones if o.herramienta == "impultienda_modificar_oferta_postcompra")
    assert op.argumentos == {"store_id": STORE, "item_id": U1, "descuento_pct": 0, "aplicar_a": "upsell"}
    assert op.ajustes == ("postcompra.u1.descuento",) and not op.dos_pasos
    assert violaciones(CATALOGO[op.herramienta], op.argumentos) == []
    texto = resumen_en_seco(plan, ctx)
    assert "Poner la oferta «Сън без болка» al precio de la escalera (sin descuento)" in texto
    # Ya a 0 %: no se reescribe.
    est = _estado(ctx, _lecturas(impultienda_ver_postcompra=_postcompra("0%")))
    est["valores"]["<item_id:u1>"] = U1
    _, _, plan = _plan(zz, estado=est)
    assert all(o.herramienta != "impultienda_modificar_oferta_postcompra" for o in plan.operaciones)
    assert "postcompra.u1.descuento" in {a.clave for a in plan.ya_estan}
