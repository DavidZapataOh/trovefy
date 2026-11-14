"""Autopsia de 8 ejes: nota ponderada, ejes flojos y tercera señal de R16."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.economia.config import PLANTILLA, cargar_texto
from trovefy.modelar.autopsia import (
    EJES,
    NOMBRES,
    EjeValorado,
    puntuar,
    senal_se_puede_mejorar,
    vende_por_presupuesto,
)
from trovefy.modelar.esquema import cargar_modelado

DEMO = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "modelar" / "modelar-demo.yaml"
REGLAS = cargar_texto(PLANTILLA.read_text(encoding="utf-8")).autopsia
PESOS = REGLAS.pesos
ORIGINAL = {"resultado_sonado": 8, "probabilidad_percibida": 5, "tiempo": 6, "esfuerzo": 7, "avatar": 6,
            "mecanismo": 4, "precio": 5, "prueba_garantia": 3}
NUESTRA = {"resultado_sonado": 8, "probabilidad_percibida": 7, "tiempo": 7, "esfuerzo": 8, "avatar": 7,
           "mecanismo": 7, "precio": 7, "prueba_garantia": 8}


def ejes(**notas):
    return {eje: EjeValorado(eje, nota, f"motivo de {eje}") for eje, nota in notas.items()}


def test_ejes_y_nombres():
    assert EJES == ("resultado_sonado", "probabilidad_percibida", "tiempo", "esfuerzo", "avatar", "mecanismo",
                    "precio", "prueba_garantia")
    assert NOMBRES["prueba_garantia"] == "Prueba y garantía" and set(NOMBRES) == set(EJES)


def test_nota_ponderada_y_flojos():
    a = puntuar(ejes(**ORIGINAL), PESOS)
    assert a.nota == Decimal("56.5") and a.cobertura == 100  # 12+10+6+10,5+6+4+5+3
    # empate a 5 entre probabilidad_percibida (peso 20) y precio (peso 10): gana el de mayor peso
    assert a.flojos == ("prueba_garantia", "mecanismo", "probabilidad_percibida")
    assert a.desglose[0] == ("resultado_sonado", 15, 8) and len(a.desglose) == 8


def test_nuestra_da_74():
    assert puntuar(ejes(**NUESTRA), PESOS).nota == Decimal("74.0")


def test_no_valorado_renormaliza():
    a = puntuar(ejes(**{**ORIGINAL, "precio": None}), PESOS)
    assert a.cobertura == 90
    assert a.nota == Decimal("57.2")  # 51,5 / 90 × 100 = 57,22…
    assert "precio" not in a.flojos
    assert ("precio", 10, None) in a.desglose


def test_eje_ausente_cuenta_como_no_valorado():
    notas = {k: v for k, v in ORIGINAL.items() if k != "tiempo"}
    assert puntuar(ejes(**notas), PESOS).cobertura == 90


def test_sin_nada_valorado():
    a = puntuar(ejes(**{e: None for e in EJES}), PESOS)
    assert a.nota is None and a.cobertura == 0 and a.flojos == ()


def test_cobertura_baja_senal_no_medida():
    parcial = {**ORIGINAL, "probabilidad_percibida": None, "esfuerzo": None, "precio": None}  # 100-20-15-10 = 55
    e_orig, e_nuestra = ejes(**parcial), ejes(**NUESTRA)
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), puntuar(e_nuestra, PESOS), e_orig, e_nuestra,
                                           REGLAS)
    assert senal is None
    assert motivo.startswith("no medida: la autopsia") and "55 de 100 puntos (hacen falta 70)" in motivo


def test_senal_si_con_mejora_suficiente():
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**NUESTRA)
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), puntuar(e_nuestra, PESOS), e_orig, e_nuestra,
                                           REGLAS)
    assert senal is True
    assert motivo.startswith("sí: +17,5 puntos y mejora sus 3 ejes más flojos")


def test_senal_no_si_un_eje_flojo_no_mejora():
    nuestra = {**NUESTRA, "mecanismo": 4, "resultado_sonado": 10}
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**nuestra)
    a_nuestra = puntuar(e_nuestra, PESOS)
    assert a_nuestra.nota - Decimal("56.5") >= REGLAS.mejora_min_puntos
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), a_nuestra, e_orig, e_nuestra, REGLAS)
    assert senal is False and "mecanismo" in motivo.lower()


def test_senal_no_si_faltan_puntos():
    nuestra = {**ORIGINAL, "prueba_garantia": 5, "mecanismo": 6, "probabilidad_percibida": 7}
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**nuestra)
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), puntuar(e_nuestra, PESOS), e_orig, e_nuestra,
                                           REGLAS)
    assert senal is False and "+8,0 puntos" in motivo and "hacen falta 10" in motivo


def test_senal_no_si_un_eje_flojo_no_se_valoro_en_la_nuestra():
    nuestra = {**NUESTRA, "mecanismo": None, "resultado_sonado": 10}
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**nuestra)
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), puntuar(e_nuestra, PESOS), e_orig, e_nuestra,
                                           REGLAS)
    assert senal is False and "mecanismo" in motivo.lower()


def test_vende_por_presupuesto_con_58():
    a = puntuar(ejes(**{**ORIGINAL, "mecanismo": 5, "tiempo": 7}), PESOS)
    assert a.nota == Decimal("58.5")
    assert vende_por_presupuesto(a, REGLAS) is True
    assert vende_por_presupuesto(puntuar(ejes(**NUESTRA), PESOS), REGLAS) is False
    assert vende_por_presupuesto(puntuar(ejes(**{e: None for e in EJES}), PESOS), REGLAS) is False


@pytest.mark.parametrize("nota", [11, -1, 7.5, True, "8"])
def test_nota_fuera_de_0_10(nota):
    with pytest.raises(ValueError):
        EjeValorado("precio", nota, "porque sí")


def test_eje_desconocido():
    with pytest.raises(ValueError):
        puntuar({"color": EjeValorado("color", 5, "x")}, PESOS)


# --- ronda de revisión de las tareas 4–5 -----------------------------------------------------------


@pytest.mark.parametrize(("cobertura", "medida"), [(70, True), (69, False)])
def test_cobertura_en_el_limite(cobertura, medida):
    # el plan: «con cobertura < 70 puntos de peso la tercera señal es "no medida"»; la cobertura es entera
    assert REGLAS.cobertura_min == 70
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**NUESTRA)
    original = replace(puntuar(e_orig, PESOS), cobertura=cobertura)
    senal, motivo = senal_se_puede_mejorar(original, puntuar(e_nuestra, PESOS), e_orig, e_nuestra, REGLAS)
    assert (senal is not None) is medida
    if not medida:
        assert "del original cubre 69 de 100" in motivo


def test_solo_la_nuestra_con_cobertura_baja():
    nuestra = {**NUESTRA, "probabilidad_percibida": None, "esfuerzo": None, "precio": None}
    e_orig, e_nuestra = ejes(**ORIGINAL), ejes(**nuestra)
    senal, motivo = senal_se_puede_mejorar(puntuar(e_orig, PESOS), puntuar(e_nuestra, PESOS), e_orig, e_nuestra,
                                           REGLAS)
    assert senal is None and "de la nuestra cubre 55 de 100" in motivo


def test_fixture_da_las_cifras_del_plan():
    m = cargar_modelado(DEMO, "p-0042-kit-demo", "XE", "bg")
    original, nuestra = puntuar(m.ejes_original, PESOS), puntuar(m.ejes_nuestra, PESOS)
    assert (original.nota, nuestra.nota) == (Decimal("56.5"), Decimal("74.0"))
    senal, _ = senal_se_puede_mejorar(original, nuestra, m.ejes_original, m.ejes_nuestra, REGLAS)
    assert senal is True
