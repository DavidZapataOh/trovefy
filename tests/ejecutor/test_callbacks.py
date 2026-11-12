from types import SimpleNamespace as NS

import pytest
from trovefy_ejecutor.callbacks import (
    compactar,
    expandir,
    firmar,
    motivo_rechazo,
    verificar,
)

K = b"k" * 32
E = NS(user_id=42, chat_id=42)


def test_formato_y_longitud():
    d = firmar("P-20261112-004", "A", 42, K)
    assert d.startswith("v1|P20261112004|A|") and len(d.split("|")[3]) == 10 and len(d.encode()) <= 64
    assert expandir(compactar("P-20261112-004")) == "P-20261112-004"
    assert expandir(compactar("Q-20261112-235959")) == "Q-20261112-235959"
    assert len(firmar("Q-20261112-235959", "R", -1001234567890, K).encode()) <= 64


def test_valido():
    assert verificar(firmar("P-20261112-004", "R", 42, K), 42, 42, E, K) == ("P-20261112-004", "R")
    assert motivo_rechazo(firmar("S-20261112-010203", "A", 42, K), 42, 42, E, K) is None


def test_rechaza_manipulaciones():
    d = firmar("P-20261112-004", "R", 42, K)
    v, i, a, h = d.split("|")
    casos = {
        f"{v}|{i}|A|{h}": "firma", f"{v}|P20261112005|{a}|{h}": "firma", f"v2|{i}|{a}|{h}": "version",
        f"{v}|{i}|X|{h}": "accion", "basura": "formato", d + "x" * 40: "largo",
        f"{v}|P2026111200٤|{a}|{h}": "formato", f"{v}|{i}|{a}|{h[:9]}é": "firma",
    }
    for data, motivo in casos.items():
        assert verificar(data, 42, 42, E, K) is None
        assert motivo_rechazo(data, 42, 42, E, K) == motivo


def test_reenvio_a_otro_chat():
    d = firmar("P-20261112-004", "A", 42, K)
    assert motivo_rechazo(d, 43, 42, NS(user_id=42, chat_id=43), K) == "firma"


def test_usuario_o_chat_ajeno_y_sin_emparejar():
    d = firmar("P-20261112-004", "A", 42, K)
    assert motivo_rechazo(d, 42, 99, E, K) == "usuario_ajeno"
    assert motivo_rechazo(d, -100, 42, E, K) == "chat_ajeno"
    assert motivo_rechazo(d, 42, 42, None, K) == "sin_emparejar"


def test_clave_vacia_e_ids_invalidos():
    for f in (
        lambda: firmar("P-20261112-004", "A", 42, b""),
        lambda: verificar("x", 42, 42, E, b""),
        lambda: motivo_rechazo("x", 42, 42, E, b""),
    ):
        with pytest.raises(ValueError):
            f()
    for malo in ("P-2026111-004", "P-20261112-0041", "X-20261112-004", "P-20261112-004\n", "Q-20261112-004"):
        with pytest.raises(ValueError):
            compactar(malo)
    with pytest.raises(ValueError):
        firmar("P-20261112-004", "X", 42, K)
    with pytest.raises(ValueError):
        expandir("P2026111")
