"""Buzón del ejecutor: lee entrada/ sin fiarse de escrituras parciales."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from trovefy_ejecutor.esquema import PropuestaInvalida

MAX_BYTES = 65_536
EDAD_MIN_S = 2.0
_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _malo(texto: str) -> PropuestaInvalida:
    return PropuestaInvalida(f"buzon: {texto}")


def _pares(pares: list[tuple[str, object]]) -> dict:
    d: dict = {}
    for k, v in pares:
        if k in d:
            raise _malo(f"clave duplicada: {k}")
        d[k] = v
    return d


def _constante(nombre: str):
    raise _malo("NaN o Infinity no permitido")


def _escribir_atomico(destino: Path, datos: dict) -> None:
    tmp = destino.with_name(f".{destino.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, destino)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Buzon:
    def __init__(self, raiz: Path, reloj: Callable[[], float] = time.time):
        self.raiz = Path(raiz)
        self.reloj = reloj
        self.entrada = self.raiz / "entrada"
        self.procesadas = self.raiz / "procesadas"
        self.estado = self.raiz / "estado"
        self.entrada.mkdir(parents=True, exist_ok=True)
        self.procesadas.mkdir(parents=True, exist_ok=True)
        self.estado.mkdir(parents=True, exist_ok=True)

    def nuevas(self) -> list[Path]:
        limite = self.reloj() - EDAD_MIN_S
        out: list[tuple[float, str, Path]] = []
        try:
            nombres = os.listdir(self.entrada)
        except FileNotFoundError:
            return []
        for nombre in nombres:
            if nombre.startswith(".") or not nombre.endswith(".json"):
                continue
            ruta = self.entrada / nombre
            try:
                st = os.lstat(ruta)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_mtime > limite:
                continue
            out.append((st.st_mtime, nombre, ruta))
        out.sort(key=lambda t: (t[0], t[1]))
        return [t[2] for t in out]

    def leer(self, ruta: Path) -> dict:
        try:
            # O_NONBLOCK: abrir una FIFO (o un dispositivo) no se queda esperando; luego S_ISREG la rechaza.
            fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as e:
            raise _malo(f"no se puede abrir (¿enlace simbólico?): {e.strerror}") from e
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise _malo("no es un archivo regular")
            with os.fdopen(fd, "rb", closefd=False) as f:
                crudo = f.read(MAX_BYTES + 1)
        finally:
            os.close(fd)
        if len(crudo) > MAX_BYTES:
            raise _malo("más de 64 KiB")
        try:
            texto = crudo.decode("utf-8")
        except UnicodeDecodeError as e:
            raise _malo("no es UTF-8") from e
        try:
            datos = json.loads(
                texto, object_pairs_hook=_pares, parse_constant=_constante
            )
        except PropuestaInvalida:
            raise
        except (ValueError, RecursionError) as e:
            raise _malo("JSON inválido") from e
        if not isinstance(datos, dict):
            raise _malo("se esperaba un objeto")
        return datos

    def procesar(self, ruta: Path, resultado: dict) -> Path:
        """Mueve ``ruta`` a ``procesadas/`` (sin pisar: ``-2``, ``-3``…) y escribe ``<id>.resultado.json``.

        ``procesadas/P-*.json`` **no es prueba** de lo aprobado ni de lo ejecutado: el archivo sigue siendo
        de quien lo depositó (Claude), que puede reescribirlo después de moverlo. Lo autoritativo es la
        base del ejecutor (``estado.sqlite``), la auditoría encadenada y la copia en el vault
        (``propuestas/<id>.md``). ``*.resultado.json`` es solo un aviso para Claude."""
        ruta = Path(ruta)
        stem, suf = ruta.stem, ruta.suffix
        n = 1
        while True:
            nombre = f"{stem}{suf}" if n == 1 else f"{stem}-{n}{suf}"
            destino = self.procesadas / nombre
            if not os.path.lexists(destino):
                break
            n += 1
        os.replace(ruta, destino)
        _escribir_atomico(self.procesadas / f"{destino.stem}.resultado.json", resultado)
        return destino

    def escribir_estado(self, nombre: str, datos: dict) -> Path:
        if not isinstance(nombre, str) or not _NOMBRE.fullmatch(nombre):
            raise ValueError(f"nombre de estado no válido: {nombre!r}")
        destino = self.estado / f"{nombre}.json"
        _escribir_atomico(destino, datos)
        return destino
