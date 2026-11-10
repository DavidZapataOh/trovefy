from trovify.caza.biblioteca import detectar_bloqueo, url_biblioteca


def test_url_por_pagina():
    assert url_biblioteca("ALL", page_id="102506312071455", estado="all") == (
        "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL"
        "&media_type=all&search_type=page&view_all_page_id=102506312071455")

def test_url_por_palabra():
    assert url_biblioteca("RO", q="fișe terapie") == (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=RO"
        "&media_type=all&q=fi%C8%99e+terapie&search_type=keyword_unordered")

def test_url_frase_dentro_de_la_pagina():
    u = url_biblioteca("RO", q="fișe", page_id="123")
    assert "view_all_page_id=123" in u and "q=fi%C8%99e" in u and "search_type=page" in u

def test_bloqueos():
    assert detectar_bloqueo("https://www.facebook.com/ads/library/", "...xfb_ad_library_is_captcha_required...") == "captcha"
    assert detectar_bloqueo("https://www.facebook.com/login/?next=x", "") == "login"
    assert detectar_bloqueo("https://www.facebook.com/checkpoint/123/", "") == "checkpoint"
    assert detectar_bloqueo("https://www.facebook.com/ads/library/?q=x", "<html>ok</html>") is None


def test_pais_invalido_o_minusculas():
    import pytest
    for p in ("ro", "ROM", "", "R1", "all"):
        with pytest.raises(ValueError):
            url_biblioteca(p, q="x")


def test_sin_q_ni_page_id_o_q_vacia():
    import pytest
    for q in (None, "", "   "):
        with pytest.raises(ValueError):
            url_biblioteca("RO", q=q)
    assert "view_all_page_id=1" in url_biblioteca("RO", q="  ", page_id="1")
    assert "q=" not in url_biblioteca("RO", q="  ", page_id="1")


def test_bloqueo_por_segmento_exacto():
    assert detectar_bloqueo("https://www.facebook.com/login", "") == "login"
    assert detectar_bloqueo("https://www.facebook.com/loginfoo", "") is None
    assert detectar_bloqueo("https://www.facebook.com/checkpointx/", "") is None


def test_captcha_false_no_es_bloqueo():
    # Grabado real (2026-11-10): la página normal trae la clave con valor false.
    normal = '..."xfb_ad_library_is_captcha_required":false,"ad_library_main":{...'
    assert detectar_bloqueo("https://www.facebook.com/ads/library/?q=x", normal) is None
    escapado = '\\"xfb_ad_library_is_captcha_required\\": false'
    assert detectar_bloqueo("https://www.facebook.com/ads/library/?q=x", escapado) is None
    assert detectar_bloqueo("https://www.facebook.com/ads/library/",
                            '"xfb_ad_library_is_captcha_required":true') == "captcha"
    assert detectar_bloqueo("https://www.facebook.com/ads/library/",
                            normal + '"xfb_ad_library_is_captcha_required":true') == "captcha"
