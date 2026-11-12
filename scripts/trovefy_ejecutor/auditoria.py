"""Auditoría append-only encadenada por hash (§5.10, resolución 13). Sin PyYAML."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
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


def _recorrer(ruta: Path) -> tuple[str | None, int, str, bool]:
    """(primer fallo, líneas válidas, hash de la última válida, existe cabeza-consistente)."""
    n_ok, ultimo = 0, GENESIS
    if not ruta.exists():
        return None, 0, GENESIS, True
    datos = ruta.read_bytes()
    trozos = datos.split(b"\n")
    cola = trozos.pop()  # vacío si el archivo termina en salto de línea
    for i, cruda in enumerate(trozos, start=1):
        try:
            linea = json.loads(cruda.decode("utf-8"))
            ok = (
                isinstance(linea, dict)
                and linea.get("n") == i
                and linea.get("hash_prev") == ultimo
                and linea.get("hash") == _hash(linea)
            )
        except (ValueError, UnicodeDecodeError):
            ok = False
        if not ok:
            return f"línea {i}: cadena rota", n_ok, ultimo, False
        n_ok, ultimo = i, linea["hash"]
    if cola:
        return f"línea {n_ok + 1}: incompleta", n_ok, ultimo, False
    return None, n_ok, ultimo, True


class Auditoria:
    def __init__(self, ruta: Path, reloj: Callable[[], datetime] = _ahora) -> None:
        self.ruta = Path(ruta)
        self._reloj = reloj
        self._n, self._hash = 0, GENESIS
        if self.ruta.exists() and self.ruta.stat().st_size:
            with self.ruta.open("rb") as f:
                f.seek(0, os.SEEK_END)
                tam = f.tell()
                f.seek(max(0, tam - 1))
                if f.read(1) != b"\n":
                    raise AuditoriaCorrupta(f"{self.ruta}: última línea incompleta")
                # cola: última línea (puede ser larga; se lee hacia atrás por bloques)
                bloque, pos = b"", tam - 1
                while pos > 0 and b"\n" not in bloque:
                    ini = max(0, pos - 4096)
                    f.seek(ini)
                    bloque = f.read(pos - ini) + bloque
                    pos = ini
                ultima = bloque.rsplit(b"\n", 1)[-1]
            try:
                linea = json.loads(ultima.decode("utf-8"))
                self._n, self._hash = int(linea["n"]), str(linea["hash"])
            except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
                raise AuditoriaCorrupta(f"{self.ruta}: última línea ilegible") from e

    @property
    def cabeza(self) -> Path:
        return _cabeza_de(self.ruta)

    def anotar(self, evento: str, **datos: Any) -> dict[str, Any]:
        minimos = CAMPOS_MINIMOS.get(evento)
        if minimos is not None:
            faltan = sorted(minimos - datos.keys())
            if faltan:
                raise ValueError(f"evento {evento}: faltan campos {', '.join(faltan)}")
        limpios = _redactar_todo(json.loads(json.dumps(datos, default=str)))
        ts = self._reloj().astimezone(UTC).isoformat(timespec="microseconds")
        linea: dict[str, Any] = {
            "n": self._n + 1, "ts": ts, "evento": evento,
            "datos": limpios, "hash_prev": self._hash,
        }
        linea["hash"] = _hash(linea)
        crudo = (json.dumps(linea, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False) + "\n").encode("utf-8")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, crudo)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._n, self._hash = linea["n"], linea["hash"]
        self._escribir_cabeza()
        return linea

    def _escribir_cabeza(self) -> None:
        tmp = self.cabeza.with_name(self.cabeza.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps({"n": self._n, "hash": self._hash}).encode("utf-8"))
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
    roto = ruta.with_name(f"{ruta.name}.roto-{sello}")
    os.replace(ruta, roto)
    cab = _cabeza_de(ruta)
    if cab.exists():
        os.replace(cab, cab.with_name(f"{cab.name}.roto-{sello}"))
    Auditoria(ruta, reloj).anotar(
        EV_CADENA_REANUDADA, archivo_anterior=roto.name, hash_ultimo_valido=ultimo
    )
    return roto
