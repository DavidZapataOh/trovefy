"""Auditoría append-only encadenada por hash (§5.10, resolución 13). Sin PyYAML."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

GENESIS = "0" * 64

EV_RECIBIDA = "recibida"
EV_VALIDACION_RECHAZADA = "validacion_rechazada"
EV_TRANSICION = "transicion"
EV_CALLBACK_INVALIDO = "callback_invalido"
EV_EJECUCION = "ejecucion"
EV_STOP = "stop"
EV_LIMITE_CAMBIADO = "limite_cambiado"
EV_MENSAJE_IGNORADO = "mensaje_ignorado"
EV_EMPAREJADO = "emparejado"
EV_EMPAREJAR_RECHAZADO = "emparejar_rechazado"
EV_CADENA_REANUDADA = "cadena_reanudada"

CAMPOS_MINIMOS: Mapping[str, frozenset[str]] = MappingProxyType({
    EV_RECIBIDA: frozenset({"id", "tipo"}),
    EV_VALIDACION_RECHAZADA: frozenset({"id", "motivo"}),
    EV_TRANSICION: frozenset({"id", "tipo", "de", "a"}),
    EV_CALLBACK_INVALIDO: frozenset({"motivo"}),
    EV_EJECUCION: frozenset({"id", "tipo", "validate_only", "ok", "detalle"}),
    EV_STOP: frozenset({"activo"}),
    EV_LIMITE_CAMBIADO: frozenset({"clave", "de", "a"}),
    EV_MENSAJE_IGNORADO: frozenset({"motivo"}),
    EV_EMPAREJADO: frozenset({"user_id", "chat_id"}),
    EV_EMPAREJAR_RECHAZADO: frozenset({"motivo"}),
    EV_CADENA_REANUDADA: frozenset({"archivo_anterior", "hash_ultimo_valido"}),
})

_PATRONES = (
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
    re.compile(r"EAA[A-Za-z0-9]+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
)


def _lock_de(ruta: Path) -> Path:
    return ruta.with_name(ruta.name + ".lock")


class AuditoriaCorrupta(Exception):
    """El archivo de auditoría no termina en línea completa o no se puede leer."""


def redactar(texto: str) -> str:
    for p in _PATRONES:
        texto = p.sub("***", texto)
    return texto


def _redactar_todo(v: Any) -> Any:
    if isinstance(v, str):
        return redactar(v)
    if isinstance(v, list):
        return [_redactar_todo(x) for x in v]
    if isinstance(v, dict):
        return {_redactar_todo(k): _redactar_todo(x) for k, x in v.items()}
    return v


def _hash(linea: Mapping[str, Any]) -> str:
    cuerpo = {k: v for k, v in linea.items() if k != "hash"}
    canon = json.dumps(cuerpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _ahora() -> datetime:
    return datetime.now(UTC)


def _cabeza_de(ruta: Path) -> Path:
    return ruta.with_name(ruta.name + ".cabeza")


def _recorrer_lineas(
    lineas: Iterable[bytes | str | Mapping[str, Any]], n0: int, hash_prev: str
) -> tuple[str | None, int, str]:
    """(primer fallo, última n válida, hash de la última válida); las posiciones del fallo son relativas."""
    n_ok, ultimo = n0 - 1, hash_prev
    for i, cruda in enumerate(lineas, start=1):
        try:
            if isinstance(cruda, Mapping):
                linea: Any = cruda
            else:
                texto = cruda.decode("utf-8") if isinstance(cruda, bytes) else cruda
                linea = json.loads(texto)
            ok = (
                isinstance(linea, Mapping)
                and linea.get("n") == n_ok + 1
                and linea.get("hash_prev") == ultimo
                and linea.get("hash") == _hash(linea)
            )
        except (ValueError, UnicodeDecodeError, TypeError):
            ok = False
        if not ok:
            return f"línea {i}: cadena rota", n_ok, ultimo
        n_ok, ultimo = n_ok + 1, linea["hash"]
    return None, n_ok, ultimo


def verificar_lineas(
    lineas: Iterable[bytes | str | Mapping[str, Any]], n0: int = 1, hash_prev: str = GENESIS
) -> str | None:
    """Comprueba un tramo de cadena que empieza en ``n0`` tras ``hash_prev``. None = cuadra; si no, el motivo."""
    return _recorrer_lineas(lineas, n0, hash_prev)[0]


def _recorrer(ruta: Path) -> tuple[str | None, int, str, bool]:
    """(primer fallo, líneas válidas, hash de la última válida, existe cabeza-consistente)."""
    if not ruta.exists():
        return None, 0, GENESIS, True
    trozos = ruta.read_bytes().split(b"\n")
    cola = trozos.pop()  # vacío si el archivo termina en salto de línea
    fallo, n_ok, ultimo = _recorrer_lineas(trozos, 1, GENESIS)
    if fallo:
        return fallo, n_ok, ultimo, False
    if cola:
        return f"línea {n_ok + 1}: incompleta", n_ok, ultimo, False
    return None, n_ok, ultimo, True


class Auditoria:
    def __init__(self, ruta: Path, reloj: Callable[[], datetime] = _ahora) -> None:
        self.ruta = Path(ruta)
        self._reloj = reloj
        if self.ruta.exists() and self.ruta.stat().st_size:
            with self.ruta.open("rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    raise AuditoriaCorrupta(f"{self.ruta}: última línea incompleta")

    @property
    def cabeza(self) -> Path:
        return _cabeza_de(self.ruta)

    def _leer_cabeza(self) -> dict[str, Any] | None:
        if not self.cabeza.exists():
            return None
        try:
            cab = json.loads(self.cabeza.read_text(encoding="utf-8"))
            if isinstance(cab, dict) and isinstance(cab.get("n"), int) and "hash" in cab:
                return cab
        except (ValueError, OSError):
            pass
        raise AuditoriaCorrupta(f"{self.cabeza}: cabeza ilegible")

    def _estado_verificado(self) -> tuple[int, str]:
        """Bajo el cerrojo: verifica la cadena y su cabeza; solo `reparar` lo desbloquea."""
        fallo, n_ok, ultimo, _ = _recorrer(self.ruta)
        if fallo:
            raise AuditoriaCorrupta(f"{self.ruta}: {fallo}")
        cab = self._leer_cabeza()
        if cab is None:
            if n_ok:
                raise AuditoriaCorrupta(f"{self.ruta}: falta el archivo de cabeza")
            return 0, GENESIS
        if n_ok and cab["n"] == n_ok and cab["hash"] == ultimo:
            return n_ok, ultimo
        if n_ok >= 1 and cab["n"] == n_ok - 1:
            # hueco benigno: caída entre el append y la cabeza
            prev = json.loads(self.ruta.read_bytes().split(b"\n")[-2])["hash_prev"]
            if prev == (cab["hash"] if cab["n"] else GENESIS):
                self._escribir_cabeza(n_ok, ultimo)
                return n_ok, ultimo
        raise AuditoriaCorrupta(f"{self.ruta}: la cabeza no coincide con la última línea")

    def anotar(self, evento: str, **datos: Any) -> dict[str, Any]:
        minimos = CAMPOS_MINIMOS.get(evento)
        if minimos is not None:
            faltan = sorted(minimos - datos.keys())
            if faltan:
                raise ValueError(f"evento {evento}: faltan campos {', '.join(faltan)}")
        limpios = _redactar_todo(json.loads(json.dumps(datos, default=str)))
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        lock = os.open(_lock_de(self.ruta), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            n, previo = self._estado_verificado()
            ts = self._reloj().astimezone(UTC).isoformat(timespec="microseconds")
            linea: dict[str, Any] = {
                "n": n + 1, "ts": ts, "evento": evento,
                "datos": limpios, "hash_prev": previo,
            }
            linea["hash"] = _hash(linea)
            crudo = (json.dumps(linea, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False) + "\n").encode("utf-8")
            fd = os.open(self.ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                vista = memoryview(crudo)
                while vista:
                    vista = vista[os.write(fd, vista):]
                os.fsync(fd)
            finally:
                os.close(fd)
            self._escribir_cabeza(linea["n"], linea["hash"])
            return linea
        finally:
            os.close(lock)  # suelta el flock

    def _escribir_cabeza(self, n: int, h: str) -> None:
        tmp = self.cabeza.with_name(f"{self.cabeza.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps({"n": n, "hash": h}).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, self.cabeza)

    def primer_fallo(self) -> str | None:
        fallo, n_ok, ultimo, _ = _recorrer(self.ruta)
        if fallo:
            return fallo
        try:
            cab = json.loads(self.cabeza.read_text(encoding="utf-8")) if self.cabeza.exists() else None
        except (ValueError, OSError):
            return "cabeza ilegible"
        if cab is None:
            return None if n_ok == 0 else "falta el archivo de cabeza"
        if not isinstance(cab, dict) or cab.get("n") != n_ok or cab.get("hash") != (ultimo if n_ok else cab.get("hash")):
            return f"la cabeza no coincide con la última línea ({n_ok}): faltan líneas del final"
        if n_ok == 0:
            return "cabeza sin líneas: archivo vaciado"
        return None

    def verificar(self) -> bool:
        return self.primer_fallo() is None


def reparar(ruta: Path, reloj: Callable[[], datetime] = _ahora) -> Path:
    ruta = Path(ruta)
    _, _, ultimo, _ = _recorrer(ruta)
    sello = reloj().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    k = 0
    while True:
        sufijo = f".roto-{sello}" + (f"-{k}" if k else "")
        roto = ruta.with_name(ruta.name + sufijo)
        cab = _cabeza_de(ruta)
        if not roto.exists() and not cab.with_name(cab.name + sufijo).exists():
            break
        k += 1
    for origen in (ruta, cab):
        destino = roto if origen is ruta else cab.with_name(cab.name + sufijo)
        if origen.exists():
            os.link(origen, destino)  # exclusivo: nunca pisa pruebas previas
            origen.unlink()
    Auditoria(ruta, reloj).anotar(
        EV_CADENA_REANUDADA, archivo_anterior=roto.name, hash_ultimo_valido=ultimo
    )
    return roto
