import random
from datetime import date

import pytest
from trovefy.caza.presupuesto import ParadaPorErrores, Presupuesto, PresupuestoAgotado


def test_presupuesto_agotado():
    p = Presupuesto(30, 2, 5, dormir=lambda s: None)
    for _ in range(30): p.antes_de_buscar()
    with pytest.raises(PresupuestoAgotado):
        p.antes_de_buscar()
    assert p.usadas == 30

def test_pausa_con_ruido_dentro_del_rango():
    dormidos = []
    p = Presupuesto(30, 2, 5, dormir=dormidos.append, azar=random.Random(1))
    for _ in range(20): p.pausa()
    assert all(2 <= s <= 5 for s in dormidos) and len(set(dormidos)) > 1

def test_esperas_tras_error():
    dormidos = []
    p = Presupuesto(30, 2, 5, dormir=dormidos.append)
    p.tras_error(); p.tras_error()
    assert dormidos == [30, 90]
    with pytest.raises(ParadaPorErrores):
        p.tras_error()

def test_desde_umbrales_vault_temporal(tmp_path):
    (tmp_path / "config").mkdir()
    def u(v):
        return f'  valor: {v}\n  fuente: "t"\n  fecha: "2026-11-10"\n  gana_sobre: "t"\n  regla: R-001\n'
    (tmp_path / "config" / "umbrales.yaml").write_text(
        "caza.max_busquedas_sesion:\n" + u(7) + "caza.pausa_min_s:\n" + u(1.5) + "caza.pausa_max_s:\n" + u(4),
        encoding="utf-8")
    p = Presupuesto.desde_umbrales(tmp_path, hoy=date(2026, 11, 10))
    assert (p.max_busquedas, p.pausa_min_s, p.pausa_max_s) == (7, 1.5, 4)


def _vault(tmp_path, mx, mn, ma):
    (tmp_path / "config").mkdir(exist_ok=True)
    def u(v):
        return f'  valor: {v}\n  fuente: "t"\n  fecha: "2026-11-10"\n  gana_sobre: "t"\n  regla: R-001\n'
    (tmp_path / "config" / "umbrales.yaml").write_text(
        "caza.max_busquedas_sesion:\n" + u(mx) + "caza.pausa_min_s:\n" + u(mn) + "caza.pausa_max_s:\n" + u(ma),
        encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("mx,mn,ma", [(7, 5, 2), (7, -1, 2), (0, 1, 2), (7, 1, -2)])
def test_desde_umbrales_valores_invalidos(tmp_path, mx, mn, ma):
    with pytest.raises(ValueError):
        Presupuesto.desde_umbrales(_vault(tmp_path, mx, mn, ma))


def test_exito_reinicia_errores():
    dormidos = []
    p = Presupuesto(30, 2, 5, dormir=dormidos.append)
    p.tras_error(); p.tras_error(); p.exito()
    p.tras_error()
    assert dormidos == [30, 90, 30]
