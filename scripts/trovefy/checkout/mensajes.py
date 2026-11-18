"""Registro de los mensajes del usuario (plan 19, Tarea 11): la aprobación de un plan del MCP lleva sus palabras.

`trovefy checkout aprobar --cita "…"` solo acepta una cita que sea, entera, un mensaje que el usuario escribió en el
chat **después** de que se escribiera el plan. Lo garantiza el hook ``UserPromptSubmit`` (`hooks/mensaje_usuario.py`):
cada vez que el usuario envía un mensaje, anota su huella (sha256 del texto normalizado) y la hora en
``~/.config/trovefy/mensajes-usuario.json``. Claude no puede escribir ese archivo: el hook `apimart_gasto` le niega
leer o escribir ``~/.config/trovefy`` y cualquier Bash que importe este módulo o lance el hook a mano. Es el mismo
patrón que la confirmación de pantallas del plan 18 (fuera del vault, en el directorio de configuración de trovefy).

Solo se guardan huellas, nunca el texto, y solo las últimas `MAX_MENSAJES`. Si el usuario ejecuta él mismo
``trovefy checkout aprobar`` en su terminal, la persona está delante y no hace falta el registro (ruling I-1).

Solo biblioteca estándar: el hook lo importa con el python3 del sistema. Nunca lanza: ante un archivo roto o un
enlace, no vale (falla cerrado).
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
import unicodedata
from pathlib import Path

NOMBRE = "mensajes-usuario.json"
MAX_MENSAJES = 50


def ruta_registro() -> Path:
    """``~/.config/trovefy/mensajes-usuario.json``."""
    return Path.home() / ".config" / "trovefy" / NOMBRE


def normalizar_mensaje(texto: str) -> str:
    """NFC, sin espacios de más (los saltos de línea cuentan como un espacio)."""
    return " ".join(unicodedata.normalize("NFC", texto).split())


def huella_mensaje(texto: str) -> str:
    return hashlib.sha256(normalizar_mensaje(texto).encode("utf-8")).hexdigest()


def _leer(ruta: Path) -> list[dict] | None:
    """Las entradas, o None si el registro es un enlace, no es un archivo normal o está roto."""
    try:
        info = os.lstat(ruta)
    except FileNotFoundError:
        return []
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(datos, list):
        return None
    return [d for d in datos if isinstance(d, dict) and isinstance(d.get("h"), str)
            and isinstance(d.get("t"), (int, float)) and not isinstance(d.get("t"), bool)]


def registrar_mensaje(texto: str, ahora: float | None = None) -> bool:
    """Anota la huella de un mensaje del usuario. False (sin escribir) si está vacío o el registro es un enlace u
    otra cosa que no es un archivo normal suyo; un registro roto se rehace."""
    if not isinstance(texto, str) or not normalizar_mensaje(texto):
        return False
    ruta = ruta_registro()
    try:
        ruta.parent.parent.mkdir(parents=True, exist_ok=True)
        ruta.parent.mkdir(mode=0o700, exist_ok=True)
        if ruta.parent.is_symlink():
            return False
        ruta.parent.chmod(0o700)
    except OSError:
        return False
    previas = _leer(ruta)
    if previas is None:
        if ruta.is_symlink() or (ruta.exists() and not ruta.is_file()):
            return False
        previas = []
    entradas = [*previas, {"t": float(time.time() if ahora is None else ahora), "h": huella_mensaje(texto)}]
    contenido = json.dumps(entradas[-MAX_MENSAJES:], separators=(",", ":"))
    try:
        fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{NOMBRE}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(contenido)
            os.chmod(tmp, 0o600)
            os.replace(tmp, ruta)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError:
        return False
    return True


def es_mensaje_del_usuario(cita: str, desde: float) -> bool:
    """¿``cita`` es, entera, un mensaje del usuario enviado en ``desde`` o después?"""
    if not isinstance(cita, str) or not normalizar_mensaje(cita):
        return False
    entradas = _leer(ruta_registro())
    if not entradas:
        return False
    h = huella_mensaje(cita)
    return any(e["h"] == h and e["t"] >= desde for e in entradas)
