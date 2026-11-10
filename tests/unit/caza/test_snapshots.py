from datetime import date

from trovify.caza.snapshots import Snapshot, abrir, guardar, historial, registrar_vistos


def test_un_punto_por_dia(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    guardar(c, Snapshot("o-1", "RO", date(2026, 11, 10), 20, 20, 15, 16, None, None, None, "playwright"))
    guardar(c, Snapshot("o-1", "RO", date(2026, 11, 10), 22, 22, 15, 16, None, None, None, "playwright"))
    h = historial(c, "o-1", "RO", date(2026, 11, 1))
    assert len(h) == 1 and h[0].total == 22 and h[0].alcance_ue is None

def test_nuevos_y_parados(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    assert registrar_vistos(c, "o-1", "RO", {"a", "b", "c"}, date(2026, 11, 10)) == (None, None)
    assert registrar_vistos(c, "o-1", "RO", {"b", "c", "d", "e"}, date(2026, 11, 11)) == (2, 1)


def test_dia_vacio_es_una_corrida(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    assert registrar_vistos(c, "o", "RO", {"a", "b", "c"}, date(2026, 11, 11)) == (None, None)
    assert registrar_vistos(c, "o", "RO", set(), date(2026, 11, 12)) == (0, 3)
    assert registrar_vistos(c, "o", "RO", set(), date(2026, 11, 13)) == (0, 0)


def test_primera_corrida_vacia_no_es_primera_vez(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    assert registrar_vistos(c, "o", "RO", set(), date(2026, 11, 10)) == (None, None)
    assert registrar_vistos(c, "o", "RO", {"a", "b"}, date(2026, 11, 11)) == (2, 0)


def test_repetir_el_dia_con_conjunto_menor(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    registrar_vistos(c, "o", "RO", {"a", "b", "c"}, date(2026, 11, 10))
    registrar_vistos(c, "o", "RO", {"a", "b", "c", "d"}, date(2026, 11, 11))
    assert registrar_vistos(c, "o", "RO", {"a"}, date(2026, 11, 11)) == (0, 2)
    filas = dict(c.execute("SELECT library_id, ultima_vez FROM anuncios_vistos").fetchall())
    assert filas["a"] == "2026-11-11"
    assert filas["b"] == "2026-11-10" and filas["c"] == "2026-11-10"
    assert "d" not in filas


def test_none_es_null_en_sql(tmp_path):
    c = abrir(tmp_path / "s.sqlite")
    guardar(c, Snapshot("o", "RO", date(2026, 11, 10), None, None, None, None, None, None, None, "x"))
    fila = c.execute("SELECT total, activos, c7, c8, nuevos, parados, alcance_ue FROM snapshots").fetchone()
    assert fila == (None,) * 7
