"""Comprobación de la cuenta de Meta: moneda, *offset*, estado y un ``validate_only`` de campaña.

Nunca crea nada real (la única escritura es ``validate_only=True``) y nunca lanza: todo fallo se vuelve un
problema en español. Los textos de error no llevan ``repr`` de excepciones ni el token.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from trovefy_ejecutor.graph import ErrorGraph, ErrorRed, InfoCuenta, clasificar

_CAMPANA_PRUEBA = {"name": "trovefy comprobar-meta", "objective": "OUTCOME_SALES", "status": "PAUSED",
                   "special_ad_categories": []}


@dataclass(frozen=True)
class InformeMeta:
    act_id: str
    leido_en: datetime
    cuenta: InfoCuenta | None
    offset_confirmado: bool
    validate_only_ok: bool
    problemas: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (self.cuenta is not None and self.cuenta.account_status == 1 and self.offset_confirmado
                and self.validate_only_ok and not self.problemas)


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _texto_error(e: ErrorGraph) -> str:
    if clasificar(e) == "token":
        return "token caducado o revocado (renuévalo en /arranque paso 13)"
    return f"Meta {e.codigo}/{e.subcodigo or '-'}"


def comprobar_meta(graph, act_id: str, *, ahora: Callable[[], datetime] = _ahora_utc) -> InformeMeta:
    problemas: list[str] = []
    try:
        leido_en = ahora()
    except Exception:  # noqa: BLE001 - nunca lanza
        leido_en = _ahora_utc()
    cuenta: InfoCuenta | None = None
    try:
        cuenta = graph.cuenta(act_id)
    except ErrorRed:
        problemas.append("sin red")
    except ErrorGraph as e:
        problemas.append(_texto_error(e))
    except Exception:  # noqa: BLE001 - nunca lanza
        problemas.append("no se pudo leer la cuenta de Meta")
    if cuenta is None:
        return InformeMeta(act_id, leido_en, None, False, False, tuple(problemas))

    offset_confirmado = cuenta.offset is not None
    if cuenta.account_status != 1:
        problemas.append(f"la cuenta no está activa (account_status {cuenta.account_status})")
    if not offset_confirmado:
        problemas.append(f"moneda {cuenta.currency} sin offset confirmado: el ejecutor rechazará importes")
    validate_ok = False
    try:
        graph.crear(act_id, "campaigns", dict(_CAMPANA_PRUEBA), validate_only=True)
        validate_ok = True
    except ErrorRed:
        problemas.append("sin red")
    except ErrorGraph as e:
        if clasificar(e) == "token":
            problemas.append(_texto_error(e))
        else:
            problemas.append(f"validate_only falló: Meta {e.codigo}/{e.subcodigo or '-'}")
    except Exception:  # noqa: BLE001 - nunca lanza
        problemas.append("validate_only falló: error inesperado")
    return InformeMeta(act_id, leido_en, cuenta, offset_confirmado, validate_ok, tuple(problemas))


def informe_a_dict(i: InformeMeta) -> dict:
    c = i.cuenta
    return {
        "fecha": i.leido_en.isoformat(),
        "cuenta": i.act_id,
        "currency": c.currency if c else None,
        "offset": c.offset if c else None,
        "timezone_name": c.timezone_name if c else None,
        "account_status": c.account_status if c else None,
        "amount_spent": c.amount_spent if c else None,
        "spend_cap": c.spend_cap if c else None,
        "validate_only": {"ok": i.validate_only_ok, "motivo": i.problemas[0] if i.problemas else None},
    }
