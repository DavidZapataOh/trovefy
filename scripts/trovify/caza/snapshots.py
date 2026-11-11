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
    # El enlace reproducible que dio la cifra: ``ResultadoBusqueda.url``; si la oferta abarca varias
    # páginas (varias búsquedas), sus URLs unidas con " | ".
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
        CREATE TABLE IF NOT EXISTS corridas (
            oferta_id TEXT NOT NULL, pais TEXT NOT NULL, dia TEXT NOT NULL,
            PRIMARY KEY (oferta_id, pais, dia)
        );
        CREATE TABLE IF NOT EXISTS paginas (
            page_id TEXT NOT NULL, pais TEXT NOT NULL, dia TEXT NOT NULL,
            total INTEGER NOT NULL, fuente TEXT NOT NULL,
            PRIMARY KEY (page_id, pais, dia)
        );
        CREATE TABLE IF NOT EXISTS vistos_dia (
            oferta_id TEXT NOT NULL, pais TEXT NOT NULL, dia TEXT NOT NULL,
            library_id TEXT NOT NULL,
            PRIMARY KEY (oferta_id, pais, dia, library_id)
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


@dataclass
class FotoPagina:
    """Total exacto de Meta de una PÁGINA (todas sus ofertas) en un país y día; nunca de una oferta."""

    page_id: str
    pais: str
    dia: date
    total: int
    fuente: str


def guardar_pagina(conn: sqlite3.Connection, page_id: str, pais: str, dia: date, total: int, fuente: str) -> None:
    """Solo con el ``count`` exacto de Meta (``ResultadoBusqueda.total_exacto``)."""
    conn.execute(
        "INSERT OR REPLACE INTO paginas (page_id, pais, dia, total, fuente) VALUES (?, ?, ?, ?, ?)",
        (page_id, pais, dia.isoformat(), int(total), fuente),
    )
    conn.commit()


def historial_pagina(conn: sqlite3.Connection, page_id: str, pais: str, desde: date) -> list[FotoPagina]:
    filas = conn.execute(
        "SELECT page_id, pais, dia, total, fuente FROM paginas WHERE page_id = ? AND pais = ? AND dia >= ? "
        "ORDER BY dia",
        (page_id, pais, desde.isoformat()),
    ).fetchall()
    return [FotoPagina(f[0], f[1], date.fromisoformat(f[2]), f[3], f[4]) for f in filas]


def historial(conn: sqlite3.Connection, oferta_id: str, pais: str, desde: date) -> list[Snapshot]:
    filas = conn.execute(
        f"SELECT {', '.join(_COLS)} FROM snapshots "
        "WHERE oferta_id = ? AND pais = ? AND dia >= ? ORDER BY dia",
        (oferta_id, pais, desde.isoformat()),
    ).fetchall()
    return [Snapshot(f[0], f[1], date.fromisoformat(f[2]), *f[3:]) for f in filas]


def registrar_vistos(
    conn: sqlite3.Connection,
    oferta_id: str,
    pais: str,
    library_ids: set[str],
    dia: date,
    *,
    completo: bool,
) -> tuple[int | None, int | None]:
    """(nuevos, parados) frente a la corrida del día anterior más reciente.

    Idea de ``diff_advertiser`` de un repo de referencia (MIT), reescrita sin
    copiar código; ver avisos privados.

    Cada corrida guarda su conjunto completo; repetir el día lo reemplaza.
    Sin corrida previa, (None, None).

    ``completo`` (obligatorio) es ``ResultadoBusqueda.completo``: con False el conjunto es solo una
    muestra (los primeros por impresiones) y compararlo inventaría arranques y paradas, así que no
    se registra nada y se devuelve (None, None) («no medido: muestra parcial»).

    Como los días incompletos no se registran, la corrida anterior puede ser de varios días antes:
    :func:`dia_anterior` da ese día, para decir la ventana («nuevos/parados desde el <día>»).
    """
    if not completo:
        return (None, None)
    d = dia.isoformat()
    with conn:
        conn.execute(
            "DELETE FROM vistos_dia WHERE oferta_id = ? AND pais = ? AND dia = ?",
            (oferta_id, pais, d),
        )
        conn.executemany(
            "INSERT INTO vistos_dia (oferta_id, pais, dia, library_id) VALUES (?, ?, ?, ?)",
            [(oferta_id, pais, d, lid) for lid in library_ids],
        )
        conn.execute(
            "INSERT OR IGNORE INTO corridas (oferta_id, pais, dia) VALUES (?, ?, ?)",
            (oferta_id, pais, d),
        )
        conn.execute(
            "DELETE FROM anuncios_vistos WHERE oferta_id = ? AND pais = ?", (oferta_id, pais)
        )
        conn.execute(
            "INSERT INTO anuncios_vistos (library_id, oferta_id, pais, primera_vez, ultima_vez) "
            "SELECT library_id, oferta_id, pais, MIN(dia), MAX(dia) FROM vistos_dia "
            "WHERE oferta_id = ? AND pais = ? GROUP BY library_id",
            (oferta_id, pais),
        )
        previa = _previa(conn, oferta_id, pais, d)
        if previa is None:
            return (None, None)
        anteriores = {
            r[0]
            for r in conn.execute(
                "SELECT library_id FROM vistos_dia WHERE oferta_id = ? AND pais = ? AND dia = ?",
                (oferta_id, pais, previa),
            )
        }
    return (len(library_ids - anteriores), len(anteriores - library_ids))


def _previa(conn: sqlite3.Connection, oferta_id: str, pais: str, d: str) -> str | None:
    return conn.execute(
        "SELECT MAX(dia) FROM corridas WHERE oferta_id = ? AND pais = ? AND dia < ?",
        (oferta_id, pais, d),
    ).fetchone()[0]


def dia_anterior(conn: sqlite3.Connection, oferta_id: str, pais: str, dia: date) -> date | None:
    """Día de la corrida completa anterior a ``dia`` (la que usa :func:`registrar_vistos` para
    comparar); None si no hay. Sirve para indicar la ventana de nuevos/parados."""
    previa = _previa(conn, oferta_id, pais, dia.isoformat())
    return date.fromisoformat(previa) if previa else None
