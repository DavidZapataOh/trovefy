"""Cálculo del cierre: funciones puras, como el bot de los vídeos.

**Qué hacen los vídeos:** «Cierre del 03/11 — Gasto Meta: 1183,38 — Neto Whop: 2644,92 — Ganancia: 1461,54» (T3 13:42):
ganancia = neto − gasto de Meta; ROAS neto = neto ÷ gasto (T3 10:05). El gasto se redondea «para arriba» (L2 0:29:05) y
las entradas a la baja. Se guía por las ventas reales, no por el píxel (E2).

Nota de diseño (no cambia el método): §4.19 resta además fijos prorrateados; el bot no lo hace y la caja ya lleva los
fijos aparte, así que la ganancia es la del bot y la página muestra los fijos del mes como dato aparte.

Ninguna cifra se estima: si falta algo, la cifra es ``(None, motivo)``. Nunca se suman monedas distintas sin convertir.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from trovefy.cierre.lectura import VentaLedger
from trovefy.cierre.plataforma import Venta
from trovefy.economia.comisiones import Comisiones
from trovefy.meta.insights import FilaInsight
from trovefy.trm import Trm, cop_a_usd_centavos

Cifra = tuple[Decimal | None, str | None]
CENT = Decimal("0.01")
SIN = (None, None)


@dataclass(frozen=True)
class Cierre:
    dia: date
    zona_cuenta: str
    zona_tienda: str | None
    gasto_usd: Cifra
    gasto_original: dict[str, Decimal]
    bruto_usd: Cifra
    comisiones_usd: Cifra
    reembolsos_usd: Cifra
    neto_usd: Cifra
    ganancia_usd: Cifra
    roas_bruto: Cifra
    roas_neto: Cifra
    ventas: int | None
    ventas_pixel: int | None
    aov_usd: Cifra
    cpa_usd: Cifra
    upsell: tuple[int, int] | None
    por_mercado: dict[str, dict]
    por_campana: list[dict]
    cambios: list[str]
    fiabilidad: Literal["alta", "media", "baja"]
    motivos_fiabilidad: list[str]
    anomalias: list[str] = field(default_factory=list)


def _cambio_tasas(cambio: object) -> dict | None:
    t = getattr(cambio, "tasas", None)
    return t if isinstance(t, dict) else None


def a_usd(importe: Decimal, moneda: str, dia: date, trm: Trm | None, cambio: object | None, al_alza: bool) -> Cifra:
    """Un importe en USD: COP con la TRM vigente ese día; EUR (y lo que el BCE publique) con el cambio del BCE."""
    moneda = (moneda or "").upper()
    modo = ROUND_CEILING if al_alza else ROUND_FLOOR
    if moneda == "USD":
        return importe.quantize(CENT, rounding=modo), None
    if moneda == "COP":
        if trm is None or not trm.vigente(dia):
            return None, f"sin cambio del {dia.strftime('%d/%m')}"
        if al_alza:
            return Decimal(cop_a_usd_centavos(importe, trm)) / 100, None
        return (importe / trm.cop_por_usd).quantize(CENT, rounding=ROUND_FLOOR), None
    tasas = _cambio_tasas(cambio)
    if not tasas or "USD" not in tasas or (moneda != "EUR" and moneda not in tasas):
        return None, f"sin cambio del {dia.strftime('%d/%m')}"
    por_eur = Decimal(1) if moneda == "EUR" else Decimal(str(tasas[moneda]))
    return (importe / por_eur * Decimal(str(tasas["USD"]))).quantize(CENT, rounding=modo), None


def _suma_por_moneda(pares: list[tuple[Decimal, str]], dia, trm, cambio, al_alza) -> Cifra:
    por_moneda: dict[str, Decimal] = defaultdict(Decimal)
    for imp, mon in pares:
        por_moneda[(mon or "").upper()] += imp
    total = Decimal(0)
    for mon, imp in sorted(por_moneda.items()):
        v, motivo = a_usd(imp, mon, dia, trm, cambio, al_alza)
        if v is None:
            return None, motivo
        total += v
    return total, None


def motivo_comisiones(faltan: list[str]) -> str:
    """«falta plataformas.whop.comision_pct» → «falta la comisión de Whop»."""
    partes = []
    for f in faltan:
        if f.startswith("falta plataformas."):
            nombre = f.split(".")[1].capitalize()
            partes.append(f"falta la comisión de {nombre}")
        elif "ruta_activa" in f:
            partes.append("falta fijar la ruta de cobro")
        else:
            partes.append(f)
    return "; ".join(dict.fromkeys(partes))


def _ratio(a: Decimal | None, b: Decimal | None, motivo_b: str | None) -> Cifra:
    if a is None or b is None:
        return None, motivo_b or "sin dato"
    if b == 0:
        return None, "sin gasto"
    return (a / b).quantize(CENT, rounding=ROUND_HALF_UP), None


def _resta(a: Cifra, *bs: Cifra) -> Cifra:
    if a[0] is None:
        return None, a[1]
    total = a[0]
    for b in bs:
        if b[0] is None:
            return None, b[1]
        total -= b[0]
    return total, None


def fiabilidad(gasto: Cifra, bruto: Cifra, *, meta_completa: bool, ventas_completa: bool, fuente_ventas: str,
               zona_cuenta: str, zona_tienda: str | None, ventas: int | None,
               ventas_pixel: int | None) -> tuple[str, list[str], list[str]]:
    """(nivel, motivos, anomalías). Alta: Meta y tienda completas por el MCP, misma zona, cambio fechado y píxel
    cerca de la tienda. Media: falla una de esas. Baja: alguna fuente «no medido»."""
    motivos: list[str] = []
    anomalias: list[str] = []
    if gasto[0] is None or bruto[0] is None or not meta_completa or not ventas_completa:
        if gasto[0] is None or not meta_completa:
            motivos.append(f"gasto de Meta no medido ({gasto[1] or 'lectura incompleta'})")
        if bruto[0] is None or not ventas_completa:
            motivos.append(f"ventas de la tienda no medidas ({bruto[1] or 'lectura incompleta'})")
        nivel = "baja"
    else:
        nivel = "alta"
        if fuente_ventas != "mcp":
            motivos.append("ventas del archivo exportado, no del MCP")
        if zona_tienda and zona_tienda != zona_cuenta:
            motivos.append(f"la tienda cuenta el día en {zona_tienda} y la cuenta en {zona_cuenta}")
        if ventas is not None and ventas_pixel is not None and abs(ventas_pixel - ventas) > max(1, ventas * 0.2):
            motivos.append(f"el píxel dice {ventas_pixel} ventas y la tienda {ventas}")
        if motivos:
            nivel = "media"
    if ventas_pixel == 0 and (ventas or 0) > 0:
        anomalias.append("píxel subnotifica: 0 compras en Meta con ventas en la tienda (§4.13)")
    return nivel, motivos, anomalias


def calcular_cierre(dia: date, gasto: list[FilaInsight], ventas: list[Venta], desaparecidas: list[VentaLedger],
                    comisiones: Comisiones | list[str], trm: Trm | None, cambio: object | None, zona_cuenta: str,
                    zona_tienda: str | None, *, meta_completa: bool = True, ventas_completa: bool = True,
                    fuente_ventas: str = "mcp", motivo_gasto: str | None = None, motivo_ventas: str | None = None,
                    mercado_de_campana: dict[str, str] | None = None) -> Cierre:
    """El cierre del día ``dia``. ``gasto`` son las filas de campaña de ese día; ``ventas``, las del día (la compra de
    prueba se descarta aquí); ``desaparecidas``, los pedidos detectados como reembolso ese día."""
    mercado_de_campana = mercado_de_campana or {}
    cambios: list[str] = []
    filas = [f for f in gasto if f.nivel == "campana" and f.fecha == dia]
    gasto_original: dict[str, Decimal] = defaultdict(Decimal)
    if not meta_completa:
        g: Cifra = (None, motivo_gasto or "no medido: falta la lectura de Meta")
    elif any(f.gasto is None or not f.moneda for f in filas):
        g = (None, "no medido: Meta no devolvió el gasto de alguna campaña")
    else:
        for f in filas:
            gasto_original[f.moneda.upper()] += f.gasto  # type: ignore[union-attr,operator]
        g = _suma_por_moneda([(f.gasto, f.moneda) for f in filas], dia, trm, cambio, True)  # type: ignore[misc]
    if "COP" in gasto_original and trm is not None:
        cambios.append(trm.etiqueta(dia))

    del_dia = [v for v in ventas if v.fecha == dia and not v.prueba]
    if not ventas_completa:
        bruto: Cifra = (None, motivo_ventas or "no medido: faltan ventas de la tienda")
        n_ventas = n_post = None
    else:
        bruto = _suma_por_moneda([(v.total, v.moneda) for v in del_dia], dia, trm, cambio, False)
        n_ventas = sum(1 for v in del_dia if not v.post_compra)
        n_post = sum(1 for v in del_dia if v.post_compra)
    otras = {v.moneda for v in del_dia} | {d.moneda for d in desaparecidas}
    if otras - {"USD", "COP"} and _cambio_tasas(cambio):
        cambios.append(f"BCE del {getattr(cambio, 'fecha', None) or '—'} ({getattr(cambio, 'url', '')})")

    reemb = _suma_por_moneda([(d.total, d.moneda) for d in desaparecidas if d.detectada == dia], dia, trm, cambio,
                             True)
    if isinstance(comisiones, list):
        com: Cifra = (None, motivo_comisiones(comisiones))
    elif bruto[0] is None:
        com = (None, bruto[1])
    else:
        pedidos = len(del_dia)
        c = bruto[0] * comisiones.pct + comisiones.fija_usd * pedidos + bruto[0] * comisiones.impuestos_pct
        com = (c.quantize(CENT, rounding=ROUND_CEILING), None)
    neto = _resta(bruto, com, reemb)
    if neto[0] is not None:
        neto = (neto[0].quantize(CENT, rounding=ROUND_FLOOR), None)
    ganancia = _resta(neto, g)
    pixel = [f.compras_pixel for f in filas]
    ventas_pixel = sum(pixel) if pixel and all(p is not None for p in pixel) else None  # type: ignore[misc]
    aov = (None, bruto[1] or "sin ventas") if bruto[0] is None or not n_ventas else \
        ((bruto[0] / n_ventas).quantize(CENT, rounding=ROUND_FLOOR), None)
    cpa = (None, g[1] or "sin ventas") if g[0] is None or not n_ventas else \
        ((g[0] / n_ventas).quantize(CENT, rounding=ROUND_CEILING), None)
    nivel, motivos, anomalias = fiabilidad(g, bruto, meta_completa=meta_completa, ventas_completa=ventas_completa,
                                           fuente_ventas=fuente_ventas, zona_cuenta=zona_cuenta,
                                           zona_tienda=zona_tienda, ventas=n_ventas, ventas_pixel=ventas_pixel)
    por_campana = []
    por_mercado: dict[str, dict] = {}
    for f in filas:
        usd = a_usd(f.gasto, f.moneda, dia, trm, cambio, True)[0] if f.gasto is not None and f.moneda else None
        mercado = mercado_de_campana.get(f.id, "sin-asignar")
        por_campana.append({"campana": f.id, "nombre": f.nombre, "mercado": mercado,
                            "gasto_usd": str(usd) if usd is not None else None})
        m = por_mercado.setdefault(mercado, {"gasto_usd": Decimal(0), "ventas": 0, "bruto_usd": Decimal(0)})
        m["gasto_usd"] = None if usd is None or m["gasto_usd"] is None else m["gasto_usd"] + usd
    for v in del_dia:
        m = por_mercado.setdefault(f"{v.producto} {v.pais}", {"gasto_usd": Decimal(0), "ventas": 0,
                                                                "bruto_usd": Decimal(0)})
        m["ventas"] += 0 if v.post_compra else 1
        usd = a_usd(v.total, v.moneda, dia, trm, cambio, False)[0]
        m["bruto_usd"] = None if usd is None or m["bruto_usd"] is None else m["bruto_usd"] + usd
    por_mercado = {k: {kk: (str(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()}
                   for k, v in por_mercado.items()}
    return Cierre(
        dia=dia, zona_cuenta=zona_cuenta, zona_tienda=zona_tienda, gasto_usd=g, gasto_original=dict(gasto_original),
        bruto_usd=bruto, comisiones_usd=com, reembolsos_usd=reemb, neto_usd=neto, ganancia_usd=ganancia,
        roas_bruto=_ratio(bruto[0], g[0], bruto[1] or g[1]), roas_neto=_ratio(neto[0], g[0], neto[1] or g[1]),
        ventas=n_ventas, ventas_pixel=ventas_pixel, aov_usd=aov, cpa_usd=cpa,
        upsell=(n_post, n_ventas) if n_post is not None and n_ventas is not None else None,
        por_mercado=por_mercado, por_campana=por_campana, cambios=list(dict.fromkeys(cambios)), fiabilidad=nivel,
        motivos_fiabilidad=motivos, anomalias=anomalias)


def contraste_utm(cierre: Cierre, instantanea_campanas_utm: dict | None) -> str | None:
    """Compara con el tablero de la tienda (``impultienda_campanas_utm → meta_ads.totales``) si está en USD; anota
    diferencias de más del 2 % o de más de US$ 3 (§4.19). Solo informa."""
    from trovefy.cierre.tiendas import contenido

    if not instantanea_campanas_utm:
        return None
    meta = contenido(instantanea_campanas_utm).get("meta_ads")
    if not isinstance(meta, dict) or not meta.get("disponible"):
        return None
    if meta.get("moneda") != "USD":
        return f"el tablero de la tienda va en {meta.get('moneda') or '—'}: no se compara"
    tot = meta.get("totales") if isinstance(meta.get("totales"), dict) else {}
    difs = []
    for nombre, nuestro, clave in (("gasto", cierre.gasto_usd[0], "gasto"), ("ganancia", cierre.ganancia_usd[0],
                                                                               "ganancia")):
        try:
            suyo = Decimal(str(tot.get(clave)))
        except ArithmeticError:
            continue
        if nuestro is None or not suyo.is_finite():
            continue
        dif = abs(nuestro - suyo)
        if dif > Decimal(3) or (suyo and dif / abs(suyo) > Decimal("0.02")):
            difs.append(f"{nombre}: cierre {nuestro} USD, tienda {suyo} USD")
    return ("difiere del tablero de la tienda — " + "; ".join(difs)) if difs else None
