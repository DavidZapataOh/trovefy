"""El píxel visto desde la tienda pública (plan 19, Tarea 7): GET sin JS (no dispara eventos), sin sesión."""

import urllib.error
from pathlib import Path

import pytest
from embudo.ejemplos_embudo import PAIS, TIENDA, P, vault_embudo
from trovefy.embudo.contexto import cargar_contexto
from trovefy.tracking.publico import leer_pixel_publico, pixeles_en_html

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "tracking"
DATASET = "1111111111111111"


def _html(nombre: str) -> bytes:
    return (FIX / nombre).read_bytes()


class _Resp:
    def __init__(self, url: str, cuerpo: bytes) -> None:
        self._url, self._cuerpo = url, cuerpo

    def read(self, n: int = -1) -> bytes:
        return self._cuerpo if n < 0 else self._cuerpo[:n]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None


def _abrir(paginas: dict[str, bytes | Exception], finales: dict[str, str] | None = None):
    pedidas: list[str] = []

    def abrir(url, timeout=None):
        pedidas.append(url)
        valor = paginas.get(url, urllib.error.URLError("sin red en los tests"))
        if isinstance(valor, Exception):
            raise valor
        return _Resp((finales or {}).get(url, url), valor)

    abrir.pedidas = pedidas
    return abrir


@pytest.fixture
def ctx(tmp_path):
    return cargar_contexto(vault_embudo(tmp_path), P, PAIS)


def test_pixeles_en_html():
    assert pixeles_en_html(_html("tienda-con-pixel.html").decode()) == {DATASET}
    assert pixeles_en_html(_html("tienda-dos-pixeles.html").decode()) == {DATASET, "5555555555555555"}
    assert pixeles_en_html(_html("tienda-sin-pixel.html").decode()) == set()
    assert pixeles_en_html("fbq('init', '123')") == set()  # menos de 6 dígitos: no es un id
    assert pixeles_en_html('<img src="//www.facebook.com/tr/?ev=PageView&id=987654321">') == {"987654321"}


def test_pixel_publico_ok(ctx):
    abrir = _abrir({TIENDA + "/": _html("tienda-con-pixel.html"), TIENDA + "/checkout": _html("tienda-con-pixel.html")})
    estado, ids, motivo = leer_pixel_publico(ctx, DATASET, abrir=abrir)
    assert (estado, ids, motivo) == ("ok", {DATASET}, None)
    assert abrir.pedidas == [TIENDA + "/", TIENDA + "/checkout"]


def test_pixel_publico_otro(ctx):
    abrir = _abrir({TIENDA + "/": _html("tienda-dos-pixeles.html"), TIENDA + "/checkout": _html("tienda-con-pixel.html")})
    estado, ids, motivo = leer_pixel_publico(ctx, DATASET, abrir=abrir)
    assert estado == "otro" and "5555555555555555" in ids
    assert "5555555555555555" in motivo


def test_pixel_no_visto(ctx):
    abrir = _abrir({TIENDA + "/": _html("tienda-sin-pixel.html"), TIENDA + "/checkout": _html("tienda-sin-pixel.html")})
    estado, ids, motivo = leer_pixel_publico(ctx, DATASET, abrir=abrir)
    assert (estado, ids) == ("no_visto", set())
    assert "JavaScript" in motivo


def test_redireccion_a_otro_host_no_medido(ctx):
    abrir = _abrir({TIENDA + "/": _html("tienda-con-pixel.html"), TIENDA + "/checkout": _html("tienda-con-pixel.html")},
                   finales={TIENDA + "/": "https://otro.example/", TIENDA + "/checkout": "https://otro.example/c"})
    estado, ids, motivo = leer_pixel_publico(ctx, DATASET, abrir=abrir)
    assert estado is None and ids == set() and motivo.startswith("no medido")


def test_sin_red_no_medido(ctx):
    estado, _, motivo = leer_pixel_publico(ctx, DATASET, abrir=_abrir({}))
    assert estado is None and motivo.startswith("no medido")


def test_una_pagina_falla_la_otra_cuenta(ctx):
    abrir = _abrir({TIENDA + "/": _html("tienda-con-pixel.html"),
                    TIENDA + "/checkout": urllib.error.HTTPError(TIENDA + "/checkout", 302, "x", {}, None)})
    estado, _, motivo = leer_pixel_publico(ctx, DATASET, abrir=abrir)
    assert estado == "ok" and "checkout" in motivo


def test_pagina_enorme_no_cuenta(ctx):
    enorme = b"<html>" + b" " * (5 * 1024 * 1024 + 10)
    estado, _, motivo = leer_pixel_publico(ctx, DATASET, abrir=_abrir({TIENDA + "/": enorme, TIENDA + "/checkout": enorme}))
    assert estado is None and motivo.startswith("no medido")


def test_sin_tienda_no_medido(tmp_path):
    v = vault_embudo(tmp_path)
    (v / "config" / "mercados.yaml").write_text(
        'ZZ: {idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo, tienda: null}\n',
        encoding="utf-8")
    ctx = cargar_contexto(v, P, PAIS)
    estado, _, motivo = leer_pixel_publico(ctx, DATASET, abrir=_abrir({}))
    assert estado is None and "tienda" in motivo
