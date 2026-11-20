"""Diagnóstico por etapa (R-014) y anuncios para renovar (plan 23, Tarea 6).

**Qué hacen los vídeos:** «¿falla el anuncio? → gancho y CTR. ¿Falla la página? → visitas que empiezan a pagar. ¿Falla
el checkout? → empiezan a pagar y no terminan» (S1 10:00); «Y si falló: ¿fue el anuncio, la oferta o la landing? Claude
te lo diagnostica» (C1 20:05); «46 pagos iniciados contra 6 ventas: 1 de cada 8» (L2 19:15); «vamos a tener que probar
nuevos ads» tras apagar (L2 19:45). Añadido (no cambia el método): los hallazgos avisan a `/creativos`, `/landing` o
`/checkout` y **nunca** tocan la campaña (regla 9 del cerebro).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from trovefy.leer import Umbrales, num, umbral
from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import LecturaOferta, Veredicto

RECHAZADOS = ("DISAPPROVED", "WITH_ISSUES")


@dataclass(frozen=True)
class Hallazgo:
    etapa: Literal["anuncio", "pagina", "checkout", "meta"]
    texto: str
    destino: Literal["/creativos", "/landing", "/checkout", "/montar"]
    numero: str
    alerta: bool  # False = solo línea del parte («dato aún flojo»)


def _pct(x: Decimal) -> str:
    return f"{num(x * 100, 1)} %"


def diagnosticar(o: LecturaOferta, f: Fiabilidad, u: Umbrales) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    clics, imp, visitas = o.clics, o.impresiones, o.visitas
    flojo = clics is None or clics < int(umbral(u, "diagnostico.clics_min"))
    nota = " · dato aún flojo" if flojo else ""

    def h(etapa, texto, destino, numero):
        hallazgos.append(Hallazgo(etapa, texto + nota, destino, numero, not flojo))

    if clics is not None and imp:
        ctr = Decimal(clics) / imp
        minimo = umbral(u, "diagnostico.ctr_min")
        if ctr < minimo:
            h("anuncio", f"falla el anuncio: CTR {_pct(ctr)} < {_pct(minimo)} (S1 10:00): gancho y creativo",
              "/creativos", _pct(ctr))
    if clics and visitas is not None:
        llegada = Decimal(visitas) / clics
        minimo = umbral(u, "diagnostico.llegada_min")
        if llegada < minimo:
            h("pagina", f"falla la llegada: {visitas} visitas de {clics} clics ({_pct(llegada)} < {_pct(minimo)}): "
                        "carga o enlace de la página (S1 10:00)", "/landing", _pct(llegada))
    pi = o.pi_tienda if o.pi_tienda is not None else (o.pi_pixel if f.pi_fiable else None)
    if pi is not None and visitas:
        tasa = Decimal(pi) / visitas
        minimo = umbral(u, "corte.anuncio.pi_visitas_min")
        if tasa < minimo:
            h("pagina", f"falla la página: {pi} pagos iniciados de {visitas} visitas ({_pct(tasa)} < {_pct(minimo)}, "
                        "C1 54:20)", "/landing", _pct(tasa))
    ventas = o.ventas_tienda
    if pi is not None and ventas is not None and pi >= int(umbral(u, "diagnostico.pi_min")):
        tasa = Decimal(ventas) / pi
        minimo = umbral(u, "diagnostico.pi_a_compra_min")
        if tasa < minimo:
            h("checkout", f"falla el checkout: {ventas} ventas de {pi} pagos iniciados (1 de cada "
                          f"{num(Decimal(pi) / ventas, 1) if ventas else '—'}; referencia 1 de cada 8, L2 19:15)",
              "/checkout", _pct(tasa))
    if o.intentos_fallidos:
        h("checkout", f"la pasarela rechazó {o.intentos_fallidos} intento{'s' if o.intentos_fallidos != 1 else ''} de "
                      "pago: revisa el checkout", "/checkout", str(o.intentos_fallidos))
    return hallazgos


def rechazados(o: LecturaOferta) -> list[Hallazgo]:
    """Anuncios que Meta rechazó o marcó con problemas (resolución 18): alerta de nivel aviso, sin corte."""
    return [Hallazgo("meta", f"{c.nombre}: Meta lo marca {c.estado_anuncio}; revísalo (no hay corte)", "/montar",
                     str(c.estado_anuncio), True)
            for c in o.conjuntos if (c.estado_anuncio or "").upper() in RECHAZADOS]


def renovar(o: LecturaOferta, veredictos: list[Veredicto]) -> list[str]:
    """Anuncios que salen APAGAR en la ronda, con su ángulo: la entrada de `/creativos --renovar` (plan 21)."""
    angulos = {c.adset_id: c.angulo for c in o.conjuntos}
    return [f"{v.nombre} ({angulos.get(v.adset_id) or 'ángulo —'})" for v in veredictos if v.estado == "APAGAR"]
