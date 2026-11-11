import json
import pathlib

import pytest
from trovefy.caza import firecrawl as fc
from trovefy.caza.cache import Cache
from trovefy.caza.cliente import (
    ClienteBibliotecaPublica,
    ErrorDeRed,
    PaginaCapturada,
    SesionBloqueada,
)
from trovefy.caza.firecrawl import (
    FirecrawlNoDisponible,
    FirecrawlRechazo,
    NavegadorFirecrawl,
    clave_firecrawl,
)
from trovefy.caza.presupuesto import Presupuesto

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures/biblioteca"
CLAVE = "".join(["fc", "-", "prueba", "-", "x" * 12])  # construida: nunca un literal de clave
URL = "https://www.facebook.com/ads/library/?q=x"


def fixture():
    return json.loads((FIX / "pagina_therapy_toolkit.json").read_text())


def respuesta_api(html, url="https://www.facebook.com/ads/library/?x=1", estado=200, creditos=5, envuelta=True):
    d = {"rawHtml": html, "metadata": {"url": url, "statusCode": estado, "creditsUsed": creditos, "proxyUsed": "basic"}}
    return {"success": True, "data": d} if envuelta else d


class HttpFalso:
    def __init__(self, *respuestas):
        self.respuestas, self.peticiones = list(respuestas), []

    def __call__(self, url, cuerpo, cabeceras):
        self.peticiones.append((url, cuerpo, cabeceras))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        codigo, datos = r
        return codigo, json.dumps(datos) if not isinstance(datos, str) else datos


class PlaywrightFalso:
    def __init__(self, paginas):
        self.paginas, self.llamadas = list(paginas), []

    def abrir(self, url, max_anuncios):
        self.llamadas.append(url)
        return self.paginas.pop(0)


def pagina_pw():
    d = fixture()
    return PaginaCapturada(d["url_final"], d["html_final"], d["html_final"], [r["cuerpo"] for r in d["respuestas"]])


def cliente(http, paginas_pw=(), cache=None, clave=CLAVE):
    pw = PlaywrightFalso(paginas_pw)
    fcn = NavegadorFirecrawl(clave, http) if clave else None
    c = ClienteBibliotecaPublica(Presupuesto(30, 0, 0, dormir=lambda s: None), pw, cache, firecrawl=fcn)
    return c, pw


def test_pide_raw_html_y_lee_con_el_mismo_parser():
    http = HttpFalso((200, respuesta_api(fixture()["html_final"])))
    c, pw = cliente(http)
    r = c.buscar("ALL", page_id="102506312071455")
    assert r.estado == "ok" and len(r.anuncios) == 30 and r.total_aprox == 234
    assert r.via == "firecrawl" and r.creditos == 5 and pw.llamadas == []
    url, cuerpo, cab = http.peticiones[0]
    assert url == "https://api.firecrawl.dev/v2/scrape"
    assert cuerpo == {"url": r.url, "formats": ["rawHtml"], "proxy": "auto", "maxAge": 0,
                      "waitFor": 3000, "onlyMainContent": False}
    assert cab["Authorization"] == f"Bearer {CLAVE}"


def test_respuesta_sin_envolver_y_success_false():
    n = NavegadorFirecrawl(CLAVE, HttpFalso((200, respuesta_api("<html></html>", envuelta=False))))
    p = n.abrir(URL, 60)
    assert p.html == "<html></html>" and p.estado_http == 200 and p.cuerpos == []
    n = NavegadorFirecrawl(CLAVE, HttpFalso((200, {"success": False, "error": "algo"})))
    with pytest.raises(FirecrawlRechazo):
        n.abrir(URL, 60)


def test_texto_son_los_encabezados():
    html = '<div role="heading" aria-level="2">~230 results</div><p>no</p><div role="heading">Otro</div>'
    p = NavegadorFirecrawl(CLAVE, HttpFalso((200, respuesta_api(html)))).abrir(URL, 60)
    assert p.texto == "~230 results\nOtro"


@pytest.mark.parametrize("codigo,frase", [(402, "sin créditos"), (401, "no vale"), (403, "no vale")])
def test_errores_de_la_api_son_no_disponible(codigo, frase):
    n = NavegadorFirecrawl(CLAVE, HttpFalso((codigo, {"error": "x"})))
    with pytest.raises(FirecrawlNoDisponible, match=frase) as e:
        n.abrir(URL, 60)
    assert CLAVE not in str(e.value)


@pytest.mark.parametrize("r", [(429, {}), (503, {}), (500, "no json"), OSError("red")])
def test_429_5xx_y_red_son_error_de_red(r):
    with pytest.raises(ErrorDeRed) as e:
        NavegadorFirecrawl(CLAVE, HttpFalso(r)).abrir(URL, 60)
    assert CLAVE not in str(e.value)


def test_estado_del_documento_se_propaga():
    p = NavegadorFirecrawl(CLAVE, HttpFalso((200, respuesta_api("", estado=403)))).abrir(URL, 60)
    assert p.estado_http == 403


def test_sin_creditos_pasa_a_playwright():
    http = HttpFalso((402, {}))
    c, pw = cliente(http, [pagina_pw(), pagina_pw()])
    r1 = c.buscar("ALL", page_id="1")
    r2 = c.buscar("ALL", page_id="2")
    assert r1.estado == r2.estado == "ok" and r1.via == r2.via == "playwright" and r1.creditos is None
    assert len(http.peticiones) == 1 and len(pw.llamadas) == 2
    assert "sin créditos de Firecrawl" in (r1.motivo or "")
    assert "Firecrawl" not in (r2.motivo or "")  # el aviso sale una sola vez


def test_clave_invalida_pasa_a_playwright():
    http = HttpFalso((401, {}))
    c, _pw = cliente(http, [pagina_pw(), pagina_pw()])
    r1, r2 = c.buscar("ALL", page_id="1"), c.buscar("ALL", page_id="2")
    assert r1.via == r2.via == "playwright" and len(http.peticiones) == 1
    assert "no vale" in (r1.motivo or "") and "Firecrawl" not in (r2.motivo or "")


def test_login_de_meta_por_firecrawl_detiene_la_sesion():
    http = HttpFalso((200, respuesta_api("<html></html>", url="https://www.facebook.com/login/?next=x")))
    c, pw = cliente(http, [pagina_pw()])
    assert c.buscar("ALL", q="x").estado == "bloqueado"
    with pytest.raises(SesionBloqueada):
        c.buscar("ALL", q="y")
    assert pw.llamadas == [] and len(http.peticiones) == 1


def test_403_de_meta_por_firecrawl_es_bloqueado_sin_cambiar_de_via():
    http = HttpFalso((200, respuesta_api("<html></html>", estado=403)))
    c, pw = cliente(http, [pagina_pw()])
    assert c.buscar("ALL", q="x").estado == "bloqueado" and pw.llamadas == []


def test_completa_usa_playwright():
    http = HttpFalso()
    c, pw = cliente(http, [pagina_pw()])
    r = c.buscar("ALL", page_id="1", completa=True)
    assert r.via == "playwright" and http.peticiones == [] and len(pw.llamadas) == 1


def test_sin_clave_usa_playwright():
    c, _pw = cliente(HttpFalso(), [pagina_pw()], clave=None)
    r = c.buscar("ALL", page_id="1")
    assert r.via == "playwright" and r.creditos is None and "Firecrawl" not in (r.motivo or "")


def test_la_clave_no_aparece_en_ningun_sitio(tmp_path):
    cache = Cache(tmp_path / "cache")
    http = HttpFalso((402, {}), (200, respuesta_api(fixture()["html_final"])))
    c, _ = cliente(http, [pagina_pw()], cache)
    r = c.buscar("ALL", page_id="1")
    assert CLAVE not in repr(r)
    textos = [p.read_text() for p in (tmp_path / "cache").rglob("*") if p.is_file()]
    assert textos and all(CLAVE not in t for t in textos)
    # la cabecera de autorización no se filtra en el repr del navegador
    assert CLAVE not in repr(NavegadorFirecrawl(CLAVE, http))


def test_cache_conserva_via_y_creditos(tmp_path):
    cache = Cache(tmp_path / "cache")
    http = HttpFalso((200, respuesta_api(fixture()["html_final"])))
    c, _ = cliente(http, cache=cache)
    c.buscar("ALL", page_id="1", max_anuncios=30)
    r = c.buscar("ALL", page_id="1", max_anuncios=30)  # caché
    assert len(http.peticiones) == 1 and r.via == "firecrawl" and r.creditos == 5


def test_solo_https_y_sin_redirecciones():
    import urllib.error
    import urllib.request

    h = fc._SinRedireccion()
    with pytest.raises(urllib.error.HTTPError):
        h.redirect_request(urllib.request.Request("https://api.firecrawl.dev/v2/scrape"), None, 302, "x", {}, "https://otro.example/")


def test_clave_firecrawl_lee_del_env(tmp_path):
    ruta = tmp_path / "claude.env"
    assert clave_firecrawl(ruta) is None  # no existe
    ruta.write_text(f"APIMART_API_KEY=otra\nFIRECRAWL_API_KEY={CLAVE}\n")
    ruta.chmod(0o600)
    assert clave_firecrawl(ruta) == CLAVE
    ruta.write_text("APIMART_API_KEY=otra\n")
    assert clave_firecrawl(ruta) is None
    ruta.write_text(f"FIRECRAWL_API_KEY={CLAVE}\n")
    ruta.chmod(0o644)
    assert clave_firecrawl(ruta) is None  # permisos inseguros: no se usa


# --- ronda de arreglos 1 -----------------------------------------------------------------


@pytest.mark.parametrize("codigo", [408, 429, 500, 502])
def test_408_429_5xx_se_reintentan(codigo):
    with pytest.raises(ErrorDeRed):
        NavegadorFirecrawl(CLAVE, HttpFalso((codigo, {}))).abrir(URL, 60)


def test_http_exception_es_error_de_red():
    import http.client

    with pytest.raises(ErrorDeRed) as e:
        NavegadorFirecrawl(CLAVE, HttpFalso(http.client.IncompleteRead(b""))).abrir(URL, 60)
    assert CLAVE not in str(e.value)


@pytest.mark.parametrize("codigo", [400, 404, 422, 302])
def test_otro_no_2xx_es_error_de_esa_busqueda_sin_cambiar_de_via(codigo):
    http = HttpFalso((codigo, {"error": "x"}), (200, respuesta_api(fixture()["html_final"])))
    c, pw = cliente(http, [pagina_pw()])
    r1 = c.buscar("ALL", page_id="1")
    assert r1.estado == "error" and r1.via == "firecrawl"
    assert r1.motivo == f"Firecrawl rechazó la petición (HTTP {codigo})"
    assert len(http.peticiones) == 1 and pw.llamadas == []  # sin reintento ni cambio de vía
    r2 = c.buscar("ALL", page_id="2")  # la sesión sigue en Firecrawl
    assert r2.estado == "ok" and r2.via == "firecrawl" and pw.llamadas == []


def test_success_false_es_error_con_texto_corto_sin_clave():
    http = HttpFalso((200, {"success": False, "error": f"fallo {CLAVE} " + "z" * 500}))
    c, _ = cliente(http)
    r = c.buscar("ALL", page_id="1")
    assert r.estado == "error" and r.motivo.startswith("Firecrawl rechazó la petición (success:false: fallo")
    assert CLAVE not in r.motivo and len(r.motivo) < 250


def test_tres_rechazos_seguidos_paran_la_sesion():
    from trovefy.caza.presupuesto import ParadaPorErrores

    c, _ = cliente(HttpFalso((400, {}), (400, {}), (400, {})))
    c.buscar("ALL", page_id="1")
    c.buscar("ALL", page_id="2")
    with pytest.raises(ParadaPorErrores):
        c.buscar("ALL", page_id="3")


@pytest.mark.parametrize("clave", ["clave con espacio", "cláve☃", "con\nsalto"])
def test_clave_con_caracteres_raros_no_disponible(clave):
    http = HttpFalso()
    with pytest.raises(FirecrawlNoDisponible, match="caracteres raros; vuelve a pegarla") as e:
        NavegadorFirecrawl(clave, http).abrir(URL, 60)
    assert http.peticiones == [] and clave not in str(e.value)


def test_proxy_usado_queda_en_el_resultado(tmp_path):
    cache = Cache(tmp_path / "cache")
    c, _ = cliente(HttpFalso((200, respuesta_api(fixture()["html_final"]))), cache=cache)
    assert c.buscar("ALL", page_id="1").proxy == "basic"
    assert c.buscar("ALL", page_id="1").proxy == "basic"  # desde caché


def test_primera_pagina_en_cache_sirve_aunque_traiga_menos_de_max_anuncios(tmp_path):
    cache = Cache(tmp_path / "cache")
    http = HttpFalso((200, respuesta_api(fixture()["html_final"])))
    c, pw = cliente(http, [pagina_pw()], cache=cache)
    r1 = c.buscar("ALL", page_id="1")  # max_anuncios=60 por defecto, 30 anuncios, no completo
    assert r1.completo is False and len(r1.anuncios) == 30
    r2 = c.buscar("ALL", page_id="1")
    assert len(http.peticiones) == 1 and r2.via == "firecrawl" and r2.creditos == 5
    # una lectura completa no se conforma con la primera página
    r3 = c.buscar("ALL", page_id="1", completa=True)
    assert r3.via == "playwright" and len(pw.llamadas) == 1
