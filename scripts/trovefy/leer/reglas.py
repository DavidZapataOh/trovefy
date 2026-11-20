"""Reglas de corte como funciones puras (plan 23, Tarea 3; R-005, R-006, R-007, R-008, R-011, §4.13).

**Qué hacen los vídeos:**

- Anuncio: «APAGAR: US$ 3 gastados y ningún pago iniciado. O CPC mayor a US$ 0,60» (C1 20:05); «AD3 zafa porque sí
  tiene pagos iniciados» (L2 19:55); «1 pago iniciado de 13. Muy debajo del 15 %» → OFF (C1 54:20). ESPERAR:
  «todavía no gastó lo suficiente para juzgarlo» (C1 20:05). MANTENER: «vendió. Anda. No lo toques» (C1 54:20).
- Oferta sin ventas: «un promedio de US$ 25» (C1 1:24:15), a cualquier hora.
- Con ventas: paciencia de 72 h (T3 11:22); después, ROAS neto acumulado < 1,4 apaga (C1 34:25), solo con días cerrados.
- Techo US$ 100 y plazo de 1 semana (C1 0:18:10); candidato si vende más de dos días con ROAS ≥ 2 (S2 11:31, T3 15:28).
- Nunca por el CTR (S1 10:00).

Sin desvío salvo D1 (pagos iniciados del píxel sin InitiateCheckout fiable): con ``pi_fiable=False`` las ramas «0 PI» y
«< 15 %» no apagan solas; el anuncio se juzga por el CPC. Ningún número está escrito aquí: todo sale de ``umbrales``.
"""
from __future__ import annotations

from decimal import Decimal

from trovefy.leer import Umbrales, num, umbral, usd
from trovefy.leer.economia import EconomiaLeer, corte_oferta_usd, neto_de, roas_neto
from trovefy.leer.modelo import (
    Corte,
    EstadoOferta,
    LecturaConjunto,
    LecturaOferta,
    Veredicto,
)


def ventas_conjunto(c: LecturaConjunto) -> int | None:
    """Ventas del conjunto: las de la tienda (por utm_content); sin tienda, las del píxel."""
    return c.ventas if c.ventas is not None else c.metricas.compras_pixel


def veredicto_conjunto(c: LecturaConjunto, u: Umbrales, pi_fiable: bool) -> Veredicto:
    """APAGAR, ESPERAR o MANTENER, con el número puesto en ``por_que``."""
    m = c.metricas
    v = ventas_conjunto(c)
    if v:
        return Veredicto(c.adset_id, c.nombre, "MANTENER", f"vendió: {v} venta{'s' if v != 1 else ''}. No se toca "
                                                           "(C1 54:20)")
    if m.gasto_usd_c is None:
        return Veredicto(c.adset_id, c.nombre, "ESPERAR", "gasto no medido: no se juzga")
    corte = umbral(u, "corte.anuncio.gasto_usd")
    gasto = Decimal(m.gasto_usd_c) / 100
    if gasto < corte:
        return Veredicto(c.adset_id, c.nombre, "ESPERAR",
                         f"{usd(m.gasto_usd_c)} gastados: todavía no llega a {num(corte, 0)} USD (C1 20:05)")
    motivos = []
    pi = m.pi_pixel
    if pi_fiable and pi == 0:
        visitas = f" de {m.visitas} visitas" if m.visitas is not None else ""
        motivos.append(f"0 pagos iniciados{visitas}")
    cpc = m.cpc_usd
    cpc_max = umbral(u, "corte.anuncio.cpc_max_usd")
    if cpc is not None and cpc > cpc_max:
        motivos.append(f"CPC {num(cpc)} > {num(cpc_max)}")
    minimo = umbral(u, "corte.anuncio.pi_visitas_min")
    if pi_fiable and pi and m.visitas:
        tasa = Decimal(pi) / m.visitas
        if tasa < minimo:
            motivos.append(f"{pi} pago{'s' if pi != 1 else ''} iniciado{'s' if pi != 1 else ''} de {m.visitas} "
                           f"visitas ({num(tasa * 100, 1)} %, < {num(minimo * 100, 0)} %)")
    if motivos:
        return Veredicto(c.adset_id, c.nombre, "APAGAR",
                         f"{usd(m.gasto_usd_c)} gastados, " + ", ".join(motivos) + " (C1 20:05, C1 54:20)")
    extra = "" if pi_fiable else "; PI del píxel no fiable (desvío D1): solo cuenta el CPC"
    return Veredicto(c.adset_id, c.nombre, "ESPERAR",
                     f"{usd(m.gasto_usd_c)} gastados, CPC {num(cpc)}, sin señal para apagar{extra}")


def cortes_conjuntos(o: LecturaOferta, u: Umbrales, pi_fiable: bool) -> Corte | None:
    """Un solo ``pausar_conjuntos`` con los APAGAR de la ronda que siguen ``ACTIVE`` en Meta."""
    apagar = []
    for c in o.conjuntos:
        v = veredicto_conjunto(c, u, pi_fiable)
        if v.estado == "APAGAR" and (c.estado_meta or "").upper() == "ACTIVE":
            apagar.append((c, v))
    if not apagar:
        return None
    motivo = " · ".join(f"{c.nombre}: {v.por_que}" for c, v in apagar)
    return Corte("pausar_conjuntos", tuple(c.adset_id for c, _ in apagar), motivo, "normal",
                 {"conjuntos": {c.adset_id: v.por_que for c, v in apagar}})


def ventas_oferta(o: LecturaOferta) -> tuple[int | None, list[str]]:
    """Manda la tienda; sin tienda, el píxel (fiabilidad baja). Tienda ≥ 1 y píxel 0 → «el píxel subnotifica»."""
    notas = []
    if o.ventas_tienda is not None:
        if o.ventas_tienda >= 1 and o.ventas_pixel == 0:
            notas.append("el píxel subnotifica: la tienda tiene ventas y Meta 0 (§4.13); manda la tienda")
        return o.ventas_tienda, notas
    if o.ventas_pixel is not None:
        notas.append("ventas solo del píxel: la tienda no se pudo leer (fiabilidad baja)")
    return o.ventas_pixel, notas


def roas_oferta(o: LecturaOferta, e: EconomiaLeer) -> Decimal | None:
    ventas = o.ventas_tienda
    return roas_neto(neto_de(o.bruto_tienda_usd, ventas, e), o.gasto_usd_c)


def veredicto_oferta(o: LecturaOferta, e: EconomiaLeer, u: Umbrales, intradia: bool,
                     dias_con_ventas: int = 0) -> tuple[EstadoOferta, list[Corte], list[str]]:
    """Estado de la oferta, sus cortes (0 o 1, de campaña) y las notas para el parte."""
    ventas, notas = ventas_oferta(o)
    gasto_c = o.gasto_usd_c
    techo = umbral(u, "test.spend_cap_usd")
    if gasto_c is None:
        notas.append("gasto en USD no medido: ningún corte por gasto (" +
                     next((m for m in o.motivos if "TRM" in m or "gasto" in m), "sin gasto") + ")")
    elif Decimal(gasto_c) / 100 >= techo:
        notas.append(f"techo cumplido: {usd(gasto_c)} de {num(techo, 0)} USD; Meta para el gasto ahí (C1 0:18:10)")
    corte, fuente = corte_oferta_usd(u)
    evid = {"gasto_usd": usd(gasto_c), "ventas": ventas}
    if ventas == 0 and gasto_c is not None and Decimal(gasto_c) / 100 >= corte:
        return "muerto_sin_ventas", [Corte(
            "pausar_campana", (o.campaign_id,),
            f"0 ventas con {usd(gasto_c)} USD gastados (corte US$ {num(corte, 0)}, {fuente.split(' «')[0]})", "alta",
            evid)], notas
    horas = o.horas
    if ventas and not intradia:
        roas = roas_oferta(o, e)
        if roas is None:
            notas.append(f"ROAS neto no medido: {e.motivo or 'sin bruto de la tienda o sin gasto'}")
        paciencia = umbral(u, "paciencia.con_ventas_h")
        apagar = umbral(u, "roas.apagar")
        if roas is not None and horas is not None and horas >= paciencia and roas < apagar:
            return "muerto_con_ventas", [Corte(
                "pausar_campana", (o.campaign_id,),
                f"{ventas} ventas, ROAS neto {num(roas)} < {num(apagar, 1)} tras {int(horas)} h (C1 34:25, T3 11:22)",
                "alta", {**evid, "roas_neto": str(roas)})], notas
        if roas is not None and horas is not None and horas < paciencia and roas < apagar:
            notas.append(f"ROAS neto {num(roas)} con {int(horas)} h: se aguanta hasta las {int(paciencia)} h (T3 11:22)")
        if roas is not None and dias_con_ventas > 2 and roas >= umbral(u, "roas.escalar"):
            notas.append(f"candidato: vende {dias_con_ventas} días con ROAS neto {num(roas)}; no se toca (C1 20:05); "
                         "la pre-escala es de la fase 4 (S2 11:31)")
            return "candidato", [], notas
    plazo = umbral(u, "test.plazo_dias")
    if not intradia and horas is not None and horas >= plazo * 24:
        return "plazo_cumplido", [Corte(
            "pausar_campana", (o.campaign_id,),
            f"plazo de {int(plazo)} días cumplido sin pasar a candidato ({ventas or 0} ventas, {usd(gasto_c)} USD; "
            "C1 0:18:10)", "normal", evid)], notas
    return "test", [], notas


def falta_para_corte(o: LecturaOferta, u: Umbrales) -> str | None:
    """«faltan 6,20 USD para el corte sin ventas» (solo sin ventas y con gasto medido)."""
    ventas, _ = ventas_oferta(o)
    if ventas or o.gasto_usd_c is None:
        return None
    corte, _ = corte_oferta_usd(u)
    falta = int(corte * 100) - o.gasto_usd_c
    return f"faltan {usd(max(falta, 0))} USD para el corte sin ventas (US$ {num(corte, 0)}, C1 1:24:15)"
