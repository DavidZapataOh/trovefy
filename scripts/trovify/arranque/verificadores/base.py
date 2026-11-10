"""Utilidades comunes de los verificadores: ejecutar comandos sin colgarse y guardar evidencia."""

import json
import os
import re
import signal
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from trovify.vault.escritura import ZONA_NEGOCIO

_SEGURO = re.compile(r"^[A-Za-z0-9_-]+$")


def correr(cmd: list[str], timeout: float = 10) -> tuple[int | None, str]:
    """Ejecuta `cmd`; devuelve (código, salida). `None` si no existe o se agota el tiempo."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # grupo propio: un snap colgado se mata entero
        )
    except (FileNotFoundError, PermissionError):  # PermissionError: un directorio del PATH no es legible
        return None, "no instalado"
    except OSError as exc:
        return None, f"no se pudo ejecutar: {exc.strerror or exc}"
    try:
        salida, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.communicate(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None, "tiempo agotado"
    return proc.returncode, salida.decode("utf-8", errors="replace").strip()


def guardar_evidencia(vault: Path, id: str, nombre: str, datos: dict | bytes) -> str:
    """Escribe la evidencia en config/evidencia/ y devuelve su ruta relativa al vault."""
    if not _SEGURO.match(id) or not _SEGURO.match(nombre):
        raise ValueError("id y nombre de evidencia solo admiten letras, números, - y _")
    ext = "png" if isinstance(datos, bytes) else "json"
    rel = f"config/evidencia/{id}-{nombre}-{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}.{ext}"
    destino = Path(vault) / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    contenido = datos if isinstance(datos, bytes) else json.dumps(datos, ensure_ascii=False, indent=2).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return rel
