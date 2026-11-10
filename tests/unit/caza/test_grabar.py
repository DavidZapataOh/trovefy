"""Partes puras de la grabadora de fixtures: redacción, filtrado, recorte y escritura segura.

Los valores con forma de token se construyen en tiempo de ejecución (un hook bloquea tokens literales).
"""

import json
import random
import string

import pytest
from trovify.caza.grabar import (
    SecretoEnCaptura,
    componer,
    contar_anuncios,
    es_respuesta_de_datos,
    guardar,
    recortar,
    recortar_html,
    redactar,
)

R = "<redactado>"


def _aleatorio(n: int = 24, alfabeto: str = string.ascii_letters + string.digits) -> str:
    rnd = random.Random(n)
    return "".join(rnd.choice(alfabeto) for _ in range(n))


def _token_meta() -> str:
    return "E" + "AA" + _aleatorio(40)


def test_redacta_campos_json_de_sesion():
    v = _aleatorio()
    for clave in ("lsd", "fb_dtsg", "jazoest", "__spin_r", "__spin_t", "__spin_b", "__hsi", "hsi",
                  "__dyn", "__csr", "__rev", "datr", "_js_datr", "LSD"):
        texto = json.dumps({clave: v, "otro": "queda"})
        r = redactar(texto)
        assert v not in r, clave
        assert json.loads(r) == {clave: R, "otro": "queda"}, clave
    n = random.Random(1).randint(10**9, 10**10)
    assert json.loads(redactar(json.dumps({"__spin_t": n}))) == {"__spin_t": R}


def test_redacta_cualquier_campo_con_token_en_el_nombre():
    v = _aleatorio()
    datos = {"token": v, "async_get_token": v, "collationToken": v, "AccessToken": v, "nulo_token": None,
             "page_id": "102506312071455"}
    r = json.loads(redactar(json.dumps(datos)))
    assert r == {"token": R, "async_get_token": R, "collationToken": R, "AccessToken": R, "nulo_token": None,
                 "page_id": "102506312071455"}


def test_redacta_formas_de_meta_en_html():
    v = _aleatorio()
    html = (
        f'["LSD",[],{{"token":"{v}"}},323]'
        f'["DTSGInitialData",[],{{"token":"{v}"}},258]'
        f'["_js_datr","{v}",86400000]'
        f'<input type="hidden" name="lsd" value="{v}" autocomplete="off">'
        f'<input type="hidden" name="jazoest" value="{v}">'
        f'<a href="/ads/library/?lsd={v}&amp;jazoest={v}&q=x">'
        f'"url":"\\/ajax\\/x?__dyn={v}\\u0026__csr={v}\\u0026__rev={v}\\u0026q=y"'
    )
    r = redactar(html)
    assert v not in r
    assert "q=x" in r and "q=y" in r


def test_redacta_json_escapado_dentro_de_cadenas():
    v = _aleatorio()
    interno = json.dumps({"fb_dtsg": v, "variables": json.dumps({"lsd": v, "q": "ok"})})
    r = redactar(interno)
    assert v not in r
    assert json.loads(json.loads(r)["variables"]) == {"lsd": R, "q": "ok"}


def test_urls_de_medios_se_sustituyen():
    host = "scontent-mad1-1.xx." + "fbcdn.net"
    plano = f"https://{host}/v/t39.30808-6/{_aleatorio()}.jpg?stp=dst&_nc_cat=1&oh=00_{_aleatorio()}"
    escapado = plano.replace("/", "\\/")
    video = f"https://video-mad1-1.xx.{'fbcdn'}.net/o1/v/t2/f2/m69/{_aleatorio()}.mp4?efg=x"
    datos = {"original_image_url": plano, "video_hd_url": video, "link_url": "https://tienda.example/p",
             "page_profile_uri": "https://www.facebook.com/algo/"}
    r = json.loads(redactar(json.dumps(datos)))
    assert r == {"original_image_url": "<media>", "video_hd_url": "<media>",
                 "link_url": "https://tienda.example/p", "page_profile_uri": "https://www.facebook.com/algo/"}
    r2 = redactar('{"u":"' + escapado + '","v":"x"}')
    assert json.loads(r2) == {"u": "<media>", "v": "x"}


def test_redaccion_idempotente_y_no_toca_datos_del_anuncio():
    anuncio = {"ad_archive_id": "123", "collation_count": 3, "start_date": 1730000000,
               "snapshot": {"body": {"text": "Fișe de lucru"}, "page_name": "Therapy Toolkit"}}
    texto = json.dumps(anuncio, ensure_ascii=False)
    assert redactar(texto) == texto
    assert redactar(redactar(texto)) == texto


def test_es_respuesta_de_datos():
    assert es_respuesta_de_datos("https://www.facebook.com/api/graphql/")
    assert es_respuesta_de_datos("https://www.facebook.com/api/graphql/?x=1")
    assert not es_respuesta_de_datos("https://static.xx.fbcdn.net/rsrc.php/v3/x.js")
    assert not es_respuesta_de_datos("https://www.facebook.com/ads/library/?q=x")
    assert not es_respuesta_de_datos("https://otro.example/api/graphql/")


def _cuerpo(ids):
    edges = [{"node": {"collated_results": [{"ad_archive_id": str(i), "snapshot": {}}]}} for i in ids]
    return json.dumps({"data": {"ad_library_main": {"search_results_connection": {"edges": edges}}}})


def test_contar_anuncios_distintos():
    assert contar_anuncios(_cuerpo([1, 2, 3]) + _cuerpo([3, 4])) == 4
    assert contar_anuncios("nada") == 0


def test_recortar_html_conserva_bloques_de_datos_y_marcadores():
    datos = json.dumps({"require": [["x", {"ad_archive_id": "9", "snapshot": {}}]]})
    html = (
        '<html><head><script src="a.js"></script>'
        '<script type="application/json" data-sjs>{"otro":"bootloader"}</script>'
        f'<script type="application/json" data-content-len="9" data-sjs>{datos}</script></head>'
        '<body><div class="x"><div class="y"><span>~1,700 results</span></div>'
        '<div>Otro texto largo que no interesa</div></div>'
        '<div role="heading"><span>No ads match your search criteria.</span></div></body></html>'
    )
    r = recortar_html(html)
    assert datos in r
    assert "bootloader" not in r and "a.js" not in r and "no interesa" not in r
    assert "<span>~1,700 results</span>" in r
    assert "No ads match your search criteria." in r


def test_recortar_respuestas_respeta_tamano_y_minimo():
    grandes = [_cuerpo(range(k * 10, k * 10 + 10)) + " " * 300_000 for k in range(6)]
    captura = {"url": "u", "url_final": "u", "capturado_en": "t", "html_final": "<html></html>",
               "respuestas": [{"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": c}
                              for c in grandes]
               + [{"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": '{"data":{}}'}]}
    r = recortar(captura, max_bytes=1_000_000, min_anuncios=20)
    assert len(json.dumps(r, ensure_ascii=False).encode()) <= 1_000_000
    assert contar_anuncios("".join(x["cuerpo"] for x in r["respuestas"])) >= 20
    assert all("ad_archive_id" in x["cuerpo"] for x in r["respuestas"])


def test_recortar_falla_si_no_cabe_con_el_minimo():
    captura = {"url": "u", "url_final": "u", "capturado_en": "t", "html_final": "",
               "respuestas": [{"url": "https://www.facebook.com/api/graphql/", "estado": 200,
                               "cuerpo": _cuerpo(range(30)) + " " * 2_000_000}]}
    with pytest.raises(ValueError):
        recortar(captura, max_bytes=1_000_000, min_anuncios=20)


def test_recortar_sin_anuncios_conserva_respuestas_de_busqueda():
    vacia = json.dumps({"data": {"ad_library_main": {"search_results_connection": {"count": 0, "edges": []}}}})
    captura = {"url": "u", "url_final": "u", "capturado_en": "t", "html_final": "",
               "respuestas": [{"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": vacia},
                              {"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": '{"x":1}'}]}
    assert [x["cuerpo"] for x in recortar(captura)["respuestas"]] == [vacia]


def test_componer_redacta_y_guardar_rechaza_secretos(tmp_path):
    v = _aleatorio()
    c = componer("https://www.facebook.com/ads/library/?q=x&lsd=" + v, "https://www.facebook.com/ads/library/?q=x",
                 "<html>" + json.dumps({"fb_dtsg": v}) + "</html>",
                 [{"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": json.dumps({"lsd": v})}],
                 capturado_en="2026-11-10T00:00:00+00:00")
    assert v not in json.dumps(c)
    assert set(c) == {"url", "url_final", "capturado_en", "html_final", "respuestas"}
    assert set(c["respuestas"][0]) == {"url", "estado", "cuerpo"}
    salida = tmp_path / "f.json"
    guardar(c, salida)
    assert json.loads(salida.read_text()) == c

    c["html_final"] += _token_meta()  # un secreto que la redacción no conoce
    otra = tmp_path / "g.json"
    with pytest.raises(SecretoEnCaptura) as e:
        guardar(c, otra)
    assert not otra.exists()
    assert "EAA" not in str(e.value)


def test_marcadores_reales_y_texto_de_anuncios_fuera():
    html = (
        '<div role="heading">~230 resultados</div><div role="heading">&gt;50.000 resultados</div>'
        "<div>Estos resultados incluyen anuncios</div><span>Resultados visibles en 3 semanas</span>"
        "<div>No hay ningún anuncio que coincida con los criterios de búsqueda</div>"
    )
    r = recortar_html(html)
    assert "~230 resultados" in r and "&gt;50.000 resultados" in r and "No hay ningún anuncio" in r
    assert "Estos resultados" not in r and "visibles" not in r


def test_redacta_sesion_y_cursor_de_paginacion():
    v = _aleatorio()
    datos = {"sessionID": v, "session_id": v, "haste_session": v, "end_cursor": v, "cursor": None,
             "page_info": {"has_next_page": True}}
    r = json.loads(redactar(json.dumps(datos)))
    assert r == {"sessionID": R, "session_id": R, "haste_session": R, "end_cursor": R, "cursor": None,
                 "page_info": {"has_next_page": True}}
