import pytest
from trovefy.caja.config import CajaInvalida, cargar_caja, iniciar_caja

PLANTILLA = """\
capital_usd: 500
sobres_usd: {herramientas: 20, tests: 280, reserva: 200}
test: {techo_usd: 30, prorroga_hasta_usd: 55, diario_usd: 25}
prescala_diario_usd: 20
tope_diario_ejecutor_usd: 50
reserva_desbloqueada: false
apimart_aviso_usd: 1.00
cuenta: {id: null, moneda: null}
tests: []
"""


def _vault(tmp_path, texto=PLANTILLA):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "caja.yaml").write_text(texto, encoding="utf-8")
    return tmp_path


def test_plantilla_carga(tmp_path):
    v = tmp_path / "v"
    v.mkdir()
    iniciar_caja(v, None, None)
    c = cargar_caja(v)
    assert c.sobres == {"herramientas": 2000, "tests": 28000, "reserva": 20000}
    assert c.capital == 50000
    assert c.techo_test == 3000
    assert c.prorroga_hasta == 5500
    assert c.tope_diario_ejecutor == 5000
    assert c.apimart_aviso == 100
    assert c.reserva_desbloqueada is False
    assert c.cuenta.id is None and c.tests == ()
    v2 = tmp_path / "v2"
    v2.mkdir()
    iniciar_caja(v2, "act_0000000000000000", "COP")
    c2 = cargar_caja(v2)
    assert (c2.cuenta.id, c2.cuenta.moneda) == ("act_0000000000000000", "COP")


def test_plantilla_sin_cuenta_real():
    from pathlib import Path

    t = (Path(__file__).parents[3] / "templates/cerebro/config/caja.yaml").read_text()
    assert "act_" not in t.replace("`", "")


def test_sobres_no_suman_capital(tmp_path):
    v = _vault(tmp_path, PLANTILLA.replace("tests: 280", "tests: 270"))
    with pytest.raises(CajaInvalida):
        cargar_caja(v)


@pytest.mark.parametrize("malo", ["-5", "20.005"])
def test_importe_negativo_o_tres_decimales(tmp_path, malo):
    v = _vault(
        tmp_path,
        PLANTILLA.replace("prescala_diario_usd: 20", f"prescala_diario_usd: {malo}"),
    )
    with pytest.raises(CajaInvalida):
        cargar_caja(v)


def test_falta_archivo(tmp_path):
    with pytest.raises(FileNotFoundError, match="trovefy caja iniciar"):
        cargar_caja(tmp_path)


def test_iniciar_no_sobrescribe(tmp_path):
    iniciar_caja(tmp_path, None, None)
    with pytest.raises(FileExistsError):
        iniciar_caja(tmp_path, "act_0000000000000000", "COP")


def _con_tests(*items):
    cuerpo = "".join(
        f"  - {{producto: {p}, pais: {c}, campana_id: {i}, estado: vivo, diario_usd: 25}}\n"
        for p, c, i in items
    )
    return PLANTILLA.replace("tests: []\n", "tests:\n" + cuerpo)


def test_campana_id_duplicado_se_rechaza(tmp_path):
    v = _vault(tmp_path, _con_tests(("a", "CO", "c1"), ("b", "MX", "c1")))
    with pytest.raises(CajaInvalida, match="campana_id"):
        cargar_caja(v)


def test_producto_pais_duplicado_se_rechaza(tmp_path):
    v = _vault(tmp_path, _con_tests(("a", "CO", "c1"), ("a", "CO", "c2")))
    with pytest.raises(CajaInvalida, match="producto"):
        cargar_caja(v)


def test_campana_null_repetida_es_valida(tmp_path):
    v = _vault(tmp_path, _con_tests(("a", "CO", "null"), ("b", "CO", "null")))
    assert len(cargar_caja(v).tests) == 2
