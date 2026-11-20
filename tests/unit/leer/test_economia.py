"""Economía para la lectura (plan 23, Tarea 1): corte de US$ 25, neto y ROAS neto, sin inventar comisiones."""
from decimal import Decimal

from trovefy.leer.economia import corte_oferta_usd, leer_economia, neto_de, roas_neto
from trovefy.vault import frontmatter

from .ejemplos import ECO, ECO_NO, PAIS, P, U, vault_test


def test_corte_oferta_25_como_c1():
    v, fuente = corte_oferta_usd(U)
    assert v == Decimal(25) and "C1 1:24:15" in fuente


def test_leer_economia_sin_ruta(tmp_path):
    v = vault_test(tmp_path, economia=False)
    frontmatter.escribir(v / "productos" / P / "ESCALERA.md",
                         {"tipo": "escalera", "fecha": "2026-11-18", "paises": {PAIS: {
                             "aov_usd": "17.56", "be_usd": None, "cpa_be_usd": None,
                             "be_usd_motivo": "no medido: falta ruta_activa en config/economia.yaml"}}}, "\n")
    e = leer_economia(v, P, PAIS)
    assert e.cpa_be_usd is None and not e.medida
    assert "falta ruta_activa" in e.motivo and e.aov_usd == Decimal("17.56")


def test_leer_economia_con_comisiones(tmp_path):
    e = leer_economia(vault_test(tmp_path), P, PAIS)
    assert e.medida and e.costes_pct == Decimal("0.03") and e.comision_fija_usd == Decimal("0.30")


def test_neto_sin_costes_es_none():
    assert neto_de(Decimal("13.90"), 1, ECO_NO) is None
    assert neto_de(None, 1, ECO) is None


def test_neto_y_roas():
    # 13,90 × 0,97 − 0,30 = 13,183 → 13,18 (a la baja); gasto 5,00 → ROAS 2,63
    n = neto_de(Decimal("13.90"), 1, ECO)
    assert n == Decimal("13.18") and roas_neto(n, 500) == Decimal("2.63")
    assert roas_neto(n, 0) is None and roas_neto(n, None) is None
