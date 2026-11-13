from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ejemplos_caja import CFG, TRM, con_test, g, un_test
from trovefy.caja.calculo import calcular
from trovefy.caja.limites import recomendar
from trovefy.caja.salida import escribir_caja, linea_informe

COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 9, 0, tzinfo=COT)
GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "caja" / "caja-280.md"


def test_caja_md_golden(tmp_path):
    estado = calcular(CFG, [], [])
    ruta = escribir_caja(tmp_path, estado, CFG, recomendar(estado, CFG), TRM, AHORA)
    assert ruta == tmp_path / "wiki" / "analisis" / "caja.md"
    assert ruta.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


def test_linea_informe_formato():
    cfg = replace(CFG, tests=(un_test("cerrado"),))
    estado = calcular(cfg, [], [g(2500)])
    assert linea_informe(estado) == (
        "Caja: tests 255 de 280 (huecos: 8) · reserva 200 · cobrado — · en tránsito —"
    )


def test_linea_informe_decimales_con_coma():
    estado = calcular(CFG, [], [])
    estado = replace(estado, restante={**estado.restante, "tests": 25461})
    assert "tests 254,61 de 280" in linea_informe(estado)


def test_linea_informe_no_medido():
    cfg = con_test("vivo")
    estado = calcular(cfg, [], [])
    assert estado.huecos is None
    assert linea_informe(estado).startswith(
        "Caja: tests no medido (huecos: —) · reserva 200"
    )


def test_caja_md_no_medido_no_pone_cero(tmp_path):
    cfg = con_test("vivo")
    estado = calcular(cfg, [], [])
    ruta = escribir_caja(tmp_path, estado, cfg, recomendar(estado, cfg), None, AHORA)
    texto = ruta.read_text(encoding="utf-8")
    assert "Huecos de test restantes: no medido" in texto
    assert "no medido: sin gasto registrado de p1 CO" in texto
    assert "sin TRM" in texto
