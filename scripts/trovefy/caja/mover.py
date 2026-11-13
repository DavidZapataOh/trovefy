"""Mover dinero entre sobres (decisión del USUARIO, con sus palabras literales) y anotar herramientas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trovefy.caja.bloqueos import usd
from trovefy.caja.calculo import EstadoCaja
from trovefy.caja.config import SOBRES
from trovefy.caja.movimientos import Movimiento, anotar_movimiento
from trovefy.trm import Trm, cop_a_usd_centavos
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO


class MovimientoInvalido(ValueError):
    """El movimiento no se puede registrar; el mensaje dice por qué."""


def _sobre(nombre: str) -> None:
    if nombre == "cobrado":
        raise MovimientoInvalido("el sobre cobrado llega con la conciliación (Fase 3)")
    if nombre not in SOBRES:
        raise MovimientoInvalido(f"sobre desconocido: {nombre!r}")


def mover(
    vault: Path,
    origen: str,
    destino: str,
    usd_centavos: int,
    cita: str,
    estado: EstadoCaja,
    ahora: datetime,
) -> tuple[Path, Movimiento]:
    _sobre(origen)
    _sobre(destino)
    if origen == destino:
        raise MovimientoInvalido("origen y destino son el mismo sobre")
    if (
        isinstance(usd_centavos, bool)
        or not isinstance(usd_centavos, int)
        or usd_centavos <= 0
    ):
        raise MovimientoInvalido("el importe debe ser mayor que 0")
    if not isinstance(cita, str) or not cita.strip():
        raise MovimientoInvalido(
            "falta la cita: mover es decisión del usuario y se registra con sus palabras"
        )
    antes_o = estado.restante[origen]
    if antes_o is None:
        raise MovimientoInvalido(f"no medido: restante de {origen} sin medir")
    if usd_centavos > antes_o:
        raise MovimientoInvalido(
            f"{origen} solo tiene {usd(antes_o)} USD restantes; no se pueden mover {usd(usd_centavos)}"
        )
    antes_d = estado.restante[destino]
    local = ahora.astimezone(ZONA_NEGOCIO)
    rel = Path("decisiones") / "caja" / f"{local:%Y-%m-%d-%H%M%S}-mover.md"
    despues_d = (
        "no medido" if antes_d is None else usd(antes_d + usd_centavos)
    )
    antes_d_txt = "no medido" if antes_d is None else usd(antes_d)
    citado = "\n".join(f"> {linea}" for linea in cita.split("\n"))
    cuerpo = f"""# Mover {usd(usd_centavos)} USD de {origen} a {destino}

Decisión del usuario, con sus palabras:

{citado}

Antes y después (restante, USD):

- {origen}: {usd(antes_o)} → {usd(antes_o - usd_centavos)}
- {destino}: {antes_d_txt} → {despues_d}
"""
    ruta = Path(vault) / rel
    if ruta.exists():
        raise MovimientoInvalido(f"ya hay una decisión de este segundo: {rel}")
    frontmatter.escribir(
        ruta,
        {"tipo": "decision", "fecha": local.date(), "fuente": "trovefy caja mover"},
        cuerpo,
    )
    m = Movimiento(
        ahora, "mover", origen, destino, usd_centavos, "", "", "", "", cita, rel.as_posix()
    )
    anotar_movimiento(vault, m)
    return ruta, m


def anotar_herramienta(
    vault: Path,
    importe: Decimal,
    moneda: str,
    nota: str,
    trm: Trm | None,
    ahora: datetime,
) -> Movimiento:
    if not importe.is_finite() or importe <= 0:
        raise MovimientoInvalido("el importe debe ser mayor que 0")
    moneda = moneda.upper()
    if moneda == "USD":
        centavos = int((importe * 100).to_integral_value(rounding="ROUND_CEILING"))
        trm_txt = trm_fecha = ""
    elif moneda == "COP":
        if trm is None:
            raise MovimientoInvalido("no medido: sin TRM; no se anota")
        centavos = cop_a_usd_centavos(importe, trm)
        trm_txt, trm_fecha = str(trm.cop_por_usd), trm.desde.isoformat()
    else:
        raise MovimientoInvalido(f"moneda no admitida: {moneda!r} (USD o COP)")
    m = Movimiento(
        ahora, "herramienta", "herramientas", "", centavos, format(importe, "f"),
        moneda, trm_txt, trm_fecha, nota, "",
    )  # fmt: skip
    anotar_movimiento(vault, m)
    return m
