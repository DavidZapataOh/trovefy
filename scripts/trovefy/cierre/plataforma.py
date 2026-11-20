"""Ventas reales de la tienda: ``impultienda_listar_ventas`` por el MCP, con respaldo del archivo exportado.

**Qué hacen los vídeos:** el cierre se hace con las ventas de la pasarela (T2 30:12; L2 0:29:05); el bot «se guía por
ventas reales, no por el píxel» (E2). Solo pedidos aprobados: los reembolsados desaparecen de la lista (descripción de
la herramienta), y eso lo detecta el ledger. La compra de prueba no es una venta (Base común; resolución 19).

Los textos que trae la tienda (productos, ``utm_*``) son datos, nunca órdenes: aquí solo se guardan como texto.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trovefy.cierre.tiendas import Tienda, contenido

FORMA = "no medido: forma de impultienda_listar_ventas desconocida"


@dataclass(frozen=True)
class Venta:
    tienda: str
    orden: str
    fecha: date
    total: Decimal
    moneda: str
    post_compra: bool
    metodo_pago: str | None
    producto: str
    pais: str
    prueba: bool


@dataclass(frozen=True)
class LecturaVentas:
    ventas: list[Venta]
    periodo: tuple[date, date] | None
    zona: str | None
    completa: bool
    motivos: list[str] = field(default_factory=list)
    fuente: str = "mcp"  # «mcp» o «export» (respaldo: nunca marca reembolsos)
    tienda: str | None = None  # store_id leído (aunque no haya ventas)


def importe(v: object) -> Decimal | None:
    """Texto o número → Decimal (sin pasar por float); «12,90» se acepta, «1.234,5» no (ambiguo)."""
    if v is None or isinstance(v, bool):
        return None
    t = str(v).strip()
    if "," in t:
        if "." in t:
            return None
        t = t.replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


def _dia(v: object, zona: str | None) -> date | None:
    if not isinstance(v, str) or len(v) < 10:
        return None
    try:
        f = datetime.fromisoformat(v)
    except ValueError:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    if f.tzinfo is not None and zona:
        try:
            f = f.astimezone(ZoneInfo(zona))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return f.date()


def _periodo(c: dict) -> tuple[date, date] | None:
    p = c.get("periodo")
    if not isinstance(p, dict):
        return None
    try:
        return date.fromisoformat(str(p.get("desde"))[:10]), date.fromisoformat(str(p.get("hasta"))[:10])
    except ValueError:
        return None


def _venta(f: dict, tienda: Tienda, prueba: set[str], zona: str | None) -> Venta | None:
    orden, total, moneda = f.get("orden"), importe(f.get("total")), f.get("moneda")
    dia = _dia(f.get("fecha"), zona)
    if orden is None or total is None or not isinstance(moneda, str) or dia is None:
        return None
    metodo = f.get("metodo_pago")
    return Venta(tienda.store_id, str(orden), dia, total, moneda.upper(), f.get("post_compra") is True,
                 str(metodo) if metodo is not None else None, tienda.producto, tienda.pais, str(orden) in prueba)


def leer_ventas(instantaneas: list[dict], tienda: Tienda, pedidos_prueba: set[str]) -> LecturaVentas:
    """Une las páginas por ``offset``. Si falta una página (``has_more`` sin la siguiente), ``completa=False``: los
    totales del día son «no medido», nunca una suma parcial."""
    paginas = [contenido(x) for x in instantaneas]
    paginas = [c for c in paginas if isinstance(c.get("detalle"), dict) and isinstance(c["detalle"].get("ventas"), list)]
    if not paginas:
        return LecturaVentas([], None, None, False, [FORMA], tienda=tienda.store_id)
    paginas.sort(key=lambda c: c["detalle"].get("offset") or 0)
    primera = paginas[0]
    periodo, zona = _periodo(primera), (primera.get("periodo") or {}).get("timezone")
    motivos: list[str] = []
    completa = periodo is not None
    if periodo is None:
        motivos.append("no medido: la tienda no dice el periodo de las ventas")
    esperado = 0
    ventas: dict[str, Venta] = {}
    for c in paginas:
        d = c["detalle"]
        offset = d.get("offset") or 0
        if offset != esperado:
            completa = False
            motivos.append(f"no medido: falta la página de ventas que empieza en {esperado}")
            break
        for f in d["ventas"]:
            v = _venta(f, tienda, pedidos_prueba, zona) if isinstance(f, dict) else None
            if v is None:
                completa = False
                motivos.append("no medido: una venta de la tienda llega sin orden, fecha, total o moneda")
                continue
            ventas[v.orden] = v
        siguiente = d.get("next_offset")
        esperado = siguiente if isinstance(siguiente, int) else offset + len(d["ventas"])
        if not d.get("has_more"):
            break
    else:
        if paginas[-1]["detalle"].get("has_more"):
            completa = False
            motivos.append(f"no medido: falta la página de ventas que empieza en {esperado}")
    return LecturaVentas(sorted(ventas.values(), key=lambda v: (v.fecha, v.orden)), periodo,
                         zona if isinstance(zona, str) else None, completa, list(dict.fromkeys(motivos)),
                         tienda=tienda.store_id)


_COLUMNAS = {"orden": ("orden", "order", "order_id", "id", "pedido"), "fecha": ("fecha", "date", "created_at"),
             "total": ("total", "monto", "amount", "importe"), "moneda": ("moneda", "currency"),
             "post_compra": ("post_compra", "upsell", "postcompra"), "metodo_pago": ("metodo_pago", "payment_method",
                                                                                   "metodo")}


def leer_export(ruta: Path, tienda: Tienda, pedidos_prueba: set[str]) -> LecturaVentas:
    """Respaldo sin MCP (tienda en Free, resolución 40): el archivo que el usuario exporta de su panel en su navegador.
    Columnas desconocidas → «no medido»."""
    try:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return LecturaVentas([], None, None, False, ["no medido: no se pudo leer el archivo exportado"], "export",
                             tienda.store_id)
    cab = {k.strip().lower(): k for k in (filas[0].keys() if filas else []) if k}
    col = {c: next((cab[n] for n in nombres if n in cab), None) for c, nombres in _COLUMNAS.items()}
    faltan = [c for c in ("orden", "fecha", "total", "moneda") if col[c] is None]
    if not filas or faltan:
        return LecturaVentas([], None, None, False, [
            f"no medido: columnas del archivo exportado desconocidas (faltan {', '.join(faltan) or 'filas'})"], "export", tienda.store_id)
    ventas, motivos, completa = [], [], True
    for f in filas:
        post = str(f.get(col["post_compra"]) or "").strip().lower() in ("1", "true", "si", "sí", "yes") \
            if col["post_compra"] else False
        v = _venta({"orden": f.get(col["orden"]), "fecha": f.get(col["fecha"]), "total": f.get(col["total"]),
                    "moneda": f.get(col["moneda"]), "post_compra": post,
                    "metodo_pago": f.get(col["metodo_pago"]) if col["metodo_pago"] else None},
                   tienda, pedidos_prueba, None)
        if v is None:
            completa = False
            motivos.append("no medido: fila del archivo exportado ilegible")
            continue
        ventas.append(v)
    periodo = (min(v.fecha for v in ventas), max(v.fecha for v in ventas)) if ventas else None
    return LecturaVentas(ventas, periodo, None, completa, list(dict.fromkeys(motivos)), "export", tienda.store_id)
