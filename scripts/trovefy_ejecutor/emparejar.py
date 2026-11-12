"""Emparejamiento del bot con un código de 6 dígitos (diseño §4.2 paso 12).

La CLI toma el mismo candado que `servir` antes de llamar aquí (resolución 7):
este módulo nunca convive con otro consumidor de getUpdates.
"""

from __future__ import annotations

import hmac
import math
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .auditoria import (
    EV_EMPAREJADO,
    EV_EMPAREJAR_RECHAZADO,
    EV_MENSAJE_IGNORADO,
    Auditoria,
    redactar,
)
from .buzon import Buzon
from .estado import Almacen
from .secretos import cargar_secretos, guardar_secretos
from .telegram import ClienteTelegram, ErrorRedTelegram, ErrorTelegram

MAX_FALLOS = 5
_ESPERA_MAX_S = 25
_FORMA_CODIGO = re.compile(r"[0-9]{6}")
SIN_CONTAR = frozenset({"antiguo", "no_codigo"})


@dataclass(frozen=True)
class Emparejamiento:
    user_id: int
    chat_id: int


@dataclass
class CodigoPendiente:
    codigo: str
    caduca: datetime
    fallos: int = 0
    emitido: datetime | None = None


def nuevo_codigo(ahora: datetime, minutos: int = 10) -> CodigoPendiente:
    return CodigoPendiente(
        f"{secrets.randbelow(10**6):06d}", ahora + timedelta(minutes=minutos), emitido=ahora
    )


def intentar_emparejar(
    update: dict, pendiente: CodigoPendiente, actual: Emparejamiento | None, ahora: datetime
) -> Emparejamiento | str:
    if actual is not None:
        return "ya_emparejado"
    m = update.get("message") if isinstance(update, dict) else None
    if not isinstance(m, dict) or not isinstance(m.get("text"), str):
        return "no_es_mensaje"
    de = m.get("from") if isinstance(m.get("from"), dict) else {}
    chat = m.get("chat") if isinstance(m.get("chat"), dict) else {}
    uid, cid = de.get("id"), chat.get("id")
    if de.get("is_bot") is True:
        return "bot"
    if (
        chat.get("type") != "private"
        or not isinstance(uid, int) or isinstance(uid, bool)
        or not isinstance(cid, int) or isinstance(cid, bool)
        or cid != uid
    ):
        return "no_privado"
    fecha = m.get("date")
    if (
        pendiente.emitido is not None
        and isinstance(fecha, int) and not isinstance(fecha, bool)
        and fecha < int(pendiente.emitido.timestamp())
    ):
        return "antiguo"  # cola anterior a la emisión del código: no cuenta como intento
    recibido_txt = "".join(m["text"].split())
    if not _FORMA_CODIGO.fullmatch(recibido_txt):
        return "no_codigo"  # /start, charla…: se ignora sin gastar intentos
    if ahora >= pendiente.caduca:
        return "caducado"
    if pendiente.fallos >= MAX_FALLOS:
        return "agotado"
    recibido = recibido_txt.encode("ascii")
    if not hmac.compare_digest(recibido, pendiente.codigo.encode("ascii")):
        pendiente.fallos += 1
        return "codigo"
    return Emparejamiento(uid, cid)


def leer_emparejamiento(secretos: Path) -> Emparejamiento | None:
    s = cargar_secretos(secretos)
    if s.telegram_user_id is None or s.telegram_chat_id is None:
        return None
    return Emparejamiento(s.telegram_user_id, s.telegram_chat_id)


def guardar_emparejamiento(secretos: Path, e: Emparejamiento) -> None:
    if _estado_par(secretos) != "ninguno":
        raise ValueError("ya emparejado")
    guardar_secretos(
        secretos, {"TELEGRAM_USER_ID": str(e.user_id), "TELEGRAM_CHAT_ID": str(e.chat_id)}
    )


def _estado_par(secretos: Path) -> str:
    try:
        s = cargar_secretos(secretos)
    except FileNotFoundError:
        return "ninguno"
    n = (s.telegram_user_id is not None) + (s.telegram_chat_id is not None)
    return ("ninguno", "a_medias", "completo")[n]


def ejecutar_emparejamiento(
    cliente: ClienteTelegram,
    almacen: Almacen,
    secretos: Path,
    mostrar: Callable[[str], None],
    *,
    auditoria: Auditoria,
    buzon: Buzon | None = None,
    ahora: Callable[[], datetime],
    minutos: int = 10,
) -> Emparejamiento | None:
    estado = _estado_par(secretos)
    if estado == "a_medias":
        raise ValueError("emparejamiento a medias: revisa secretos.env")
    if estado == "completo":
        raise ValueError("ya emparejado")
    pendiente = nuevo_codigo(ahora(), minutos)
    mostrar(
        f"Código de emparejamiento: {pendiente.codigo} (caduca en {minutos} min). "
        "Envíalo al bot desde tu chat privado."
    )
    while True:
        restante = (pendiente.caduca - ahora()).total_seconds()
        if restante <= 0 or pendiente.fallos >= MAX_FALLOS:
            return None
        espera = min(_ESPERA_MAX_S, max(1, math.ceil(restante)))
        for upd in cliente.obtener_updates(almacen.ultimo_update() + 1, timeout_s=espera):
            uid = upd.get("update_id")
            if not isinstance(uid, int):
                continue
            almacen.marcar_update(uid)
            r = intentar_emparejar(upd, pendiente, leer_emparejamiento(secretos), ahora())
            if isinstance(r, str):
                if r in SIN_CONTAR:
                    auditoria.anotar(EV_MENSAJE_IGNORADO, motivo=r)
                    continue
                auditoria.anotar(EV_EMPAREJAR_RECHAZADO, motivo=r)
                if r in ("caducado", "agotado"):
                    return None
                continue
            guardar_emparejamiento(secretos, r)
            auditoria.anotar(EV_EMPAREJADO, user_id=r.user_id, chat_id=r.chat_id)
            if buzon is not None:
                buzon.escribir_estado(
                    "emparejamiento", {"emparejado": True, "fecha": ahora().isoformat(timespec="seconds")}
                )
            try:
                cliente.enviar(r.chat_id, "Emparejado. Desde ahora solo este chat puede aprobar.")
            except (ErrorTelegram, ErrorRedTelegram) as exc:
                # el emparejamiento ya está guardado y auditado; se avisa en la CLI
                mostrar("Emparejado, pero no se pudo confirmar en Telegram.")
                auditoria.anotar(
                    EV_MENSAJE_IGNORADO, motivo="confirmacion_no_enviada", error=redactar(str(exc))
                )
            return r
