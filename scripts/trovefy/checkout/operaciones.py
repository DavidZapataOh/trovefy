"""Plan de operaciones del MCP de Impultienda, etapa a etapa, y su resumen en seco (plan 19, Tarea 11).

La receta (Tarea 10) dice qué poner y con qué llamadas reales del catálogo; aquí se decide qué llamadas van en la
etapa que toca (`trovefy.checkout.etapas`), con sus ids ya rellenos, y se escribe el resumen que aprueba el usuario.

- `REGLAS` es la tabla cerrada de herramientas que trovefy sabe resumir, comparar con lo leído y releer. Un ajuste
  cuya llamada no está en `REGLAS`, o cuya herramienta no es ``escritura`` en el catálogo cargado, va a mano.
- `planificar` no repite lo que ya está igual en la tienda (normalizado) ni lo que ya se aplicó y releyó: reaplicar
  no reescribe.
- La huella del plan es `trovefy.tienda.mcp.huella_plan` de sus operaciones: la misma que exige la guarda del hook.

Funciones puras: leen el estado (`MCP-ESTADO.json`, ya cargado) y no escriben nada.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from trovefy.checkout.etapas import (
    LOCAL,
    Paso,
    clave_de,
    listos,
    pasos_de,
    pieza_de,
    produce,
    requiere,
)
from trovefy.checkout.receta import Ajuste, Llamada, _nombre, marcadores, rellenar
from trovefy.embudo.contexto import Contexto
from trovefy.tienda.mcp import (
    Herramienta,
    frase_aprobacion,
    huella_catalogo,
    huella_plan,
)

# --- normalización ------------------------------------------------------------------------------------------------

_CENTIMOS = Decimal("0.01")
_SI = frozenset({"sí", "si", "true", "1", "activo", "activa", "yes", "on"})
_NO = frozenset({"no", "false", "0", "inactivo", "inactiva", "off"})


def _precio(valor: object) -> Decimal | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float, Decimal)):
        texto = str(valor)
    elif isinstance(valor, str):
        texto = re.sub(r"[^\d.,]", "", valor).strip(".,")
        if "," in texto and "." in texto:
            decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
            texto = texto.replace("." if decimal == "," else ",", "").replace(",", ".")
        else:
            texto = texto.replace(",", ".")
    else:
        return None
    try:
        return Decimal(texto).quantize(_CENTIMOS)
    except (InvalidOperation, ValueError):
        return None


def normalizar(tipo: str, valor: object) -> object:
    """Valor comparable: ``precio`` → `Decimal` con dos decimales («13,90 €», «EUR 13.9», 13.9 → 13.90); ``texto`` →
    NFC, sin mayúsculas ni espacios de más; ``bool``; ``archivo`` → el nombre, sin mayúsculas; ``lista`` → códigos
    ordenados. None si no se puede leer (nunca un valor inventado)."""
    if valor is None:
        return None
    if tipo == "precio":
        return _precio(valor)
    if tipo == "texto":
        return " ".join(unicodedata.normalize("NFC", str(valor)).casefold().split())
    if tipo == "bool":
        if isinstance(valor, bool):
            return valor
        t = str(valor).strip().casefold()
        return True if t in _SI else False if t in _NO else None
    if tipo == "archivo":
        return PurePosixPath(str(valor).replace("\\", "/")).name.casefold() or None
    if tipo == "lista":
        if not isinstance(valor, (list, tuple, set)):
            return None
        return sorted(str(x).strip().upper() for x in valor)
    raise ValueError(f"tipo de normalización desconocido: {tipo!r}")


def _igual(tipo: str, a: object, b: object) -> bool:
    na, nb = normalizar(tipo, a), normalizar(tipo, b)
    return na is not None and na == nb


def precio_texto(valor: object) -> str:
    p = normalizar("precio", valor)
    return "?" if p is None else str(p).replace(".", ",")


# --- página propia de un upsell (<html:uN>) -------------------------------------------------------------------------

_BOTON = re.compile(r"\[\[(aceptar|rechazar):\s*([^\]]+?)\s*\]\]")
_GUION_COMENTARIO = re.compile(r"<!--.*?-->", re.DOTALL)
FALTAN_BOTONES = ("revisar a mano: faltan los botones en la página del upsell: añade una línea [[aceptar: «texto»]] "
                  "y otra [[rechazar: «texto»]] (el «sí» y el «no, gracias», igual de visibles)")


def _escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def pagina_html(texto_md: str) -> str | None:
    """El HTML de la página de un upsell (``checkout/<PAIS>/upsells/<clave>.md``): títulos ``#``/``##``, párrafos y
    los dos botones ``[[aceptar: …]]`` (``data-pp-accept``) y ``[[rechazar: …]]`` (``data-pp-decline``). Todo el
    texto va escapado: nada de HTML del archivo pasa tal cual. None si falta alguno de los dos botones."""
    texto = _GUION_COMENTARIO.sub("", texto_md or "")
    tipos = {m.group(1) for m in _BOTON.finditer(texto)}
    if tipos != {"aceptar", "rechazar"}:
        return None
    bloques: list[str] = []
    for parrafo in re.split(r"\n\s*\n", texto):
        lineas = [x.strip() for x in parrafo.strip().splitlines() if x.strip()]
        if not lineas:
            continue
        for linea in lineas:
            boton = _BOTON.fullmatch(linea)
            if boton:
                atributo = "data-pp-accept" if boton.group(1) == "aceptar" else "data-pp-decline"
                bloques.append(f"<p><button type=\"button\" {atributo}>{_escapar(boton.group(2))}</button></p>")
            elif linea.startswith("## "):
                bloques.append(f"<h2>{_escapar(linea[3:].strip())}</h2>")
            elif linea.startswith("# "):
                bloques.append(f"<h1>{_escapar(linea[2:].strip())}</h1>")
            else:
                bloques.append(f"<p>{_escapar(linea)}</p>")
    return "\n".join(bloques) + "\n"


def valores_locales(ajustes: list[Ajuste]) -> tuple[dict[str, str], dict[str, str]]:
    """``(valores, manuales)``: ``<html:uN>`` de cada página de upsell de la receta y, si no se puede (faltan los
    botones o el archivo), el motivo por el que esa página va a mano."""
    valores: dict[str, str] = {}
    manuales: dict[str, str] = {}
    for a in ajustes:
        if not re.fullmatch(r"postcompra\.u[123]\.pagina", a.clave):
            continue
        pieza = a.clave.split(".")[1]
        ruta = Path(a.valor) if isinstance(a.valor, Path) else None
        try:
            html = pagina_html(ruta.read_text(encoding="utf-8")) if ruta and ruta.is_file() else None
        except (OSError, UnicodeDecodeError):
            html = None
        if html is None:
            manuales[a.clave] = FALTAN_BOTONES
        else:
            valores[f"<html:{pieza}>"] = html
    return valores, manuales


# --- reglas por herramienta --------------------------------------------------------------------------------------

Estado = str  # "ok" | "distinto" | "no_medido" | "pendiente_aprobar_panel"


@dataclass(frozen=True)
class Info:
    """Lo que una regla necesita además de los argumentos: la instantánea normalizada de la tienda, los valores
    conocidos, el paso y el contexto."""

    inst: dict
    valores: dict
    paso: Paso
    ctx: Contexto


def _tienda(i: Info) -> dict:
    return i.inst.get("tienda") or {}


def _producto(i: Info, args: dict) -> dict | None:
    prods = i.inst.get("productos") or {}
    if args.get("item_id"):
        return (prods.get("por_id") or {}).get(args["item_id"])
    return prods.get("principal")


def _mercado(i: Info, market_id: str | None = None) -> dict | None:
    mercados = (i.inst.get("markets") or {}).get("mercados") or []
    if market_id:
        return next((m for m in mercados if m.get("id") == market_id), None)
    return next((m for m in mercados if not m.get("es_default") and i.ctx.pais in m.get("paises", [])), None)


def _pieza(i: Info) -> str | None:
    return next((p for p in (pieza_de(a) for a in i.paso.ajustes) if p), None)


def _titulo(i: Info) -> str:
    p = _pieza(i)
    pieza = i.ctx.piezas.get(p) if p else None
    return pieza.titulo if pieza else "el producto"


def _ofertas(i: Info) -> list[dict]:
    return (i.inst.get("postcompra") or {}).get("ofertas") or []


def _html(i: Info, oferta_id: str | None) -> dict | None:
    return (i.inst.get("html") or {}).get(oferta_id or "")


def _cmp(tipo: str, pedido: object, leido: object, hay_lectura: bool) -> Estado:
    if not hay_lectura:
        return "no_medido"
    return "ok" if _igual(tipo, pedido, leido) else "distinto"


_IDIOMAS = {"bg": "búlgaro", "ro": "rumano", "es-ES": "español", "it": "italiano", "pt-PT": "portugués",
            "en-US": "inglés", "fr": "francés", "de": "alemán", "pl": "polaco", "hu": "húngaro", "cs": "checo",
            "el": "griego", "hr": "croata", "sk": "eslovaco", "sl": "esloveno"}
_CHECKOUT = {
    "pedir_nombre": lambda v: f"pedir nombre: {'sí' if v else 'no'}",
    "pedir_apellido": lambda v: f"pedir apellido: {'sí' if v else 'no'}",
    "pedir_telefono": lambda v: f"pedir teléfono: {'sí' if v else 'no'}",
    "ocultar_barra_compradores": lambda v: "ocultar la barra de «N personas compraron»" if v else "mostrar la barra",
    "color_boton_pagar": lambda v: f"botón de pagar en verde ({v})",
    "resumen_posicion": lambda v: "resumen del pedido arriba" if v == "top" else "resumen del pedido abajo",
}


def _frase_tienda(a: dict, i: Info) -> str:
    return f"Poner el nombre de la tienda: «{a['nombre']}»"


def _frase_idioma(a: dict, i: Info) -> str:
    nombre = _IDIOMAS.get(a["idioma"], a["idioma"])
    return f"Cambiar el idioma de la tienda a {nombre} (emails al comprador y textos fijos)"


def _frase_markets(a: dict, i: Info) -> str:
    return "Activar Markets (precio fijo por país)" if a.get("activar") else "Desactivar Markets"


def _frase_mercado(a: dict, i: Info) -> str:
    return f"Crear el mercado «{a.get('nombre')}» en {a.get('moneda')} con {', '.join(a.get('paises') or [])}"


def _frase_asignar(a: dict, i: Info) -> str:
    return f"Poner {', '.join(a['paises'])} en su mercado"


def _frase_editar(a: dict, i: Info) -> str:
    quien = "del producto principal" if not a.get("item_id") else f"del producto «{_titulo(i)}»"
    return f"Poner el nombre {quien}: «{a['nombre']}»" if "nombre" in a else f"Editar el producto «{_titulo(i)}»"


def _frase_fijar(a: dict, i: Info) -> str:
    moneda = _tienda(i).get("moneda") or "la moneda de la tienda"
    return f"Poner el precio del producto «{_titulo(i)}» en {precio_texto(a['precio'])} {moneda} (sin precio tachado)"


def _frase_por_pais(a: dict, i: Info) -> str:
    return (f"Poner el precio del producto «{_titulo(i)}» en {precio_texto(a.get('precio'))} {i.ctx.moneda} para "
            f"los compradores de {i.ctx.pais} (sin precio tachado)")


def _frase_entregable(a: dict, i: Info) -> str:
    if a.get("modo") == "subir":
        return (f"Pedir el enlace para subir el PDF «{a.get('nombre_archivo')}» de «{_titulo(i)}» (lo subo yo y el "
                "enlace no se guarda)")
    return f"Marcar el PDF subido como lo que recibe el comprador de «{_titulo(i)}»"


def _frase_checkout(a: dict, i: Info) -> str:
    partes = [_CHECKOUT[k](v) for k, v in a.items() if k in _CHECKOUT]
    return "Checkout: " + "; ".join(partes)


def _frase_disenar(a: dict, i: Info) -> str:
    return "Checkout: sin temporizador de cuenta atrás"


def _frase_bloques(a: dict, i: Info) -> str:
    if i.paso.solo_vista_previa:
        return "Ver qué bloques hay abajo del checkout (solo vista previa: no cambia nada)"
    if a.get("posicion") == "abajo":
        bloques = a.get("bloques")
        cuantos = f" ({len(bloques)} bloques)" if isinstance(bloques, list) else ""
        return f"Volver a poner los bloques de abajo del checkout sin cuenta atrás ni cupos{cuantos}"
    return "Poner la foto del producto arriba del checkout"


def _frase_crear(a: dict, i: Info) -> str:
    moneda = _tienda(i).get("moneda") or "la moneda de la tienda"
    cuando = ", solo después de la compra" if a.get("solo_post_compra") else ""
    return f"Crear el upsell «{a['nombre']}» a {precio_texto(a.get('precio'))} {moneda}{cuando}"


def _frase_funnel(a: dict, i: Info) -> str:
    return f"Crear y activar el funnel post-compra «{a.get('nombre')}» (ofrece «{_titulo(i)}» después de pagar)"


def _frase_agregar(a: dict, i: Info) -> str:
    return f"Añadir «{_titulo(i)}» al funnel post-compra"


def _frase_guardar_html(a: dict, i: Info) -> str:
    return f"Guardar la página propia de la oferta «{_titulo(i)}» ({len(a.get('html') or '')} caracteres)"


def _frase_alternar_html(a: dict, i: Info) -> str:
    return f"Mostrar la página propia de la oferta «{_titulo(i)}»" if a.get("activo") else "Volver a la plantilla"


def _frase_recursos(a: dict, i: Info) -> str:
    return ("Pedir un enlace para que subas la foto del producto (entregable/medios/mockup.png) a Recursos: lo abres, "
            "la arrastras y me avisas")


# ya_esta(args, info) -> bool -------------------------------------------------------------------------------------


def _ya_tienda(a: dict, i: Info) -> bool:
    t = _tienda(i)
    return bool(t) and all(_igual("texto", v, t.get(k)) for k, v in a.items() if k != "store_id")


def _ya_idioma(a: dict, i: Info) -> bool:
    return _tienda(i).get("idioma") == a["idioma"]


def _ya_markets(a: dict, i: Info) -> bool:
    return (i.inst.get("markets") or {}).get("activo") is a.get("activar")


def _ya_mercado(a: dict, i: Info) -> bool:
    for m in (i.inst.get("markets") or {}).get("mercados") or []:
        if m.get("es_default") or m.get("moneda") != a.get("moneda"):
            continue
        if any(p in m.get("paises", []) for p in a.get("paises") or []) or _igual("texto", m.get("nombre"),
                                                                                 a.get("nombre")):
            return True
    return False


def _ya_asignar(a: dict, i: Info) -> bool:
    m = _mercado(i, a.get("market_id"))
    return m is not None and set(a["paises"]) <= set(m.get("paises", []))


def _ya_editar(a: dict, i: Info) -> bool:
    p = _producto(i, a)
    if not p:
        return False
    if "nombre" in a and not _igual("texto", a["nombre"], p.get("titulo")):
        return False
    return not ("solo_post_compra" in a and p.get("solo_post_compra") is not a["solo_post_compra"])


def _ya_fijar(a: dict, i: Info) -> bool:
    p = _producto(i, a)
    if not p or not _igual("precio", a["precio"], p.get("precio")):
        return False
    return not ("precio_original" in a and a["precio_original"] is None and p.get("precio_original") is not None)


def _ya_crear(a: dict, i: Info) -> bool:
    prods = (i.inst.get("productos") or {}).get("por_id") or {}
    return any(_igual("texto", p.get("titulo"), a["nombre"]) and p.get("tipo") == a["tipo"] for p in prods.values())


def _ya_oferta(a: dict, i: Info) -> bool:
    item = a.get("item_id") or i.valores.get(f"<item_id:{_pieza(i)}>")
    return bool(item) and any(o.get("item_id") == item for o in _ofertas(i))


def _ya_alternar(a: dict, i: Info) -> bool:
    h = _html(i, a.get("oferta_id"))
    return bool(h) and h.get("modo_html_activo") is a.get("activo")


def _nunca(a: dict, i: Info) -> bool:
    return False


# releer(args, info, respuesta) -> (pedido, leido, estado) -------------------------------------------------------


def _hay(i: Info, clave: str) -> bool:
    return bool(i.inst.get(clave))


def _r_tienda(a: dict, i: Info, r: object):
    return a.get("nombre"), _tienda(i).get("nombre"), _cmp("texto", a.get("nombre"), _tienda(i).get("nombre"),
                                                           _hay(i, "tienda"))


def _r_idioma(a: dict, i: Info, r: object):
    leido = _tienda(i).get("idioma")
    return a["idioma"], leido, _cmp("texto", a["idioma"], leido, _hay(i, "tienda"))


def _r_markets(a: dict, i: Info, r: object):
    leido = (i.inst.get("markets") or {}).get("activo")
    return a.get("activar"), leido, _cmp("bool", a.get("activar"), leido, _hay(i, "markets"))


def _r_mercado(a: dict, i: Info, r: object):
    m = _mercado(i)
    if m is None:
        return a.get("moneda"), None, "distinto" if _hay(i, "markets") else "no_medido"
    return a.get("moneda"), m.get("moneda"), _cmp("texto", a.get("moneda"), m.get("moneda"), True)


def _r_asignar(a: dict, i: Info, r: object):
    m = _mercado(i, a.get("market_id"))
    leido = None if m is None else m.get("paises", [])
    if not _hay(i, "markets"):
        return a["paises"], leido, "no_medido"
    return a["paises"], leido, "ok" if leido is not None and set(a["paises"]) <= set(leido) else "distinto"


def _r_editar(a: dict, i: Info, r: object):
    p = _producto(i, a)
    if "nombre" not in a:
        return None, None, "no_medido"
    leido = p.get("titulo") if p else None
    return a["nombre"], leido, _cmp("texto", a["nombre"], leido, _hay(i, "productos"))


def _r_fijar(a: dict, i: Info, r: object):
    p = _producto(i, a)
    leido = p.get("precio") if p else None
    return a["precio"], leido, _cmp("precio", a["precio"], leido, _hay(i, "productos"))


def _r_por_pais(a: dict, i: Info, r: object):
    fijo = r.get("precio_fijo") if isinstance(r, dict) else None
    leido = fijo.get("precio") if isinstance(fijo, dict) else None
    if leido is None:
        return a.get("precio"), None, "no_medido"
    estado = _cmp("precio", a.get("precio"), leido, True)
    if estado == "ok" and a.get("precio_original", 0) is None and fijo.get("precio_original") is not None:
        estado = "distinto"
    return a.get("precio"), leido, estado


def _r_entregable(a: dict, i: Info, r: object):
    if a.get("modo") == "subir":
        ruta = r.get("ruta") if isinstance(r, dict) else None
        return a.get("nombre_archivo"), "enlace de subida recibido" if ruta else None, "ok" if ruta else "no_medido"
    # Al confirmar, el MCP solo dice el estado del ebook: «uploaded» es el PDF propio cargado. Otro valor no prueba
    # que no esté (un formato que no se conoce es «no medido», nunca verde): lo confirma la compra de prueba.
    p = (((i.inst.get("productos") or {}).get("por_id")) or {}).get(a.get("item_id"))
    leido = p.get("estado_generacion") if p else None
    return "uploaded", leido, "ok" if leido == "uploaded" else "no_medido"


def _r_aplicado(a: dict, i: Info, r: object):
    """``configurar_checkout`` devuelve ``aplicado: [campos]`` (el servidor confirma esos campos con lo enviado);
    ``disenar_checkout``, ``aplicado: {columna: valor}``: se compara **valor a valor** con lo pedido (M2); si falta
    alguna clave pedida (columnas del panel con otro nombre) o el formato no se conoce, «no medido», nunca verde. Lo
    que se ve se comprueba además desde fuera (Tarea 12)."""
    pedidos = sorted(k for k in a if k != "store_id")
    aplicado = r.get("aplicado") if isinstance(r, dict) else None
    if isinstance(aplicado, list) and aplicado and all(isinstance(x, str) for x in aplicado):
        confirmados = set(aplicado)
        bien = all(k in confirmados or COLUMNAS_PANEL.get(k) in confirmados for k in pedidos)
        return pedidos, sorted(aplicado), "ok" if bien else "distinto"
    if isinstance(aplicado, dict) and pedidos:
        claves = {k: k if k in aplicado else COLUMNAS_PANEL.get(k) for k in pedidos}
        if all(c in aplicado for c in claves.values()):
            leido = {k: aplicado[c] for k, c in claves.items()}
            iguales = all(_mismo_valor(a[k], leido[k]) for k in pedidos)
            return {k: a[k] for k in pedidos}, leido, "ok" if iguales else "distinto"
    return pedidos, None, "no_medido"


# Nombre de columna del panel con que el conector confirma cada parámetro (respuestas reales, BG 2026-11-18).
COLUMNAS_PANEL: dict[str, str] = {
    "pedir_nombre": "checkout_fields",
    "pedir_apellido": "checkout_fields",
    "pedir_telefono": "checkout_fields",
    "ocultar_barra_compradores": "checkout_hide_social_proof",
    "resumen_posicion": "checkout_summary_position",
    "color_boton_pagar": "checkout_pay_button_color",
    "minutos_timer_bump": "checkout_bump_timer_minutes",
}


def _mismo_valor(pedido: object, leido: object) -> bool:
    if isinstance(pedido, str) and isinstance(leido, str):
        return _igual("texto", pedido, leido)
    return type(pedido) is type(leido) and pedido == leido


def _r_bloques(a: dict, i: Info, r: object):
    if i.paso.solo_vista_previa:
        actuales = r.get("actuales") if isinstance(r, dict) else None
        return "vista previa", None if actuales is None else f"{len(actuales)} bloques", \
            "ok" if isinstance(actuales, list) else "no_medido"
    n = r.get("bloques") if isinstance(r, dict) else None
    if not isinstance(r, dict) or r.get("modo") != "aplicado" or not isinstance(n, int):
        return len(a.get("bloques") or []), None, "no_medido"
    return len(a.get("bloques") or []), n, "ok" if n == len(a.get("bloques") or []) else "distinto"


def _r_crear(a: dict, i: Info, r: object):
    prods = ((i.inst.get("productos") or {}).get("por_id")) or {}
    p = next((x for x in prods.values() if _igual("texto", x.get("titulo"), a["nombre"])), None)
    if not _hay(i, "productos"):
        return a["nombre"], None, "no_medido"
    if p is None:
        return a["nombre"], None, "distinto"
    bien = p.get("tipo") == a["tipo"] and p.get("solo_post_compra") is bool(a.get("solo_post_compra"))
    return a["nombre"], p.get("titulo"), "ok" if bien else "distinto"


def _r_oferta(a: dict, i: Info, r: object):
    item = a.get("item_id") or i.valores.get(f"<item_id:{_pieza(i)}>")
    if not _hay(i, "postcompra"):
        return "en el funnel", None, "no_medido"
    esta = any(o.get("item_id") == item for o in _ofertas(i))
    return "en el funnel", "en el funnel" if esta else "no está", "ok" if esta else "distinto"


def _r_guardar_html(a: dict, i: Info, r: object):
    h = _html(i, a.get("oferta_id"))
    if h is None:
        return "página guardada", None, "no_medido"
    bien = h.get("tiene_html") is True
    return "página guardada", "página guardada" if bien else "sin página", "ok" if bien else "distinto"


def _r_alternar_html(a: dict, i: Info, r: object):
    h = _html(i, a.get("oferta_id"))
    if h is None:
        return a.get("activo"), None, "no_medido"
    return a.get("activo"), h.get("modo_html_activo"), _cmp("bool", a.get("activo"), h.get("modo_html_activo"), True)


def _r_recursos(a: dict, i: Info, r: object):
    url = (i.inst.get("recursos") or {}).get("mockup")
    return "foto en Recursos", "foto en Recursos" if url else None, "ok" if url else "no_medido"


@dataclass(frozen=True)
class Regla:
    frase: Callable[[dict, Info], str]
    ya_esta: Callable[[dict, Info], bool]
    releer: Callable[[dict, Info, object], tuple[object, object, Estado]]


REGLAS: dict[str, Regla] = {
    "impultienda_configurar_tienda": Regla(_frase_tienda, _ya_tienda, _r_tienda),
    "impultienda_cambiar_idioma": Regla(_frase_idioma, _ya_idioma, _r_idioma),
    "impultienda_activar_markets": Regla(_frase_markets, _ya_markets, _r_markets),
    "impultienda_configurar_mercado": Regla(_frase_mercado, _ya_mercado, _r_mercado),
    "impultienda_asignar_paises": Regla(_frase_asignar, _ya_asignar, _r_asignar),
    "impultienda_editar_producto": Regla(_frase_editar, _ya_editar, _r_editar),
    "impultienda_fijar_precio": Regla(_frase_fijar, _ya_fijar, _r_fijar),
    "impultienda_precio_por_pais": Regla(_frase_por_pais, _nunca, _r_por_pais),
    "impultienda_cargar_entregable": Regla(_frase_entregable, _nunca, _r_entregable),
    "impultienda_configurar_checkout": Regla(_frase_checkout, _nunca, _r_aplicado),
    "impultienda_disenar_checkout": Regla(_frase_disenar, _nunca, _r_aplicado),
    "impultienda_bloques_checkout": Regla(_frase_bloques, _nunca, _r_bloques),
    "impultienda_crear_producto": Regla(_frase_crear, _ya_crear, _r_crear),
    "impultienda_crear_funnel_postcompra": Regla(_frase_funnel, _ya_oferta, _r_oferta),
    "impultienda_agregar_oferta_postcompra": Regla(_frase_agregar, _ya_oferta, _r_oferta),
    "impultienda_guardar_html_postcompra": Regla(_frase_guardar_html, _nunca, _r_guardar_html),
    "impultienda_alternar_html_postcompra": Regla(_frase_alternar_html, _ya_alternar, _r_alternar_html),
    "impultienda_link_subida_recursos": Regla(_frase_recursos, _nunca, _r_recursos),
}
# Lo que se lee tras aplicar cada herramienta (y siempre las de base, que dan los ids).
LECTURAS_BASE: tuple[str, ...] = ("impultienda_listar_tiendas", "impultienda_listar_productos",
                                  "impultienda_ver_markets", "impultienda_ver_postcompra")
# Estados de una escritura ya aplicada que no se vuelven a planificar.
HECHA = frozenset({"ok", "no_medido", "pendiente_aprobar_panel"})


# --- el plan de una etapa ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Operacion:
    n: int
    ajustes: tuple[str, ...]
    herramienta: str
    argumentos: dict
    lectura: str | None
    clave: str = ""
    dos_pasos: bool = False
    solo_vista_previa: bool = False
    frase: str = ""


@dataclass(frozen=True)
class Espera:
    """Un paso que va en una etapa posterior: lo que le falta (ids que da una escritura anterior)."""

    ajustes: tuple[str, ...]
    herramienta: str
    frase: str
    faltan: tuple[str, ...]


@dataclass
class Plan:
    operaciones: list[Operacion]
    manuales: list[Ajuste]
    ya_estan: list[Ajuste]
    huella: str
    huella_catalogo: str
    etapa: int = 1
    pendientes: list[Espera] = field(default_factory=list)
    motivos_manuales: dict[str, str] = field(default_factory=dict)
    lecturas_despues: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    pasos: list[Paso] = field(default_factory=list)


def _dos_pasos(h: Herramienta) -> bool:
    return "token" in ((h.esquema or {}).get("properties") or {})


def _motivo_sin_llamada(a: Ajuste) -> str:
    return a.motivo if a.motivo else "el conector no tiene herramienta para esto"


def _manuales(ajustes: list[Ajuste], catalogo: dict[str, Herramienta], estado: dict,
              locales_manuales: dict[str, str]) -> dict[str, str]:
    motivos: dict[str, str] = {}
    for a in ajustes:
        if not a.llamadas:
            motivos[a.clave] = _motivo_sin_llamada(a)
            continue
        for ll in a.llamadas:
            h = catalogo.get(ll.herramienta)
            if h is None or h.clase != "escritura":
                clase = "no está en el catálogo" if h is None else f"es {h.clase} en el catálogo"
                motivos[a.clave] = f"no disponible por el conector ({clase}): lo haces tú en tu panel"
                break
            if ll.herramienta not in REGLAS:
                motivos[a.clave] = "no disponible por el conector (trovefy no sabe releerlo): lo haces tú en tu panel"
                break
    motivos.update({k: v for k, v in locales_manuales.items() if k not in motivos})
    for m in (estado.get("manuales") or {}).values():
        for clave in m.get("ajustes", []):
            motivos.setdefault(clave, m.get("motivo", "revisar a mano"))
    return motivos


def _con_funnel_existente(pasos: list[Paso], inst: dict) -> list[Paso]:
    """Si la tienda ya tiene un funnel post-compra, el primer upsell se añade con ``agregar_oferta_postcompra``
    (``crear_funnel_postcompra`` en modo «siempre» solo vale sin ningún funnel)."""
    if not (inst.get("postcompra") or {}).get("funnels"):
        return pasos
    salida = []
    for p in pasos:
        if p.herramienta == "impultienda_crear_funnel_postcompra":
            pieza = next((x for x in (pieza_de(a) for a in p.ajustes) if x), None)
            args = {"store_id": "<store_id>", "item_id": f"<item_id:{pieza}>"}
            h = "impultienda_agregar_oferta_postcompra"
            p = Paso(clave_de(h, args), p.ajustes, h, args, "impultienda_ver_postcompra")
        salida.append(p)
    return salida


def _lecturas_despues(ops: list[Operacion], valores: dict) -> list[dict]:
    store = valores.get("<store_id>")
    lecturas = [{"herramienta": "impultienda_listar_tiendas", "argumentos": {}}]
    lecturas += [{"herramienta": h, "argumentos": {"store_id": store}} for h in LECTURAS_BASE[1:]]
    if any(o.herramienta == "impultienda_link_subida_recursos" for o in ops):
        lecturas.append({"herramienta": "impultienda_ver_recursos", "argumentos": {"store_id": store,
                                                                                    "tipo": "imagen"}})
    vistas: set[str] = set()
    for o in ops:
        oferta = o.argumentos.get("oferta_id")
        if o.lectura == "impultienda_leer_html_postcompra" and oferta and oferta not in vistas:
            vistas.add(oferta)
            lecturas.append({"herramienta": "impultienda_leer_html_postcompra",
                             "argumentos": {"store_id": store, "oferta_id": oferta}})
    return lecturas


def planificar(ctx: Contexto, ajustes: list[Ajuste], catalogo: dict[str, Herramienta], estado_actual: dict, *,
               etapa: int = 1) -> Plan:
    """El plan de la etapa ``etapa``: las llamadas cuyos ids ya se conocen (lecturas y etapas anteriores), sin lo
    que ya está igual en la tienda ni lo ya aplicado; lo que espera a otra etapa; lo que va a mano. ``estado_actual``
    es el contenido de ``MCP-ESTADO.json`` (``valores``, ``instantanea``, ``hechas``, ``manuales``)."""
    inst = estado_actual.get("instantanea") or {}
    valores = dict(estado_actual.get("valores") or {})
    hechas = estado_actual.get("hechas") or {}
    locales, manuales_locales = valores_locales(ajustes)
    motivos = _manuales(ajustes, catalogo, estado_actual, manuales_locales)
    manuales = [a for a in ajustes if a.clave in motivos]
    validos = [a for a in ajustes if a.clave not in motivos]
    pasos = _con_funnel_existente(pasos_de(validos), inst)
    conocidos = set(valores) | set(locales)
    todos = {**valores, **locales}

    hechos: set[str] = set()
    ya: set[str] = set()  # igual en la tienda, o aplicado y releído «ok»
    for p in pasos:
        estado_paso = (hechas.get(p.clave) or {}).get("estado")
        if estado_paso in HECHA:
            hechos.add(p.clave)
            if estado_paso == "ok":
                ya.add(p.clave)
            continue
        if produce(p) and produce(p) <= set(valores) and (p.solo_vista_previa
                                                           or p.herramienta == "impultienda_link_subida_recursos"):
            hechos.add(p.clave)  # la vista previa o el enlace ya dieron lo suyo
            ya.add(p.clave)
            continue
        if requiere(p) <= conocidos:
            info = Info(inst, valores, p, ctx)
            if REGLAS[p.herramienta].ya_esta(rellenar(Llamada(p.herramienta, p.argumentos, None), todos), info):
                ya.add(p.clave)
                hechos.add(p.clave)
    lista, esperan = listos(pasos, conocidos, hechos)

    operaciones: list[Operacion] = []
    for n, p in enumerate(lista, 1):
        args = rellenar(Llamada(p.herramienta, p.argumentos, None), todos)
        info = Info(inst, valores, p, ctx)
        operaciones.append(Operacion(
            n=n, ajustes=p.ajustes, herramienta=p.herramienta, argumentos=args, lectura=p.lectura, clave=p.clave,
            dos_pasos=_dos_pasos(catalogo[p.herramienta]) and not p.solo_vista_previa,
            solo_vista_previa=p.solo_vista_previa, frase=REGLAS[p.herramienta].frase(args, info)))
    pendientes = []
    for p, faltan in esperan:
        info = Info(inst, valores, p, ctx)
        try:
            frase = REGLAS[p.herramienta].frase(_plantilla(p.argumentos, todos), info)
        except (KeyError, TypeError, ValueError):
            frase = p.herramienta
        pendientes.append(Espera(p.ajustes, p.herramienta, frase, tuple(sorted(faltan))))

    por_ajuste: dict[str, list[str]] = {}
    for p in pasos:
        for a in p.ajustes:
            por_ajuste.setdefault(a, []).append(p.clave)
    ya_estan = [a for a in validos if por_ajuste.get(a.clave) and all(k in ya for k in por_ajuste[a.clave])]
    ops_json = [{"herramienta": o.herramienta, "argumentos": o.argumentos} for o in operaciones]
    return Plan(operaciones=operaciones, manuales=manuales, ya_estan=ya_estan, huella=huella_plan(ops_json),
                huella_catalogo=huella_catalogo(catalogo), etapa=etapa, pendientes=pendientes,
                motivos_manuales=motivos, lecturas_despues=_lecturas_despues(operaciones, valores), pasos=pasos)


def _plantilla(argumentos: object, valores: dict) -> object:
    """Los argumentos con los marcadores conocidos rellenos y el resto tal cual (para resumir lo que espera)."""
    if isinstance(argumentos, str):
        return valores.get(argumentos, argumentos) if argumentos in marcadores(argumentos) else argumentos
    if isinstance(argumentos, dict):
        return {k: _plantilla(v, valores) for k, v in argumentos.items()}
    if isinstance(argumentos, list):
        return [_plantilla(v, valores) for v in argumentos]
    return argumentos


# --- resumen en seco ---------------------------------------------------------------------------------------------


_PARTES = {"titulo": "nombre", "precio": "precio", "entregable": "PDF", "pagina": "página propia",
           "activo": "en el funnel post-compra"}


def _etiqueta(a: Ajuste) -> str:
    """El nombre del ajuste para el usuario, sin claves internas."""
    partes = a.clave.split(".")
    if partes[0] == "market":
        return {"activo": "Markets activo", "moneda": f"Mercado de {partes[1]} en su moneda",
                "paises": f"{partes[1]} en su mercado"}.get(partes[2], _nombre(a))
    if partes[0] == "postcompra":
        return f"Upsell {partes[1].upper()}: {_PARTES.get(partes[2], partes[2])}"
    if partes[0] == "emails":
        return {"entrega": "Email de entrega", "seguimiento_72h": "Email de las 72 h"}.get(partes[1], a.clave)
    return _nombre(a)


def resumen_en_seco(plan: Plan, ctx: Contexto) -> str:
    """El resumen que aprueba el usuario: una línea por operación de la etapa, lo que ya está bien, lo que va en las
    etapas siguientes y lo que irá a mano. En español llano, sin nombres de herramienta ni ids."""
    lineas = [f"# Etapa {plan.etapa} · checkout de {ctx.producto} en {ctx.pais}", ""]
    if plan.operaciones:
        lineas += [("Esto es lo que voy a cambiar en tu tienda de Impultienda en esta etapa. Nada se aplica sin tu "
                    "«sí»; además, el conector te pedirá aprobar cada llamada."), ""]
        for o in plan.operaciones:
            extra = " (primero verás una vista previa)" if o.dos_pasos else ""
            lineas.append(f"{o.n}. {o.frase}{extra}")
    else:
        lineas.append("En esta etapa no hay nada que cambiar por el conector.")
    if plan.ya_estan:
        lineas += ["", "## Ya está bien", ""]
        lineas += [f"- {_etiqueta(a)}" for a in plan.ya_estan]
    if plan.pendientes:
        lineas += ["", "## En las etapas siguientes (cuando tengamos los datos que dan estos cambios)", ""]
        lineas += [f"- {e.frase}" for e in plan.pendientes]
    if plan.manuales:
        lineas += ["", "## Irá a mano (lo haces tú en tu panel; te guío paso a paso)", ""]
        lineas += [f"- {_etiqueta(a)}: {plan.motivos_manuales.get(a.clave, a.motivo)}" for a in plan.manuales]
    if plan.avisos:
        lineas += ["", "## Avisos", ""]
        lineas += [f"- {x}" for x in plan.avisos]
    if plan.operaciones:
        frase = frase_aprobacion(plan.etapa, plan.huella)
        pide = (f"Si te parece bien, apruébalo tú con esta frase exacta: «{frase}». Está atada a este plan: si el "
                "plan cambia, cambia la frase. Ejecuta tú, en tu terminal (fuera de Claude):")
        orden = f'    trovefy checkout aprobar --producto {ctx.producto} --pais {ctx.pais} --cita "{frase}"'
        nadie = ("Claude no puede aprobarlo por ti, y cualquier otra respuesta («sí», «ok», «dale») no aprueba "
                 "nada.")
        lineas += ["", "## Para aprobarlo", "", pide, "", orden, "", nadie]
    texto = "\n".join(lineas) + "\n"
    return LOCAL.sub("", texto)
