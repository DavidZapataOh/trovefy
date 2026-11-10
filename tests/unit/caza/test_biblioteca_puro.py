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
