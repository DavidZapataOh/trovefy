import json
import pathlib
from datetime import UTC, date, datetime

import pytest
from trovify.caza.parser import (
    FormatoDesconocido,
    parsear_detalle,
    parsear_respuestas,
    sin_resultados,
    total_aproximado,
)

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures/biblioteca"


def cuerpos(nombre):
    d = json.loads((FIX / nombre).read_text())
    return [r["cuerpo"] for r in d["respuestas"]], d["html_final"]


def test_pagina_therapy_toolkit():
    c, html_final = cuerpos("pagina_therapy_toolkit.json")
    anuncios = parsear_respuestas(c, "ALL", html=html_final)
    assert len(anuncios) >= 20
    assert {a.page_id for a in anuncios} == {"102506312071455"}
    assert all(isinstance(a.inicio, date) and a.inicio <= date(2026, 11, 10) for a in anuncios)
    assert len({a.library_id for a in anuncios}) == len(anuncios)


def test_varias_paginas_en_impultienda():
    c, _ = cuerpos("palabra_impultienda.json")
    assert len({a.page_id for a in parsear_respuestas(c, "ALL")}) >= 10


def test_vacio_y_totales():
    _, html = cuerpos("vacio.json")
    assert sin_resultados(html)
    assert total_aproximado("~1,700 results") == 1700
    assert total_aproximado("~1.700 resultados") == 1700
    assert total_aproximado("1 result") == 1
    assert total_aproximado("sin cifra") is None


def test_formato_desconocido_no_inventa():
    with pytest.raises(FormatoDesconocido):
        parsear_respuestas(['{"data": {"otra_cosa": 1}}', "no es json"], "RO")


def test_totales_reales_y_variantes():
    assert total_aproximado("~230 resultados") == 230
    assert total_aproximado(">50.000 resultados") == 50000
    assert total_aproximado("&gt;50.000 resultados") == 50000
    assert total_aproximado("Aproximadamente 450 resultados") == 450
    assert total_aproximado("About 1,200 results") == 1200
    assert total_aproximado("1 resultado") == 1
    assert total_aproximado("~1.5 results") is None
    assert total_aproximado("") is None


def test_sin_resultados_en_ambos_idiomas():
    assert sin_resultados("No hay ningún anuncio que coincida con los criterios de búsqueda")
    assert sin_resultados("<div>No ads match your search criteria</div>")
    assert not sin_resultados("~230 resultados")


def test_vacio_con_estructura_conocida_devuelve_lista_vacia():
    _, html = cuerpos("vacio.json")
    assert parsear_respuestas([], "RO", html=html) == []


def test_campos_y_fechas_utc_y_opcionales():
    c, html_final = cuerpos("pagina_therapy_toolkit.json")
    a = parsear_respuestas(c, "ALL", html=html_final)[0]
    assert a.library_id == "2363595284386790"
    assert a.pais == "ALL"
    assert a.inicio == datetime.fromtimestamp(1791270000, UTC).date()
    assert a.fin == datetime.fromtimestamp(1794297600, UTC).date()
    assert a.activo is True
    assert "FACEBOOK" in a.plataformas
    assert a.collation_id == "1117578817420071"
    assert a.collation_count == 1
    assert a.enlace_destino == "https://learning-skills-activity.online/en/"
    assert a.titulo


def _cuerpo(*nodos):
    edges = [{"node": {"collated_results": [n]}} for n in nodos]
    return json.dumps({"data": {"ad_library_main": {"search_results_connection": {"edges": edges}}}})


def _anuncio(**extra):
    base = {"ad_archive_id": "1", "page_id": "9", "page_name": "P", "start_date": 1791270000,
            "is_active": True, "publisher_platform": ["FACEBOOK"], "snapshot": {}}
    base.update(extra)
    return base


def test_ausentes_son_none_y_duplicados_una_vez():
    r = parsear_respuestas([_cuerpo(_anuncio(), _anuncio())], "AR")
    assert len(r) == 1
    a = r[0]
    assert a.fin is None and a.titulo is None and a.enlace_destino is None
    assert a.collation_id is None and a.collation_count is None
    assert a.texto == ""


def test_anuncio_malo_se_descarta_y_se_cuenta():
    malo = _anuncio(ad_archive_id="2")
    del malo["start_date"]
    r = parsear_detalle([_cuerpo(malo, _anuncio())], "AR")
    assert [a.library_id for a in r.anuncios] == ["1"]
    assert r.descartados == 1
    assert r.total_json is None


def test_todos_malos_es_formato_desconocido():
    malo = _anuncio()
    del malo["start_date"]
    with pytest.raises(FormatoDesconocido):
        parsear_detalle([_cuerpo(malo)], "AR")


def test_edge_sin_collated_results_se_descarta():
    cuerpo = json.dumps({"data": {"ad_library_main": {"search_results_connection": {"edges": [
        {"node": {}}, {"node": {"collated_results": [_anuncio()]}}]}}}})
    r = parsear_detalle([cuerpo], "AR")
    assert len(r.anuncios) == 1 and r.descartados == 1


def test_total_json_del_html_real():
    _, html = cuerpos("pagina_therapy_toolkit.json")
    assert parsear_detalle([], "ALL", html=html).total_json == 234
    _, html = cuerpos("vacio.json")
    assert parsear_detalle([], "RO", html=html).total_json == 0


def test_total_no_toma_texto_suelto():
    assert total_aproximado("2026-11-10 resultados") is None
    assert total_aproximado("Logra 3 resultados en 30 dias\n~230 resultados") == 230
    assert total_aproximado("Logra 3 resultados en 30 dias ~230 resultados") == 230
    assert total_aproximado("Logra 3 resultados garantizados") is None
    assert total_aproximado('<div role="heading">1 resultado</div>') == 1
    assert total_aproximado("0 resultados") == 0


def _html_con_json(doc):
    return "<html><body><script type=\"application/json\">" + json.dumps(doc) + "</script></body></html>"


def test_sin_resultados_manda_el_json():
    vacio = {"x": {"search_results_connection": {"count": 0, "edges": []}}}
    assert sin_resultados(_html_con_json(vacio))
    con = {"x": {"search_results_connection": {"count": 1, "edges": [
        {"node": {"collated_results": [_anuncio(snapshot={"body": {"text": "No ads match your search criteria"}})]}}]}}}
    html = _html_con_json(con) + "<p>No ads match your search criteria</p>"
    assert not sin_resultados(html)


def _cuerpo_pag(ids, hay_mas):
    edges = [{"node": {"collated_results": [_anuncio(ad_archive_id=i)]}} for i in ids]
    con = {"edges": edges, "page_info": {"has_next_page": hay_mas}}
    return json.dumps({"data": {"ad_library_main": {"search_results_connection": con}}})


def test_hay_mas_de_la_ultima_conexion():
    _, html = cuerpos("pagina_therapy_toolkit.json")
    assert parsear_detalle([], "ALL", html=html).hay_mas is True
    _, html = cuerpos("vacio.json")
    assert parsear_detalle([], "RO", html=html).hay_mas is False
    c, html = cuerpos("palabra_impultienda.json")
    assert parsear_detalle(c, "ALL", html=html).hay_mas is True
    assert parsear_detalle([_cuerpo_pag(["1"], True), _cuerpo_pag(["2"], False)], "AR").hay_mas is False
    assert parsear_detalle([_cuerpo(_anuncio())], "AR").hay_mas is None  # sin page_info: no se sabe


def test_primera_pagina_del_html_va_delante():
    c, html = cuerpos("palabra_impultienda.json")
    solo_html = [a.library_id for a in parsear_detalle([], "ALL", html=html).anuncios]
    todos = [a.library_id for a in parsear_detalle(c, "ALL", html=html).anuncios]
    assert len(solo_html) == 30 and todos[:30] == solo_html and len(todos) == 70


def test_sin_resultados_ignora_scripts_y_estilos():
    js = "<script>var i18n = {vacio: 'No hay ningún anuncio que coincida'};</script>"
    css = "<style>/* no ads found */</style>"
    desconocido = '<script type="application/json">{"data": {"otra_cosa": 1}}</script>'
    assert not sin_resultados("<html>" + js + css + desconocido + "</html>")
    assert sin_resultados("<html>" + js + '<div role="heading">No hay ningún anuncio que coincida</div></html>')
