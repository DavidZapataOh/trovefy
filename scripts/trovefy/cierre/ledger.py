"""Ledgers del cierre con *upsert* de 7 días y reembolsos detectados.

**Qué hacen los vídeos:** «Cierre de caja contra la pasarela → ledger → cerebro» (C1 0:50:20); el cierre anota también
reembolsos (C1, fase 10 del playbook del cerebro).

Meta y la tienda corrigen días pasados (§4.19): cada cierre relee 7 días y actualiza filas sin duplicarlas. La tienda
solo devuelve pedidos aprobados, así que un reembolso se ve como un pedido que estaba y ya no está: queda
``desaparecida`` con el día en que se detectó (y resta ese día). Nunca se borra una fila.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from trovefy.caja.gasto import CABECERA as CABECERA_GASTO
from trovefy.cierre.lectura import CABECERA_VENTAS, carpeta, filas_csv
from trovefy.cierre.plataforma import LecturaVentas
from trovefy.meta.insights import FilaInsight
from trovefy.vault.escritura import escribir_atomico


def _csv(cabecera: list[str], filas: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cabecera, lineterminator="\n")
    w.writeheader()
    for f in filas:
        w.writerow({k: f.get(k, "") for k in cabecera})
    return buf.getvalue()


def importe_dos_decimales(d: Decimal) -> str:
    """Siempre «83700.00»: así el ledger nunca cae en la regla del COP ambiguo de `trovefy.caja.gasto` (al alza)."""
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_CEILING):.2f}"


def upsert_gasto(vault: Path, filas: list[FilaInsight], cuenta: str) -> list[Path]:
    """Una fila por ``(fecha, cuenta, campana)``; solo nivel campaña y solo filas con fecha, gasto y moneda."""
    por_mes: dict[str, dict[tuple[str, str, str], dict[str, str]]] = {}
    for f in filas:
        if f.nivel != "campana" or f.fecha is None or f.gasto is None or not f.moneda:
            continue
        clave = (f.fecha.isoformat(), cuenta, f.id)
        por_mes.setdefault(f.fecha.isoformat()[:7], {})[clave] = {
            "fecha": clave[0], "cuenta": cuenta, "campana": f.id, "gasto": importe_dos_decimales(f.gasto),
            "moneda": f.moneda.upper()}
    rutas = []
    for mes, nuevas in sorted(por_mes.items()):
        ruta = carpeta(vault, "gasto") / f"{mes}.csv"
        existentes = {(r["fecha"], r["cuenta"], r["campana"]): r for r in filas_csv(ruta, CABECERA_GASTO)}
        existentes.update(nuevas)
        escribir_atomico(ruta, _csv(CABECERA_GASTO, [existentes[k] for k in sorted(existentes)]))
        rutas.append(ruta)
    return rutas


@dataclass
class ResultadoVentas:
    nuevas: int = 0
    actualizadas: int = 0
    desaparecidas: list[str] = field(default_factory=list)
    rutas: list[Path] = field(default_factory=list)


def upsert_ventas(vault: Path, lectura: LecturaVentas, ahora: datetime) -> ResultadoVentas:
    """*Upsert* por ``(tienda, orden)``. Con una lectura completa del MCP, un pedido del ledger dentro del periodo que ya
    no aparece queda ``desaparecida`` (con ``detectada`` = hoy en la zona de ``ahora``); si vuelve, vuelve su estado."""
    marca = ahora.isoformat(timespec="seconds")
    hoy = ahora.date().isoformat()
    res = ResultadoVentas()
    c = carpeta(vault, "ventas")
    antes: dict[str, list[dict[str, str]]] = (
        {r.stem: filas_csv(r, CABECERA_VENTAS) for r in sorted(c.glob("*.csv"))} if c.is_dir() else {})
    filas: dict[tuple[str, str], dict[str, str]] = {(r["tienda"], r["orden"]): dict(r)
                                                   for fs in antes.values() for r in fs}
    fuente = "impultienda_listar_ventas" if lectura.fuente == "mcp" else "archivo exportado"
    vistas: set[tuple[str, str]] = set()
    for v in lectura.ventas:
        clave = (v.tienda, v.orden)
        vistas.add(clave)
        previa = filas.get(clave)
        nueva = {"fecha": v.fecha.isoformat(), "tienda": v.tienda, "orden": v.orden, "producto": v.producto,
                 "pais": v.pais, "total": f"{v.total}", "moneda": v.moneda, "post_compra": "si" if v.post_compra else "no",
                 "metodo_pago": v.metodo_pago or "", "estado": "prueba" if v.prueba else "aprobada",
                 "visto_primero": (previa or {}).get("visto_primero") or marca, "visto_ultimo": marca,
                 "fuente": fuente, "detectada": ""}
        if previa is None:
            res.nuevas += 1
        elif any(previa.get(k) != nueva[k] for k in nueva if k != "visto_ultimo"):
            res.actualizadas += 1
        filas[clave] = nueva
    if lectura.completa and lectura.fuente == "mcp" and lectura.periodo is not None:
        desde, hasta = (d.isoformat() for d in lectura.periodo)
        tiendas = {v.tienda for v in lectura.ventas} | ({lectura.tienda} if lectura.tienda else set())
        for clave, r in filas.items():
            if (r["tienda"] in tiendas and desde <= r["fecha"] <= hasta and r["estado"] == "aprobada"
                    and clave not in vistas):
                r["estado"], r["detectada"] = "desaparecida", hoy
                res.desaparecidas.append(r["orden"])
    despues: dict[str, list[dict[str, str]]] = {}
    for r in sorted(filas.values(), key=lambda r: (r["fecha"], r["tienda"], r["orden"])):
        despues.setdefault(r["fecha"][:7], []).append(r)
    for mes in sorted(set(antes) | set(despues)):
        if despues.get(mes, []) == antes.get(mes, []):
            continue
        ruta = c / f"{mes}.csv"
        escribir_atomico(ruta, _csv(CABECERA_VENTAS, despues.get(mes, [])))
        res.rutas.append(ruta)
    return res
