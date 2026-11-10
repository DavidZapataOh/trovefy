import dataclasses

from trovify.caza.destino import (
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
    assert plat == "hotmart" and clave_oferta("https://kits.netlify.app/", chk) == "hotmart:pay.hotmart.com/X1234567Y"
    assert clave_oferta("https://jogosdenatal.netlify.app/oferta/natal", None) == "jogosdenatal.netlify.app/oferta/natal"
    assert clave_oferta("https://www.therapytoolkit.com/es/pagina", None) == "therapytoolkit.com"


def test_gateway_otros():
    assert detectar_gateway(["https://tienda.impultienda.ar/checkout"])[0] == "impultienda"
    assert detectar_gateway(["https://whop.com/checkout/plan_abc"])[0] == "whop"
    assert detectar_gateway(["https://x.mycartpanda.com/p"])[0] == "cartpanda"
    assert detectar_gateway(["https://buy.stripe.com/abc"])[0] == "stripe"
    assert detectar_gateway(["https://example.com/", "https://t.co/x"]) is None


def test_clave_whop_no_colapsa_checkouts():
    assert clave_oferta("https://a.com/", "https://whop.com/checkout/plan_1") == "whop:whop.com/plan_1"


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
    ).cloaker
    assert resolver_destino("https://tienda.example.com/", Falso(p), lambda u: (u, "hola")).cloaker is True


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

    from trovify.caza.destino import detectar_tracker, urls_en_html

    html = (Path(__file__).parents[2] / "fixtures" / "landings" / "hotmart_minima.html").read_text()
    urls = urls_en_html(html)
    assert detectar_gateway(urls) == ("hotmart", "https://pay.hotmart.com/X1234567Y?off=abc")
    assert detectar_tracker(urls) == "voluum"
