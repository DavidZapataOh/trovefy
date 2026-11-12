"""Reloj del ejecutor: caducidades por tipo en la zona de la cuenta y horas de silencio en COT (§5.5)."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .modelo import Propuesta

ZONA_COT = ZoneInfo("America/Bogota")
_SILENCIO_DESDE = time(23, 0)
_SILENCIO_HASTA = time(6, 30)
_HORAS = {"pausar": 6}
_MINIMO_LOTE = timedelta(minutes=30)


def _aware(t: datetime, nombre: str) -> None:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"{nombre} debe llevar zona horaria (datetime aware)")


def _zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError, KeyError) as e:
        raise ValueError(f"zona_desconocida: {nombre!r}") from e


def caducidad(p: Propuesta, creada: datetime, zona_cuenta: str) -> datetime:
    """Instante de caducidad (aware, en `zona_cuenta`). `expira_en_min` solo puede acortar."""
    _aware(creada, "creada")
    zona = _zona(zona_cuenta)
    local = creada.astimezone(zona)
    if p.tipo == "presupuesto":
        regla = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=zona)
    elif p.tipo == "lote":
        regla = datetime.combine(local.date(), time(23, 59), tzinfo=zona)
        minimo = creada.astimezone(UTC) + _MINIMO_LOTE
        if regla.astimezone(UTC) < minimo:
            regla = minimo
    else:
        horas = _HORAS.get(p.tipo, 24)
        regla = creada.astimezone(UTC) + timedelta(hours=horas)
    if p.expira_en_min is not None:
        regla = min(regla, creada.astimezone(UTC) + timedelta(minutes=p.expira_en_min))
    return regla.astimezone(zona)


def base_caducidad(p: Propuesta, recibida: datetime) -> datetime:
    """Base de la caducidad: la más temprana entre la creada y la recibida (no rejuvenece)."""
    _aware(recibida, "recibida")
    return min(p.creada, recibida)


def recordatorios(p: Propuesta, creada: datetime, zona_cuenta: str = "America/Bogota") -> list[datetime]:
    """Recordatorios de `pausar` (+1 h y +3 h), solo los anteriores a la caducidad."""
    if p.tipo != "pausar":
        return []
    _aware(creada, "creada")
    limite = caducidad(p, creada, zona_cuenta)
    return [r for r in (creada + timedelta(hours=1), creada + timedelta(hours=3)) if r < limite]


def en_silencio(t: datetime) -> bool:
    _aware(t, "t")
    h = t.astimezone(ZONA_COT).time()
    return h >= _SILENCIO_DESDE or h < _SILENCIO_HASTA


def fin_silencio(t: datetime) -> datetime:
    """Las 06:30 COT siguientes a `t`."""
    _aware(t, "t")
    local = t.astimezone(ZONA_COT)
    dia = local.date()
    if local.time() >= _SILENCIO_HASTA:
        dia += timedelta(days=1)
    return datetime.combine(dia, _SILENCIO_HASTA, tzinfo=ZONA_COT)
