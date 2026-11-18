"""Comprobación del checkout público desde fuera (plan 19, Tarea 12).

Sin red y sin navegador: el HTML del checkout ya pintado (con ``data-tf-oculto`` en lo que no se ve) sale de
``tests/fixtures/checkout/``; el navegador real solo corre en ``tests/integracion``. Tienda ficticia.
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, TIENDA, P, vault_embudo
from trovefy import cli, navegador
from trovefy.checkout.fuera import (
    EstadoFuera,
    Vista,
    analizar,
    comprobar_fuera,
    estado_global,
    leer_precio,
    politica_red,
    ver_como_url,
)
from trovefy.checkout.receta import OpcionesReceta, ajustes_de_checkout
from trovefy.embudo.contexto import cargar_contexto, ruta_pais
from trovefy.embudo.pegado import dicho, guardar_pegado, indice
from trovefy.mapa import cargar, limites_de_plan
from trovefy.vault import frontmatter

RAIZ = Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests" / "fixtures" / "checkout"
MAX = limites_de_plan(cargar(RAIZ / "templates/impultienda/mapa.yaml"), "Max")
CHECKOUT = TIENDA + "/checkout"
AHORA = datetime(2026, 11, 17, 12, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _html(nombre: str) -> str:
    return (FIX / nombre).read_text(encoding="utf-8")


def _pagina(nombre: str, url: str = CHECKOUT):
    return analizar(url, Vista(url, 200, _html(nombre)))


@pytest.fixture
def zz(tmp_path):
    v = vault_embudo(tmp_path)
    prod = v / "productos" / P
    (prod / "entregable" / "medios").mkdir(parents=True, exist_ok=True)
    (prod / "entregable" / "medios" / "mockup.png").write_bytes(PNG)
    ctx = cargar_contexto(v, P, PAIS)
    return v, ctx


def _ajustes(ctx, **opciones):
    return ajustes_de_checkout(ctx, MAX, {}, OpcionesReceta("Max", **opciones))[0]


def _por_clave(estados: list[EstadoFuera]) -> dict[str, EstadoFuera]:
    return {e.clave: e for e in estados}


def _captura(v, ctx, clave: str, valores: dict, tmp_path: Path, n: int = 0):
    origen = tmp_path / f"c{n}.png"
    origen.write_bytes(PNG)
    return guardar_pegado(v, ctx, clave, origen, valores, AHORA.replace(second=n))


# --- lectura de la página ------------------------------------------------------------------------------------


def test_analizar_solo_lo_visible():
    p = _pagina("checkout-eur.html")
    assert p.campos_obligatorios == ("email", "nombre", "telefono")
    assert (p.moneda_vista, p.precio_visto, p.pais_visto) == ("EUR", Decimal("13.90"), "ZZ")
    assert p.foto_arriba and not p.bump
    assert "09:59" not in p.texto and "Остават" not in p.texto and "купуват" not in p.texto
    assert p.escasez == ()


def test_leer_precio():
    assert leer_precio("13,90 €") == (Decimal("13.90"), "EUR")
    assert leer_precio("EUR 13.9") == (Decimal("13.90"), "EUR")
    assert leer_precio("US$ 15,29") == (Decimal("15.29"), "USD")
    assert leer_precio("1.234,50 €") == (Decimal("1234.50"), "EUR")
    assert leer_precio("sin precio") == (None, None)


def test_ver_como_url():
    assert ver_como_url(CHECKOUT, "ZZ") == CHECKOUT + "?edit=1&preview_country=ZZ"
    assert ver_como_url(CHECKOUT + "?p=1", "ZZ") == CHECKOUT + "?p=1&edit=1&preview_country=ZZ"


# --- comprobar_fuera -------------------------------------------------------------------------------------------


def test_checkout_publico_ok(zz):
    _v, ctx = zz
    estados = comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-eur.html"), {})
    malos = [e for e in estados if e.estado != "ok"]
    assert malos == []
    claves = {e.clave for e in estados}
    assert {"producto.front.precio", "checkout.idioma", "checkout.campos", "checkout.escasez", "checkout.bump",
            "checkout.foto", "producto.front.titulo"} <= claves
    assert all(e.fuente == "fuera" for e in estados)
    assert estado_global(estados) == "completo"


def test_checkout_en_usd_pide_ver_como(zz):
    _v, ctx = zz
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-usd.html"), {}))
    precio = e["producto.front.precio"]
    assert precio.estado == "no_medido"
    assert "USD" in precio.detalle and "Ver como" in precio.detalle and "V1 0:31:50" in precio.detalle
    assert e["checkout.idioma"].estado == "no_medido"
    assert estado_global(list(e.values())) == "a_medias"


def test_vista_publica_como_el_pais_cierra_precio(zz):
    _v, ctx = zz
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-usd.html"), {},
                                   ver_como=_pagina("checkout-eur.html", ver_como_url(CHECKOUT, PAIS))))
    assert e["producto.front.precio"].estado == "ok"
    assert e["producto.front.precio"].fuente == "fuera"
    assert "preview_country" in e["producto.front.precio"].evidencia
    assert e["checkout.idioma"].estado == "ok"


def test_vista_como_ignorada_no_mide(zz):
    _v, ctx = zz
    ignorada = _pagina("checkout-usd.html", ver_como_url(CHECKOUT, PAIS))  # la tienda sigue viendo CO
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-usd.html"), {}, ver_como=ignorada))
    assert e["producto.front.precio"].estado == "no_medido"


def test_precio_distinto_falla(zz):
    _v, ctx = zz
    html = _html("checkout-eur.html").replace('value="13.9"', 'value="14"')
    pagina = analizar(CHECKOUT, Vista(CHECKOUT, 200, html))
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), pagina, {}))
    assert e["producto.front.precio"].estado == "falla"
    assert "14" in e["producto.front.precio"].visto


def test_ver_como_pegado_cierra_precio(zz, tmp_path):
    v, ctx = zz
    ajustes = _ajustes(ctx)
    _captura(v, ctx, "ver-como", {"precio": "13,90 €"}, tmp_path)
    idx = indice(v, ctx)
    sin_relectura = _por_clave(comprobar_fuera(ctx, ajustes, _pagina("checkout-usd.html"), idx))
    assert sin_relectura["producto.front.precio"].estado == "no_medido"
    assert "relectura" in sin_relectura["producto.front.precio"].detalle
    relecturas = [SimpleNamespace(ajuste=f"market.{PAIS}.moneda", estado="ok"),
                  SimpleNamespace(ajuste=next(a for a in ajustes if a.clave == "producto.front.precio"),
                                  estado="ok")]
    e = _por_clave(comprobar_fuera(ctx, ajustes, _pagina("checkout-usd.html"), idx, relecturas=relecturas))
    assert e["producto.front.precio"].estado == "captura"
    assert e["producto.front.precio"].evidencia.startswith("checkout/ZZ/evidencia/ver-como-")


def test_ver_como_pegado_con_otro_precio_falla(zz, tmp_path):
    v, ctx = zz
    ajustes = _ajustes(ctx)
    _captura(v, ctx, "ver-como", {"precio": "14,00 €"}, tmp_path)
    relecturas = [SimpleNamespace(ajuste="producto.front.precio", estado="ok")]
    e = _por_clave(comprobar_fuera(ctx, ajustes, _pagina("checkout-usd.html"), indice(v, ctx),
                                   relecturas=relecturas))
    assert e["producto.front.precio"].estado == "falla"


def test_ver_como_dicho_no_cierra_precio(zz):
    v, ctx = zz
    dicho(v, ctx, "ver-como", "Lo vi como Bulgaria y sale 13,90 €", AHORA)
    relecturas = [SimpleNamespace(ajuste="producto.front.precio", estado="ok")]
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-usd.html"), indice(v, ctx),
                                   relecturas=relecturas))
    assert e["producto.front.precio"].estado == "no_medido"


def test_campo_telefono_de_mas_falla(zz):
    _v, ctx = zz
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx, telefono=False), _pagina("checkout-eur.html"), {}))
    assert e["checkout.campos"].estado == "falla"
    assert "telefono" in e["checkout.campos"].detalle


def test_sin_telefono_falla(zz):
    _v, ctx = zz
    html = _html("checkout-eur.html").replace('<label>Телефон *</label>\n  <input type="tel"',
                                              '<label data-tf-oculto="1">Телефон *</label>\n  <input data-tf-oculto="1" type="tel"')
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), analizar(CHECKOUT, Vista(CHECKOUT, 200, html)), {}))
    assert e["checkout.campos"].estado == "falla"
    assert "no pide" in e["checkout.campos"].detalle and "telefono" in e["checkout.campos"].detalle


def test_apellido_bump_titulo_y_boton_fallan(zz):
    _v, ctx = zz
    e = _por_clave(comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-con-apellido.html"), {}))
    assert e["checkout.campos"].estado == "falla" and "apellido" in e["checkout.campos"].detalle
    assert e["checkout.bump"].estado == "falla"
    assert e["producto.front.titulo"].estado == "falla"
    assert e["checkout.boton"].estado == "falla"


def test_escasez_para(zz):
    _v, ctx = zz
    estados = comprobar_fuera(ctx, _ajustes(ctx), _pagina("checkout-con-reloj.html"), {})
    e = _por_clave(estados)
    assert e["checkout.escasez"].estado == "parado"
    assert "06:59" in e["checkout.escasez"].detalle
    assert "души" in e["checkout.escasez"].detalle
    assert estado_global(estados) == "parado"


def test_redireccion_no_mide(zz):
    _v, ctx = zz
    pagina = analizar(CHECKOUT, Vista(TIENDA + "/", 200, _html("checkout-eur.html")))
    estados = comprobar_fuera(ctx, _ajustes(ctx), pagina, {})
    assert {e.estado for e in estados} == {"no_medido"}
    assert "redirige" in estados[0].detalle


# --- red del navegador --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("url", "metodo", "esperado"), [
    (CHECKOUT, "GET", "seguir"),
    ("https://fonts.googleapis.com/css2?family=Inter", "GET", "seguir"),
    (CHECKOUT, "POST", "abortar"),
    ("https://sb.impultienda.example/rest/v1/visits", "POST", "abortar"),
    ("https://sb.impultienda.example/functions/v1/impulpay-prepare", "GET", "abortar"),
    ("https://cdn.whop.com/elements/amber/elements.js", "GET", "abortar"),
    ("https://js.stripe.com/v3/", "GET", "abortar"),
    ("https://www.paypal.com/sdk/js", "GET", "abortar"),
    ("https://www.mercadopago.com.ar/checkout", "GET", "abortar"),
    ("https://connect.facebook.net/en_US/fbevents.js", "GET", "abortar"),
    ("https://www.facebook.com/tr?id=1", "GET", "abortar"),
    ("https://www.clarity.ms/tag/x", "GET", "abortar"),
    (CHECKOUT + "?fbclid=x", "GET", "abortar"),
])
def test_politica_red(url, metodo, esperado):
    assert politica_red(url, metodo) == esperado


# --- CLI ------------------------------------------------------------------------------------------------------


class _Pagina:
    """Una página de Playwright de mentira: sirve el HTML de las fixtures según la URL."""

    def __init__(self, servir):
        self.servir = servir
        self.url = "about:blank"
        self.rutas = []
        self.context = SimpleNamespace(route=lambda patron, f: self.rutas.append(f), on=lambda *a: None,
                                       route_web_socket=lambda *a: None)

    def goto(self, url, **_):
        self.url = url
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_load_state(self, *a, **k):
        pass

    def evaluate(self, _js, *a):
        return None

    def content(self):
        return self.servir(self.url)


@pytest.fixture
def vault_cli(zz, monkeypatch):
    v, ctx = zz
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    checkout_cli = importlib.import_module("trovefy.checkout_cli")
    monkeypatch.setattr(checkout_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(importlib.import_module("trovefy.checkout.fuera"), "_esperar", lambda host: None)
    return v, ctx


def _sesion_falsa(monkeypatch, servir):
    llamadas = []

    @contextmanager
    def sesion(servicio, visible=True, perfil_persistente=True, viewport=None, **kw):
        llamadas.append((servicio, perfil_persistente, visible))
        yield _Pagina(servir)

    monkeypatch.setattr(navegador, "sesion", sesion)
    for prohibida in ("abrir", "capturar"):
        monkeypatch.setattr(navegador, prohibida,
                            lambda *a, _n=prohibida, **k: pytest.fail(f"navegador.{_n} abre un panel"))
    return llamadas


def _servir_por_pais(url: str) -> str:
    return _html("checkout-eur.html" if "preview_country=ZZ" in url else "checkout-usd.html")


def test_comprobar_no_abre_panel(vault_cli, monkeypatch, capsys):
    _v, _ctx = vault_cli
    llamadas = _sesion_falsa(monkeypatch, _servir_por_pais)
    cli.main(["checkout", "comprobar", "--producto", P, "--pais", PAIS])
    assert llamadas, "no leyó el checkout público"
    assert all(servicio == "comprador" and persistente is False and visible is False
               for servicio, persistente, visible in llamadas)
    assert not any(s in ("impultienda", "meta", "hotmart", "whop") for s, _, _ in llamadas)


def test_comprobacion_md_a_medias_con_manual(vault_cli, monkeypatch, capsys):
    _v, ctx = vault_cli
    _sesion_falsa(monkeypatch, _servir_por_pais)
    codigo = cli.main(["checkout", "comprobar", "--producto", P, "--pais", PAIS])
    assert codigo == 1
    ruta = ruta_pais(ctx) / "COMPROBACION.md"
    meta, cuerpo = frontmatter.leer(ruta)
    assert meta["estado"] == "a_medias"
    assert meta["url"] == CHECKOUT
    por_clave = {e["clave"]: e for e in meta["estados"]}
    assert por_clave["producto.front.precio"]["estado"] == "ok"  # por la vista pública como ZZ
    assert por_clave["checkout.plantilla"]["estado"] == "no_medido"  # va a mano y no hay evidencia
    assert "## A mano" in cuerpo and "checkout.plantilla" in cuerpo
    assert "trovefy checkout evidencia" in capsys.readouterr().out


def test_comprobacion_completa_con_manual_cerrado(vault_cli, monkeypatch, tmp_path):
    v, ctx = vault_cli
    _sesion_falsa(monkeypatch, _servir_por_pais)
    cli.main(["checkout", "comprobar", "--producto", P, "--pais", PAIS])
    meta, _ = frontmatter.leer(ruta_pais(ctx) / "COMPROBACION.md")
    for e in meta["estados"]:
        if e["estado"] == "no_medido":
            assert e["fuente"] is None
    pendientes = [e["clave"] for e in meta["estados"] if e["estado"] != "ok"]
    from trovefy.checkout.manual import clave_captura
    for n, clave in enumerate(pendientes):
        dicho(v, ctx, clave_captura(clave), f"Hecho en mi panel: {clave}", AHORA.replace(minute=n))
    assert cli.main(["checkout", "comprobar", "--producto", P, "--pais", PAIS]) == 0
    meta, _ = frontmatter.leer(ruta_pais(ctx) / "COMPROBACION.md")
    assert meta["estado"] == "completo"
