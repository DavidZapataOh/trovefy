"""Receta del checkout como datos (plan 19, Tarea 10; «DESVÍOS RESUELTOS» de la cabecera del plan).

Funciones puras: leen el `Contexto` del producto-país y devuelven qué poner en Impultienda, ajuste a ajuste, cada uno
con la cita del vídeo que lo justifica y, si el conector lo permite, las llamadas exactas al MCP oficial expresadas
con las herramientas **reales** del catálogo (`config/impultienda_tools.json`) y sus nombres de parámetro reales.
Ninguna llamada lleva ``confirmar`` ni ``token`` (los pone el paso de dos fases del propio conector) y todas cumplen
las restricciones del catálogo: ``disenar_checkout`` siempre con ``minutos_timer_bump: 0`` y sin ``pago_*`` ni
``anuncio_bonos`` (R-e, M-4); ``bloques_checkout`` nunca con ``countdown`` ni ``stock`` (D-01); ``configurar_checkout``
solo con los parámetros del ruling R-f.

Los ids que solo se conocen al leer la tienda van como marcadores (``<store_id>``, ``<market_id>``,
``<item_id:u1>``, ``<ruta:front>``, ``<bloques:abajo>``…): los rellena la Tarea 11 con las lecturas del MCP
(`rellenar`; ``<bloques:abajo>`` con `limpiar_bloques` de los bloques actuales). M6 de la revisión T6–10: como esos
ids solo se conocen al ejecutar, el plan aprobado no puede llevar su huella final de una vez; la Tarea 11 lo
resuelve con planes por etapas (test ``xfail`` en ``tests/unit/checkout/test_receta.py``).

D-01 completo (M5): sin temporizador, sin bloques ``countdown``/``stock`` (tampoco los que ya hubiera abajo), sin
barra de compradores, sin precio tachado (``precio_original: None``) y sin ``{timer}``/``{count}`` en los textos.

Lo que manda la cabecera del plan (ruling del 2026-11-17): teléfono sí, sin order bump, upsells como los vídeos
empezando por U1, sin downsell propio (el de recuperación automático del funnel sí, R-c), sin email de 72 h.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from trovefy.embudo.contexto import Contexto, Pieza, ruta_pais
from trovefy.vault.producto import ruta_producto

# --- vocabulario ---------------------------------------------------------------------------------------------------

_P = r"[A-Z]{2}"
VOCABULARIO: tuple[str, ...] = (
    r"tienda\.(nombre|logo)",
    rf"market\.{_P}\.(activo|moneda|paises|precio_front)",
    r"tracking\.pixel_id",
    r"producto\.front\.(titulo|precio|entregable)",
    r"checkout\.(idioma|campos|temporizador|cupos|foto|plantilla|boton|garantia|clarity)",
    r"bump\.(titulo|precio|entregable|activo)",
    r"postcompra\.u[123]\.(titulo|precio|entregable|pagina|activo|descuento)",
    r"downsell\.[a-z_]+",
    r"emails\.(entrega|seguimiento_72h)",
)
_VOCABULARIO = re.compile("|".join(f"(?:{v})" for v in VOCABULARIO))
_MARCADOR = re.compile(r"<[a-z_]+(?::[a-z0-9_]+)?>")

PLANTILLA_VIDEOS = "Bambú"
VERDE = "#16a34a"
LOGIN = "https://impultienda.ar/login"
# `impultienda_cambiar_idioma` (enum del esquema): código del mercado → código de la tienda.
_IDIOMAS_TIENDA = frozenset({
    "es-AR", "es-ES", "es-MX", "es-419", "en-US", "pt-BR", "fr", "it", "de", "ar", "nl", "pl", "sv", "da", "no", "fi",
    "sr", "ja", "ko", "zh-CN", "zh-TW", "ru", "uk", "tr", "ro", "hu", "cs", "sk", "el", "bg", "mk", "sq", "sl", "lt",
    "lv", "et", "is", "ca", "hy", "ka", "kk", "he", "hi", "bn", "ur", "id", "ms", "vi", "th", "pt-PT", "hr",
})
_IDIOMA_POR_DEFECTO = {"es": "es-ES", "en": "en-US", "pt": "pt-PT", "zh": "zh-CN"}
# `impultienda_disenar_checkout.plantilla` (descripción del esquema).
PLANTILLAS_CONECTOR = ("default", "hotmart", "cartpanda", "perfectpay", "mundpay", "kiwify", "digistore24", "stripe",
                       "shopify", "limonada", "comanda", "pluma", "opalo", "escudo", "coral", "vitrina", "firma")

CITA_FUNNEL = "V1 1:04:46"
AVISO_DOWNSELL = ("sin downsell propio (ruling del 2026-11-17: el de los vídeos es engañoso); el funnel post-compra "
                  "crea uno de recuperación por upsell con descuento real (40→60 %), aceptado por R-c, sin textos de "
                  "urgencia")


@dataclass(frozen=True)
class OpcionesReceta:
    """``plan``: el de Impultienda con el que se calcula (``Max`` en la prueba). ``telefono``: sí por ruling.
    ``bump_apagado`` y ``email_72h``: no por ruling (se conservan como opción del plan). ``moneda_tienda``: la base
    de la tienda (USD): si no es la del mercado, el precio va por Markets."""

    plan: str
    telefono: bool = True
    bump_apagado: bool = False
    email_72h: bool = False
    moneda_tienda: str = "USD"


@dataclass(frozen=True)
class Llamada:
    """Una llamada al MCP: ``herramienta`` del catálogo (sin el prefijo del cliente), ``argumentos`` con los nombres
    reales del esquema (ids como marcadores) y la herramienta de ``lectura`` con la que se relee (None = solo se
    comprueba desde fuera)."""

    herramienta: str
    argumentos: dict
    lectura: str | None


@dataclass(frozen=True)
class Ajuste:
    clave: str
    valor: str | bool | int | Path
    motivo: str
    cita: str | None
    fuera: bool
    llamadas: tuple[Llamada, ...] = field(default=())

    def __post_init__(self) -> None:
        if not isinstance(self.clave, str) or not _VOCABULARIO.fullmatch(self.clave):
            raise ValueError(f"clave de ajuste fuera del vocabulario: {self.clave!r}")


@dataclass(frozen=True)
class PasoReceta:
    n: int
    pestana: str
    instruccion: str
    ajustes: tuple[str, ...]


# --- marcadores ----------------------------------------------------------------------------------------------------


def marcadores(argumentos: object) -> set[str]:
    """Los marcadores (``<store_id>``, ``<item_id:u1>``…) que quedan en los argumentos."""
    if isinstance(argumentos, str):
        return set(_MARCADOR.findall(argumentos)) if _MARCADOR.fullmatch(argumentos) else set()
    if isinstance(argumentos, dict):
        return set().union(*(marcadores(v) for v in argumentos.values())) if argumentos else set()
    if isinstance(argumentos, (list, tuple)):
        return set().union(*(marcadores(v) for v in argumentos)) if argumentos else set()
    return set()


def _sustituir(valor: object, valores: dict[str, str]) -> object:
    if isinstance(valor, str) and _MARCADOR.fullmatch(valor):
        if valor not in valores:
            raise ValueError(f"falta el valor de {valor}")
        return valores[valor]
    if isinstance(valor, dict):
        return {k: _sustituir(v, valores) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sustituir(v, valores) for v in valor]
    return valor


def rellenar(llamada: Llamada, valores: dict[str, str]) -> dict:
    """Los argumentos con cada marcador sustituido; ``ValueError`` si falta alguno."""
    return _sustituir(llamada.argumentos, valores)  # type: ignore[return-value]


def operaciones(ajustes: Iterable[Ajuste]) -> list[dict]:
    """``[{herramienta, argumentos}]`` en el orden de la receta, sin llamadas repetidas (base del ``PLAN-MCP``)."""
    vistas: set[str] = set()
    salida: list[dict] = []
    for a in ajustes:
        for ll in a.llamadas:
            clave = json.dumps([ll.herramienta, ll.argumentos], sort_keys=True, ensure_ascii=False)
            if clave not in vistas:
                vistas.add(clave)
                salida.append({"herramienta": ll.herramienta, "argumentos": ll.argumentos})
    return salida


# --- escasez, testimonios y guion de upsell (D-01) -----------------------------------------------------------------

PALABRAS_ESCASEZ: tuple[str, ...] = (
    # es
    "últimas", "últimos", "último día", "quedan", "solo hoy", "sólo hoy", "cupos", "plazas limitadas", "se agota",
    "se agotan", "agotado", "termina hoy", "expira", "cuenta atrás", "cuenta regresiva", "date prisa",
    # bg
    "остават", "остана", "останаха", "само днес", "последни", "последен шанс", "ограничен брой", "изчерпва",
    "изчерпват", "бързайте", "изтича", "броени",
    # ro / it / en
    "ultimele", "doar azi", "grăbește-te", "mai sunt", "solo oggi", "affrettati", "posti limitati", "only today",
    "last chance", "hurry", "spots left", "limited time", "selling out",
)
_RELOJ = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")
# Marcadores de la plataforma que se convierten en cuenta atrás o en cupos al mostrarse (M5).
_MARCADOR_ESCASEZ = re.compile(r"\{\s*(?:timer|count|countdown|stock|cupos)\s*\}")
_PATRONES_ESCASEZ = [(p, re.compile(rf"(?<!\w){re.escape(p)}(?!\w)")) for p in PALABRAS_ESCASEZ]
_TESTIMONIO = (
    re.compile(r"[«\"“„][^«»\"“”„]{8,}[»\"”“]\s*[—–-]\s*\w+"),  # «…» — Nombre
    re.compile(r"[★⭐]{3,}"),
    re.compile(r"(?<![\d.,])[1-5](?:[.,]\d)?\s*/\s*5(?![\d])"),
)


def hay_escasez(texto: str) -> list[str]:
    """Las palabras de escasez o urgencia (y los relojes ``09:59`` y los marcadores ``{timer}``/``{count}``) que
    aparecen, en orden de aparición."""
    normal = (texto or "").casefold()
    hallados: list[tuple[int, str]] = []
    for palabra, patron in _PATRONES_ESCASEZ:
        hallados += [(m.start(), palabra) for m in patron.finditer(normal)]
    hallados += [(m.start(), m.group(0)) for m in _RELOJ.finditer(normal)]
    hallados += [(m.start(), m.group(0)) for m in _MARCADOR_ESCASEZ.finditer(normal)]
    return [p for _, p in sorted(hallados)]


def hay_testimonio(texto: str) -> list[str]:
    """Lo que parece un testimonio o una valoración (cita con nombre, estrellas, «5/5»). En el test 1 no hay
    compradores: cualquier testimonio sería inventado (D-01). Pedir una reseña real no cuenta."""
    return [m.group(0) for p in _TESTIMONIO for m in p.finditer(texto or "")]


_TIPOS_BLOQUE = ("image", "carousel", "video", "text")
_CLAVES_BLOQUE = frozenset({"tipo", "url", "alt", "ancho_pct", "imagenes", "alto", "orientacion", "autoplay",
                            "etiqueta", "texto"})
AVISO_HTML = ("revisar a mano: los bloques HTML de arriba y abajo del checkout los conserva el conector y no los toca; "
              "míralos en tu panel (Diseño de checkout) y quita cualquier cuenta atrás, cupos o «N personas "
              "compraron» (D-01)")


def limpiar_bloques(actuales: object) -> tuple[list[dict], list[str]]:
    """Los bloques que ya hay en una posición del checkout (``actuales`` de la vista previa de
    ``impultienda_bloques_checkout``), listos para volver a mandarse sin escasez (D-01, M5): fuera ``countdown``,
    ``stock`` y cualquier bloque con palabras de urgencia o ``{timer}``/``{count}``; un bloque HTML o de tipo
    desconocido no se puede reenviar (el conector conserva los HTML): se avisa «revisar a mano». Devuelve
    ``(bloques, avisos)``; ``ValueError`` si ``actuales`` no es una lista."""
    if not isinstance(actuales, list):
        raise ValueError("los bloques actuales no son una lista: no se reenvía nada (no medido)")  # noqa: TRY004 - dato del MCP
    limpios: list[dict] = []
    avisos: list[str] = []
    # La vista previa real describe una posición vacía como ["(sin bloques)"].
    actuales = [b for b in actuales if not (isinstance(b, str) and b.strip().casefold() == "(sin bloques)")]
    for n, b in enumerate(actuales, 1):
        tipo = b.get("tipo") if isinstance(b, dict) else None
        if tipo in ("countdown", "stock"):
            avisos.append(f"quitado: bloque {n} ({tipo}, D-01)")
            continue
        if tipo == "html":
            avisos.append(f"revisar a mano: bloque {n} es HTML: el conector no lo toca; míralo en tu panel y quita "
                          "cualquier cuenta atrás o cupos (D-01)")
            continue
        if tipo not in _TIPOS_BLOQUE:
            avisos.append(f"revisar a mano: bloque {n} de tipo «{tipo}» desconocido: no se reenvía")
            continue
        textos = [v for k in ("texto", "alt") if isinstance(v := b.get(k), str)]
        escasez = [p for t in textos for p in hay_escasez(t)]
        if escasez:
            avisos.append(f"quitado: bloque {n} ({tipo}) con escasez o urgencia: {', '.join(dict.fromkeys(escasez))}")
            continue
        limpios.append({k: v for k, v in b.items() if k in _CLAVES_BLOQUE})
    return limpios, avisos


GUION_UPSELL: tuple[tuple[str, str], ...] = (
    ("gracias", "confirma que la compra ya está hecha y que el PDF llega por email"),
    ("problema", "U1: el mismo problema, mejor resuelto; U2/U3: el problema siguiente"),
    ("oferta", "qué es el producto, en una frase"),
    ("contenido", "qué incluye, de verdad (lo que trae el PDF)"),
    ("resultado", "qué consigue el comprador, sin promesas de salud ni de ingresos"),
    ("precio", "el precio declarado y el descuento real, si lo hay"),
    ("garantia", "la garantía y cómo llega"),
    ("decision", "el botón «sí» y el «no, gracias», igual de visibles"),
)
_GUION = re.compile(r"<!--\s*guion:\s*([a-z_]+)\s*-->")


def validar_pagina_upsell(texto_md: str) -> list[str]:
    """Problemas de la página de un upsell (``checkout/<PAIS>/upsells/<clave>.md``): los 8 puntos de
    `GUION_UPSELL`, marcados con ``<!-- guion: <clave> -->`` y en orden, sin escasez ni testimonios. ``[]`` = bien.

    El «guion de 8 puntos» de los vídeos es de la mentoría (🔒, V1 1:04:46): este es el nuestro, honesto."""
    esperadas = [c for c, _ in GUION_UPSELL]
    vistas = _GUION.findall(texto_md or "")
    problemas = [f"falta el punto «{c}» del guion ({d})" for c, d in GUION_UPSELL if c not in vistas]
    problemas += [f"punto desconocido en el guion: «{c}»" for c in dict.fromkeys(vistas) if c not in esperadas]
    presentes = [c for c in dict.fromkeys(vistas) if c in esperadas]
    if presentes != [c for c in esperadas if c in presentes]:
        problemas.append("los puntos del guion no van en orden")
    if len(vistas) != len(set(vistas)):
        problemas.append("un punto del guion aparece dos veces")
    escasez = hay_escasez(texto_md)
    if escasez:
        problemas.append(f"escasez o urgencia (D-01): {', '.join(dict.fromkeys(escasez))}")
    testimonios = hay_testimonio(texto_md)
    if testimonios:
        problemas.append(f"testimonio o valoración inventados (D-01): {testimonios[0]}")
    return problemas


# --- la receta -----------------------------------------------------------------------------------------------------


def _numero(precio: Decimal) -> int | float:
    """El precio como número JSON para el MCP (el esquema pide ``number``). Se comprueba la ida y vuelta: el
    `Decimal` del vault y el número enviado son el mismo importe."""
    numero: int | float = int(precio) if precio == precio.to_integral_value() else float(str(precio))
    if Decimal(repr(numero)) != precio:
        raise ValueError(f"el precio {precio} no se puede enviar exacto")
    return numero


def _idioma_tienda(idioma: str) -> str | None:
    if idioma in _IDIOMAS_TIENDA:
        return idioma
    return _IDIOMA_POR_DEFECTO.get(idioma)


def _texto(valor: object) -> str:
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, Path):
        return valor.name
    return str(valor)


class _Receta:
    def __init__(self, ctx: Contexto, limites_plan: dict | None, emails: dict[str, Path], opciones: OpcionesReceta):
        self.ctx = ctx
        self.limites = limites_plan
        self.emails = emails
        self.o = opciones
        self.ajustes: list[Ajuste] = []
        self.avisos: list[str] = []
        self.por_mercado = ctx.moneda != opciones.moneda_tienda
        # «No disponible en el plan Free» (descripción de impultienda_crear_funnel_postcompra).
        self.sin_funnel = opciones.plan.strip().casefold() == "free"
        self.dir_producto = ruta_producto(ctx.vault, ctx.producto).parent

    def poner(self, clave: str, valor, motivo: str, cita: str | None, fuera: bool, *llamadas: Llamada) -> None:
        self.ajustes.append(Ajuste(clave, valor, motivo, cita, fuera, tuple(llamadas)))

    def precio(self, pieza: Pieza, item: str | None) -> Llamada:
        """Precio de la pieza en la moneda del mercado: por Markets si la tienda cobra en otra moneda. Siempre con
        ``precio_original: None``: sin precio tachado (un «antes» inventado sería un falso descuento, D-01)."""
        if self.por_mercado:
            args = {"store_id": "<store_id>", "market_id": "<market_id>", "precio": _numero(pieza.precio),
                    "precio_original": None}
            if item:
                args["item_id"] = item
            return Llamada("impultienda_precio_por_pais", args, "impultienda_ver_markets")
        args = {"store_id": "<store_id>", "precio": _numero(pieza.precio), "precio_original": None}
        if item:
            args["item_id"] = item
        return Llamada("impultienda_fijar_precio", args, "impultienda_listar_productos")

    @staticmethod
    def entregable(clave: str, pdf: Path) -> tuple[Llamada, Llamada]:
        base = {"store_id": "<store_id>", "tipo": "ebook", "item_id": f"<item_id:{clave}>"}
        return (Llamada("impultienda_cargar_entregable", {**base, "modo": "subir", "nombre_archivo": pdf.name},
                        "impultienda_listar_productos"),
                Llamada("impultienda_cargar_entregable", {**base, "modo": "confirmar", "ruta": f"<ruta:{clave}>"},
                        "impultienda_listar_productos"))

    # -- bloques de la receta, en el orden en que se aplican ------------------------------------------------------

    def tienda(self) -> None:
        if self.ctx.marca is None:
            self.avisos.append("no medido: falta nombre_local en BRANDBOOK.md: el nombre de la tienda no se cambia")
            return
        self.poner("tienda.nombre", self.ctx.marca,
                   "la tienda con el nombre del producto; el subdominio no se toca (ya lleva la marca y cambiarlo "
                   "rompe la landing)", "V1 0:43:47", True,
                   Llamada("impultienda_configurar_tienda", {"store_id": "<store_id>", "nombre": self.ctx.marca},
                           "impultienda_listar_tiendas"))

    def idioma(self) -> None:
        codigo = _idioma_tienda(self.ctx.idioma)
        motivo = ("mismo idioma que la página: los emails al comprador y los textos fijos salen en él (el checkout "
                  "se traduce solo según el idioma del comprador)")
        if codigo is None:
            self.avisos.append(f"no disponible: el idioma «{self.ctx.idioma}» no está entre los de la tienda")
            self.poner("checkout.idioma", self.ctx.idioma, motivo, "S1 7:16", False)
            return
        self.poner("checkout.idioma", self.ctx.idioma, motivo, "S1 7:16", False,
                   Llamada("impultienda_cambiar_idioma", {"store_id": "<store_id>", "idioma": codigo},
                           "impultienda_listar_tiendas"))

    def mercado(self) -> None:
        if not self.por_mercado:
            return
        p, moneda = self.ctx.pais, self.ctx.moneda
        self.poner(f"market.{p}.activo", True,
                   f"Markets activo para cobrar en {moneda} (la tienda cobra en {self.o.moneda_tienda}); exige el "
                   "modo Multidivisa: si el conector lo rechaza, cámbialo tú en tu panel (cambiar_moneda es "
                   "prohibida)", "V1 0:55:14", False,
                   Llamada("impultienda_activar_markets", {"store_id": "<store_id>", "activar": True},
                           "impultienda_ver_markets"))
        self.poner(f"market.{p}.moneda", moneda, f"un mercado propio para {p} en {moneda}, creado con su país",
                   "V1 0:55:14", False,
                   Llamada("impultienda_configurar_mercado",
                           {"store_id": "<store_id>", "nombre": f"{p} {moneda}", "moneda": moneda, "paises": [p]},
                           "impultienda_ver_markets"))
        self.poner(f"market.{p}.paises", p,
                   f"{p} en su mercado (si el mercado ya existía; al crearlo ya entra con su país)", "V1 0:54:12",
                   False,
                   Llamada("impultienda_asignar_paises",
                           {"store_id": "<store_id>", "market_id": "<market_id>", "paises": [p]},
                           "impultienda_ver_markets"))

    def front(self) -> None:
        front = self.ctx.piezas["front"]
        if front.pdf is None:
            raise ValueError("falta el PDF del front")
        self.poner("producto.front.titulo", front.titulo, "el título del producto principal", None, True,
                   Llamada("impultienda_editar_producto", {"store_id": "<store_id>", "nombre": front.titulo},
                           "impultienda_listar_productos"))
        donde = f"precio fijo del mercado {self.ctx.pais}" if self.por_mercado else "precio de venta"
        self.poner("producto.front.precio", str(front.precio),
                   f"mismo precio que la página: {front.precio} {self.ctx.moneda} ({donde})", "S1 7:16", True,
                   self.precio(front, None))
        self.poner("producto.front.entregable", front.pdf, "el PDF real del producto (nunca un aviso «llega en "
                   "24 h»)", "A6.3", False, *self.entregable("front", front.pdf))

    def checkout(self) -> None:
        campos = "email,nombre,telefono" if self.o.telefono else "email,nombre"
        self.poner("checkout.campos", campos, "pocos campos: email, nombre y teléfono (el email se pide siempre)",
                   "V1 0:31:50", True,
                   Llamada("impultienda_configurar_checkout",
                           {"store_id": "<store_id>", "pedir_nombre": True, "pedir_apellido": False,
                            "pedir_telefono": self.o.telefono}, None))
        self.poner("checkout.temporizador", False, "sin reloj de cuenta atrás (D-01: los vídeos ponen 7 min; es "
                   "regla legal, no desvío)", "V1 0:31:50", True,
                   Llamada("impultienda_disenar_checkout", {"store_id": "<store_id>", "minutos_timer_bump": 0}, None))
        self.poner("checkout.cupos", False,
                   "sin cupos ni prueba social inventada (D-01: los vídeos ponen 12): se oculta la barra de "
                   "compradores y los bloques de abajo se vuelven a mandar sin cuenta atrás ni cupos "
                   "(<bloques:abajo> = los actuales, de la vista previa, pasados por limpiar_bloques); se comprueba "
                   "en el checkout público", "V1 0:31:50", True,
                   Llamada("impultienda_configurar_checkout",
                           {"store_id": "<store_id>", "ocultar_barra_compradores": True}, None),
                   Llamada("impultienda_bloques_checkout",
                           {"store_id": "<store_id>", "posicion": "abajo", "bloques": "<bloques:abajo>"}, None))
        self.avisos.append(AVISO_HTML)
        mockup = self.dir_producto / "entregable" / "medios" / "mockup.png"
        if mockup.is_file() and not mockup.is_symlink():
            self.poner("checkout.foto", mockup,
                       "foto y precio arriba: la imagen se sube a Recursos (link_subida_recursos; la arrastras tú) "
                       "y su dirección pública (ver_recursos) va en <url:mockup>", "S1 5:40", True,
                       Llamada("impultienda_bloques_checkout",
                               {"store_id": "<store_id>", "posicion": "arriba",
                                "bloques": [{"tipo": "image", "url": "<url:mockup>",
                                             "alt": self.ctx.piezas["front"].titulo, "ancho_pct": 60}]}, None),
                       Llamada("impultienda_configurar_checkout",
                               {"store_id": "<store_id>", "resumen_posicion": "top"}, None))
        else:
            self.avisos.append("no medido: falta entregable/medios/mockup.png: la foto del checkout queda para "
                               "cuando /producto la genere")
        self.poner("checkout.plantilla", PLANTILLA_VIDEOS,
                   "plantilla Bambú, si tu panel la ofrece: el conector no la tiene (solo "
                   f"{', '.join(PLANTILLAS_CONECTOR)}); si no aparece, se queda la actual", "V1 0:31:50", True)
        self.avisos.append(f"no disponible: la plantilla «{PLANTILLA_VIDEOS}» no está en el conector; la eliges en "
                           "tu panel si te la ofrece")
        self.poner("checkout.boton", "verde", f"botón de pagar verde ({VERDE}; R-f)", "V1 0:31:50", True,
                   Llamada("impultienda_configurar_checkout", {"store_id": "<store_id>", "color_boton_pagar": VERDE},
                           None))
        self.garantia()
        self.poner("checkout.clarity", "fuera del checkout",
                   "quita Clarity del checkout (Configuraciones → Tracking de tu tienda): el checkout es una página de "
                   "Impultienda sin aviso de cookies y Clarity solo carga en la landing tras el consentimiento; "
                   "configurar_tracking es prohibida (R-d), así que lo haces tú", None, True)

    def garantia(self) -> None:
        """La garantía del checkout, la misma que promete la landing (``core.garantia_dias`` de OFERTA.md). El conector
        solo deja mostrarla u ocultarla (``ocultar_garantia``), no fijar los días: va a mano."""
        from trovefy.vault import frontmatter

        dias = None
        oferta = self.dir_producto / "OFERTA.md"
        if oferta.is_file() and not oferta.is_symlink():
            meta, _ = frontmatter.leer(oferta)
            core = meta.get("core") if isinstance(meta, dict) else None
            valor = core.get("garantia_dias") if isinstance(core, dict) else None
            dias = valor if isinstance(valor, int) and not isinstance(valor, bool) and valor > 0 else None
        if dias is None:
            self.avisos.append("no medido: falta core.garantia_dias en OFERTA.md: pon en el checkout la misma garantía "
                               "que dice la landing")
        texto = f"{dias} días" if dias else "la misma que la landing"
        self.poner("checkout.garantia", texto,
                   f"garantía de {texto} en el checkout, la misma que promete la landing (una garantía distinta "
                   "confunde al comprador); el conector no deja fijar los días: lo cambias tú en tu panel",
                   None, True)

    def bump(self) -> None:
        if not self.o.bump_apagado:
            return
        bump = self.ctx.piezas.get("bump")
        if bump is None:
            self.avisos.append("no medido: ESCALERA.md no trae el paso bump")
            return
        motivo = ("desvío (b), solo con aprobación: bump creado y apagado (§4.1); a mano en tu panel, porque el "
                  "conector no deja apagar un producto de una tienda clásica y quedaría vendiéndose")
        self.poner("bump.titulo", bump.titulo, motivo, "V1 0:38:35", False)
        self.poner("bump.precio", str(bump.precio), motivo, "V1 0:38:35", False)
        if bump.pdf is not None:
            self.poner("bump.entregable", bump.pdf, motivo, "V1 0:38:35", False)
        else:
            self.avisos.append("no medido: falta el PDF vigente del bump")
        self.poner("bump.activo", False, motivo, "V1 0:38:35", False)

    def upsells(self) -> None:
        tope = None if self.limites is None else self.limites.get("upsells")
        if tope is None:
            self.avisos.append(f"no medido: el tope de upsells del plan {self.o.plan} (léelo con "
                               "impultienda_ver_plan): no entra ningún upsell")
        usados = 0
        for clave in ("u1", "u2", "u3"):
            pieza = self.ctx.piezas.get(clave)
            if pieza is None:
                continue
            if not pieza.activo:
                self.avisos.append(f"no disponible: {clave} está apagado en ESCALERA.md "
                                   f"({pieza.motivo_inactivo or 'sin motivo'}); entra cuando /modelar lo active y "
                                   "/producto lo produzca (orden de producción, no desvío)")
                continue
            if pieza.pdf is None:
                self.avisos.append(f"no medido: falta el PDF vigente de {clave}: no entra en el funnel")
                continue
            if tope is None:
                continue
            if usados >= tope:
                self.avisos.append(f"desvío (c): el plan {self.o.plan} deja {tope} upsell(s); {clave} queda fuera "
                                   "(los vídeos usan tres)")
                continue
            pagina = ruta_pais(self.ctx) / "upsells" / f"{clave}.md"
            problemas = (validar_pagina_upsell(pagina.read_text(encoding="utf-8"))
                         if pagina.is_file() and not pagina.is_symlink() else None)
            self._upsell(clave, pieza, pagina if problemas == [] else None, primero=usados == 0)
            if problemas is None:
                self.avisos.append(f"no medido: falta la página de {clave} (checkout/{self.ctx.pais}/upsells/"
                                   f"{clave}.md, la escribe Claude con el guion de 8 puntos)")
            elif problemas:
                self.avisos.append(f"la página de {clave} no vale: {'; '.join(problemas)}")
            usados += 1
        if usados:
            self.avisos.append("el funnel post-compra aplica sus descuentos progresivos (15→35 %) a cada oferta "
                               "(la primera se corrige a 0 %: al precio de la escalera) y crea un downsell de "
                               "recuperación por upsell (40→60 %, descuento real, R-c)")

    def _upsell(self, clave: str, pieza: Pieza, pagina: Path | None, *, primero: bool) -> None:
        item = f"<item_id:{clave}>"
        self.poner(f"postcompra.{clave}.titulo", pieza.titulo,
                   "upsell solo post-compra (precio base en la moneda de la tienda con la misma cifra; el comprador "
                   "del mercado paga el precio fijo)", "V1 1:05:50", False,
                   Llamada("impultienda_crear_producto",
                           {"store_id": "<store_id>", "nombre": pieza.titulo, "tipo": "upsell",
                            "precio": _numero(pieza.precio), "solo_post_compra": True},
                           "impultienda_listar_productos"))
        self.poner(f"postcompra.{clave}.precio", str(pieza.precio), f"{pieza.precio} {self.ctx.moneda}",
                   "V1 1:07:55", False, self.precio(pieza, item))
        assert pieza.pdf is not None
        self.poner(f"postcompra.{clave}.entregable", pieza.pdf, "su entregable real cargado", "V1 1:05:30", False,
                   *self.entregable(clave, pieza.pdf))
        if pagina is not None:
            oferta = f"<oferta_id:{clave}>"
            self.poner(f"postcompra.{clave}.pagina", pagina,
                       "su página con el guion de 8 puntos, en HTML propio (<html:…> = la página renderizada)",
                       "V1 1:05:30", True,
                       Llamada("impultienda_guardar_html_postcompra",
                               {"store_id": "<store_id>", "oferta_id": oferta, "html": f"<html:{clave}>"},
                               "impultienda_leer_html_postcompra"),
                       Llamada("impultienda_alternar_html_postcompra",
                               {"store_id": "<store_id>", "oferta_id": oferta, "activo": True},
                               "impultienda_leer_html_postcompra"))
        if self.sin_funnel:
            self.avisos.append(f"no disponible: el plan {self.o.plan} no tiene funnel post-compra "
                               "(crear_funnel_postcompra): el upsell queda creado pero no se ofrece hasta que cambies "
                               "de plan")
            return
        if primero:
            activo = Llamada("impultienda_crear_funnel_postcompra",
                             {"store_id": "<store_id>", "nombre": f"{self.ctx.marca or self.ctx.producto} "
                                                                   f"{self.ctx.pais}", "modo": "siempre"},
                             "impultienda_ver_postcompra")
        else:
            activo = Llamada("impultienda_agregar_oferta_postcompra", {"store_id": "<store_id>", "item_id": item},
                             "impultienda_ver_postcompra")
        self.poner(f"postcompra.{clave}.activo", True, "en el funnel post-compra, activo", CITA_FUNNEL, False, activo)
        if primero:
            # El funnel da a la primera oferta un 15 % por defecto (16,92 en vez de los 19,90 € que dice su página):
            # U1 va al precio de la ESCALERA. Solo el downsell de recuperación conserva su descuento real (R-c).
            self.poner(f"postcompra.{clave}.descuento", 0,
                       "la primera oferta al precio de la escalera, sin el descuento por defecto del funnel (el "
                       "downsell de recuperación conserva el suyo, R-c)", None, False,
                       Llamada("impultienda_modificar_oferta_postcompra",
                               {"store_id": "<store_id>", "item_id": item, "descuento_pct": 0, "aplicar_a": "upsell"},
                               "impultienda_ver_postcompra"))

    def downsell(self) -> None:
        self.avisos.append(AVISO_DOWNSELL)

    def correos(self) -> None:
        from trovefy.checkout.emails import (
            validar_email,  # emails importa de este módulo
        )

        claves = ["entrega"] + (["seguimiento_72h"] if self.o.email_72h else [])
        for clave in claves:
            ruta = self.emails.get(clave)
            rel = f"checkout/{self.ctx.pais}/emails/{clave}.md"
            if ruta is None or not Path(ruta).is_file():
                self.avisos.append(f"no medido: falta el email {clave} ({rel}, lo escribe Claude)")
                continue
            problemas = validar_email(Path(ruta), self.ctx.idioma, clave)
            if problemas:
                self.avisos.append(f"el email {clave} no vale: {'; '.join(problemas)}")
                continue
            motivo = ("lo pegas tú en tu panel: el conector no tiene herramienta para el texto de los emails"
                      if clave == "entrega" else
                      "desvío (e), solo con aprobación: pide una reseña real a las 72 h")
            self.poner(f"emails.{clave}", Path(ruta), motivo, None, False)


def ajustes_de_checkout(ctx: Contexto, limites_plan: dict | None, emails: dict[str, Path],
                        opciones: OpcionesReceta) -> tuple[list[Ajuste], list[str]]:
    """Los ajustes del checkout para ``ctx`` en el orden en que se aplican, y los avisos («no medido: …»,
    «no disponible: …», «desvío …»). ``limites_plan`` es `trovefy.mapa.limites_de_plan` del plan de ``opciones``
    (None = no medido). ``emails``: ``{clave: ruta}`` de los emails escritos. ``ValueError`` sin el PDF del front."""
    r = _Receta(ctx, limites_plan, emails, opciones)
    r.tienda()
    r.idioma()
    r.mercado()
    r.front()
    r.checkout()
    r.bump()
    r.upsells()
    r.downsell()
    r.correos()
    return r.ajustes, list(dict.fromkeys(r.avisos))


# --- receta manual (respaldo, Tarea 12) ----------------------------------------------------------------------------

_PESTANAS: tuple[tuple[str, str], ...] = (
    (r"tienda\.", "General"),
    (r"checkout\.idioma", "General"),
    (r"checkout\.clarity", "Meta / Tracking"),
    (r"market\.", "búscalo en tu panel: Markets"),
    (r"producto\.", "búscalo en tu panel: Productos (el principal)"),
    (r"checkout\.", "búscalo en tu panel: Diseño de checkout"),
    (r"bump\.", "búscalo en tu panel: Productos (order bump)"),
    (r"postcompra\.", "búscalo en tu panel: Marketing → Upsells post-compra"),
    (r"emails\.", "búscalo en tu panel: emails al comprador"),
    (r"tracking\.", "Meta / Tracking"),
)
_NOMBRES = {
    "tienda.nombre": "Nombre de la tienda", "checkout.idioma": "Idioma", "producto.front.titulo": "Nombre del producto",
    "producto.front.precio": "Precio", "producto.front.entregable": "Entregable (PDF)",
    "checkout.campos": "Datos que se piden", "checkout.temporizador": "Temporizador", "checkout.cupos": "Cupos",
    "checkout.foto": "Imagen arriba del checkout", "checkout.plantilla": "Plantilla",
    "checkout.boton": "Color del botón de pagar", "checkout.garantia": "Garantía",
    "checkout.clarity": "Microsoft Clarity en el checkout",
}


def _pestana(clave: str) -> str:
    return next(p for patron, p in _PESTANAS if re.match(patron, clave))


def _nombre(a: Ajuste) -> str:
    if a.clave in _NOMBRES:
        return _NOMBRES[a.clave]
    partes = a.clave.split(".")
    return " ".join(partes[1:]) if partes[0] in ("market", "postcompra") else a.clave


def receta_manual(ajustes: Iterable[Ajuste]) -> list[PasoReceta]:
    """La misma receta en pasos para el panel (respaldo de la Tarea 12). Las pestañas vistas van por su nombre
    (General, Pagos, Meta / Tracking, Remarketing, GhostAds, Dominio, Webhooks); el resto, «búscalo en tu panel: …».
    El primer paso es entrar por ``https://impultienda.ar/login`` (``app.impultienda.ar`` no es el panel)."""
    pasos = [PasoReceta(1, "Entrar", f"Abre {LOGIN} en tu navegador e inicia sesión (trovefy no entra).", ())]
    for a in ajustes:
        texto = f"{_nombre(a)}: {_texto(a.valor)} — {a.motivo}"
        if a.clave.endswith((".precio", ".precio_front")):
            texto = f"{_nombre(a)}: {str(a.valor).replace('.', ',')} — {a.motivo}"
        pasos.append(PasoReceta(len(pasos) + 1, _pestana(a.clave), texto, (a.clave,)))
    return pasos
