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
    assert len(ofertas[0].anuncios) == 2
    # se conserva el destino no medido para que el filtro dé su motivo
    assert ofertas[0].destino.estado == "no_medido" and ofertas[1].destino.estado == "no_medido"


def _d(url, **kw):
    from dataclasses import replace

    return replace(destino_impultienda(), url_anuncio=url, url_final=url, **kw)


def test_destino_determinista_con_varios_destinos():
    u1, u2, u3 = "https://x.com/a", "https://x.com/b", "https://x.com/c"
    ds = {
        u1: _d(u1, precio=None, moneda=None, cloaker=False),
        u2: _d(u2, precio=20.0, moneda="EUR", cloaker=True),
        u3: _d(u3, precio=12.0, moneda="EUR", cloaker=False),
    }
    ads = [anuncio("1", "1", date(2026, 9, 1), destino=u1), anuncio("2", "2", date(2026, 9, 2), destino=u2),
           anuncio("3", "3", date(2026, 9, 3), destino=u3)]
    resultados = []
    for orden in (ads, list(reversed(ads))):
        [o] = agrupar(orden, ds)
        resultados.append(o)
    a, b = resultados
    assert a.clave == b.clave == "impultienda:a"
    assert a.destino == b.destino and a.destinos == b.destinos
    assert len(a.destinos) == 3
    assert a.destino.cloaker is True and a.destino.precio == 12.0
    assert a.destino.url_anuncio == u2  # el primer modelable por fecha, no el u1 sin precio


def test_destino_primero_por_fecha_si_ninguno_modelable():
    u1, u2 = "https://x.com/a", "https://x.com/b"
    ds = {u1: _d(u1, precio=None), u2: _d(u2, precio=None)}
    ads = [anuncio("2", "2", date(2026, 9, 5), destino=u2), anuncio("1", "1", date(2026, 9, 1), destino=u1)]
    [o] = agrupar(ads, ds)
    assert o.destino.url_anuncio == u1


def test_precio_explicito_gana_a_moneda_ambigua():
    u1, u2 = "https://x.com/a", "https://x.com/b"
    ds = {u1: _d(u1, precio=5.0, moneda=None), u2: _d(u2, precio=30.0, moneda="EUR")}
    [o] = agrupar([anuncio("1", "1", date(2026, 9, 1), destino=u1), anuncio("2", "2", date(2026, 9, 2), destino=u2)], ds)
    assert (o.destino.precio, o.destino.moneda) == (30.0, "EUR")


def test_precio_reemplazado_quita_el_motivo_ambiguo():
    u1, u2 = "https://x.com/a", "https://x.com/b"
    d1 = _d(u1, precio=5.0, moneda=None)
    d1.motivo = "no medido: símbolo $ ambiguo"
    ds = {u1: d1, u2: _d(u2, precio=30.0, moneda="EUR")}
    [o] = agrupar([anuncio("1", "1", date(2026, 9, 1), destino=u1), anuncio("2", "2", date(2026, 9, 2), destino=u2)], ds)
    assert (o.destino.precio, o.destino.moneda) == (30.0, "EUR")
    assert "ambiguo" not in (o.destino.motivo or "")


def test_precio_en_la_moneda_del_pais_de_los_anuncios():
    from trovify.config.mercados import Mercado
    u1 = "https://x.com/a"
    d = _d(u1, precio=29.0, moneda="EUR")
    d.precios = [(29.0, "EUR"), (120.0, "RON")]
    ads = [anuncio("1", "1", date(2026, 9, 1), "RO", destino=u1), anuncio("2", "1", date(2026, 9, 2), "RO", destino=u1)]
    ro = Mercado("RO", "ro", "RON", "Europe/Bucharest", (11.9, 15.9), None, "candidato")
    [o] = agrupar(ads, {u1: d}, {"RO": ro})
    assert (o.destino.precio, o.destino.moneda) == (120.0, "RON")
    [o] = agrupar(ads, {u1: d})
    assert (o.destino.precio, o.destino.moneda) == (29.0, "EUR")
