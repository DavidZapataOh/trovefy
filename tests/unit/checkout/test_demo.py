"""Recorrido de comprador en modo demo (plan 19, Tarea 13): landing → botón → checkout → oferta post-compra.

Página de Playwright de mentira (sirve las fixtures por URL); ningún navegador, ninguna red. El recorrido nunca
escribe en el formulario ni pulsa «pagar»: la página falsa falla el test si alguien lo intenta.
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, TIENDA, P, vault_embudo
from trovefy import cli, navegador
from trovefy.checkout.demo import (
    PASOS_FIJOS,
    ejecutar_demo,
    escribir_embudo,
    estado_embudo,
    recorrer,
    validar_upsell_demo,
)
from trovefy.embudo.contexto import cargar_contexto, ruta_pais
from trovefy.tracking.modelo import utm_de_prueba
from trovefy.vault import frontmatter
from trovefy.vault.producto import ruta_producto

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "checkout"
AHORA = datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
DEMO = TIENDA + "/post-purchase/demo?t=tokendemo123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _html(nombre: str) -> str:
    return (FIX / nombre).read_text(encoding="utf-8")


class _Localizador:
    def __init__(self, pagina, selector):
        self.pagina, self.selector = pagina, selector

    @property
    def first(self):
        return self

    def count(self):
        es_landing = urlsplit(self.pagina.url).path in ("", "/")
        return 1 if self.selector == "a[data-tf-checkout]" and es_landing else 0

    def get_attribute(self, nombre):
        return "/checkout" if nombre == "href" else None

    def click(self, **_):
        self.pagina.clics.append(self.selector)
        query = urlsplit(self.pagina.url).query if self.pagina.conserva_utm else ""
        self.pagina.url = TIENDA + "/checkout" + (f"?{query}" if query else "")

    def __getattr__(self, nombre):
        if nombre in ("fill", "type", "press", "check", "select_option", "set_input_files", "tap", "dblclick"):
            return lambda *a, **k: pytest.fail(f"el recorrido intentó {nombre} en {self.selector}")
        raise AttributeError(nombre)


class _Pagina:
    def __init__(self, checkout: str = "checkout-eur.html", conserva_utm: bool = True):
        self.checkout = checkout
        self.conserva_utm = conserva_utm
        self.url = "about:blank"
        self.clics: list[str] = []
        self.visitadas: list[str] = []
        self.context = SimpleNamespace(route=lambda *a: None, on=lambda *a: None, route_web_socket=lambda *a: None)

    def goto(self, url, **_):
        self.url = url
        self.visitadas.append(url)
        return SimpleNamespace(status=200)

    def locator(self, selector):
        return _Localizador(self, selector)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, _ms):
        pass

    def evaluate(self, *_a):
        return 0

    def content(self):
        ruta = urlsplit(self.url).path
        if ruta in ("", "/"):
            return _html("landing.html")
        if ruta == "/checkout":
            return _html(self.checkout)
        if ruta == "/post-purchase/demo":
            return _html("upsell.html")
        return "<html><body>404</body></html>"

    def screenshot(self, path=None, **_):
        Path(path).write_bytes(PNG)

    def __getattr__(self, nombre):
        if nombre in ("fill", "type", "press", "check", "select_option", "click", "tap", "dispatch_event"):
            return lambda *a, **k: pytest.fail(f"el recorrido intentó page.{nombre}")
        raise AttributeError(nombre)


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    return v, cargar_contexto(v, P, PAIS)


def _recorrer(ctx, pagina, demo=DEMO, **kw):
    capturas = ruta_pais(ctx) / "demo"
    return recorrer(pagina, ctx, capturas, demo, esperar=lambda host: None, **kw)


def _por_clave(pasos):
    return {p.clave: p for p in pasos}


def test_demo_completa_ok(zz):
    _v, ctx = zz
    pasos = _recorrer(ctx, _Pagina())
    assert [p.clave for p in pasos] == [*PASOS_FIJOS, "upsell_u1"]
    malos = [(p.clave, p.detalle) for p in pasos if p.estado != "ok"]
    assert malos == []
    assert estado_embudo(pasos) == "ok"
    assert _por_clave(pasos)["checkout_precio"].captura == "checkout/ZZ/demo/demo-checkout.png"
    assert (ruta_pais(ctx) / "demo" / "demo-checkout.png").is_file()


def test_utm_perdidos_falla(zz):
    _v, ctx = zz
    pasos = _por_clave(_recorrer(ctx, _Pagina(conserva_utm=False)))
    assert pasos["checkout_utm"].estado == "falla"
    assert "utm_source" in pasos["checkout_utm"].detalle


def test_precio_distinto_falla(zz, tmp_path):
    _v, ctx = zz
    raro = tmp_path / "raro.html"
    raro.write_text(_html("checkout-eur.html").replace('value="13.9"', 'value="15.9"'), encoding="utf-8")
    pagina = _Pagina()
    pagina.content = lambda: raro.read_text(encoding="utf-8") if "/checkout" in pagina.url else _html("landing.html")
    pasos = _por_clave(_recorrer(ctx, pagina, demo=None))
    assert pasos["checkout_precio"].estado == "falla"


def test_idioma_distinto_falla(zz, tmp_path):
    _v, ctx = zz
    espanol = (_html("checkout-usd.html").replace('value="USD"', 'value="EUR"').replace('value="15.29"', 'value="13.9"')
               .replace('id="buyer-country" value="CO"', 'id="buyer-country" value="ZZ"')
               .replace('value="es-419"', 'value="es"'))
    pagina = _Pagina()
    pagina.content = lambda: espanol if "/checkout" in pagina.url else _html("landing.html")
    pasos = _por_clave(_recorrer(ctx, pagina, demo=None))
    assert pasos["checkout_precio"].estado == "ok"
    assert pasos["checkout_idioma"].estado == "falla"


def test_bump_y_apellido_fallan(zz):
    _v, ctx = zz
    pasos = _por_clave(_recorrer(ctx, _Pagina(checkout="checkout-con-apellido.html")))
    assert pasos["campos"].estado == "falla" and "apellido" in pasos["campos"].detalle
    assert pasos["sin_bump"].estado == "falla"


def test_demo_no_pulsa_pagar(zz):
    _v, ctx = zz
    pagina = _Pagina()
    _recorrer(ctx, pagina)
    assert pagina.clics == ["a[data-tf-checkout]"]
    assert not any("fbclid" in u for u in pagina.visitadas)


def test_landing_con_utm_de_prueba(zz):
    _v, ctx = zz
    pagina = _Pagina()
    _recorrer(ctx, pagina)
    pares = {k: x[0] for k, x in parse_qs(urlsplit(pagina.visitadas[0]).query).items()}
    assert pares == utm_de_prueba()


def test_upsell_demo_otro_host_rechazado(zz):
    _v, ctx = zz
    for malo in ("https://otro.example/post-purchase/demo?t=x", TIENDA + "/post-purchase/pagar?t=x",
                 "http://prueba.impultienda.example/post-purchase/demo?t=x"):
        with pytest.raises(ValueError):
            validar_upsell_demo(malo, ctx)
    pagina = _Pagina()
    pasos = _por_clave(_recorrer(ctx, pagina, demo="https://otro.example/post-purchase/demo?t=x"))
    assert pasos["upsell_u1"].estado == "falla"
    assert not any("otro.example" in u for u in pagina.visitadas)


def test_sin_enlace_demo_incompleto(zz):
    _v, ctx = zz
    pasos = _recorrer(ctx, _Pagina(), demo=None)
    assert _por_clave(pasos)["upsell_u1"].estado == "no_medido"
    assert estado_embudo(pasos) == "incompleto"


def test_upsell_sin_guion_falla(zz, tmp_path):
    _v, ctx = zz
    pagina = _Pagina()
    sin_guion = _html("upsell.html").replace("<!-- guion: garantia -->", "")
    original = pagina.content
    pagina.content = lambda: sin_guion if "post-purchase" in pagina.url else original()
    pasos = _por_clave(_recorrer(ctx, pagina))
    assert pasos["upsell_u1"].estado == "falla"
    assert "garantia" in pasos["upsell_u1"].detalle


def _producto_con_qa(v):
    ruta = ruta_producto(v, P)
    meta, cuerpo = frontmatter.leer(ruta)
    meta["paises"][PAIS]["landing"] = {"url": TIENDA + "/", "qa": {
        "archivo": f"landing/{PAIS}/QA-publicada.md", "version": "v1",
        "utm_checkout": {"ok": True, "destino": TIENDA + "/checkout", "captura": None, "interceptado": True,
                         "fuente": f"landing/{PAIS}/QA-publicada.md"}}}
    frontmatter.escribir(ruta, meta, cuerpo)


def test_upsell_demo_sin_query_en_embudo(zz):
    v, ctx = zz
    ruta = escribir_embudo(v, ctx, _recorrer(ctx, _Pagina()), ahora=AHORA)
    texto = ruta.read_text(encoding="utf-8")
    assert ruta == ruta_pais(ctx) / "embudo.md"
    assert "/post-purchase/demo" in texto
    assert "tokendemo123" not in texto and "demo?t=" not in texto
    meta, _ = frontmatter.leer(ruta)
    assert meta["estado"] == "ok"


def test_utm_checkout_sobrescribe_interceptado(zz):
    v, ctx = zz
    _producto_con_qa(v)
    escribir_embudo(v, ctx, _recorrer(ctx, _Pagina()), ahora=AHORA)
    meta, _ = frontmatter.leer(ruta_producto(v, P))
    qa = meta["paises"][PAIS]["landing"]["qa"]
    utm = qa["utm_checkout"]
    assert utm["interceptado"] is False
    assert utm["ok"] is True
    assert utm["fuente"] == f"checkout/{PAIS}/embudo.md"
    assert utm["captura"] == f"checkout/{PAIS}/demo/demo-checkout.png"
    assert utm["destino"].startswith(TIENDA + "/checkout?") and "utm_source=fb" in utm["destino"]
    assert qa["version"] == "v1"  # el resto de landing.qa se conserva


def test_demo_usa_perfil_vacio(zz, monkeypatch):
    _v, ctx = zz
    llamadas = []

    @contextmanager
    def sesion(servicio, visible=True, perfil_persistente=True, viewport=None, **kw):
        llamadas.append((servicio, visible, perfil_persistente, viewport))
        yield _Pagina()

    monkeypatch.setattr(navegador, "sesion", sesion)
    monkeypatch.setattr(importlib.import_module("trovefy.checkout.fuera"), "_esperar", lambda host: None)
    pasos = ejecutar_demo(ctx, ruta_pais(ctx) / "demo", DEMO)
    assert llamadas == [("comprador", False, False, (390, 844))]
    assert estado_embudo(pasos) == "ok"


def test_cli_demo(zz, monkeypatch, capsys):
    v, ctx = zz
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr(importlib.import_module("trovefy.checkout_cli"), "_ahora", lambda: AHORA)
    monkeypatch.setattr(importlib.import_module("trovefy.checkout.fuera"), "_esperar", lambda host: None)

    @contextmanager
    def sesion(servicio, visible=True, perfil_persistente=True, viewport=None, **kw):
        assert (servicio, perfil_persistente) == ("comprador", False)
        yield _Pagina()

    monkeypatch.setattr(navegador, "sesion", sesion)
    assert cli.main(["checkout", "demo", "--producto", P, "--pais", PAIS, "--upsell-demo", DEMO]) == 0
    assert (ruta_pais(ctx) / "embudo.md").is_file()
    assert "tokendemo123" not in capsys.readouterr().out
    assert cli.main(["checkout", "demo", "--producto", P, "--pais", PAIS, "--upsell-demo",
                     "https://otro.example/post-purchase/demo?t=x"]) == 2


def test_guion_por_texto_sin_comentarios(zz):
    """La página publicada no lleva los comentarios del guion: los puntos se reconocen por su título visible."""
    from trovefy.checkout.demo import guion_por_texto

    _v, ctx = zz
    md = "".join(f"<!-- guion: {c} -->\n## Título {c}\n\nТекст.\n\n" for c in ("gracias", "problema", "oferta"))
    (ruta_pais(ctx) / "upsells").mkdir(parents=True, exist_ok=True)
    (ruta_pais(ctx) / "upsells" / "u1.md").write_text(md, encoding="utf-8")
    texto = "Título gracias Текст. Título problema Текст. Título oferta"
    assert guion_por_texto(ctx, "u1", texto) == ["gracias", "problema", "oferta"]
    assert guion_por_texto(ctx, "u1", "Título oferta  Título gracias") == ["oferta", "gracias"]
    assert guion_por_texto(ctx, "u2", texto) == []


def test_enlace_demo_en_el_dominio_propio(zz):
    _v, ctx = zz
    propio = SimpleNamespace(**{**vars(ctx), "landing_hosting": "impultienda",
                                "landing_url": "https://www.mitienda-demo.test/"})
    url = "https://mitienda-demo.test/post-purchase/demo?t=abc"
    assert validar_upsell_demo(url, propio) == url
