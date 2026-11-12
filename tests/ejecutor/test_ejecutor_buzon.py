import json
import os

import pytest
from fabricas import presupuesto
from trovefy_ejecutor.buzon import Buzon
from trovefy_ejecutor.esquema import PropuestaInvalida


def buzon(tmp_path, ahora=10_000.0):
    (tmp_path / "entrada").mkdir(exist_ok=True)
    return Buzon(tmp_path, reloj=lambda: ahora)


def poner(tmp_path, nombre, texto, mtime=1_000.0):
    (tmp_path / "entrada").mkdir(exist_ok=True)
    f = tmp_path / "entrada" / nombre
    f.write_text(texto)
    os.utime(f, (mtime, mtime))
    return f


def test_solo_completos(tmp_path):
    b = buzon(tmp_path)
    poner(tmp_path, ".P-1.json.tmp", "{")
    poner(tmp_path, ".P-0.json", "{}")
    poner(tmp_path, "P-2.json", json.dumps(presupuesto()))
    assert [p.name for p in b.nuevas()] == ["P-2.json"]


def test_json_reciente_se_espera(tmp_path):
    poner(tmp_path, "P-3.json", '{"version": 1,', mtime=9_999.5)
    assert buzon(tmp_path).nuevas() == []


@pytest.mark.parametrize(
    "texto,motivo",
    [
        ('{"version": 1, "id": "P-2026', "JSON"),
        ('{"gasto": NaN}', "NaN"),
        ("[1, 2]", "objeto"),
        ("x" * 70_000, "64 KiB"),
    ],
)
def test_json_truncado_se_rechaza(tmp_path, texto, motivo):
    f = poner(tmp_path, "P-4.json", texto)
    with pytest.raises(PropuestaInvalida, match=motivo):
        buzon(tmp_path).leer(f)


def test_claves_duplicadas_se_rechazan(tmp_path):
    f = poner(tmp_path, "P-7.json", '{"id": "P-20261112-004", "id": "P-20261112-005"}')
    with pytest.raises(PropuestaInvalida, match="duplicad"):
        buzon(tmp_path).leer(f)


def test_enlace_simbolico_se_rechaza(tmp_path):
    secreto = tmp_path / "secreto.env"
    secreto.write_text("TOKEN=x")
    (tmp_path / "entrada").mkdir()
    (tmp_path / "entrada/P-5.json").symlink_to(secreto)
    b = buzon(tmp_path)
    assert b.nuevas() == []
    with pytest.raises(PropuestaInvalida, match="enlace"):
        b.leer(tmp_path / "entrada/P-5.json")


def test_procesar_y_estado(tmp_path):
    b = buzon(tmp_path)
    f = poner(tmp_path, "P-6.json", json.dumps(presupuesto()))
    destino = b.procesar(
        f, {"estado": "rechazada", "motivo": "esquema: campo no permitido: color"}
    )
    assert destino.parent.name == "procesadas" and not f.exists()
    assert (
        json.loads((destino.parent / "P-6.resultado.json").read_text())["estado"]
        == "rechazada"
    )
    otro = poner(tmp_path, "P-6.json", "{}")
    assert b.procesar(otro, {}).name == "P-6-2.json"
    e = b.escribir_estado("latido", {"ts": "2026-11-12T19:10:00Z"})
    assert json.loads(e.read_text())["ts"] and oct(e.stat().st_mode & 0o777) == "0o640"
    with pytest.raises(ValueError):
        b.escribir_estado("../fuera", {})
