"""Utilidades comunes de los verificadores: ejecutar comandos sin colgarse y guardar evidencia."""

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from trovify.arranque.estado import ResultadoVerificacion
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


@dataclass(frozen=True)
class Confirmacion:
    """Estado de un patrón o mapa de una pantalla privada.

    Mientras `fecha` sea None el patrón sale de la documentación o del encargo, no de la pantalla
    real del usuario: el verificador no certifica (ni suspende) nada con él; devuelve «no medido».
    Se confirma en un commit posterior a la primera captura real, poniendo la fecha.
    """

    fecha: str | None
    fuente: str

    @property
    def confirmada(self) -> bool:
        return self.fecha is not None


MOTIVO_SIN_CONFIRMAR = "no medido: patrón sin confirmar con tu pantalla real"


def sin_query(url: str) -> str:
    """La URL sin parámetros ni fragmento (pueden llevar identificadores o tokens)."""
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))


def guardar_provisional(vault: Path, id: str, url_final: str, png: bytes | None) -> list[str]:
    """Guarda la captura (PNG) y la URL sin query en config/evidencia/provisional/; devuelve las rutas."""
    if not _SEGURO.match(id):
        raise ValueError("id de evidencia solo admite letras, números, - y _")
    base = Path(vault) / "config" / "evidencia" / "provisional"
    fecha = f"{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}"
    rutas: list[str] = []
    for nombre, contenido in (
        (f"{id}-captura-{fecha}.png", png),
        (f"{id}-url-{fecha}.json", json.dumps({"url_final": sin_query(url_final)}, ensure_ascii=False).encode("utf-8")),
    ):
        if contenido is None:
            continue
        base.mkdir(parents=True, exist_ok=True)
        destino = base / nombre
        fd, tmp = tempfile.mkstemp(dir=base, prefix=".tmp-")
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
        rutas.append(destino.relative_to(vault).as_posix())
    return rutas


def resultado_provisional(vault: Path, id: str, captura, png: bytes | None) -> ResultadoVerificacion:
    """«No medido» para un patrón sin confirmar: guarda la captura provisional y nunca certifica."""
    rutas = guardar_provisional(vault, id, captura.url_final, png)
    lineas = [f"? {MOTIVO_SIN_CONFIRMAR}"] + [f"  captura provisional: {r}" for r in rutas]
    return ResultadoVerificacion(None, [], MOTIVO_SIN_CONFIRMAR, [], {}, lineas)
