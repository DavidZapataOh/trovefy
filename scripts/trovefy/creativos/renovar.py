"""Renovación cada 48 h durante el test (plan 21, Tarea 13; resolución 25).

«En ABO, cada 48 h · 2 creativos nuevos como mínimo · Sobre qué: los ángulos que ya funcionan: el que vendió o el de
mejor ROAS. Nuevos ángulos también y nuevos formatos también» (T3 18:55); variaciones elegidas por hook rate y
retención (T3 17:36). La lectura viene de ``/leer`` (plan 23): ``trafico/<PAIS>/anuncios.json``. Sin ella no se
genera nada («no medido: sin lectura de /leer»). Las piezas de reserva de la tanda 1 cuyo ángulo es el ganador entran
primero: la primera renovación cuesta casi nada («la segunda tanda sale casi gratis», L2 15:25).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.brief import Renovacion
from trovefy.creativos.contexto import ruta_tanda, siguiente_tanda, tandas
from trovefy.vault.escritura import anadir_log

SIN_LECTURA = "no medido: sin lectura de /leer"
POCO_FIABLE = "no medido: lectura poco fiable"
MIN_SOBRE_GANADOR = 2  # T3 18:55: «2 creativos nuevos como mínimo»
NUEVOS = 1


@dataclass(frozen=True)
class Ganador:
    angulo: str
    formato: str | None
    anuncio: str
    ventas: Decimal
    pi: Decimal


@dataclass(frozen=True)
class PlanRenovacion:
    ganador: Ganador
    reservas: tuple[str, ...]  # ADnn de la tanda 1 (uso: reserva) del ángulo ganador que se reutilizan
    nuevas_sobre_ganador: int
    nuevas_angulo_nuevo: int
    formatos: tuple[str, ...]

    @property
    def piezas_nuevas(self) -> int:
        return self.nuevas_sobre_ganador + self.nuevas_angulo_nuevo

    def para_brief(self) -> Renovacion:
        return Renovacion(piezas=self.piezas_nuevas, angulo_ganador=self.ganador.angulo,
                          sobre_ganador=self.nuevas_sobre_ganador, nuevos=self.nuevas_angulo_nuevo)


def _num(v: object) -> Decimal:
    if v is None or isinstance(v, bool):
        return Decimal(0)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return Decimal(0)
    return d if d.is_finite() else Decimal(0)


def leer_lectura(vault: Path, producto: str, pais: str) -> list[dict] | None:
    ruta = Path(vault) / "productos" / producto / "trafico" / pais / "anuncios.json"
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [d for d in datos if isinstance(d, dict)] if isinstance(datos, list) else None


def leer_manifiestos(vault: Path, producto: str, pais: str) -> dict[str, dict]:
    """Nombre del anuncio → su fila de ``manifest.csv`` (de todas las tandas cerradas)."""
    salida = {}
    for t in tandas(vault, producto, pais):
        ruta = ruta_tanda(vault, producto, pais, t) / "manifest.csv"
        if ruta.is_file():
            for fila in csv.DictReader(ruta.read_text(encoding="utf-8").splitlines()):
                salida[fila.get("nombre", "")] = {**fila, "tanda": t}
    return salida


def angulo_ganador(lectura: list[dict] | None, manifiestos: dict[str, dict]) -> Ganador | None:
    """El ángulo del anuncio con más ventas; sin ventas, el de más pagos iniciados; sin datos o con fiabilidad baja,
    ``None``."""
    if not lectura:
        return None
    filas = [d for d in lectura if d.get("nombre") in manifiestos and d.get("fiabilidad") != "baja"]
    if not filas:
        return None
    mejor = max(filas, key=lambda d: (_num(d.get("ventas")), _num(d.get("pi")), _num(d.get("roas_neto"))))
    if _num(mejor.get("ventas")) == 0 and _num(mejor.get("pi")) == 0:
        return None
    m = manifiestos[mejor["nombre"]]
    return Ganador(m.get("angulo", ""), m.get("formato"), m.get("id", ""), _num(mejor.get("ventas")),
                   _num(mejor.get("pi")))


def plan_renovacion(ganador: Ganador, reservas: list[dict], lectura: list[dict], manifiestos: dict[str, dict],
                    formatos_disponibles: tuple[str, ...]) -> PlanRenovacion:
    """Pura. Reservas del ángulo ganador primero; piezas nuevas hasta ≥ 2 sobre el ganador, y 1 de ángulo nuevo.
    Formatos: los de mejor hook rate o retención si ``/leer`` los trae (T3 17:36); si no, el del ganador y otro."""
    del_ganador = tuple(r["id"] for r in reservas if r.get("angulo") == ganador.angulo)
    nuevas = max(0, MIN_SOBRE_GANADOR - len(del_ganador))
    medidos = []
    for d in lectura:
        m = manifiestos.get(d.get("nombre"))
        if m and (d.get("hook_rate") is not None or d.get("retencion") is not None):
            medidos.append((_num(d.get("hook_rate")) + _num(d.get("retencion")), m.get("formato")))
    if medidos:
        formatos = tuple(dict.fromkeys(f for _, f in sorted(medidos, reverse=True) if f))
    else:
        otro = next((f for f in formatos_disponibles if f != ganador.formato), None)
        formatos = tuple(f for f in (ganador.formato, otro) if f)
    return PlanRenovacion(ganador, del_ganador, nuevas, NUEVOS, formatos)


def reservas_libres(manifiestos: dict[str, dict]) -> list[dict]:
    """Filas ``uso: reserva`` que aún no se montaron en una renovación."""
    usadas = {f.get("id") for f in manifiestos.values() if f.get("uso") == "renovacion"}
    return [f for f in manifiestos.values() if f.get("uso") == "reserva" and f.get("id") not in usadas]


def abrir_renovacion(vault: Path, producto: str, pais: str, formatos_disponibles: tuple[str, ...],
                     ahora: datetime) -> tuple[str, PlanRenovacion]:
    """Abre ``t<N+1>`` (grupo ``G<N+1>``) con el plan en ``TANDA.md``. ``ValueError`` (sin crear nada) si no hay
    lectura de ``/leer`` o no es fiable."""
    lectura = leer_lectura(vault, producto, pais)
    if lectura is None:
        raise ValueError(SIN_LECTURA)
    manifiestos = leer_manifiestos(vault, producto, pais)
    ganador = angulo_ganador(lectura, manifiestos)
    if ganador is None:
        raise ValueError(POCO_FIABLE)
    plan = plan_renovacion(ganador, reservas_libres(manifiestos), lectura, manifiestos, formatos_disponibles)
    tanda, n = siguiente_tanda(vault, producto, pais)
    carpeta = ruta_tanda(vault, producto, pais, tanda)
    carpeta.mkdir(parents=True, exist_ok=False)
    datos = {"tipo": "renovacion", "producto": producto, "pais": pais, "tanda": tanda, "grupo": f"G{n}",
             "plan_renovacion": {"angulo_ganador": ganador.angulo, "anuncio_ganador": ganador.anuncio,
                                 "ventas": str(ganador.ventas), "pi": str(ganador.pi),
                                 "reservas": list(plan.reservas), "nuevas_sobre_ganador": plan.nuevas_sobre_ganador,
                                 "nuevas_angulo_nuevo": plan.nuevas_angulo_nuevo, "formatos": list(plan.formatos)}}
    ficha = "\n".join([f"# Tanda {tanda} · {producto} · {pais} (G{n}, renovación)", "",
                       f"Ángulo ganador: {ganador.angulo} ({ganador.anuncio}: {ganador.ventas} ventas, {ganador.pi} PI).",
                       f"Reservas que entran: {', '.join(plan.reservas) or 'ninguna'}.",
                       (f"Piezas nuevas: {plan.nuevas_sobre_ganador} sobre el ganador y {plan.nuevas_angulo_nuevo} de "
                       f"ángulo nuevo; formatos: {', '.join(plan.formatos) or 'no medido'} (T3 18:55, T3 17:36).")])
    tanda_md.guardar(carpeta, datos, ficha, [f"- {ahora:%Y-%m-%d %H:%M} · renovación abierta"])
    anadir_log(vault, "/creativos", f"{producto} {pais}: renovación {tanda} sobre «{ganador.angulo}»",
               [(carpeta / "TANDA.md").relative_to(vault).as_posix()], ahora=ahora)
    return tanda, plan


def plan_de(carpeta: Path) -> Renovacion | None:
    meta, _, _ = tanda_md.leer(carpeta)
    p = meta.get("plan_renovacion") if meta.get("tipo") == "renovacion" else None
    if not isinstance(p, dict):
        return None
    return Renovacion(piezas=int(p.get("nuevas_sobre_ganador", 0)) + int(p.get("nuevas_angulo_nuevo", 0)),
                      angulo_ganador=str(p.get("angulo_ganador")), sobre_ganador=int(p.get("nuevas_sobre_ganador", 0)),
                      nuevos=int(p.get("nuevas_angulo_nuevo", 0)))
