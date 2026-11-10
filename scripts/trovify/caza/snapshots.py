"""Fotos diarias de la Biblioteca en SQLite; dato no medido = NULL, nunca 0."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Snapshot:
    oferta_id: str
    pais: str
    dia: date
    total: int | None
    activos: int | None
    c7: int | None
    c8: int | None
    nuevos: int | None
    parados: int | None
    alcance_ue: float | None
    fuente: str


_COLS = ("oferta_id", "pais", "dia", "total", "activos", "c7", "c8",
         "nuevos", "parados", "alcance_ue", "fuente")


def abrir(ruta: Path) -> sqlite3.Connection:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            oferta_id TEXT NOT NULL, pais TEXT NOT NULL, dia TEXT NOT NULL,
            total INTEGER, activos INTEGER, c7 INTEGER, c8 INTEGER,
            nuevos INTEGER, parados INTEGER, alcance_ue REAL, fuente TEXT NOT NULL,
            PRIMARY KEY (oferta_id, pais, dia)
        );
        CREATE TABLE IF NOT EXISTS anuncios_vistos (
            library_id TEXT NOT NULL, oferta_id TEXT NOT NULL, pais TEXT NOT NULL,
            primera_vez TEXT NOT NULL, ultima_vez TEXT NOT NULL,
            PRIMARY KEY (library_id, oferta_id, pais)
        );
        """
    )
    return conn


def guardar(conn: sqlite3.Connection, s: Snapshot) -> None:
    vals = [s.dia.isoformat() if c == "dia" else getattr(s, c) for c in _COLS]
    conn.execute(
        f"INSERT OR REPLACE INTO snapshots ({', '.join(_COLS)}) "
        f"VALUES ({', '.join('?' * len(_COLS))})",
        vals,
    )
    conn.commit()


def historial(conn: sqlite3.Connection, oferta_id: str, pais: str, desde: date) -> list[Snapshot]:
    filas = conn.execute(
        f"SELECT {', '.join(_COLS)} FROM snapshots "
        "WHERE oferta_id = ? AND pais = ? AND dia >= ? ORDER BY dia",
        (oferta_id, pais, desde.isoformat()),
    ).fetchall()
    return [Snapshot(f[0], f[1], date.fromisoformat(f[2]), *f[3:]) for f in filas]


def registrar_vistos(
    conn: sqlite3.Connection, oferta_id: str, pais: str, library_ids: set[str], dia: date
) -> tuple[int | None, int | None]:
    """(nuevos, parados) frente a la foto anterior; la primera vez, (None, None)."""
    d = dia.isoformat()
    previa = conn.execute(
        "SELECT MAX(ultima_vez) FROM anuncios_vistos WHERE oferta_id = ? AND pais = ? AND ultima_vez < ?",
        (oferta_id, pais, d),
    ).fetchone()[0]
    conocidos = {
        r[0]
        for r in conn.execute(
            "SELECT library_id FROM anuncios_vistos WHERE oferta_id = ? AND pais = ? AND primera_vez < ?",
            (oferta_id, pais, d),
        )
    }
    anteriores = set()
    if previa is not None:
        anteriores = {
            r[0]
            for r in conn.execute(
                "SELECT library_id FROM anuncios_vistos WHERE oferta_id = ? AND pais = ? AND ultima_vez = ?",
                (oferta_id, pais, previa),
            )
        }
    for lid in library_ids:
        conn.execute(
            "INSERT INTO anuncios_vistos (library_id, oferta_id, pais, primera_vez, ultima_vez) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(library_id, oferta_id, pais) "
            "DO UPDATE SET ultima_vez = excluded.ultima_vez",
            (lid, oferta_id, pais, d, d),
        )
    conn.commit()
    if previa is None:
        return (None, None)
    return (len(library_ids - conocidos), len(anteriores - library_ids))
