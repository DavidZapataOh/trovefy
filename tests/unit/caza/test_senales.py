import pathlib
from dataclasses import replace
from datetime import date, timedelta

import pytest
from ayudas import URL_TIENDA, anuncio, destino_impultienda
from trovefy.caza.oferta import agrupar
from trovefy.caza.senales import Medida, calcular_senales
from trovefy.caza.snapshots import Snapshot
from trovefy.config.mercados import cargar as cargar_mercados
from trovefy.config.umbrales import cargar

HOY = date(2026, 11, 10)
RAIZ = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config"
U = cargar(RAIZ / "umbrales.yaml")
M = cargar_mercados(RAIZ / "mercados.yaml")
D = destino_impultienda()


def oferta_con(edades, pais="RO", activo=True):
    ads = [anuncio(str(i), "100", HOY - timedelta(days=e), pais, activo=activo) for i, e in enumerate(edades)]
    return agrupar(ads, {URL_TIENDA: D})[0]


def calc(o, pais="RO", historial=(), inactivos=None, total_aprox=None, **kw):
    return calcular_senales(o, pais, HOY, list(historial), inactivos, total_aprox, umbrales=U, **kw)


def test_medida_sin_valor_exige_motivo():
    with pytest.raises(ValueError):
        Medida(None)


def test_cohortes_y_supervivencia():
    s = calc(oferta_con([30, 20, 9, 8, 7, 3, 1, 0]))
    assert s.c8.valor == 4 and s.c7.valor == 5 and s.supervivencia.valor == 5 / 8
    assert s.edad_max_dias.valor == 30 and s.escalonado_semanas.valor >= 3
    assert s.c8.suelo is False and s.total.valor == 8


def test_filtra_por_pais_y_all():
    ads = [anuncio("1", "100", HOY - timedelta(days=10), "RO"), anuncio("2", "100", HOY - timedelta(days=10), "IT")]
    o = agrupar(ads, {URL_TIENDA: D})[0]
    assert calc(o, "RO").c8.valor == 1
    assert calc(o, "ALL").c8.valor == 2


def test_crecimiento_no_medido_en_la_primera_caza():
    s = calc(oferta_con([10, 9]))
    assert s.crecimiento_7d.valor is None and "primera caza" in s.crecimiento_7d.motivo
    assert s.alcance_ue.valor is None and s.vida_mediana_dias.valor is None
    assert s.nuevos.valor is None and "primera caza" in s.nuevos.motivo


def snap(o, dias, activos):
    return Snapshot(o.oferta_id, "RO", HOY - timedelta(days=dias), activos, activos, 8, 8, None, None, None, "playwright")


def test_crecimiento_con_historial():
    o = oferta_con([20] * 13)
    s = calc(o, historial=[snap(o, 7, 10)])
    assert s.crecimiento_7d.valor == 0.3 and "acelerando" in s.banderas


def test_cayendo_y_foto_fuera_de_ventana():
    o = oferta_con([20] * 7)
    assert "cayendo" in calc(o, historial=[snap(o, 6, 10)]).banderas
    assert calc(o, historial=[snap(o, 3, 10)]).crecimiento_7d.valor is None
    assert calc(o, historial=[snap(o, 9, 10)]).crecimiento_7d.valor is None


def test_crecimiento_foto_con_cero_activos_no_medido():
    o = oferta_con([20] * 3)
    assert calc(o, historial=[snap(o, 7, 0)]).crecimiento_7d.valor is None


def test_c8_es_suelo_si_hay_tope():
    s = calc(oferta_con([20] * 60), total_aprox=1700)
    assert s.c8.valor == 60 and s.c8.suelo is True and s.c7.suelo and s.total.suelo


def test_suelo_si_busqueda_incompleta_aunque_no_haya_total():
    o = oferta_con([20] * 5)
    assert calc(o, completo=False).c8.suelo is True
    assert calc(o, completo=True).c8.suelo is False
    assert calc(o, total_aprox=5).c8.suelo is False


def test_crecimiento_no_medido_con_muestra_parcial():
    o = oferta_con([20] * 13)
    s = calc(o, historial=[snap(o, 7, 10)], completo=False)
    assert s.crecimiento_7d.valor is None and "parcial" in s.crecimiento_7d.motivo


def test_vida_mediana():
    o = oferta_con([20])
    ini = date(2026, 9, 1)
    inac = [replace(anuncio(str(i), "100", ini, activo=False), fin=ini + timedelta(days=d)) for i, d in enumerate([2, 6, 30])]
    assert calc(o, inactivos=inac).vida_mediana_dias.valor == 6
    assert calc(o, inactivos=[]).vida_mediana_dias.valor is None


def test_duplicacion():
    ads = [replace(anuncio(str(i), "100", HOY - timedelta(days=10)), collation_count=c) for i, c in enumerate([3, 1, 5])]
    ads.append(replace(anuncio("n", "100", HOY - timedelta(days=2)), collation_count=9))  # fuera de C7
    o = agrupar(ads, {URL_TIENDA: D})[0]
    assert calc(o).duplicacion.valor == 6
    assert calc(oferta_con([10])).duplicacion.valor is None


def test_expansion_cuenta_paises_idiomas_y_paginas():
    ro = replace(anuncio("1", "100", HOY - timedelta(days=9), "RO"), texto="Fișe de terapie gata de printat, acces imediat după plată")
    it = replace(anuncio("2", "200", HOY - timedelta(days=9), "IT"), texto="Schede pronte per il sostegno scolastico, accesso immediato")
    o = agrupar([ro, it], {URL_TIENDA: D})[0]
    s = calc(o, mercados=M)
    assert sorted(s.idiomas) == ["it", "ro"] and s.expansion.valor == 2 + 2 + 2
    sin = calc(o).expansion
    assert sin.valor == 4 and sin.suelo is True  # países + páginas, sin idiomas
    assert s.expansion.suelo is False


def test_alcance_ue_nunca_medido():
    assert "ads_archive" in calc(oferta_con([9])).alcance_ue.motivo


def test_nuevos_y_parados_con_ventana():
    o = oferta_con([9])
    s = calc(o, vistos=(4, 2, date(2026, 11, 3)), completo=True)
    assert s.nuevos.valor == 4 and s.parados.valor == 2 and "desde 2026-11-03" in s.nuevos.motivo


def test_nuevos_no_se_calculan_de_una_muestra_parcial():
    s = calc(oferta_con([9]), vistos=(4, 2, date(2026, 11, 3)), completo=False)
    assert s.nuevos.valor is None and "parcial" in s.nuevos.motivo


def test_moneda_distinta():
    o = oferta_con([9])  # destino en EUR, Rumanía usa RON
    assert "moneda_distinta" in calc(o, mercados=M).banderas
    o2 = agrupar([anuncio("1", "100", HOY, "RO")], {URL_TIENDA: replace(D, moneda="RON")})[0]
    assert "moneda_distinta" not in calc(o2, mercados=M).banderas
    o3 = agrupar([anuncio("1", "100", HOY, "RO")], {URL_TIENDA: replace(D, moneda=None)})[0]
    assert "moneda_distinta" not in calc(o3, mercados=M).banderas
    assert "moneda_distinta" not in calc(o).banderas


def test_supervivencia_parcial_con_total_meta_es_cota_c7_sobre_total():
    s = calc(oferta_con([20, 20, 3, 3]), completo=False, total_meta=10)
    assert s.supervivencia.valor is None and "≥ 0,20" in s.supervivencia.motivo


def test_supervivencia_parcial_sin_total_meta_no_da_numero():
    s = calc(oferta_con([20, 20, 3, 3]), completo=False, total_aprox=100)
    assert s.supervivencia.valor is None and s.supervivencia.motivo == "no medido: muestra parcial"


def snap_total(o, dias, total, activos=None):
    return Snapshot(o.oferta_id, "RO", HOY - timedelta(days=dias), total, activos, None, None, None, None, None, "x")


def test_crecimiento_lectura_parcial_con_total_meta():
    o = oferta_con([20] * 30)
    s = calc(o, historial=[snap_total(o, 7, 180)], completo=False, total_meta=234)
    assert s.crecimiento_7d.valor == pytest.approx(0.3) and "acelerando" in s.banderas
    assert s.total.valor == 234 and s.total.suelo is False and s.c8.suelo is True


def test_crecimiento_lectura_parcial_sin_total_meta_no_medido():
    o = oferta_con([20] * 30)
    s = calc(o, historial=[snap_total(o, 7, 180)], completo=False, total_aprox=234)
    assert s.crecimiento_7d.valor is None and "parcial" in s.crecimiento_7d.motivo


def test_crecimiento_lectura_completa_usa_cargados_y_foto_sin_cifras_no_medido():
    o = oferta_con([20] * 13)
    assert calc(o, historial=[snap_total(o, 7, 10)], completo=True).crecimiento_7d.valor == 0.3
    assert calc(o, historial=[snap_total(o, 7, None)], completo=True).crecimiento_7d.valor is None


def test_duplicacion_con_collation_parcial_es_suelo():
    ads = [replace(anuncio("1", "100", HOY - timedelta(days=10)), collation_count=3),
           anuncio("2", "100", HOY - timedelta(days=10))]
    o = agrupar(ads, {URL_TIENDA: D})[0]
    d = calc(o).duplicacion
    assert d.valor == 2 and d.suelo is True


def test_nuevos_sin_corrida_completa_previa():
    s = calc(oferta_con([9]), vistos=(None, None, None), completo=True)
    assert "sin corrida completa previa" in s.nuevos.motivo


def test_crecimiento_foto_sin_total_exacto_no_medido_aunque_tenga_activos():
    o = oferta_con([20] * 13)
    m = calc(o, historial=[snap_total(o, 7, None, activos=10)], completo=True).crecimiento_7d
    assert m.valor is None and "no tiene total exacto" in m.motivo
