"""Página del cierre (``wiki/analisis/cierres/AAAA-MM-DD.md``) y el mensaje del bot: las 3 cifras, en su orden.

**Qué hacen los vídeos:** el bot avisa «al celular y lo anota en el panel» (T3 13:20) con «Cierre del 03/11 — Gasto
Meta: 1183,38 — Neto Whop: 2644,92 — Ganancia: 1461,54» (T3 13:42); a las 23:30 «y próximos movimientos» (C1 0:50:20);
a las 08:30 «Ganancia de ayer» (L2 22:40). El mensaje son esas 3 cifras y nada más (a las 23:30, más la línea de los
próximos movimientos). La página guarda además ventas, CPA, AOV, upsell, ROAS neto, fiabilidad, caja y pendientes
(añadido, no cambia el método: no va en el mensaje).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from trovefy.cierre import ORIGEN
from trovefy.cierre.calculo import Cierre, Cifra
from trovefy.vault import frontmatter

Momento = Literal["noche", "manana"]
HORA = {"noche": "23:30", "manana": "08:30"}


def num(v: Decimal) -> str:
    """Como el bot: coma decimal, dos decimales, sin separador de miles."""
    return f"{v:.2f}".replace(".", ",")


def cifra(c: Cifra) -> str:
    return num(c[0]) if c[0] is not None else f"— ({c[1] or 'sin dato'})"


def ruta_cierre(vault: Path, dia: date) -> Path:
    return Path(vault) / "wiki" / "analisis" / "cierres" / f"{dia.isoformat()}.md"


def informe(cierre: Cierre, momento: Momento, movimientos: list[str]) -> str:
    titulo = f"Cierre del {cierre.dia:%d/%m}" + (" (hasta las 23:30)" if momento == "noche" else "")
    lineas = [titulo, f"Gasto Meta: {cifra(cierre.gasto_usd)}", f"Neto: {cifra(cierre.neto_usd)}",
              f"Ganancia: {cifra(cierre.ganancia_usd)}"]
    if momento == "noche":
        lineas.append("Próximos movimientos: " + ("; ".join(movimientos) if movimientos else "ninguno pendiente"))
    return "\n".join(lineas)


def alerta_de(cierre: Cierre, texto: str, momento: Momento) -> dict:
    """Alerta del buzón (§5.2): no cambia nada en Meta."""
    from trovefy.aprobaciones.fuentes import enmascarar_cuentas

    return {"tipo": "alerta", "origen": ORIGEN, "nivel": "info", "titulo": f"Cierre {cierre.dia:%d/%m}"[:120],
            "texto": enmascarar_cuentas(texto)[:3000], "prioridad": "normal"}


def _c(c: Cifra) -> str | None:
    return str(c[0]) if c[0] is not None else None


def _no_medido(cierre: Cierre) -> list[str]:
    salida = []
    for nombre in ("gasto_usd", "bruto_usd", "comisiones_usd", "reembolsos_usd", "neto_usd", "ganancia_usd",
                   "roas_neto", "aov_usd", "cpa_usd"):
        v, motivo = getattr(cierre, nombre)
        if v is None:
            salida.append(f"{nombre}: {motivo}")
    return salida


def leer_cierre(vault: Path, dia: date) -> tuple[dict, str] | None:
    ruta = ruta_cierre(vault, dia)
    if not ruta.is_file():
        return None
    return frontmatter.leer(ruta)


def escribir_cierre(vault: Path, cierre: Cierre, texto: str, momento: Momento, ahora: datetime, *,
                    alerta_id: str | None = None, fuentes: list[dict] | None = None, caja: str | None = None,
                    pendientes: list[str] | None = None, fijos_del_mes: str | None = None,
                    contraste: str | None = None) -> Path:
    """Escribe (o reescribe) la página del día. La de las 08:30 manda y guarda la de las 23:30 en ``historial``;
    una de las 23:30 no pisa una de las 08:30 ya escrita (solo se añade al historial)."""
    from trovefy.secretos import buscar_secreto

    ruta = ruta_cierre(vault, cierre.dia)
    previo = leer_cierre(vault, cierre.dia)
    meta_previa = previo[0] if previo else {}
    momentos = dict(meta_previa.get("momentos") or {})
    historial = list(meta_previa.get("historial") or [])
    registro = {"generado": ahora.isoformat(timespec="seconds"), "alerta_id": alerta_id}
    if momento == "noche":
        registro["provisional"] = True
    anterior = momentos.get(momento)
    if anterior:
        historial.append({"momento": momento, **anterior, "informe": meta_previa.get("informe")})
    momentos[momento] = registro
    meta = {
        "tipo": "cierre", "fecha": cierre.dia.isoformat(), "zona": cierre.zona_cuenta,
        "zona_tienda": cierre.zona_tienda, "momentos": momentos,
        "fuentes": fuentes or [], "cambios": cierre.cambios,
        "totales": {"gasto_usd": _c(cierre.gasto_usd), "gasto_original": {k: str(v) for k, v in
                                                                         cierre.gasto_original.items()},
                    "bruto_usd": _c(cierre.bruto_usd), "comisiones_usd": _c(cierre.comisiones_usd),
                    "reembolsos_usd": _c(cierre.reembolsos_usd), "neto_usd": _c(cierre.neto_usd),
                    "ganancia_usd": _c(cierre.ganancia_usd), "roas_bruto": _c(cierre.roas_bruto)},
        "ventas": cierre.ventas, "ventas_pixel": cierre.ventas_pixel, "cpa": _c(cierre.cpa_usd),
        "aov": _c(cierre.aov_usd), "upsell": list(cierre.upsell) if cierre.upsell else None,
        "roas_neto": _c(cierre.roas_neto), "fiabilidad": cierre.fiabilidad,
        "motivos_fiabilidad": cierre.motivos_fiabilidad, "por_mercado": cierre.por_mercado,
        "por_campana": cierre.por_campana, "anomalias": cierre.anomalias, "no_medido": _no_medido(cierre),
        "contraste_tienda": contraste, "caja": caja, "pendientes": pendientes or [], "fijos_del_mes": fijos_del_mes,
        "informe": texto, "historial": historial,
    }
    if momento == "noche" and "manana" in momentos and previo:
        # El definitivo ya está escrito: la noche solo deja constancia.
        meta = dict(meta_previa)
        meta["momentos"] = momentos
        meta["historial"] = [*historial, {"momento": "noche", **registro, "informe": texto}]
    cuerpo = (f"\n# Cierre del {cierre.dia:%d/%m/%Y}\n\n"
              f"Generado a las {HORA[momento]} ({'provisional' if momento == 'noche' else 'día cerrado'}).\n\n"
              f"```\n{meta['informe']}\n```\n\n"
              f"Fiabilidad: **{meta['fiabilidad']}**"
              + (f" ({'; '.join(meta['motivos_fiabilidad'])})" if meta["motivos_fiabilidad"] else "") + "\n")
    texto_final = frontmatter.renderizar(meta, cuerpo)
    nombre = buscar_secreto(texto_final)
    if nombre:
        raise ValueError(f"el cierre trae algo con forma de secreto ({nombre}): no se escribe")
    frontmatter.escribir(ruta, meta, cuerpo)
    return ruta
