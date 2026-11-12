"""Lectura y escritura de secretos.env del ejecutor (0600, sin mostrar valores)."""

from __future__ import annotations

import errno
import fcntl
import os
import re
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


def _abrir_seguro(ruta: Path) -> int:
    """Abre sin seguir enlaces y valida por descriptor (sin TOCTOU)."""
    try:
        fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise SecretosInseguros(f"{ruta} es un enlace simbólico") from None
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecretosInseguros(f"{ruta} no es un archivo regular")
        if st.st_mode & 0o077:
            raise SecretosInseguros(
                f"{ruta} tiene permisos {stat.S_IMODE(st.st_mode):04o}; se exige 0600"
            )
        if st.st_uid != os.getuid():
            raise SecretosInseguros(f"{ruta} no pertenece al usuario que ejecuta")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _leer_texto(ruta: Path) -> str:
    fd = _abrir_seguro(ruta)
    with os.fdopen(fd, "r", encoding="utf-8", newline="") as f:
        return f.read()


_NOMBRE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _lineas(texto: str) -> list[str]:
    lineas = texto.split("\n")
    if lineas and lineas[-1] == "":
        lineas.pop()
    return lineas


def _leer_pares(texto: str) -> list[tuple[str, str]]:
    pares: list[tuple[str, str]] = []
    vistas: set[str] = set()
    for n, linea in enumerate(_lineas(texto), start=1):
        linea = linea.strip(" \t\r")
        if not linea or linea.startswith("#"):
            continue
        clave, sep, valor = linea.partition("=")
        if not sep:
            raise ValueError(f"línea {n} sin '='")
        clave = clave.strip()
        if clave.startswith("export ") or clave == "export":
            raise ValueError(f"línea {n} usa 'export'; no se admite")
        if clave not in CLAVES:
            if _NOMBRE.match(clave) and len(clave) <= 40:
                raise ValueError(f"clave desconocida: {clave}")
            raise ValueError(f"línea {n} con clave desconocida")
        valor = valor.strip(" \t\r")
        if not valor.isprintable():
            raise ValueError(f"{clave}: caracteres no permitidos")
        if valor[:1] in ("'", '"'):
            raise ValueError(f"{clave}: no se admiten valores entre comillas")
        if clave in vistas:
            raise ValueError(f"{clave} duplicada")
        vistas.add(clave)
        pares.append((clave, valor))
    return pares


def _entero(clave: str, valor: str) -> int:
    if not (valor.isascii() and valor.isdigit()):
        raise ValueError(f"{clave} no es un entero")
    return int(valor)


def cargar_secretos(ruta: Path) -> Secretos:
    ruta = Path(ruta)
    d = dict(_leer_pares(_leer_texto(ruta)))
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
    guardar_secretos(ruta, {clave: valor}, sobrescribir=sobrescribir)


def guardar_secretos(ruta: Path, pares: dict[str, str], *, sobrescribir: bool = False) -> None:
    """Escribe varias claves en UNA sola escritura atómica bajo el candado."""
    ruta = Path(ruta)
    for clave, valor in pares.items():
        if clave not in CLAVES:
            raise ValueError(f"clave desconocida: {clave}")
        if (
            not valor.isprintable()
            or len(valor.splitlines()) > 1
            or valor != valor.strip()
        ):
            raise ValueError(f"el valor de {clave} contiene caracteres no permitidos")
    lock = ruta.with_name(ruta.name + ".lock")
    lfd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lfd, fcntl.LOCK_EX)
        _guardar_bloqueado(ruta, pares, sobrescribir)
    finally:
        os.close(lfd)


def _guardar_bloqueado(ruta: Path, pares: dict[str, str], sobrescribir: bool) -> None:
    lineas: list[str] = []
    try:
        lineas = _lineas(_leer_texto(ruta))
    except FileNotFoundError:
        pass
    nuevas: list[str] = []
    puestas: set[str] = set()
    for linea in lineas:
        k = linea.strip().partition("=")[0].strip()
        if k in pares and not linea.lstrip().startswith("#"):
            if not sobrescribir:
                raise ValueError(f"{k} ya está guardada")
            if k not in puestas:
                nuevas.append(f"{k}={pares[k]}")
                puestas.add(k)
            continue
        nuevas.append(linea)
    for k, v in pares.items():
        if k not in puestas:
            nuevas.append(f"{k}={v}")
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
