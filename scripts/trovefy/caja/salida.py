"""``wiki/analisis/caja.md`` y la línea de caja del informe. Dato ausente = «no medido» o «—», nunca 0."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from trovefy_ejecutor.dinero import Moneda, formatear

from trovefy.caja.bloqueos import usd
from trovefy.caja.calculo import EstadoCaja
from trovefy.caja.config import SOBRES, ConfigCaja
from trovefy.caja.limites import Recomendacion
from trovefy.trm import Trm, usd_centavos_a_cop
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO

_COP = Moneda("COP", 1)
_USD = Moneda("USD", 100)


def _u(centavos: int | None) -> str:
    return "—" if centavos is None else usd(centavos)


def linea_informe(estado: EstadoCaja) -> str:
    asignado_tests = usd(estado.asignado["tests"])
    r = estado.restante["tests"]
    if r is None:
        tests = "tests no medido (huecos: —)"
    else:
        huecos = "—" if estado.huecos is None else str(estado.huecos)
        tests = f"tests {usd(r)} de {asignado_tests} (huecos: {huecos})"
    reserva = estado.restante["reserva"]
    return (
        f"Caja: {tests} · reserva {'no medido' if reserva is None else usd(reserva)}"
        " · cobrado — · en tránsito —"
    )


def _usd_cop(centavos: int, trm: Trm | None) -> str:
    base = f"{usd(centavos)} USD"
    if trm is None:
        return f"{base} (COP no medido: sin TRM)"
    return f"{base} ≈ {formatear(int(usd_centavos_a_cop(centavos, trm)), _COP)}"


def escribir_caja(
    vault: Path,
    estado: EstadoCaja,
    config: ConfigCaja,
    rec: Recomendacion,
    trm: Trm | None,
    ahora: datetime,
) -> Path:
    dia = ahora.astimezone(ZONA_NEGOCIO).date()
    filas = []
    for s in SOBRES:
        comprometido = _u(estado.comprometido) if s == "tests" else "—"
        gastado = estado.gastado[s]
        filas.append(
            f"| {s} | {usd(estado.asignado[s])} | {_u(gastado)} | {comprometido} "
            f"| {_u(estado.restante[s])} |"
        )
    if estado.huecos is None:
        huecos = "Huecos de test restantes: no medido"
    else:
        extra = "—" if estado.huecos_con_prorroga is None else estado.huecos_con_prorroga
        huecos = f"Huecos de test restantes: {estado.huecos} ({extra} si hay una prórroga)"
    vivos = [t for t in config.tests if t.estado == "vivo"]
    if vivos:
        lista = "\n".join(
            f"- {t.producto} · {t.pais} · {usd(t.presupuesto_diario)} USD al día"
            + (" · prórroga" if t.prorroga else "")
            for t in vivos
        )
        tests_vivos = f"Tests vivos: {len(vivos)}\n\n{lista}"
    else:
        tests_vivos = "Tests vivos: 0"
    cambio = (
        trm.etiqueta(dia) if trm is not None else f"— (no medido: sin TRM del {dia.isoformat()})"
    )
    tope = (
        "no medido"
        if rec.tope_diario is None
        else _usd_cop(rec.tope_diario, trm)
    )
    limite = (
        "no medido"
        if rec.limite_cuenta_restante is None
        else _usd_cop(rec.limite_cuenta_restante, trm)
    )
    motivos = (
        "\n".join(f"- {m}" for m in dict.fromkeys(rec.motivos))
        if rec.motivos
        else "Nada: todo está medido."
    )
    cuerpo = f"""# Caja

{linea_informe(estado)}

## Sobres (USD)

| Sobre | Asignado | Gastado | Comprometido | Restante |
|---|---|---|---|---|
{chr(10).join(filas)}

## Tests

{huecos}

{tests_vivos}

Cobrado: — (llega con /cierre y /caja --conciliar, Fase 3)

## Cambio usado

{cambio}

## Límites recomendados

- Tope diario total: {tope}
- Límite de gasto de la cuenta (restante de los sobres): {limite}

## No medido

{motivos}
"""
    ruta = Path(vault) / "wiki" / "analisis" / "caja.md"
    frontmatter.escribir(
        ruta, {"tipo": "analisis", "fecha": dia, "fuente": "trovefy caja"}, cuerpo
    )
    return ruta
