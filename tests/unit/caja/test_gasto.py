from dataclasses import replace

from ejemplos_caja import CFG, con_test, ledger, trm_fijo
from trovefy.caja.calculo import calcular
from trovefy.caja.gasto import gastos_de_tests

CERRADO = con_test("cerrado")
VIVO = con_test("vivo")


def test_gasto_cop_parcial(tmp_path):
    ledger(tmp_path, [["2026-11-11", "act_1", "c1", "83700", "COP"]])
    gs = gastos_de_tests(tmp_path, CERRADO, trm_fijo)
    assert gs[0].usd_centavos == 2539
    assert calcular(CERRADO, [], gs).huecos == 8


def test_gasto_sin_trm_no_medido(tmp_path):
    ledger(tmp_path, [["2026-11-08", "act_1", "c1", "83700", "COP"]])
    e = calcular(CERRADO, [], gastos_de_tests(tmp_path, CERRADO, trm_fijo))
    assert e.huecos is None and any(
        "no medido: sin TRM del 2026-11-08" in m for m in e.motivos
    )


def test_cada_dia_con_su_trm_y_redondeo_al_alza(tmp_path):
    ledger(
        tmp_path,
        [
            ["2026-11-11", "a", "c1", "100", "COP"],
            ["2026-11-12", "a", "c1", "100", "COP"],
        ],
    )
    # 100/3297.07*100 = 3.03 -> 4 por dia (al alza), no 7 por sumar antes de redondear
    assert gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0].usd_centavos == 8


def test_trm_no_vigente_ese_dia_no_convierte(tmp_path):
    from datetime import date

    from ejemplos_caja import TRM

    # trm_de devuelve la «última publicada» (no vigente el 13): no se usa
    ledger(tmp_path, [["2026-11-13", "a", "c1", "100", "COP"]])
    gs = gastos_de_tests(tmp_path, CERRADO, lambda d: TRM)
    assert (
        gs[0].usd_centavos is None
        and "no medido: sin TRM del 2026-11-13" in gs[0].motivo
    )
    assert not TRM.vigente(date(2026, 11, 13))


def test_usd_pasa_tal_cual_y_otra_moneda_no_medida(tmp_path):
    ledger(tmp_path, [["2026-11-11", "a", "c1", "12.34", "USD"]])
    assert gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0].usd_centavos == 1234
    ledger(tmp_path, [["2026-11-11", "a", "c1", "5", "EUR"]])
    g = gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0]
    assert g.usd_centavos is None and "EUR" in g.motivo


def test_sin_tests_es_cero(tmp_path):
    assert gastos_de_tests(tmp_path, CFG, trm_fijo) == []


def test_test_vivo_sin_ledger_no_medido(tmp_path):
    g = gastos_de_tests(tmp_path, VIVO, trm_fijo)[0]
    assert g.usd_centavos is None
    assert (
        g.motivo
        == "no medido: sin gasto registrado de p1 CO (llega con /cierre, Fase 3)"
    )


def test_test_sin_campana_id_no_medido(tmp_path):
    cfg = replace(VIVO, tests=(replace(VIVO.tests[0], campana_id=None),))
    assert gastos_de_tests(tmp_path, cfg, trm_fijo)[0].usd_centavos is None


def test_campana_sin_asignar_cuenta_en_tests(tmp_path):
    ledger(tmp_path, [["2026-11-11", "a", "otra", "12.00", "USD"]])
    gs = gastos_de_tests(tmp_path, CFG, trm_fijo)
    assert (gs[0].producto, gs[0].pais, gs[0].usd_centavos) == (
        "sin-asignar",
        "—",
        1200,
    )
    assert calcular(CFG, [], gs).restante["tests"] == 26800


def test_cop_con_tres_decimales_es_ambiguo(tmp_path):
    ledger(tmp_path, [["2026-11-11", "a", "c1", "83.700", "COP"]])
    g = gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0]
    assert g.usd_centavos is None and "no medido: importe COP ambiguo" in g.motivo


def test_cop_con_dos_decimales_se_lee(tmp_path):
    ledger(tmp_path, [["2026-11-11", "a", "c1", "83700.50", "COP"]])
    assert gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0].usd_centavos == 2539


def test_csv_con_bom_y_filas_vacias(tmp_path):
    d = tmp_path / "ledger" / "gasto"
    d.mkdir(parents=True)
    (d / "x.csv").write_bytes(
        b"\xef\xbb\xbffecha,cuenta,campana,gasto,moneda\n\n2026-11-11,a,c1,12.00,USD\n,,,,\n\n"
    )
    assert gastos_de_tests(tmp_path, CERRADO, trm_fijo)[0].usd_centavos == 1200
