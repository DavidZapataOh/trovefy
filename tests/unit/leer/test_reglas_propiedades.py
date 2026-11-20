"""Propiedades de las reglas, con una rejilla de casos (sin dependencias nuevas)."""
from decimal import Decimal
from itertools import product

from trovefy.leer.reglas import veredicto_conjunto, veredicto_oferta

from .ejemplos import ECO, U, conj, of

GASTOS = ("0", "2.99", "3", "10", "24.99", "25", "60", "100")
VENTAS = (0, 1, 3, 8)
HORAS = (1, 24, 71, 72, 100, 200)
BRUTOS = ("10", "40", "120")


def test_nunca_muerto_con_ventas_antes_de_72h_ni_intradia():
    for g, v, h, b, intra in product(GASTOS, VENTAS[1:], HORAS, BRUTOS, (True, False)):
        e, _, _ = veredicto_oferta(of(g, ventas=v, bruto=b, horas=h), ECO, U, intradia=intra, dias_con_ventas=1)
        if h < 72 or intra:
            assert e != "muerto_con_ventas", (g, v, h, b, intra)


def test_nunca_corte_sin_ventas_por_debajo_de_25():
    for g, h, intra in product(GASTOS, HORAS, (True, False)):
        e, cortes, _ = veredicto_oferta(of(g, ventas=0, horas=h), ECO, U, intradia=intra)
        if Decimal(g) < 25:
            assert e != "muerto_sin_ventas", (g, h)
        else:
            assert e == "muerto_sin_ventas" and cortes[0].prioridad == "alta"


def test_conjunto_con_ventas_nunca_apagar():
    for g, pi, cpc, fiable, v in product(GASTOS, (0, 1, 5), ("0.10", "0.70", "2"), (True, False), (1, 2)):
        c = conj(gasto=g, visitas=20, pi=pi, cpc=cpc, ventas=v)
        assert veredicto_conjunto(c, U, fiable).estado == "MANTENER"


def test_menos_de_3_usd_nunca_apagar():
    for g, pi, cpc in product(("0", "1", "2.99"), (0, 1), ("0.10", "5")):
        assert veredicto_conjunto(conj(gasto=g, visitas=20, pi=pi, cpc=cpc), U, True).estado == "ESPERAR"
