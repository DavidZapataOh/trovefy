"""Candado de instancia única (flock) compartido por `servir` y `emparejar`."""
from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MENSAJE_OTRO = "Ya hay un ejecutor en marcha; detén el servicio: sudo systemctl stop trovefy-ejecutor"


class OtroEjecutorActivo(Exception):
    """Otro proceso tiene el candado."""


@contextmanager
def candado(ruta: Path) -> Iterator[None]:
    # El archivo no se borra nunca al salir: borrarlo permite una carrera.
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OtroEjecutorActivo(MENSAJE_OTRO) from None
        yield
    finally:
        os.close(fd)  # cerrar el fd libera el flock
