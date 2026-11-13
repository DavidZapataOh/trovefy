"""Copia al vault: escrituras atómicas solo en tres carpetas, con cola de reintento.

El vault lo puede escribir otro usuario (Claude): nunca se sigue un enlace simbólico fuera de las
carpetas permitidas. Se recorre desde la raíz con descriptores de directorio y ``O_NOFOLLOW``.
"""
from __future__ import annotations

import errno
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from .auditoria import redactar
from .comandos import NotaMotivo
from .ejecutar import Resultado
from .estado import FilaPropuesta
from .reloj import ZONA_COT

CARPETAS = ("propuestas", "ledger/auditoria", "raw/telegram")
_FLAGS_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_ENLACE = (errno.ELOOP, errno.ENOTDIR)
_PERMANENTES = (errno.EISDIR, errno.ENAMETOOLONG, errno.ENOTDIR)
MAX_INTENTOS = 20
# Claude es dueño de los P-*.json que deposita y sigue pudiendo reescribirlos tras moverlos a procesadas/.
NOTA_FUENTE = ("Fuente de verdad: la base del ejecutor y esta copia (y la auditoría). "
               "`procesadas/P-*.json` del buzón no es prueba: lo escribió quien depositó y puede cambiarlo.")
_SIMPLE = re.compile(r"[A-Za-z0-9_.:/-]+")


class _Enlace(Exception):
    """Una componente del camino es un enlace simbólico (no es un fallo transitorio)."""


class _Existe(Exception):
    """``nuevo=True`` y el destino ya existe."""


def _normalizar(relativa: str) -> tuple[str, ...]:
    if not isinstance(relativa, str) or not relativa or "\0" in relativa or "\\" in relativa:
        raise ValueError(f"ruta no permitida: {relativa!r}")
    partes = PurePosixPath(relativa).parts
    if relativa.startswith("/") or any(p in ("", ".", "..") for p in partes):
        raise ValueError(f"ruta no permitida: {relativa!r}")
    for carpeta in CARPETAS:
        c = tuple(carpeta.split("/"))
        if len(partes) > len(c) and partes[: len(c)] == c:
            return partes
    raise ValueError(f"fuera de las carpetas permitidas: {relativa!r}")


def _abrir_sub(fd_padre: int, nombre: str, crear: bool) -> int:
    try:
        return os.open(nombre, _FLAGS_DIR, dir_fd=fd_padre)
    except FileNotFoundError:
        if not crear:
            raise
    except OSError as e:
        if e.errno in _ENLACE:  # ELOOP / ENOTDIR: enlace simbólico o no es carpeta
            raise _Enlace(nombre) from e
        raise
    try:
        os.mkdir(nombre, 0o750, dir_fd=fd_padre)
    except FileExistsError:
        pass
    try:
        return os.open(nombre, _FLAGS_DIR, dir_fd=fd_padre)
    except OSError as e:
        if e.errno in _ENLACE:
            raise _Enlace(nombre) from e
        raise


def _vacio(s: str | None) -> str:
    if s is None:
        return "null"
    return s if _SIMPLE.fullmatch(s) and s not in ("null", "true", "false") else json.dumps(s, ensure_ascii=False)


class CopiaVault:
    def __init__(self, vault: Path | None, pendientes: Path) -> None:
        self.vault = None if vault is None else Path(vault)
        self.pendientes = Path(pendientes)
        self._ok = True

    # -- escritura atómica ----------------------------------------------------------------
    def _escribir_ya(self, partes: tuple[str, ...], texto: str, nuevo: bool) -> None:
        assert self.vault is not None
        fds: list[int] = []
        try:
            fds.append(os.open(self.vault, os.O_RDONLY | os.O_DIRECTORY))  # la raíz misma puede ser un enlace
            for p in partes[:-1]:
                fds.append(_abrir_sub(fds[-1], p, crear=True))
            d = fds[-1]
            nombre = partes[-1]
            tmp = f".{nombre}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640, dir_fd=d)
            try:
                try:
                    vista = memoryview(texto.encode("utf-8"))
                    while vista:
                        vista = vista[os.write(fd, vista):]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                if nuevo:
                    try:
                        os.link(tmp, nombre, src_dir_fd=d, dst_dir_fd=d, follow_symlinks=False)
                    except FileExistsError:
                        raise _Existe(nombre) from None
                else:
                    os.replace(tmp, nombre, src_dir_fd=d, dst_dir_fd=d)
            finally:
                try:
                    os.unlink(tmp, dir_fd=d)
                except FileNotFoundError:
                    pass
        finally:
            for f in fds:
                os.close(f)

    def _intentar(
        self, partes: tuple[str, ...], texto: str, nuevo: bool
    ) -> Literal["ok", "reintentar", "descartar", "roto"]:
        try:
            self._escribir_ya(partes, texto, nuevo)
        except _Existe:
            return "descartar"
        except _Enlace:
            self._ok = False
            return "descartar"
        except OSError as e:
            self._ok = False
            return "roto" if e.errno in _PERMANENTES else "reintentar"
        self._ok = True
        return "ok"

    def escribir(self, relativa: str, texto: str, *, nuevo: bool = False) -> bool:
        return self._escribir(relativa, redactar(texto), nuevo)

    def _escribir(self, relativa: str, texto: str, nuevo: bool) -> bool:
        partes = _normalizar(relativa)
        if self.vault is None:
            return True
        if self._numeros() and self.reintentar():
            # la cola sigue bloqueada: detrás de ella, para que nada viejo pise a lo nuevo
            self._encolar(relativa, texto, nuevo)
            return False
        r = self._intentar(partes, texto, nuevo)
        if r == "reintentar":
            self._encolar(relativa, texto, nuevo)
        return r == "ok"

    # -- cola -----------------------------------------------------------------------------
    def ocupada(self, relativa: str) -> bool:
        """(plan 12) La ruta ya existe en el vault o espera en la cola (``nuevo`` no la pisaría)."""
        if self.vault is not None and os.path.lexists(self.vault / relativa):
            return True
        for n in self._numeros():
            try:
                if json.loads((self.pendientes / f"{n}.json").read_text(encoding="utf-8")).get("relativa") == relativa:
                    return True
            except (OSError, ValueError, AttributeError):
                continue
        return False

    def _numeros(self) -> list[int]:
        try:
            return sorted(int(p.stem) for p in self.pendientes.glob("*.json") if p.stem.isdigit())
        except OSError:
            return []

    def _guardar(self, n: int, relativa: str, texto: str, nuevo: bool, intentos: int) -> None:
        tmp = self.pendientes / f"{n}.json.{uuid.uuid4().hex}.tmp"
        datos = json.dumps({"relativa": relativa, "texto": texto, "nuevo": nuevo,
                            "intentos": intentos}).encode("utf-8")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                vista = memoryview(datos)
                while vista:
                    vista = vista[os.write(fd, vista):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self.pendientes / f"{n}.json")
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _encolar(self, relativa: str, texto: str, nuevo: bool) -> None:
        try:
            self.pendientes.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.pendientes, 0o700)
            nums = self._numeros()
            self._guardar((nums[-1] + 1) if nums else 0, relativa, texto, nuevo, 0)
        except OSError:
            pass  # sin cola no hay nada más que hacer; estado() ya dice «no escribible»

    def _apartar(self, ruta: Path) -> None:
        try:
            rotos = self.pendientes / "rotos"
            rotos.mkdir(exist_ok=True, mode=0o700)
            os.replace(ruta, rotos / f"{uuid.uuid4().hex[:8]}-{ruta.name}")
        except OSError:
            pass

    def reintentar(self) -> int:
        if self.vault is None:
            return 0
        bloqueado = False
        for n in self._numeros():
            ruta = self.pendientes / f"{n}.json"
            if bloqueado:
                continue
            try:
                d = json.loads(ruta.read_text(encoding="utf-8"))
                partes = _normalizar(d["relativa"])
                texto, nuevo = d["texto"], bool(d["nuevo"])
                intentos = int(d.get("intentos", 0))
                if not isinstance(texto, str):
                    raise TypeError("texto")
            except (OSError, ValueError, KeyError, TypeError):
                self._apartar(ruta)
                continue
            r = self._intentar(partes, texto, nuevo)
            if r == "reintentar":
                intentos += 1
                if intentos > MAX_INTENTOS:
                    self._apartar(ruta)
                    continue
                try:
                    self._guardar(n, d["relativa"], texto, nuevo, intentos)
                except OSError:
                    pass
                bloqueado = True  # se conserva el orden: no se aplica nada posterior
            elif r == "roto":
                self._apartar(ruta)
            else:
                try:
                    ruta.unlink()
                except OSError:
                    pass
        return len(self._numeros())

    def estado(self) -> Literal["ok", "no escribible"]:
        return "ok" if self._ok else "no escribible"

    # -- contenidos -----------------------------------------------------------------------
    def resultado(self, fila: FilaPropuesta, r: Resultado | None, texto_telegram: str) -> bool:
        cb = None
        if fila.clase != "no_gasto" and fila.tipo != "alerta":
            v = fila.datos.get("callback_id")
            cb = v if isinstance(v, str) else None
        cabecera = [
            "---",
            "tipo: propuesta-resultado",
            f"id: {_vacio(fila.id)}",
            f"tipo_propuesta: {_vacio(fila.tipo)}",
            f"estado: {_vacio(fila.estado)}",
            f"fecha: {fila.actualizada.astimezone(ZONA_COT).isoformat(timespec='seconds')}",
            f"callback_id: {_vacio(cb)}",
            f"parcial: {'true' if r is not None and r.parcial else 'false'}",
            "---",
            "",
            texto_telegram,
            "",
            NOTA_FUENTE,
        ]
        if r is not None:
            cabecera += ["", f"Detalle: {r.detalle}"]
            for op in r.operaciones:
                cabecera.append(
                    f"- {op.entidad_id} {op.campo}: {op.estado} "
                    f"({op.antes!r} -> {op.pedido!r} -> {op.despues!r}) {op.detalle}")
            if r.ids_creados:
                cabecera.append("")
                cabecera.append("ids_creados:")
                for k, v in r.ids_creados.items():
                    cabecera.append(f"- {k}: {v}")
        return self.escribir(f"propuestas/{fila.id}.md", redactar("\n".join(cabecera) + "\n"))

    def auditoria(self, origen: Path, dia: date) -> bool:
        try:
            crudo = Path(origen).read_bytes()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        mias: list[bytes] = []
        for linea in crudo.split(b"\n"):
            if not linea:
                continue
            try:
                ts = datetime.fromisoformat(json.loads(linea)["ts"])
                if ts.astimezone(ZONA_COT).date() == dia:
                    mias.append(linea)
            except (ValueError, KeyError, TypeError):
                continue
        if not mias:
            return True
        texto = b"\n".join(mias).decode("utf-8") + "\n"
        return self._escribir(f"ledger/auditoria/{dia.isoformat()}.jsonl", texto, False)

    def motivo(self, nota: NotaMotivo) -> bool:
        return self.escribir(nota.ruta_relativa, nota.contenido, nuevo=True)
