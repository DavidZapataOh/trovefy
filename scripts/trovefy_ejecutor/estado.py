"""Estado SQLite de propuestas con transiciones atómicas (§5.5)."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .esquema import cargar_propuesta, volcar_propuesta
from .modelo import Clase, Estado, Propuesta

_FINALES: frozenset[Estado] = frozenset()

TRANSICIONES: Mapping[Estado, frozenset[Estado]] = MappingProxyType({
    "recibida": frozenset({"enviada", "obsoleta", "caducada", "rechazada", "ejecutando"}),
    "enviada": frozenset({"enviada", "aceptada", "rechazada", "caducada", "obsoleta"}),
    "aceptada": frozenset({"ejecutando", "obsoleta", "fallida"}),
    "ejecutando": frozenset({"ejecutada", "fallida", "discrepancia"}),
    "ejecutada": _FINALES, "fallida": _FINALES, "discrepancia": _FINALES,
    "rechazada": _FINALES, "caducada": _FINALES, "obsoleta": _FINALES,
})


class IdDuplicado(Exception):
    """Ya existe una propuesta con ese id."""


class TransicionInvalida(ValueError):
    """Par de estados fuera de TRANSICIONES."""


@dataclass(frozen=True)
class FilaPropuesta:
    id: str
    tipo: str
    clase: Clase
    cuenta: str | None
    estado: Estado
    propuesta: Propuesta
    recibida: datetime
    actualizada: datetime
    chat_id: int | None
    message_id: int | None
    datos: dict[str, Any]


def _utc(d: datetime) -> datetime:
    if not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("datetime naive: se exige zona horaria")
    return d.astimezone(UTC)


def _iso(d: datetime) -> str:
    return _utc(d).isoformat(timespec="microseconds")


def _de_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


_ESQUEMA = """
CREATE TABLE IF NOT EXISTS propuestas(
  id TEXT PRIMARY KEY, tipo TEXT NOT NULL, clase TEXT NOT NULL, cuenta TEXT, estado TEXT NOT NULL,
  json TEXT NOT NULL, recibida TEXT NOT NULL, actualizada TEXT NOT NULL,
  chat_id INTEGER, message_id INTEGER, datos TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS historial(id TEXT NOT NULL, de TEXT, a TEXT NOT NULL, cuando TEXT NOT NULL, datos TEXT);
CREATE INDEX IF NOT EXISTS ix_historial_id ON historial(id);
CREATE TABLE IF NOT EXISTS cambios(entidad TEXT NOT NULL, campo TEXT NOT NULL, cuando TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_cambios ON cambios(entidad, campo, cuando);
CREATE TABLE IF NOT EXISTS kv(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


class Almacen:
    def __init__(self, ruta: Path, reloj: Callable[[], datetime] = lambda: datetime.now(UTC)):
        ruta = Path(ruta)
        nuevo = not ruta.exists()
        self._reloj = reloj
        self._con = sqlite3.connect(str(ruta), isolation_level=None, timeout=5.0)
        self._con.execute("PRAGMA busy_timeout=5000")
        if nuevo:
            os.chmod(ruta, 0o600)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._escribir(lambda c: [c.execute(sql) for sql in _ESQUEMA.split(";") if sql.strip()])
        for sufijo in ("-wal", "-shm"):
            p = Path(str(ruta) + sufijo)
            if p.exists():
                os.chmod(p, 0o600)

    def _escribir(self, fn):
        c = self._con
        c.execute("BEGIN IMMEDIATE")
        try:
            r = fn(c)
        except BaseException:
            c.execute("ROLLBACK")
            raise
        try:
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return r

    def _ahora(self) -> str:
        return _iso(self._reloj())

    def registrar(self, p: Propuesta) -> None:
        ahora = self._ahora()
        js = json.dumps(volcar_propuesta(p), ensure_ascii=False)

        def fn(c):
            if c.execute("SELECT 1 FROM propuestas WHERE id=?", (p.id,)).fetchone():
                raise IdDuplicado(p.id)
            c.execute("INSERT INTO propuestas(id,tipo,clase,cuenta,estado,json,recibida,actualizada,datos)"
                      " VALUES(?,?,?,?,?,?,?,?,'{}')",
                      (p.id, p.tipo, p.clase, p.cuenta, "recibida", js, ahora, ahora))
            c.execute("INSERT INTO historial(id,de,a,cuando,datos) VALUES(?,NULL,'recibida',?,NULL)", (p.id, ahora))
        self._escribir(fn)

    def transicion(self, id: str, de: Estado, a: Estado, /, **datos) -> bool:
        """Mueve ``de → a`` de forma atómica. False si el estado actual no es ``de`` o el id no existe.

        ``recibida → ejecutando`` solo vale para las clases ``no_gasto`` y ``notificacion``.
        """
        if a not in TRANSICIONES.get(de, frozenset()):
            raise TransicionInvalida(f"{de} -> {a}")
        ahora = self._ahora()

        def fn(c):
            fila = c.execute("SELECT datos, clase FROM propuestas WHERE id=? AND estado=?", (id, de)).fetchone()
            if fila is None:
                return False
            if de == "recibida" and a == "ejecutando" and fila[1] not in ("no_gasto", "notificacion"):
                raise TransicionInvalida(f"{de} -> {a} no vale para la clase {fila[1]}")
            fusion = {**json.loads(fila[0]), **datos}
            cur = c.execute("UPDATE propuestas SET estado=?, datos=?, actualizada=? WHERE id=? AND estado=?",
                            (a, json.dumps(fusion, ensure_ascii=False), ahora, id, de))
            if cur.rowcount != 1:
                return False
            c.execute("INSERT INTO historial(id,de,a,cuando,datos) VALUES(?,?,?,?,?)",
                      (id, de, a, ahora, json.dumps(datos, ensure_ascii=False) if datos else None))
            return True
        return self._escribir(fn)

    _COLS = "id,tipo,clase,cuenta,estado,json,recibida,actualizada,chat_id,message_id,datos"

    @staticmethod
    def _fila(r) -> FilaPropuesta:
        return FilaPropuesta(id=r[0], tipo=r[1], clase=r[2], cuenta=r[3], estado=r[4],
                             propuesta=cargar_propuesta(json.loads(r[5])), recibida=_de_iso(r[6]),
                             actualizada=_de_iso(r[7]), chat_id=r[8], message_id=r[9], datos=json.loads(r[10]))

    def obtener(self, id: str) -> FilaPropuesta | None:
        r = self._con.execute(f"SELECT {self._COLS} FROM propuestas WHERE id=?", (id,)).fetchone()
        return self._fila(r) if r else None

    def en_estado(self, *estados: Estado) -> list[FilaPropuesta]:
        if not estados:
            return []
        q = ",".join("?" * len(estados))
        rs = self._con.execute(f"SELECT {self._COLS} FROM propuestas WHERE estado IN ({q})"
                               " ORDER BY recibida, rowid", estados).fetchall()
        return [self._fila(r) for r in rs]

    def historial(self, id: str) -> list[tuple[Estado | None, Estado, datetime]]:
        rs = self._con.execute("SELECT de,a,cuando FROM historial WHERE id=? ORDER BY rowid", (id,)).fetchall()
        return [(r[0], r[1], _de_iso(r[2])) for r in rs]

    def envios_desde(self, desde: datetime) -> list[datetime]:
        d = _iso(desde)
        # Envíos a Telegram: entrada en «enviada» y, para las notificaciones (resolución 21), llegada a «ejecutada».
        rs = self._con.execute(
            "SELECT h.cuando FROM historial h JOIN propuestas p ON p.id=h.id WHERE h.cuando>=?"
            " AND ((h.a='enviada' AND h.de IS NOT 'enviada') OR (h.a='ejecutada' AND p.clase='notificacion'))"
            " ORDER BY h.cuando, h.rowid", (d,)).fetchall()
        return [_de_iso(r[0]) for r in rs]

    def guardar_mensaje(self, id: str, chat_id: int, message_id: int) -> None:
        self._escribir(lambda c: c.execute("UPDATE propuestas SET chat_id=?, message_id=? WHERE id=?",
                                           (chat_id, message_id, id)))

    def ultimo_update(self) -> int:
        r = self._con.execute("SELECT valor FROM kv WHERE clave='ultimo_update'").fetchone()
        return int(r[0]) if r else 0

    def marcar_update(self, update_id: int) -> None:
        def fn(c):
            r = c.execute("SELECT valor FROM kv WHERE clave='ultimo_update'").fetchone()
            if r is None or int(r[0]) < update_id:
                c.execute("INSERT OR REPLACE INTO kv(clave,valor) VALUES('ultimo_update',?)", (str(update_id),))
        self._escribir(fn)

    def actualizar_datos(self, id: str, estado: Estado, /, **datos) -> bool:
        """(extra, plan 12) Fusiona ``datos`` sin cambiar el estado ni el historial; False si el estado
        actual no es ``estado`` o el id no existe. Nunca es una transición."""
        ahora = self._ahora()

        def fn(c):
            fila = c.execute("SELECT datos FROM propuestas WHERE id=? AND estado=?", (id, estado)).fetchone()
            if fila is None:
                return False
            fusion = {**json.loads(fila[0]), **datos}
            cur = c.execute("UPDATE propuestas SET datos=?, actualizada=? WHERE id=? AND estado=?",
                            (json.dumps(fusion, ensure_ascii=False), ahora, id, estado))
            return cur.rowcount == 1
        return self._escribir(fn)

    _KV_RESERVADAS = frozenset({"ultimo_update"})

    def consumir(self, clave: str) -> bool:
        """(extra, plan 12) True solo la primera vez para ``clave`` (persistente): p. ej. un ``Q-`` usado."""
        def fn(c):
            cur = c.execute("INSERT OR IGNORE INTO kv(clave,valor) VALUES(?,?)",
                            (f"consumido:{clave}", self._ahora()))
            return cur.rowcount == 1
        return self._escribir(fn)

    def _clave_kv(self, clave: str) -> str:
        if clave in self._KV_RESERVADAS or clave.startswith("consumido:"):
            raise ValueError(f"clave reservada: {clave}")
        return f"kv:{clave}"

    def poner_kv(self, clave: str, valor: str) -> None:
        k = self._clave_kv(clave)
        self._escribir(lambda c: c.execute("INSERT OR REPLACE INTO kv(clave,valor) VALUES(?,?)", (k, valor)))

    def leer_kv(self, clave: str) -> str | None:
        r = self._con.execute("SELECT valor FROM kv WHERE clave=?", (self._clave_kv(clave),)).fetchone()
        return r[0] if r else None

    def borrar_kv(self, clave: str) -> None:
        k = self._clave_kv(clave)
        self._escribir(lambda c: c.execute("DELETE FROM kv WHERE clave=?", (k,)))

    def registrar_cambio(self, entidad: str, campo: str, cuando: datetime) -> None:
        w = _iso(cuando)
        self._escribir(lambda c: c.execute("INSERT INTO cambios(entidad,campo,cuando) VALUES(?,?,?)",
                                           (entidad, campo, w)))

    def cambios_desde(self, entidad: str, campo: str, desde: datetime) -> int:
        return self._con.execute("SELECT COUNT(*) FROM cambios WHERE entidad=? AND campo=? AND cuando>=?",
                                 (entidad, campo, _iso(desde))).fetchone()[0]

    def ultimo_cambio(self, entidad: str, campo: str) -> datetime | None:
        r = self._con.execute("SELECT MAX(cuando) FROM cambios WHERE entidad=? AND campo=?",
                              (entidad, campo)).fetchone()
        return _de_iso(r[0]) if r and r[0] else None

    def cerrar(self) -> None:
        self._con.close()
