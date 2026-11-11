import dataclasses

from trovefy.caza.destino import (
    Destino,
    PaginaLanding,
    clave_oferta,
    deshacer_redireccion_fb,
    detectar_gateway,
    extraer_precio,
    motivo_dudoso,
    oferta_id,
    resolver_destino,
    veredicto_landing,
)


def test_redireccion():
    u = "https://l.facebook.com/l.php?u=https%3A%2F%2Fgeriactiva.impultienda.ar%2F%3Futm_source%3Dfb&h=AT0"
    assert deshacer_redireccion_fb(u) == "https://geriactiva.impultienda.ar/?utm_source=fb"
    assert deshacer_redireccion_fb("https://x.com/a") == "https://x.com/a"


def test_gateway_y_clave():
    plat, chk = detectar_gateway(["https://kits.netlify.app/", "https://pay.hotmart.com/X1234567Y?off=abc"])
    assert plat == "hotmart" and clave_oferta("https://kits.netlify.app/", chk) == "hotmart:X1234567Y"
    assert clave_oferta("https://jogosdenatal.netlify.app/oferta/natal", None) == "jogosdenatal.netlify.app/oferta/natal"
    assert clave_oferta("https://www.therapytoolkit.com/es/pagina", None) == "therapytoolkit.com"


def test_gateway_otros():
    assert detectar_gateway(["https://tienda.impultienda.ar/checkout"])[0] == "impultienda"
    assert detectar_gateway(["https://whop.com/checkout/plan_abc"])[0] == "whop"
    assert detectar_gateway(["https://x.mycartpanda.com/p"])[0] == "cartpanda"
    assert detectar_gateway(["https://buy.stripe.com/abc"])[0] == "stripe"
    assert detectar_gateway(["https://example.com/", "https://t.co/x"]) is None


def test_clave_whop_no_colapsa_checkouts():
    assert clave_oferta("https://a.com/", "https://whop.com/checkout/plan_1") == "whop:plan_1"


def test_oferta_id_estable():
    assert oferta_id("hotmart:pay.hotmart.com/X1234567Y") == oferta_id("hotmart:pay.hotmart.com/X1234567Y")
    assert oferta_id("x").startswith("o-")
    assert oferta_id("a") != oferta_id("b")


def test_precio_al_contado():
    assert extraer_precio("Antes 39,90 € · Hoy 13,90 €") == (13.90, "EUR")  # sin el ancla
    assert extraer_precio("12x de R$ 9,90 ou R$ 97,00 à vista") == (97.00, "BRL")
    assert extraer_precio("Preț: 79 lei") == (79.0, "RON")
    assert extraer_precio("Gratis") is None
    assert extraer_precio("US$ 1,297.00") == (1297.0, "USD")
    assert extraer_precio("199 Kč") == (199.0, "CZK")
    assert extraer_precio("49 zł") == (49.0, "PLN")


def test_veredicto_landing():
    base = Destino("u", "u", "hotmart", "https://pay.hotmart.com/X1", 13.9, "EUR", None, False, False, "ok", None)
    assert veredicto_landing(base) == "modelable"
    sin = dataclasses.replace(base, checkout=None, gateway=None)
    assert veredicto_landing(sin) == "dudoso" and "checkout" in motivo_dudoso(sin)
    assert veredicto_landing(dataclasses.replace(base, precio=None)) == "dudoso"
    assert motivo_dudoso(base) is None


# --- resolver_destino con navegador y robot falsos ---------------------------------------------


class Falso:
    def __init__(self, pagina=None, error=None, checkout=None):
        self.pagina, self.error, self.checkout, self.abiertas = pagina, error, checkout, []

    def abrir_landing(self, url, espera_s=3.5):
        self.abiertas.append(url)
        if self.error:
            raise self.error
        if self.checkout is not None and "pay.hotmart" in url:
            return self.checkout
        return self.pagina


def pagina(**kw):
    base = {
        "url_final": "https://tienda.example.com/", "html": "<html><title>Kit</title></html>",
        "texto": "Kit completo " * 20 + "Hoy 13,90 €", "titulo": "Kit", "estado_http": 200,
        "cadena": ["https://tienda.example.com/"], "peticiones": [], "reproductor": False,
    }
    base.update(kw)
    return PaginaLanding(**base)


def robot_igual(url):
    return url, "<title>Kit</title>" + "Kit completo " * 20 + "Hoy 13,90 €"


def test_resolver_ok_con_checkout_en_html():
    p = pagina(html='<a href="https://pay.hotmart.com/X1234567Y?off=1">Comprar</a><title>Kit</title>')
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert d.estado == "ok" and d.gateway == "hotmart" and d.precio == 13.9 and d.moneda == "EUR"
    assert d.cloaker is False and d.red_social is False and veredicto_landing(d) == "modelable"


def test_resolver_precio_en_checkout():
    p = pagina(texto="Kit completo " * 20, html='<a href="https://pay.hotmart.com/X1234567Y">c</a>')
    chk = pagina(url_final="https://pay.hotmart.com/X1234567Y", texto="Total 29,90 €")
    d = resolver_destino("https://tienda.example.com/", Falso(p, checkout=chk), robot_igual)
    assert d.precio == 29.9


def test_resolver_cadena_antes_que_html():
    p = pagina(cadena=["https://a.com/", "https://pay.kiwify.com.br/AbC"], html='<a href="https://buy.stripe.com/x">')
    d = resolver_destino("https://a.com/", Falso(p), robot_igual)
    assert d.gateway == "kiwify"


def test_resolver_tracker():
    p = pagina(peticiones=["https://abc.rdtk.io/x", "https://track.voluum.com/click"])
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert d.tracker == "redtrack"


def test_resolver_cloaker_por_host_titulo_y_longitud():
    p = pagina()
    assert resolver_destino("https://tienda.example.com/", Falso(p), lambda u: ("https://otra.com/", "x" * 400)).cloaker
    assert resolver_destino(
        "https://tienda.example.com/", Falso(p), lambda u: (u, "<title>Blog</title>" + "Kit completo " * 20)
    ).cloaker is True
    assert resolver_destino("https://tienda.example.com/", Falso(p), lambda u: (u, "hola")).cloaker is None


def test_resolver_robot_falla_cloaker_none():
    def roto(u):
        raise OSError("sin red")

    assert resolver_destino("https://tienda.example.com/", Falso(pagina()), roto).cloaker is None


def test_resolver_vsl_por_reproductor_visible():
    d = resolver_destino("https://tienda.example.com/", Falso(pagina(reproductor=True)), robot_igual)
    assert d.vsl is True
    # la cadena en el HTML no basta
    d = resolver_destino("https://tienda.example.com/", Falso(pagina(html="vturb-smartplayer")), robot_igual)
    assert d.vsl is False


def test_resolver_no_medido():
    d = resolver_destino("https://x.com/", Falso(error=TimeoutError("lento")), robot_igual)
    assert d.estado == "no_medido" and d.motivo and veredicto_landing(d) == "dudoso"
    d = resolver_destino("https://x.com/", Falso(pagina(estado_http=404)), robot_igual)
    assert d.estado == "no_medido" and "404" in d.motivo
    d = resolver_destino("https://x.com/", Falso(pagina(url_final="https://x.com/login")), robot_igual)
    assert d.estado == "no_medido" and "login" in d.motivo
    d = resolver_destino("https://x.com/", Falso(pagina(estado_http=451)), robot_igual)
    assert d.estado == "no_medido" and "geobloque" in d.motivo


def test_resolver_red_social_no_abre_nada():
    nav = Falso(pagina())
    for u in ("https://wa.me/123", "https://www.instagram.com/x", "https://m.me/x", "https://play.google.com/store/apps/x"):
        d = resolver_destino(u, nav, robot_igual)
        assert d.red_social is True
    assert nav.abiertas == []


def test_resolver_nunca_abre_facebook_y_desenvuelve():
    nav = Falso(pagina())
    u = "https://l.facebook.com/l.php?u=https%3A%2F%2Ftienda.example.com%2F&h=AT0"
    d = resolver_destino(u, nav, robot_igual)
    assert nav.abiertas == ["https://tienda.example.com/"] and d.url_anuncio == u
    nav = Falso(pagina())
    d = resolver_destino("https://www.facebook.com/page", nav, robot_igual)
    assert nav.abiertas == [] and d.red_social is True


def test_fixture_html_minima():
    from pathlib import Path

    from trovefy.caza.destino import detectar_tracker, urls_en_html

    html = (Path(__file__).parents[2] / "fixtures" / "landings" / "hotmart_minima.html").read_text()
    urls = urls_en_html(html)
    assert detectar_gateway(urls) == ("hotmart", "https://pay.hotmart.com/X1234567Y?off=abc")
    assert detectar_tracker(urls) == "voluum"


def test_gateway_ignora_sdk_y_recursos():
    assert detectar_gateway(["https://sdk.mercadopago.com/js/v2"]) is None
    assert detectar_gateway(["https://gumroad.com/js/gumroad.js"]) is None
    assert detectar_gateway(["https://x.gumroad.com/l/abc"])[0] == "gumroad"


def test_resolver_gateway_no_sale_de_scripts_ni_peticiones_de_recursos():
    p = pagina(
        html='<script src="https://sdk.mercadopago.com/js/v2"></script><img src="https://buy.stripe.com/i.png">',
        peticiones=["https://sdk.mercadopago.com/js/v2", "https://pay.hotmart.com/X1234567Y/img.png"],
        documentos=[],
    )
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert d.gateway is None
    p = pagina(documentos=["https://pay.kiwify.com.br/AbC123"])
    assert resolver_destino("https://tienda.example.com/", Falso(p), robot_igual).gateway == "kiwify"


def test_clave_misma_oferta_entre_hosts_hotmart():
    ks = {clave_oferta("https://a.com/", u) for u in (
        "https://pay.hotmart.com/X1234567Y?off=abc", "https://go.hotmart.com/X1234567Y", "https://hotm.art/X1234567Y")}
    assert ks == {"hotmart:X1234567Y"}
    assert clave_oferta("https://a.com/", "https://pay.hotmart.com/Z999") != "hotmart:X1234567Y"


def test_clave_stripe_sesiones_no_se_juntan():
    a = clave_oferta("https://a.com/", "https://checkout.stripe.com/c/pay/cs_live_a1")
    b = clave_oferta("https://b.com/", "https://checkout.stripe.com/c/pay/cs_live_b2")
    assert a == "a.com" and b == "b.com"
    assert clave_oferta("https://a.com/", "https://buy.stripe.com/abc123") == "stripe:abc123"


def test_clave_otras_plataformas():
    assert clave_oferta("https://a.com/", "https://pay.kiwify.com.br/AbC") == "kiwify:AbC"
    assert clave_oferta("https://a.com/", "https://whop.com/mi-empresa/") == "whop:mi-empresa"
    assert clave_oferta("https://a.com/", "https://t.impultienda.ar/checkout") == "impultienda:t"
    assert clave_oferta("https://a.com/", "https://x.gumroad.com/l/slug") == "gumroad:x.gumroad.com/slug"


def test_url_no_valida_no_llega_al_navegador():
    nav = Falso(pagina())
    for u in ("file:///etc/passwd", "http://localhost:8000/", "http://127.0.0.1/", "http://192.168.1.5/x",
              "http://169.254.169.254/latest", "javascript:alert(1)", "data:text/html,hola", "http://intranet/x"):
        d = resolver_destino(u, nav, robot_igual)
        assert d.estado == "no_medido" and d.motivo == "enlace no válido", u
    assert nav.abiertas == []


def test_robot_http_rechaza_url_no_valida():
    import pytest
    from trovefy.caza.destino import pedir_como_robot_http

    with pytest.raises(ValueError):
        pedir_como_robot_http("file:///etc/passwd")


def test_cloaker_spa_es_no_medido():
    p = pagina()
    d = resolver_destino("https://tienda.example.com/", Falso(p), lambda u: (u, "<title>Kit</title><div id=root></div>"))
    assert d.cloaker is None and "JavaScript" in d.motivo
    # el texto se compara sin etiquetas ni scripts: HTML largo pero casi sin texto sigue siendo un cascarón
    html = "<title>Kit</title>" + "<script>var a=1;</script><div class=x></div>" * 200
    assert resolver_destino("https://tienda.example.com/", Falso(p), lambda u: (u, html)).cloaker is None


def test_precio_cuotas_sin_x_y_envio():
    assert extraer_precio("3 cuotas de $ 33 o $ 99") == (99.0, None)
    assert extraer_precio("3 parcelas de R$ 33,00 ou R$ 97,00") == (97.0, "BRL")
    assert extraer_precio("Envío 2,50 € Total 29 €") == (29.0, "EUR")
    assert extraer_precio("Shipping $5 Price $40") == (40.0, None)


def test_moneda_solo_usd_con_senal_explicita():
    assert extraer_precio("Precio $ 17.000") == (17000.0, None)
    assert extraer_precio("MXN $499") == (499.0, "MXN")
    assert extraer_precio("$499 ARS") == (499.0, "ARS")
    assert extraer_precio("US$ 17") == (17.0, "USD")
    assert extraer_precio("17 USD") == (17.0, "USD")
    assert extraer_precio("17 dólares") == (17.0, "USD")
    assert extraer_precio("COP $ 59.900") == (59900.0, "COP")
    assert extraer_precio("CLP 9.990") == (9990.0, "CLP")
    assert extraer_precio("S/ 50 PEN") == (50.0, "PEN")
    assert extraer_precio("UYU 450") == (450.0, "UYU")


def test_resolver_dolar_ambiguo_deja_moneda_none_y_motivo():
    p = pagina(texto="Kit completo " * 20 + "Hoy $ 17.000", html='<a href="https://pay.hotmart.com/X1234567Y">c</a>')
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert d.precio == 17000.0 and d.moneda is None and "símbolo $ ambiguo" in d.motivo
    assert veredicto_landing(d) == "modelable"


def test_hotm_art_usa_codigo_de_pay_si_la_cadena_llega():
    p = pagina(cadena=["https://hotm.art/AbCd", "https://pay.hotmart.com/X1234567Y?off=1"],
               url_final="https://pay.hotmart.com/X1234567Y")
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert clave_oferta(d.url_final, d.checkout) == "hotmart:X1234567Y"
    p = pagina(cadena=["https://hotm.art/AbCd"])
    d = resolver_destino("https://tienda.example.com/", Falso(p), robot_igual)
    assert clave_oferta(d.url_final, d.checkout) == "hotmart:AbCd"  # sin llegar a pay.: código corto


def test_instagram_l_se_desenvuelve():
    u = "https://l.instagram.com/?u=https%3A%2F%2Ftienda.example.com%2Fx&e=AT0"
    assert deshacer_redireccion_fb(u) == "https://tienda.example.com/x"


def test_filtro_de_rutas_del_navegador():
    from trovefy.caza.destino import _filtrar_ruta

    class Ruta:
        def __init__(self, url):
            self.request = type("R", (), {"url": url})()
            self.accion = None

        def abort(self):
            self.accion = "abort"

        def continue_(self):
            self.accion = "continue"

    esperado = {
        "https://tienda.example.com/a.js": "continue",
        "data:image/png;base64,AAAA": "continue",
        "https://connect.facebook.net/x.js": "abort",
        "https://www.facebook.com/tr": "abort",
        "https://l.instagram.com/?u=x": "abort",
        "http://127.0.0.1:9/": "abort",
        "http://192.168.0.2/": "abort",
        "file:///etc/passwd": "abort",
    }
    for url, accion in esperado.items():
        r = Ruta(url)
        _filtrar_ruta(r)
        assert r.accion == accion, url


# --- ola final: precios y monedas -------------------------------------------------------------


def test_dolar_ambiguo_no_gana_a_un_precio_con_moneda():
    assert extraer_precio("Plan básico $9 · Precio final 49 lei") == (49.0, "RON")


def test_varias_monedas_nunca_el_minimo_entre_monedas():
    assert extraer_precio("120 lei sau 29 €") == (120.0, "RON")  # la primera explícita
    assert extraer_precio("120 lei sau 29 €", moneda_pais="EUR") == (29.0, "EUR")  # la del país del anuncio
    assert extraer_precio("Antes 159 lei, hoy 120 lei; 29 €", moneda_pais="RON") == (120.0, "RON")
    assert extraer_precio("120 lei sau 29 €", moneda_pais="MDL") == (120.0, "RON")  # sin la del país: la primera


def test_codigos_de_moneda_solo_en_mayusculas():
    assert extraer_precio("compra 2 pen") is None
    assert extraer_precio("cop 15 unidades") is None
    assert extraer_precio("15 COP") == (15.0, "COP")
    assert extraer_precio("ron 5 minute") is None
    assert extraer_precio("Preț: 79 Lei") == (79.0, "RON")  # «lei» es palabra, no código: vale en cualquier caja
