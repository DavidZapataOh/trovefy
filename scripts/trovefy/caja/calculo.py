"""Sobres, comprometido, restante y huecos de test. Funciones puras, enteros en centavos de USD.
Todo dato desconocido es ``None`` con su motivo en ``motivos``; nunca 0 ni estimación."""

from __future__ import annotations

from dataclasses import dataclass

from trovefy.caja.config import SOBRES, ConfigCaja
from trovefy.caja.gasto import GastoTest
from trovefy.caja.movimientos import Movimiento, MovimientosCorruptos


@dataclass(frozen=True)
class EstadoCaja:
    asignado: dict[str, int]
    gastado: dict[str, int | None]
    comprometido: int | None
    restante: dict[str, int | None]
    huecos: int | None
    huecos_con_prorroga: int | None
    vivos: int
    motivos: tuple[str, ...]


def calcular(
    config: ConfigCaja, movimientos: list[Movimiento], gastos: list[GastoTest]
) -> EstadoCaja:
    motivos: list[str] = []

    def aviso(m: str | None) -> None:
        if m and m not in motivos:
            motivos.append(m)

    asignado = dict(config.sobres)
    for m in movimientos:
        if m.tipo != "mover":
            continue
        if m.origen not in asignado or m.destino not in asignado:
            raise MovimientosCorruptos(
                f"mover con sobre desconocido: {m.origen!r} -> {m.destino!r}"
            )
        asignado[m.destino] += m.usd_centavos
        asignado[m.origen] -= m.usd_centavos
    herramientas = sum(m.usd_centavos for m in movimientos if m.tipo == "herramienta")

    tests_gastado: int | None = 0
    for g in gastos:
        if g.usd_centavos is None:
            tests_gastado = None
            aviso(g.motivo or f"no medido: gasto de {g.producto} {g.pais}")
        elif tests_gastado is not None:
            tests_gastado += g.usd_centavos
    gastado: dict[str, int | None] = {
        "herramientas": herramientas,
        "tests": tests_gastado,
        "reserva": 0,
    }

    por_test = {(g.producto, g.pais): g for g in gastos}
    vivos = [t for t in config.tests if t.estado == "vivo"]
    comprometido: int | None = 0
    for t in vivos:
        g = por_test.get((t.producto, t.pais))
        if g is None or g.usd_centavos is None:
            comprometido = None
            aviso(
                (g.motivo if g else None)
                or f"no medido: sin gasto registrado de {t.producto} {t.pais} "
                "(llega con /cierre, Fase 3)"
            )
            continue
        techo = config.prorroga_hasta if t.prorroga else config.techo_test
        if comprometido is not None:
            comprometido += max(0, techo - g.usd_centavos)

    restante: dict[str, int | None] = {
        s: asignado[s] - (gastado[s] or 0) for s in SOBRES if s != "tests"
    }
    for s in ("herramientas", "reserva"):
        r_s = restante[s]
        if r_s is not None and r_s < 0:
            aviso(f"sobregasto de {s}: restante {r_s / 100:.2f} USD")
    huecos = huecos_prorroga = None
    if tests_gastado is None or comprometido is None:
        restante["tests"] = None
    else:
        r = asignado["tests"] - tests_gastado - comprometido
        restante["tests"] = r
        if r < 0:
            aviso(f"sobregasto de tests: restante {r / 100:.2f} USD")
        if config.techo_test <= 0:
            aviso("no medido: techo_test <= 0, no se pueden contar huecos")
        else:
            huecos = max(0, r) // config.techo_test
            extra = config.prorroga_hasta - config.techo_test
            huecos_prorroga = max(0, r - extra) // config.techo_test
    return EstadoCaja(
        asignado,
        gastado,
        comprometido,
        restante,
        huecos,
        huecos_prorroga,
        len(vivos),
        tuple(motivos),
    )
