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
