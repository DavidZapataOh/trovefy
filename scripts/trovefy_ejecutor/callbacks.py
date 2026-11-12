"""callback_data firmado con HMAC para los botones Aceptar/Rechazar [§5.5].

Formato: ``v1|P20261112004|A|<hmac10>`` (<= 64 bytes). Un botón falsificado,
reenviado a otro chat o pulsado por otra persona nunca debe aprobar nada.
Solo biblioteca estándar; no importa nada de ``trovefy``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from typing import Literal, Protocol

VERSION = "v1"
RE_ID = r"^(P-[0-9]{8}-[0-9]{3}|[SQ]-[0-9]{8}-[0-9]{6})$"
_RE_ID = re.compile(RE_ID)
_RE_COMPACTO = re.compile(r"^(?:P[0-9]{11}|[SQ][0-9]{14})$")
_MAX_BYTES = 64
_LARGO_HMAC = 10
_ACCIONES = ("A", "R")


class _Emparejamiento(Protocol):
    user_id: int
    chat_id: int


def _ok_id(id: str) -> bool:
    return _RE_ID.fullmatch(id) is not None and not id.endswith("\n")


def compactar(id: str) -> str:
    if not isinstance(id, str) or not _ok_id(id):
        raise ValueError("id de callback no válido")
    return id.replace("-", "")


def expandir(c: str) -> str:
    if not isinstance(c, str) or _RE_COMPACTO.fullmatch(c) is None:
        raise ValueError("id compacto no válido")
    id = f"{c[0]}-{c[1:9]}-{c[9:]}"
    if not _ok_id(id):
        raise ValueError("id compacto no válido")
    return id


def _clave(clave: bytes) -> None:
    if not clave:
        raise ValueError("la clave HMAC no puede estar vacía")


def _hmac(id: str, accion: str, chat_id: int, clave: bytes) -> str:
    mensaje = f"{id}|{accion}|{chat_id}".encode()
    digest = hmac.new(clave, mensaje, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:_LARGO_HMAC]


def firmar(id: str, accion: Literal["A", "R"], chat_id: int, clave: bytes) -> str:
    _clave(clave)
    if accion not in _ACCIONES:
        raise ValueError("acción no válida")
    data = f"{VERSION}|{compactar(id)}|{accion}|{_hmac(id, accion, chat_id, clave)}"
    assert len(data.encode()) <= _MAX_BYTES
    return data


def motivo_rechazo(
    data: str, chat_id: int, user_id: int, emparejado: _Emparejamiento | None, clave: bytes
) -> str | None:
    _clave(clave)
    if emparejado is None:
        return "sin_emparejar"
    if not isinstance(data, str) or len(data.encode("utf-8", "replace")) > _MAX_BYTES:
        return "largo"
    if chat_id != emparejado.chat_id:
        return "chat_ajeno"
    if user_id != emparejado.user_id:
        return "usuario_ajeno"
    partes = data.split("|")
    if len(partes) != 4:
        return "formato"
    version, compacto, accion, h = partes
    try:
        id = expandir(compacto)
    except ValueError:
        return "formato"
    if version != VERSION:
        return "version"
    if accion not in _ACCIONES:
        return "accion"
    esperado = _hmac(id, accion, chat_id, clave).encode()
    if not hmac.compare_digest(h.encode("utf-8", "replace"), esperado):
        return "firma"
    return None


def verificar(
    data: str, chat_id: int, user_id: int, emparejado: _Emparejamiento | None, clave: bytes
) -> tuple[str, str] | None:
    if motivo_rechazo(data, chat_id, user_id, emparejado, clave) is not None:
        return None
    _, compacto, accion, _ = data.split("|")
    return expandir(compacto), accion
