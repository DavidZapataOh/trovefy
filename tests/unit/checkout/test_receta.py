"""Receta del checkout como datos (plan 19, Tarea 10; «DESVÍOS RESUELTOS» de la cabecera del plan).

La receta se expresa con las herramientas reales del catálogo del MCP de Impultienda y sus nombres de parámetro
reales: cada llamada tiene que pasar `violaciones()` y la guarda del hook. Ningún test llama al MCP.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from embudo.ejemplos_embudo import PAIS, PASOS_FICTICIOS, P, vault_embudo
from plan_aprobado import plan_aprobado
from trovefy.checkout.receta import (
    GUION_UPSELL,
    Ajuste,
    Llamada,
    OpcionesReceta,
    ajustes_de_checkout,
    hay_escasez,
    hay_testimonio,
    limpiar_bloques,
    marcadores,
    operaciones,
    receta_manual,
    rellenar,
    validar_pagina_upsell,
)
from trovefy.embudo.contexto import cargar_contexto, ruta_pais
from trovefy.mapa import cargar, limites_de_plan
from trovefy.tienda.mcp import cargar_catalogo, huella_plan, violaciones

RAIZ = Path(__file__).resolve().parents[3]
MAPA = cargar(RAIZ / "templates/impultienda/mapa.yaml")
MAX = limites_de_plan(MAPA, "Max")
FREE = limites_de_plan(MAPA, "Free")
CATALOGO = cargar_catalogo()
UUID = "00000000-0000-4000-8000-00000000000{}"

EMAIL_BG = """---
asunto: Вашето ръководство е готово
---
Здравейте,

Благодарим ви за поръчката. Ръководството „Спокойно тяло“ е прикачено към този имейл и можете да го
изтеглите веднага. Ако имате въпроси, просто отговорете на това писмо и ще ви помогнем.

Поздрави,
Екипът на Somatix
"""


def _pagina_u1() -> str:
    partes = []
    for clave, _ in GUION_UPSELL:
        partes.append(f"<!-- guion: {clave} -->\n## {clave}\n\nТекст за {clave}.\n")
    return "\n".join(partes)


def _preparar(v: Path, *, mockup: bool = True, pagina_u1: bool = True) -> dict[str, Path]:
    prod = v / "productos" / P
    if mockup:
        (prod / "entregable" / "medios").mkdir(parents=True, exist_ok=True)
        (prod / "entregable" / "medios" / "mockup.png").write_bytes(b"\x89PNG ficticio")
    pais = prod / "checkout" / PAIS
    if pagina_u1:
        (pais / "upsells").mkdir(parents=True, exist_ok=True)
        (pais / "upsells" / "u1.md").write_text(_pagina_u1(), encoding="utf-8")
    (pais / "emails").mkdir(parents=True, exist_ok=True)
    (pais / "emails" / "entrega.md").write_text(EMAIL_BG, encoding="utf-8")
    return {"entrega": pais / "emails" / "entrega.md"}


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v)
    return cargar_contexto(v, P, PAIS), emails


@pytest.fixture
def zz_tres_activos(tmp_path):
    pasos = {k: dict(v) for k, v in PASOS_FICTICIOS.items()}
    for k in ("u2", "u3"):
        pasos[k].update(activo=True, motivo_inactivo=None)
    v = vault_embudo(tmp_path, pasos=pasos)
    prod = v / "productos" / P
    from trovefy.vault import frontmatter
    meta, cuerpo = frontmatter.leer(prod / "PRODUCTO.md")
    for k in ("u2", "u3"):
        rel = f"entregable/upsells/{k}/{k}-bg-v1.pdf"
        (prod / rel).parent.mkdir(parents=True, exist_ok=True)
        (prod / rel).write_bytes(b"%PDF-1.7 ficticio")
        meta["entregable"]["bg"][k] = {"version": 1, "pdf": rel, "paginas": 2}
    frontmatter.escribir(prod / "PRODUCTO.md", meta, cuerpo)
    emails = _preparar(v)
    for k in ("u2", "u3"):
        (prod / "checkout" / PAIS / "upsells" / f"{k}.md").write_text(_pagina_u1(), encoding="utf-8")
    return cargar_contexto(v, P, PAIS), emails


def _por_clave(aj: list[Ajuste]) -> dict[str, Ajuste]:
    return {a.clave: a for a in aj}


# --- reglas de la receta -----------------------------------------------------------------------------------------


def test_receta_por_defecto_sigue_a_los_videos(zz):
    ctx, emails = zz
    aj, av = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    claves = {a.clave for a in aj}
    assert f"market.{PAIS}.activo" in claves and f"market.{PAIS}.moneda" in claves
    assert not any(c.startswith("bump.") for c in claves)
    assert ("producto.front.precio", "13.90") in [(a.clave, a.valor) for a in aj]
    assert _por_clave(aj)["tienda.nombre"].valor == "Somatix"
    assert _por_clave(aj)["checkout.campos"].valor == "email,nombre,telefono"  # teléfono: sí (ruling)
    assert _por_clave(aj)["checkout.idioma"].valor == "bg"
    assert "emails.entrega" in claves and "emails.seguimiento_72h" not in claves
    assert not any(c.startswith("downsell.") for c in claves)
    assert any("downsell" in a and "R-c" in a for a in av)


def test_market_en_eur_con_las_herramientas_de_markets(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))[0])
    assert [ll.herramienta for ll in aj[f"market.{PAIS}.activo"].llamadas] == ["impultienda_activar_markets"]
    mercado = aj[f"market.{PAIS}.moneda"].llamadas[0]
    assert mercado.herramienta == "impultienda_configurar_mercado"
    assert mercado.argumentos["moneda"] == "EUR" and mercado.argumentos["paises"] == [PAIS]
    assert aj[f"market.{PAIS}.paises"].llamadas[0].herramienta == "impultienda_asignar_paises"
    precio = aj["producto.front.precio"].llamadas[0]
    assert precio.herramienta == "impultienda_precio_por_pais"
    assert precio.argumentos["precio"] == 13.9 and Decimal(repr(precio.argumentos["precio"])) == Decimal("13.90")
    assert precio.argumentos["market_id"] == "<market_id>" and "item_id" not in precio.argumentos


def test_misma_moneda_que_la_tienda_usa_fijar_precio(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max", moneda_tienda="EUR"))[0])
    assert not any(c.startswith("market.") for c in aj)
    assert aj["producto.front.precio"].llamadas[0].herramienta == "impultienda_fijar_precio"


def test_bump_apagado_opcion(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max", bump_apagado=True))[0])
    assert aj["bump.activo"].valor is False
    # El bump no se crea por el conector: no podría quedar apagado en una tienda clásica.
    assert all(not aj[c].llamadas for c in aj if c.startswith("bump."))


def test_telefono_opcion(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max", telefono=False))[0])
    assert aj["checkout.campos"].valor == "email,nombre"
    args = aj["checkout.campos"].llamadas[0].argumentos
    assert args["pedir_telefono"] is False and args["pedir_nombre"] is True


def test_u1_completo(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))[0])
    for campo in ("titulo", "precio", "entregable", "pagina", "activo"):
        assert f"postcompra.u1.{campo}" in aj
    assert aj["postcompra.u1.precio"].valor == "19.90"
    assert aj["postcompra.u1.pagina"].valor == ruta_pais(ctx) / "upsells" / "u1.md"
    creado = aj["postcompra.u1.titulo"].llamadas[0]
    assert creado.herramienta == "impultienda_crear_producto"
    assert creado.argumentos["tipo"] == "upsell" and creado.argumentos["solo_post_compra"] is True
    assert aj["postcompra.u1.activo"].llamadas[0].herramienta == "impultienda_crear_funnel_postcompra"


def test_u2_u3_inactivos_dan_aviso(zz):
    ctx, emails = zz
    aj, av = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    assert not any(a.clave.startswith(("postcompra.u2", "postcompra.u3")) for a in aj)
    for k in ("u2", "u3"):
        assert any(a.startswith("no disponible") and k in a for a in av)


def test_free_un_solo_upsell(zz_tres_activos):
    ctx, emails = zz_tres_activos
    aj, av = ajustes_de_checkout(ctx, FREE, emails, OpcionesReceta("Free"))
    assert {a.clave.split(".")[1] for a in aj if a.clave.startswith("postcompra.")} == {"u1"}
    assert any(a.startswith("desvío") and "u2" in a for a in av)
    aj_max, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    assert {a.clave.split(".")[1] for a in aj_max if a.clave.startswith("postcompra.")} == {"u1", "u2", "u3"}
    otros = _por_clave(aj_max)
    assert otros["postcompra.u2.activo"].llamadas[0].herramienta == "impultienda_agregar_oferta_postcompra"


def test_limites_desconocidos_no_meten_upsells(zz):
    ctx, emails = zz
    aj, av = ajustes_de_checkout(ctx, None, emails, OpcionesReceta("Max"))
    assert not any(a.clave.startswith("postcompra.") for a in aj)
    assert any(a.startswith("no medido") and "ver_plan" in a for a in av)


def test_sin_temporizador_ni_cupos(zz):
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))[0])
    assert aj["checkout.temporizador"].valor is False and aj["checkout.cupos"].valor is False
    disenos = [ll for a in aj.values() for ll in a.llamadas if ll.herramienta == "impultienda_disenar_checkout"]
    assert disenos and all(ll.argumentos["minutos_timer_bump"] == 0 for ll in disenos)
    bloques = [b for a in aj.values() for ll in a.llamadas if ll.herramienta == "impultienda_bloques_checkout"
               for b in rellenar(ll, _relleno([ll]))["bloques"]]
    assert bloques and not any(b["tipo"] in ("countdown", "stock") for b in bloques)


def test_barra_de_compradores_oculta(zz):
    """M5: la barra «N personas compraron» es prueba social sin compradores reales (D-01): se oculta."""
    ctx, emails = zz
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))[0])
    configs = [ll.argumentos for a in aj.values() for ll in a.llamadas
               if ll.herramienta == "impultienda_configurar_checkout"]
    assert any(c.get("ocultar_barra_compradores") is True for c in configs)
    assert not any("texto_barra_compradores" in c or "posicion_barra_compradores" in c for c in configs)


def test_bloques_de_abajo_se_reenvian_sin_escasez(zz):
    """M5: los bloques que ya hay abajo del checkout se releen y se vuelven a mandar sin cuenta atrás ni cupos."""
    ctx, emails = zz
    aj, av = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    abajo = [ll for a in aj for ll in a.llamadas
             if ll.herramienta == "impultienda_bloques_checkout" and ll.argumentos["posicion"] == "abajo"]
    assert len(abajo) == 1 and abajo[0].argumentos["bloques"] == "<bloques:abajo>"
    assert any("HTML" in a and "a mano" in a for a in av)  # los bloques HTML no los toca el conector


def test_limpiar_bloques():
    limpios, avisos = limpiar_bloques(ACTUALES_ABAJO)
    assert [b["tipo"] for b in limpios] == ["text", "image"]
    assert limpios[0]["texto"].startswith("Pago seguro")
    assert any("countdown" in a for a in avisos) and any("stock" in a for a in avisos)
    assert any("остават" in a for a in avisos)
    limpios, avisos = limpiar_bloques([{"tipo": "html", "html": "<div id=t></div>"}, {"tipo": "raro"}])
    assert limpios == []
    assert any("revisar a mano" in a and "HTML" in a for a in avisos)
    assert any("revisar a mano" in a and "raro" in a for a in avisos)
    assert limpiar_bloques([]) == ([], [])
    with pytest.raises(ValueError):
        limpiar_bloques("no es una lista")


def test_bloques_limpios_pasan_el_catalogo():
    limpios, _ = limpiar_bloques(ACTUALES_ABAJO)
    args = {"store_id": UUID.format(1), "posicion": "abajo", "bloques": limpios}
    assert violaciones(CATALOGO["impultienda_bloques_checkout"], args) == []


def test_sin_precio_tachado(zz):
    """M5: precio_original: None, para que no salga un precio tachado (falso descuento)."""
    ctx, emails = zz
    for opciones in (OpcionesReceta("Max"), OpcionesReceta("Max", moneda_tienda="EUR")):
        aj, _ = ajustes_de_checkout(ctx, MAX, emails, opciones)
        precios = [ll for a in aj for ll in a.llamadas
                   if ll.herramienta in ("impultienda_precio_por_pais", "impultienda_fijar_precio")]
        assert precios
        for ll in precios:
            assert "precio_original" in CATALOGO[ll.herramienta].esquema["properties"]
            assert ll.argumentos["precio_original"] is None, ll


def test_free_sin_funnel_postcompra(zz):
    """L6: el plan Free no tiene funnel post-compra: la receta no lo crea y lo avisa."""
    ctx, emails = zz
    aj, av = ajustes_de_checkout(ctx, limites_de_plan(MAPA, "Free"), emails, OpcionesReceta("Free"))
    nombres = {ll.herramienta for a in aj for ll in a.llamadas}
    assert "impultienda_crear_funnel_postcompra" not in nombres
    assert "impultienda_agregar_oferta_postcompra" not in nombres
    assert any("Free" in a and "funnel" in a for a in av)


def test_foto_y_plantilla(zz):
    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    d = _por_clave(aj)
    assert d["checkout.foto"].valor == ctx.vault / "productos" / P / "entregable" / "medios" / "mockup.png"
    assert d["checkout.plantilla"].valor == "Bambú" and not d["checkout.plantilla"].llamadas
    assert "si tu panel la ofrece" in d["checkout.plantilla"].motivo
    assert d["checkout.boton"].llamadas[0].argumentos["color_boton_pagar"].startswith("#")


def test_sin_mockup_no_medido(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v, mockup=False)
    aj, av = ajustes_de_checkout(cargar_contexto(v, P, PAIS), MAX, emails, OpcionesReceta("Max"))
    assert "checkout.foto" not in {a.clave for a in aj}
    assert any(a.startswith("no medido") and "mockup" in a for a in av)


def test_sin_pdf_front_error(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v)
    (v / "productos" / P / "entregable" / "prueba-bg-v1.pdf").unlink()
    with pytest.raises(ValueError, match="falta el PDF del front"):
        ajustes_de_checkout(cargar_contexto(v, P, PAIS), MAX, emails, OpcionesReceta("Max"))


def test_sin_email_de_entrega_no_medido(zz):
    ctx, _ = zz
    aj, av = ajustes_de_checkout(ctx, MAX, {}, OpcionesReceta("Max"))
    assert "emails.entrega" not in {a.clave for a in aj}
    assert any(a.startswith("no medido") and "entrega" in a for a in av)


def test_email_72h_opcion(zz):
    ctx, emails = zz
    _, av = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max", email_72h=True))
    assert any(a.startswith("no medido") and "seguimiento_72h" in a for a in av)


def test_pagina_upsell_mal_da_aviso(tmp_path):
    v = vault_embudo(tmp_path)
    emails = _preparar(v, pagina_u1=False)
    aj, av = ajustes_de_checkout(cargar_contexto(v, P, PAIS), MAX, emails, OpcionesReceta("Max"))
    assert "postcompra.u1.pagina" not in {a.clave for a in aj}
    assert any("u1" in a and "página" in a for a in av)


def test_vocabulario_cerrado():
    with pytest.raises(ValueError):
        Ajuste("tienda.contraseña", "x", "m", None, False)
    Ajuste(f"market.{PAIS}.activo", True, "m", None, False)


def test_opciones_por_defecto():
    o = OpcionesReceta("Max")
    assert (o.telefono, o.bump_apagado, o.email_72h, o.moneda_tienda) == (True, False, False, "USD")


# --- las llamadas pasan el catálogo y la guarda del hook ----------------------------------------------------------


ACTUALES_ABAJO = [
    {"tipo": "text", "etiqueta": "p", "texto": "Pago seguro y entrega inmediata por email."},
    {"tipo": "countdown", "minutos": 7, "texto": "La oferta termina en"},
    {"tipo": "stock", "inicial": 12, "minimo": 3, "texto": "Quedan {count} cupos"},
    {"tipo": "text", "etiqueta": "p", "texto": "Остават само 3 места!"},
    {"tipo": "image", "url": "https://cdn.ejemplo.test/sello.png", "alt": "Sello", "ancho_pct": 40},
]


def _relleno(llamadas: list[Llamada]) -> dict[str, object]:
    todos = sorted({m for ll in llamadas for m in marcadores(ll.argumentos)})
    return {m: (limpiar_bloques(ACTUALES_ABAJO)[0] if m.startswith("<bloques:") else UUID.format(i % 10))
            for i, m in enumerate(todos)}


def test_cada_llamada_pasa_violaciones(zz_tres_activos):
    ctx, emails = zz_tres_activos
    for opciones in (OpcionesReceta("Max"), OpcionesReceta("Max", telefono=False, bump_apagado=True)):
        aj, _ = ajustes_de_checkout(ctx, MAX, emails, opciones)
        llamadas = [ll for a in aj for ll in a.llamadas]
        assert llamadas
        valores = _relleno(llamadas)
        for ll in llamadas:
            h = CATALOGO[ll.herramienta]
            assert h.clase == "escritura", ll.herramienta
            args = rellenar(ll, valores)
            assert not marcadores(args)
            assert violaciones(h, args) == [], (ll.herramienta, args)
            assert ll.lectura is None or CATALOGO[ll.lectura].clase == "lectura"
            assert "confirmar" not in args and "token" not in args


def test_marcadores_y_rellenar():
    ll = Llamada("impultienda_fijar_precio", {"store_id": "<store_id>", "item_id": "<item_id:u1>", "precio": 1},
                 "impultienda_listar_productos")
    assert marcadores(ll.argumentos) == {"<store_id>", "<item_id:u1>"}
    with pytest.raises(ValueError, match="item_id:u1"):
        rellenar(ll, {"<store_id>": "s"})
    assert rellenar(ll, {"<store_id>": "s", "<item_id:u1>": "i"}) == {"store_id": "s", "item_id": "i", "precio": 1}


def test_operaciones_en_orden_y_sin_repetir(zz):
    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    ops = operaciones(aj)
    assert ops[0]["herramienta"] == "impultienda_configurar_tienda"
    nombres = [o["herramienta"] for o in ops]
    assert nombres.index("impultienda_activar_markets") < nombres.index("impultienda_configurar_mercado") \
        < nombres.index("impultienda_precio_por_pais")
    assert len({json.dumps(o, sort_keys=True) for o in ops}) == len(ops)


def test_la_guarda_del_hook_deja_pasar_el_plan_aprobado(zz, monkeypatch):
    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    ops = operaciones(aj)
    valores = _relleno([Llamada(o["herramienta"], o["argumentos"], None) for o in ops])
    ops = [{"herramienta": o["herramienta"], "argumentos": rellenar(Llamada(o["herramienta"], o["argumentos"], None),
                                                                     valores)} for o in ops]
    carpeta = ruta_pais(ctx)
    carpeta.mkdir(parents=True, exist_ok=True)
    huella = huella_plan(ops)
    assert huella == hashlib.sha256(json.dumps(ops, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":")).encode()).hexdigest()
    # Aprobado como lo deja `trovefy checkout aprobar` (huella del plan, su frase y el mensaje en el registro).
    plan_aprobado(ctx.vault, ops, pais=ctx.pais, producto=ctx.producto)
    monkeypatch.setenv("TROVEFY_VAULT", str(ctx.vault))
    monkeypatch.syspath_prepend(str(RAIZ / "hooks"))
    guarda = importlib.import_module("impultienda_guard")
    for o in ops:
        assert guarda.clasificar("mcp__impultienda__" + o["herramienta"], o["argumentos"]) == ("allow", ""), o
    # Una llamada con temporizador o con bloques de cupos no pasaría nunca.
    malo = {"store_id": UUID.format(1), "minutos_timer_bump": 7}
    assert guarda.clasificar("mcp__impultienda__impultienda_disenar_checkout", malo)[0] == "deny"


# --- escasez, testimonios, guion -----------------------------------------------------------------------------------


def test_hay_escasez():
    assert hay_escasez("Остават 2 места · 09:59") == ["остават", "09:59"]
    assert hay_escasez("La oferta acaba en {timer}") == ["{timer}"]
    assert hay_escasez("Solo { count } libres") == ["{ count }"]
    assert hay_escasez("¡Solo hoy! Quedan pocas plazas") == ["solo hoy", "quedan"]
    assert hay_escasez("Ръководство за спокойно тяло, 13,90 €") == []


def test_hay_testimonio():
    assert hay_testimonio("«Това ръководство промени живота ми!» — Мария, София")
    assert hay_testimonio("★★★★★ 5/5")
    assert not hay_testimonio("Ще се радваме да ни оставите честен отзив, ако искате.")


def test_guion_upsell_completo():
    assert len(GUION_UPSELL) == 8
    assert validar_pagina_upsell(_pagina_u1()) == []


def test_guion_upsell_incompleto():
    texto = _pagina_u1().replace(f"<!-- guion: {GUION_UPSELL[3][0]} -->", "")
    problemas = validar_pagina_upsell(texto)
    assert any(GUION_UPSELL[3][0] in p for p in problemas)


def test_guion_upsell_con_timer():
    texto = _pagina_u1() + "\nОферта до {timer}\n"
    assert any("escasez" in p and "{timer}" in p for p in validar_pagina_upsell(texto))


def test_guion_upsell_desordenado_y_con_escasez():
    claves = [c for c, _ in GUION_UPSELL]
    orden = claves[1:2] + claves[:1] + claves[2:]
    texto = "\n".join(f"<!-- guion: {c} -->\nТекст." for c in orden) + "\nОстават 3 места!"
    problemas = validar_pagina_upsell(texto)
    assert any("orden" in p for p in problemas) and any("escasez" in p for p in problemas)


# --- receta manual (respaldo) ------------------------------------------------------------------------------------


def test_receta_manual_sin_app_impultienda(zz):
    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    pasos = receta_manual(aj)
    texto = "\n".join(f"{p.pestana} {p.instruccion}" for p in pasos)
    assert "app.impultienda.ar" not in texto
    assert "https://impultienda.ar/login" in texto
    assert {c for p in pasos for c in p.ajustes} == {a.clave for a in aj}
    vistas = {"General", "Pagos", "Meta / Tracking", "Remarketing", "GhostAds", "Dominio", "Webhooks"}
    for p in pasos:
        assert p.pestana in vistas or p.pestana.startswith("búscalo en tu panel: ") or p.pestana == "Entrar"
    assert re.search(r"13[,.]90", texto)


# --- límites del plan en el mapa -----------------------------------------------------------------------------------


def test_limites_del_plan_en_el_mapa():
    assert MAX["upsells"] == 3 and FREE["upsells"] == 1
    assert limites_de_plan(MAPA, "Starter")["upsells"] == 1 and limites_de_plan(MAPA, "Pro")["upsells"] == 2
    assert MAX["bumps"] is None and MAX["downsell"] is None  # no publicado: se lee con impultienda_ver_plan
    assert "ver_plan" in MAPA["fuente_limites"]


# --- M6 (revisión T6–10): ids en tiempo de ejecución → Tarea 11 -------------------------------------------------


def test_m6_plan_por_etapas_con_ids_de_la_lectura(zz):
    """Los ids que solo se conocen al ejecutar (``<market_id>``, ``<item_id:u1>``, ``<ruta:…>``, ``<oferta_id:u1>``,
    ``<bloques:abajo>``, ``<url:mockup>``) parten la receta en etapas: cada etapa solo lleva marcadores que ya se
    conocen por las lecturas o por las escrituras de etapas anteriores, así que cada una se aprueba con sus ids ya
    rellenos y su huella final."""
    from trovefy.checkout.etapas import etapas_de, produce

    ctx, emails = zz
    aj, _ = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    leidos = {"<store_id>", "<item_id:front>"}  # de listar_tiendas y listar_productos
    etapas = etapas_de(aj, leidos)
    assert len(etapas) >= 3
    conocidos = set(leidos)
    vistos: list[str] = []
    for etapa in etapas:
        assert etapa
        for paso in etapa:
            faltan = marcadores(paso.argumentos) - conocidos
            assert {m for m in faltan if not m.startswith("<html:")} == set(), (paso.herramienta, faltan)
        for paso in etapa:
            conocidos |= produce(paso)
            vistos.append(paso.herramienta)
    # Todas las llamadas de la receta acaban en alguna etapa, en orden de dependencias.
    claves = [p.clave for e in etapas for p in e]
    assert len(claves) == len(set(claves))
    assert len(claves) == len(operaciones(aj)) + 2  # + la vista previa de los bloques y el enlace de Recursos
    assert {o["herramienta"] for o in operaciones(aj)} <= set(vistos)
    primera = {p.herramienta for p in etapas[0]}
    assert "impultienda_precio_por_pais" not in primera          # espera al <market_id> del mercado creado
    assert "impultienda_guardar_html_postcompra" not in primera  # espera a la oferta del funnel
    pos = {h: i for i, e in enumerate(etapas) for h in (p.herramienta for p in e)}
    assert pos["impultienda_crear_funnel_postcompra"] > pos["impultienda_crear_producto"]
    assert pos["impultienda_guardar_html_postcompra"] > pos["impultienda_crear_funnel_postcompra"]
    # Con el mercado ya leído, el precio del front entra en la primera etapa.
    etapas_con_mercado = etapas_de(aj, leidos | {"<market_id>"})
    assert any(p.herramienta == "impultienda_precio_por_pais" and "item_id" not in p.argumentos
               for p in etapas_con_mercado[0])


# --- hallazgos en la tienda real (2026-11-17) ----------------------------------------------------------------------


def test_hallazgos_de_la_tienda_real_quedan_cubiertos(zz):
    """Precio 0, barra «5 души купуват в момента», campo apellido, botón azul sin foto, garantía de 7 días y Clarity
    en el checkout: la receta fija cada uno por el conector o, si no hay herramienta, lo deja a mano."""
    ctx, emails = zz
    from trovefy.vault import frontmatter

    frontmatter.escribir(ctx.vault / "productos" / P / "OFERTA.md", {"tipo": "oferta", "core": {"garantia_dias": 30}},
                         "Ficticio.\n")
    aj = _por_clave(ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))[0])
    llamadas = [(a.clave, ll) for a in aj.values() for ll in a.llamadas]
    args = [(c, ll.herramienta, ll.argumentos) for c, ll in llamadas]
    # Precio de ZZ por Markets, 13,90 EUR, sin tachado.
    assert ("producto.front.precio", "impultienda_precio_por_pais",
            {"store_id": "<store_id>", "market_id": "<market_id>", "precio": 13.9, "precio_original": None}) in args
    checkout = {k: v for _, h, a in args if h == "impultienda_configurar_checkout" for k, v in a.items()}
    assert checkout["ocultar_barra_compradores"] is True
    assert checkout["pedir_telefono"] is True and checkout["pedir_apellido"] is False
    assert checkout["color_boton_pagar"] == "#16a34a" and checkout["resumen_posicion"] == "top"
    assert any(h == "impultienda_bloques_checkout" and a["posicion"] == "arriba" and a["bloques"][0]["tipo"] == "image"
               for _, h, a in args)
    # Garantía: el catálogo solo tiene `ocultar_garantia` (sin días) → a mano, con los días de OFERTA.md.
    con_garantia = [n for n, h in CATALOGO.items() if h.clase == "escritura"
                    and any("garant" in k and k != "ocultar_garantia" for k in h.esquema.get("properties", {}))]
    assert con_garantia == []
    assert aj["checkout.garantia"].valor == "30 días" and aj["checkout.garantia"].llamadas == ()
    # Clarity fuera del checkout: a mano (configurar_tracking es prohibida).
    assert aj["checkout.clarity"].llamadas == () and CATALOGO["impultienda_configurar_tracking"].clase == "prohibida"
    pasos = {p.ajustes[0]: p for p in receta_manual(aj.values())[1:]}
    assert pasos["checkout.clarity"].pestana == "Meta / Tracking"


def test_garantia_sin_oferta_no_medida(zz):
    ctx, emails = zz
    aj, avisos = ajustes_de_checkout(ctx, MAX, emails, OpcionesReceta("Max"))
    assert _por_clave(aj)["checkout.garantia"].valor == "la misma que la landing"
    assert any("garantia_dias" in a for a in avisos)


def test_limpiar_bloques_respuesta_real_sin_bloques():
    """La vista previa real describe la posición vacía como ["(sin bloques)"] (BG, 2026-11-18)."""
    assert limpiar_bloques(["(sin bloques)"]) == ([], [])
