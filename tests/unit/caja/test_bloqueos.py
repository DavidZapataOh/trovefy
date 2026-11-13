from dataclasses import replace

import pytest
from ejemplos_caja import CFG, un_test
from trovefy.caja.bloqueos import (
    Veredicto,
    puede_gastar,
    puede_lanzar_test,
    puede_preescalar,
    usd,
)
from trovefy.caja.calculo import EstadoCaja, calcular


def _cfg(vivos=0, cerrados=0, desbloqueada=False, **kw):
    tests = tuple(
        un_test("vivo", campana=f"v{i}", producto=f"v{i}") for i in range(vivos)
    ) + tuple(
        un_test("cerrado", campana=f"c{i}", producto=f"c{i}") for i in range(cerrados)
    )
    return replace(CFG, tests=tests, reserva_desbloqueada=desbloqueada, **kw)


def _estado(cfg, **kw):
    base = EstadoCaja(
        asignado=dict(cfg.sobres),
        gastado={"herramientas": 0, "tests": 0, "reserva": 0},
        comprometido=0,
        restante=dict(cfg.sobres),
        huecos=9,
        huecos_con_prorroga=8,
        vivos=0,
        motivos=(),
    )
    return replace(base, **kw)


def test_usd_formato():
    assert (usd(2500), usd(2539), usd(2550), usd(5), usd(0)) == (
        "25",
        "25,39",
        "25,50",
        "0,05",
        "0",
    )


def test_dos_tests_de_25_caben_en_50():
    cfg = _cfg(vivos=1)
    assert puede_lanzar_test(_estado(cfg), cfg) == Veredicto(
        True, "cabe: 25 + 25 <= 50 de tope diario"
    )


def test_tercer_test_bloqueado():
    cfg = _cfg(vivos=2)
    v = puede_lanzar_test(_estado(cfg), cfg)
    assert not v.permitido and v.motivo == "no cabe: 50 + 25 > 50 de tope diario"


def test_test_cerrado_no_cuenta_en_la_suma_diaria():
    cfg = _cfg(vivos=1, cerrados=3)
    assert puede_lanzar_test(_estado(cfg), cfg).permitido


def test_sin_huecos_no_hay_test():
    cfg = _cfg()
    e = calcular(cfg, [], [])
    e = replace(e, restante={**e.restante, "tests": 2900}, huecos=0)
    v = puede_lanzar_test(e, cfg)
    assert not v.permitido and v.motivo == "0 huecos de test: no hay más tests este mes"


def test_huecos_no_medidos_bloquean():
    cfg = _cfg()
    e = _estado(cfg, huecos=None, motivos=("no medido: sin TRM del 2026-11-08",))
    v = puede_lanzar_test(e, cfg)
    assert not v.permitido and v.motivo == "no medido: sin TRM del 2026-11-08"


@pytest.mark.parametrize("campo", ["comprometido", "restante", "gastado"])
def test_cualquier_none_bloquea_todo(campo):
    cfg = _cfg(desbloqueada=True)
    e = _estado(cfg)
    e = replace(
        e,
        **{
            campo: None
            if campo == "comprometido"
            else {
                **getattr(e, campo),
                "tests": None,
                "reserva": None,
                "herramientas": None,
            }
        },
    )
    for v in (
        puede_lanzar_test(e, cfg),
        puede_preescalar(e, cfg),
        puede_gastar("tests", 100, e),
    ):
        assert not v.permitido and v.motivo.startswith("no medido:")


def test_preescala_adicional_bloqueada():
    cfg = _cfg(vivos=2, desbloqueada=True)
    v = puede_preescalar(_estado(cfg), cfg)
    assert not v.permitido and "50 + 20 > 50" in v.motivo


def test_preescala_permitida():
    cfg = _cfg(vivos=1, desbloqueada=True)
    assert puede_preescalar(_estado(cfg), cfg).permitido


def test_reserva_bloqueada_sin_pre_escala():
    cfg = _cfg(desbloqueada=False)
    v = puede_preescalar(_estado(cfg), cfg)
    assert not v.permitido and "reserva" in v.motivo


def test_preescala_sin_saldo_en_reserva():
    cfg = _cfg(desbloqueada=True)
    e = _estado(cfg, restante={**cfg.sobres, "reserva": 1999})
    assert not puede_preescalar(e, cfg).permitido


def test_puede_gastar_sin_sobre():
    cfg = _cfg()
    e = _estado(cfg, restante={"herramientas": 2000, "tests": 28000, "reserva": 500})
    assert puede_gastar("tests", 1000, e).permitido
    v = puede_gastar("reserva", 1000, e)
    assert not v.permitido and "reserva" in v.motivo and "5" in v.motivo


@pytest.mark.parametrize(
    "sobre,monto", [("cajon", 100), ("tests", -1), ("tests", True), ("tests", 1.5)]
)
def test_puede_gastar_entradas_invalidas(sobre, monto):
    assert not puede_gastar(sobre, monto, _estado(_cfg())).permitido
