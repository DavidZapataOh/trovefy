"""Modelo de tracking del producto-país (plan 19, Tarea 5; §4.9 de la spec, D-17).

- Un dataset (píxel) por producto y país, con nombre «MARCA PAÍS» como en los vídeos («SOSTEGNO IT 2026»,
  V1 1:15:20): cirílico transliterado con la tabla oficial búlgara (2009), máximo 50 caracteres.
- UTM con la plantilla literal de §4.9 en cada anuncio. UTMify sí («DESVÍOS RESUELTOS», cabecera del plan 19):
  añade la atribución por anuncio; los pedidos de /cierre siguen saliendo de ``impultienda_listar_ventas``.
- Un único emisor por evento [D-17]: la tienda (píxel + CAPI nativo de Impultienda) o, con la landing en
  Cloudflare, ``assets/pixel.js`` solo para PageView y ViewContent (resolución 23). Ruta Hotmart fuera: el
  ``worker`` no es un emisor válido.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from trovefy.landing.qa import PARES_PUBLICADA

EVENTOS: tuple[str, ...] = ("PageView", "ViewContent", "InitiateCheckout", "Purchase")
PLANTILLA_UTM = (
    "utm_source=fb&utm_medium=paid&utm_campaign={{campaign.name}}|{{campaign.id}}"
    "&utm_term={{adset.name}}|{{adset.id}}&utm_content={{ad.name}}|{{ad.id}}"
)
Emisor = Literal["impultienda", "landing", "worker", "ninguno"]
EMISORES: tuple[str, ...] = ("impultienda", "landing", "worker", "ninguno")
ESTADOS: tuple[str, ...] = ("pendiente", "dataset", "configurado", "verificado", "no_verificado")
MAX_NOMBRE = 50

# Sistema oficial búlgaro de transliteración (Ley de transliteración, 2009).
_BG = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
}
_P_ID = re.compile(r"p-\d{4}-(.+)")
_PAIS = re.compile(r"[A-Z]{2}")


@dataclass
class Tracking:
    producto: str
    pais: str
    dataset_nombre: str
    dataset_id: str | None
    emisores: dict[str, str]
    pixel_publico: Literal["ok", "otro", "no_visto"] | None
    pixel_config: Literal["mcp", "captura", "dicho"] | None
    capi: Literal["dicho", "visto_en_meta"] | None
    eventos: dict[str, int | None] | None
    fuente_eventos: Literal["mcp", "captura"] | None
    estado: Literal["pendiente", "dataset", "configurado", "verificado", "no_verificado"]
    evidencia: list[str] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)


def utm_de_prueba() -> dict[str, str]:
    """Los pares de ``UTM_PUBLICADA`` del 18 (resolución 22): sin ``fbclid``, no generan eventos falsos para Meta."""
    return dict(PARES_PUBLICADA)


def _latin(texto: str) -> str:
    t = "".join(_BG.get(ch, ch) for ch in texto.lower())
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split()).upper()


def nombre_dataset(marca: str | None, producto: str, pais: str) -> str:
    """«MARCA PAÍS» (sin marca, el nombre del p-id); en mayúsculas latinas, máximo 50 caracteres."""
    codigo = pais.strip().upper() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(codigo):
        raise ValueError(f"país mal escrito: «{pais}»; usa su código de dos letras")
    base = _latin(marca) if isinstance(marca, str) else ""
    if not base:
        m = _P_ID.fullmatch(producto or "")
        base = _latin(m.group(1) if m else str(producto))
    if not base:
        raise ValueError("sin marca ni producto para nombrar el dataset")
    base = base[: MAX_NOMBRE - len(codigo) - 1].rstrip()
    return f"{base} {codigo}"


def emisores_por_defecto(ruta: str, landing_hosting: str | None) -> dict[str, str]:
    """Quién emite cada evento: la tienda; con la landing en Cloudflare, ``pixel.js`` emite PageView y ViewContent."""
    if ruta != "impultienda":
        raise ValueError("la ruta Hotmart está fuera (plan 19, «DESVÍOS RESUELTOS»): solo Impultienda")
    if landing_hosting == "impultienda":
        return {e: "impultienda" for e in EVENTOS}
    if landing_hosting == "cloudflare":
        return {"PageView": "landing", "ViewContent": "landing",
                "InitiateCheckout": "impultienda", "Purchase": "impultienda"}
    raise ValueError("falta el hosting de la landing (impultienda o cloudflare): publica la landing con /landing")


def validar_emisores(tabla: dict) -> list[str]:
    """Problemas de la tabla evento → emisor ([] si está bien): un único emisor por evento [D-17]."""
    problemas: list[str] = []
    for evento in tabla:
        if evento not in EVENTOS:
            problemas.append(f"{evento}: no es uno de los eventos verificados ({', '.join(EVENTOS)})")
    for evento in EVENTOS:
        emisor = tabla.get(evento)
        if emisor is None:
            problemas.append(f"{evento}: sin emisor")
            continue
        if isinstance(emisor, (list, tuple, set)):
            distintos = sorted({str(x) for x in emisor})
            if len(distintos) != 1:
                problemas.append(f"{evento}: dos emisores ({', '.join(distintos)}); debe ser uno solo [D-17]")
                continue
            emisor = distintos[0]
        if emisor not in EMISORES:
            problemas.append(f"{evento}: emisor desconocido «{emisor}»")
        elif emisor == "worker":
            problemas.append(f"{evento}: «worker» solo existía en la ruta Hotmart, que está fuera")
        elif emisor == "ninguno" and evento == "Purchase":
            problemas.append("Purchase: sin emisor no hay compra que optimizar")
    return problemas
