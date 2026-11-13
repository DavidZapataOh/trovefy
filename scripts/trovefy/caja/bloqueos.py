"""Bloqueos de la caja para ``/listo`` y ``/escalar``. Falla cerrado: cualquier dato sin medir
(``None``) no permite nada y el motivo dice «no medido: …». Un test cerrado no suma al gasto
diario comprometido."""

from __future__ import annotations

from dataclasses import dataclass

from trovefy.caja.calculo import EstadoCaja
from trovefy.caja.config import SOBRES, ConfigCaja


@dataclass(frozen=True)
class Veredicto:
    permitido: bool
    motivo: str


def usd(centavos: int) -> str:
    """Centavos → «25» o «25,39» (coma decimal, sin ceros sobrantes)."""
    signo = "-" if centavos < 0 else ""
    enteros, cent = divmod(abs(centavos), 100)
    return f"{signo}{enteros}" + (f",{cent:02d}" if cent else "")


def _sin_medir(estado: EstadoCaja) -> str | None:
    """Motivo «no medido: …» si algún dato del estado es None; si no, None."""
    faltan = (
        estado.huecos is None
        or estado.comprometido is None
        or any(v is None for v in estado.restante.values())
        or any(v is None for v in estado.gastado.values())
    )
    if not faltan:
        return None
    for m in estado.motivos:
        if m.startswith("no medido:"):
            return m
    return "no medido: el estado de la caja tiene datos sin medir"


def _diario_vivos(config: ConfigCaja) -> int:
    return sum(t.presupuesto_diario for t in config.tests if t.estado == "vivo")


def _cabe(config: ConfigCaja, extra: int) -> Veredicto | None:
    vivos = _diario_vivos(config)
    if vivos + extra > config.tope_diario_ejecutor:
        return Veredicto(
            False,
            f"no cabe: {usd(vivos)} + {usd(extra)} > {usd(config.tope_diario_ejecutor)} de tope diario",
        )
    return None


def puede_lanzar_test(estado: EstadoCaja, config: ConfigCaja) -> Veredicto:
    if (m := _sin_medir(estado)) is not None:
        return Veredicto(False, m)
    assert estado.huecos is not None
    if estado.huecos < 1:
        return Veredicto(False, "0 huecos de test: no hay más tests este mes")
    if (no := _cabe(config, config.diario_test)) is not None:
        return no
    return Veredicto(
        True,
        f"cabe: {usd(_diario_vivos(config))} + {usd(config.diario_test)} <= "
        f"{usd(config.tope_diario_ejecutor)} de tope diario",
    )


def puede_preescalar(estado: EstadoCaja, config: ConfigCaja) -> Veredicto:
    if (m := _sin_medir(estado)) is not None:
        return Veredicto(False, m)
    if not config.reserva_desbloqueada:
        return Veredicto(
            False, "reserva bloqueada: la pre-escala exige desbloquear la reserva"
        )
    reserva = estado.restante["reserva"]
    assert reserva is not None
    if reserva < config.diario_prescala:
        return Veredicto(
            False,
            f"reserva sin saldo: restan {usd(reserva)} < {usd(config.diario_prescala)} de pre-escala",
        )
    if (no := _cabe(config, config.diario_prescala)) is not None:
        return no
    return Veredicto(
        True, "pre-escala permitida: reserva desbloqueada, con saldo y dentro del tope"
    )


def puede_gastar(sobre: str, usd_centavos: int, estado: EstadoCaja) -> Veredicto:
    if sobre not in SOBRES:
        return Veredicto(False, f"sobre desconocido: {sobre!r}")
    if (
        isinstance(usd_centavos, bool)
        or not isinstance(usd_centavos, int)
        or usd_centavos < 0
    ):
        return Veredicto(False, f"importe inválido: {usd_centavos!r}")
    if (m := _sin_medir(estado)) is not None:
        return Veredicto(False, m)
    restante = estado.restante[sobre]
    assert restante is not None
    if usd_centavos > restante:
        return Veredicto(
            False,
            f"sin sobre: {usd(usd_centavos)} > {usd(restante)} restantes en {sobre}",
        )
    return Veredicto(
        True, f"cabe en {sobre}: {usd(usd_centavos)} <= {usd(restante)} restantes"
    )
