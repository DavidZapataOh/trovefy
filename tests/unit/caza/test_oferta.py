from datetime import date

from ayudas import URL_TIENDA, anuncio, destino_impultienda
from trovify.caza.oferta import agrupar, marcar_original


def test_original_y_copias():
    ads = [anuncio("1", "100", date(2026, 8, 27)), anuncio("2", "100", date(2026, 9, 1), "IT"),
           anuncio("3", "200", date(2026, 9, 20)), anuncio("4", "300", date(2026, 9, 25))]
    [o] = agrupar(ads, {URL_TIENDA: destino_impultienda()})
    o = marcar_original(o)
    assert sorted(o.page_ids) == ["100", "200", "300"]
    assert o.original_page_id == "100" and o.origen == "original"


def test_sin_destino_agrupa_por_pagina():
    ofertas = agrupar([anuncio("1", "100", date(2026, 9, 1), destino=None)], {})
    assert ofertas[0].clave == "pagina:100" and ofertas[0].destino is None


def test_empate_gana_mas_paises():
    ads = [anuncio("1", "100", date(2026, 9, 1), "RO"), anuncio("2", "200", date(2026, 9, 1), "RO"),
           anuncio("3", "200", date(2026, 9, 2), "IT")]
    o = marcar_original(agrupar(ads, {URL_TIENDA: destino_impultienda()})[0])
    assert o.original_page_id == "200"


def test_una_sola_pagina_desconocido():
    o = marcar_original(agrupar([anuncio("1", "100", date(2026, 9, 1))], {URL_TIENDA: destino_impultienda()})[0])
    assert o.origen == "desconocido" and o.original_page_id is None


def test_destino_no_medido_cae_a_la_pagina():
    from dataclasses import replace

    d = replace(destino_impultienda(), estado="no_medido", checkout=None, gateway=None, url_final=None)
    ofertas = agrupar(
        [anuncio("1", "100", date(2026, 9, 1), destino=None), anuncio("2", "100", date(2026, 9, 2)),
         anuncio("3", "200", date(2026, 9, 2))],
        {URL_TIENDA: d},
    )
    assert [o.clave for o in ofertas] == ["pagina:100", "pagina:200"]
    assert len(ofertas[0].anuncios) == 2 and ofertas[0].destino is None
