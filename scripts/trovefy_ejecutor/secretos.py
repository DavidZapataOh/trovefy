"""Lectura y escritura de secretos.env del ejecutor (0600, sin mostrar valores)."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

CLAVES = (
    "META_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "HMAC_CLAVE",
    "TELEGRAM_USER_ID",
    "TELEGRAM_CHAT_ID",
    "CLAUDE_UID",
)
_HMAC_MIN_BYTES = 32


class SecretosInseguros(Exception):
    """El archivo de secretos no es seguro; el mensaje nunca contiene valores."""


@dataclass(frozen=True)
class Secretos:
    meta_token: str | None
    telegram_bot_token: str | None
    hmac_clave: bytes | None
    telegram_user_id: int | None
    telegram_chat_id: int | None
    claude_uid: int | None

    def __repr__(self) -> str:
        def oculto(v: object) -> str:
            return "None" if v is None else "***"

        return (
            f"Secretos(meta_token={oculto(self.meta_token)}, "
            f"telegram_bot_token={oculto(self.telegram_bot_token)}, "
            f"hmac_clave={oculto(self.hmac_clave)}, "
            f"telegram_user_id={self.telegram_user_id!r}, "
            f"telegram_chat_id={self.telegram_chat_id!r}, "
            f"claude_uid={self.claude_uid!r})"
        )

    __str__ = __repr__


def _comprobar_permisos(ruta: Path) -> None:
    """Lanza FileNotFoundError si no existe, SecretosInseguros si no es seguro."""
    st = os.lstat(ruta)
    if stat.S_ISLNK(st.st_mode):
        raise SecretosInseguros(f"{ruta} es un enlace simbólico")
    if not stat.S_ISREG(st.st_mode):
        raise SecretosInseguros(f"{ruta} no es un archivo regular")
    if st.st_mode & 0o077:
        raise SecretosInseguros(
            f"{ruta} tiene permisos {stat.S_IMODE(st.st_mode):04o}; se exige 0600"
        )
    if st.st_uid != os.getuid():
        raise SecretosInseguros(f"{ruta} no pertenece al usuario que ejecuta")


def _leer_pares(ruta: Path) -> list[tuple[str, str]]:
    pares: list[tuple[str, str]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        clave, sep, valor = linea.partition("=")
        clave = clave.strip()
        if not sep or clave not in CLAVES:
            raise ValueError(f"clave desconocida en {ruta}: {clave}")
        pares.append((clave, valor.strip()))
    return pares


def _entero(clave: str, valor: str) -> int:
    try:
        return int(valor)
    except ValueError:
        raise ValueError(f"{clave} no es un entero") from None


def cargar_secretos(ruta: Path) -> Secretos:
    ruta = Path(ruta)
    _comprobar_permisos(ruta)
    d = dict(_leer_pares(ruta))
    hmac: bytes | None = None
    if "HMAC_CLAVE" in d:
        try:
            hmac = bytes.fromhex(d["HMAC_CLAVE"])
        except ValueError:
            raise SecretosInseguros("HMAC_CLAVE no es hexadecimal válido") from None
        if len(hmac) < _HMAC_MIN_BYTES:
            raise SecretosInseguros("HMAC_CLAVE demasiado corta")
    return Secretos(
        meta_token=d.get("META_TOKEN"),
        telegram_bot_token=d.get("TELEGRAM_BOT_TOKEN"),
        hmac_clave=hmac,
        telegram_user_id=_entero("TELEGRAM_USER_ID", d["TELEGRAM_USER_ID"])
        if "TELEGRAM_USER_ID" in d
        else None,
        telegram_chat_id=_entero("TELEGRAM_CHAT_ID", d["TELEGRAM_CHAT_ID"])
        if "TELEGRAM_CHAT_ID" in d
        else None,
        claude_uid=_entero("CLAUDE_UID", d["CLAUDE_UID"]) if "CLAUDE_UID" in d else None,
    )


def guardar_secreto(ruta: Path, clave: str, valor: str, *, sobrescribir: bool = False) -> None:
    ruta = Path(ruta)
    if clave not in CLAVES:
        raise ValueError(f"clave desconocida: {clave}")
    if "\n" in valor or "\r" in valor:
        raise ValueError(f"el valor de {clave} no puede contener saltos de línea")
    lineas: list[str] = []
    existe = True
    try:
        _comprobar_permisos(ruta)
    except FileNotFoundError:
        existe = False
    if existe:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    nuevas: list[str] = []
    reemplazada = False
    for linea in lineas:
        k = linea.strip().partition("=")[0].strip()
        if k == clave and not linea.lstrip().startswith("#"):
            if not sobrescribir:
                raise ValueError(f"{clave} ya está guardada")
            if not reemplazada:
                nuevas.append(f"{clave}={valor}")
                reemplazada = True
            continue
        nuevas.append(linea)
    if not reemplazada:
        nuevas.append(f"{clave}={valor}")
    tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(nuevas) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
