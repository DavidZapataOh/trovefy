"""Surf ×2 cada 2 h y vuelta a la base a las 23:00, como los vídeos (plan 23, Tarea 3b)."""
from trovefy.leer.modelo import Dia
from trovefy.leer.surf import Limites, es_hora_de_base, veredicto_surf, vuelta_a_la_base

from .ejemplos import BASE, ECO, ECO_NO, U, conj


def _c(gasto_hoy="5", ventas_hoy=1, bruto_hoy="13.90", presupuesto=BASE, **kw):
    from decimal import Decimal

    return conj(gasto="10", presupuesto=presupuesto,
                hoy=Dia(int(Decimal(gasto_hoy) * 100), ventas_hoy, Decimal(bruto_hoy)), **kw)


def test_roas_2_con_venta_nueva_duplica():  # US$ 5 → 10 (S1 10:27)
    s, nota = veredicto_surf(_c(), 0, ECO, U, BASE)
    assert s.de_minima == 20000 and s.a_minima == 40000 and "S1 10:27" in s.regla and nota is None


def test_roas_2_sin_venta_nueva_no_toca():  # T3 12:35
    s, nota = veredicto_surf(_c(), 1, ECO, U, BASE)
    assert s is None and "no se toca" in nota


def test_trusa_3_04_no_se_toca_sin_venta_nueva():  # L2 21:25: «el ABO G1R va a 3,04 y no se toca»
    s, _ = veredicto_surf(_c(gasto_hoy="10", ventas_hoy=2, bruto_hoy="31.40"), 2, ECO, U, BASE)
    assert s is None


def test_roas_1_75_baja_50():  # S2 14:10
    s, _ = veredicto_surf(_c(gasto_hoy="10", ventas_hoy=1, bruto_hoy="13.90", presupuesto=80000), 1, ECO, U, BASE)
    assert s.a_minima == 40000 and "S2 14:10" in s.regla


def test_no_baja_de_la_base():
    s, _ = veredicto_surf(_c(gasto_hoy="10", ventas_hoy=0, bruto_hoy="0", presupuesto=30000), 0, ECO, U, BASE)
    assert s.a_minima == BASE
    s, _ = veredicto_surf(_c(gasto_hoy="10", ventas_hoy=0, bruto_hoy="0", presupuesto=BASE), 0, ECO, U, BASE)
    assert s is None


def test_base_a_las_23_del_pais():
    conjuntos = [_c(presupuesto=40000, sid="1"), _c(presupuesto=BASE, sid="2"), _c(presupuesto=80000, sid="3",
                                                                                  estado="PAUSED")]
    cambios = vuelta_a_la_base(conjuntos, BASE)
    assert [(s.conjunto_id, s.a_minima) for s in cambios] == [("1", BASE)]
    assert es_hora_de_base(23, U) and not es_hora_de_base(22, U)


def test_roas_no_medido_no_surfea():
    s, nota = veredicto_surf(_c(), 0, ECO_NO, U, BASE)
    assert s is None and "surf no medido" in nota


def test_doble_sobre_limite_del_ejecutor_avisa():
    s, nota = veredicto_surf(_c(presupuesto=30000), 0, ECO, U, BASE, limites=Limites(max_presupuesto_conjunto=40000))
    assert s is None and "max_presupuesto_conjunto" in nota and "limite_ejecutor" in nota
    s, nota = veredicto_surf(_c(), 0, ECO, U, BASE, limites=Limites(paso_max_pct=50))
    assert s is None and "paso_max_pct" in nota


def test_nunca_por_encima_del_techo():
    s, nota = veredicto_surf(_c(presupuesto=300000), 0, ECO, U, BASE, spend_cap=400000)
    assert s is None and "techo" in nota
