"""Escritura atómica en el vault y registro en log.md."""

import fcntl
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ZONA_NEGOCIO = ZoneInfo("America/Bogota")


def escribir_atomico(ruta: Path, contenido: str) -> None:
    """Escribe en un temporal del mismo directorio y lo mueve con os.replace."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def anadir_log(
    vault: Path,
    skill: str,
    que: str,
    archivos: list[str],
    tokens_aprox: int | None = None,
    ahora: datetime | None = None,
) -> str:
    """Añade una línea a log.md (con flock) y la devuelve."""
    ahora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    tokens = "—" if tokens_aprox is None else f"~{tokens_aprox}"
    una_linea = lambda s: re.sub(r"[\r\n]+", " ", str(s)) 
    linea = (
        f"- {ahora:%Y-%m-%d %H:%M} COT · {una_linea(skill)} · {una_linea(que)} · "
        f"{', '.join(una_linea(a) for a in archivos)} · {tokens} tokens"
    )
    ruta = Path(vault) / "log.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(linea + "\n")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return linea
