import pytest
from trovefy.producto.rutas import P_ID, PIEZA, Pieza, entregable, pieza

P = "p-0042-respira"


def test_rutas_de_pieza(tmp_path):
    v = tmp_path
    base = v / "productos" / P / "entregable"
    assert pieza(v, P, "u1") == Pieza("u1", "upsell", base / "upsells" / "u1")
    assert pieza(v, P, "u1").raiz == v / "productos/p-0042-respira/entregable/upsells/u1"
    assert pieza(v, P, "principal") == Pieza("principal", "principal", base)
    assert pieza(v, P, "bono-2") == Pieza("bono-2", "bono", base / "bonos" / "bono-2")
    assert pieza(v, P, "bump") == Pieza("bump", "bump", base / "bump")
    assert pieza(v, P, "downsell") == Pieza("downsell", "upsell", base / "upsells" / "downsell")
    assert pieza(v, P, "u3").raiz == base / "upsells" / "u3"
    assert entregable(v, P) == base


@pytest.mark.parametrize(("p_id", "pieza_id"), [
    (P, "../x"), (P, "bono-0"), ("P-1", "principal"), (P, "down"), (P, "u4"), (P, "principal\n"),
    ("p-0042-respira/../x", "principal"), ("p-0042-respira\n", "principal"), (P, ""), (P, "bono-10"),
])
def test_pieza_o_producto_invalido(tmp_path, p_id, pieza_id):
    with pytest.raises(ValueError):
        pieza(tmp_path, p_id, pieza_id)


def test_patrones():
    assert P_ID.fullmatch(P) and not P_ID.fullmatch("P-1")
    for ok in ("principal", "bono-1", "bono-9", "bump", "u1", "u2", "u3", "downsell"):
        assert PIEZA.fullmatch(ok), ok
    for malo in ("down", "bono-0", "u0", "bonos"):
        assert not PIEZA.fullmatch(malo), malo
