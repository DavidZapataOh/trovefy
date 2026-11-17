from datetime import date
from decimal import Decimal

import pytest
from trovefy.apimart.precios import CREDITO_USD, Precio, elegir_modelo, precio_imagen

from .ayudas import fixture

BASE = "https://api.apimart.ai"
HOY = date(2026, 11, 14)


def precio(v):
    return {"success": True, "data": {"model_name": "gpt-image-2", "resolution_paid_prices": {"1K": v}}}


def precio_(modelo, usd):
    return Precio(modelo, "1k", Decimal(usd), "prueba", HOY)


def explota(*_a, **_k):
    raise AssertionError("no debía llamar a la red")


def test_credito_usd():
    assert Decimal("10.5") / CREDITO_USD == 105


def test_precios_van_sin_clave(tmp_path, respuesta_json):
    abrir = respuesta_json(200, fixture("pricing-gpt-image-2.json"))
    p = precio_imagen(tmp_path, "https://api.apimart.ai", "gpt-image-2", "1k", date(2026, 11, 14), abrir)
    assert p.usd_por_imagen == Decimal("0.0085")
    assert "Authorization" not in abrir.peticiones[0][0].headers
    assert abrir.peticiones[0][0].full_url == f"{BASE}/api/pricing/model?model=gpt-image-2"
    assert p.modelo == "gpt-image-2" and p.resolucion == "1k" and p.fecha == HOY
    assert "/api/pricing/model" in p.fuente


@pytest.mark.parametrize("res,usd", [("2k", "0.015"), ("4k", "0.022")])
def test_otras_resoluciones(tmp_path, respuesta_json, res, usd):
    p = precio_imagen(tmp_path, BASE, "gpt-image-2", res, HOY, respuesta_json(200, fixture("pricing-gpt-image-2.json")))
    assert p.usd_por_imagen == Decimal(usd)


@pytest.mark.parametrize(
    "cuerpo",
    [{}, [], {"data": {}}, precio(0), precio(5), precio(-1), precio(True), precio("0.01"),
     {"data": {"resolution_paid_prices": {"2K": 0.01}}}],
)
def test_pricing_raro_es_none(tmp_path, respuesta_json, cuerpo):
    assert precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, respuesta_json(200, cuerpo)) is None
    assert not (tmp_path / "data" / "cache").exists() or not list((tmp_path / "data" / "cache").iterdir())


@pytest.mark.parametrize("codigo", [404, 500, 503])
def test_pricing_con_error_es_none(tmp_path, respuesta_json, codigo):
    assert precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, respuesta_json(codigo, {})) is None


def test_red_caida_es_none(tmp_path):
    def sin_red(*_a, **_k):
        raise TimeoutError

    assert precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, sin_red) is None


def test_precio_cache_del_dia(tmp_path, respuesta_json):
    p1 = precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, respuesta_json(200, fixture("pricing-gpt-image-2.json")))
    assert (tmp_path / "data/cache/apimart-precio-gpt-image-2-2026-11-14.json").is_file()
    p2 = precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, explota)
    assert p2 == p1
    # otra resolución sale de la misma caché del día
    assert precio_imagen(tmp_path, BASE, "gpt-image-2", "2k", HOY, explota).usd_por_imagen == Decimal("0.015")


def test_cache_de_otro_dia_no_vale(tmp_path, respuesta_json):
    precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, respuesta_json(200, fixture("pricing-gpt-image-2.json")))
    abrir = respuesta_json(200, precio(0.009))
    assert precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", date(2026, 11, 15), abrir).usd_por_imagen == Decimal("0.009")
    assert len(abrir.peticiones) == 1


def test_cache_rota_se_vuelve_a_pedir(tmp_path, respuesta_json):
    ruta = tmp_path / "data/cache/apimart-precio-gpt-image-2-2026-11-14.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{roto")
    p = precio_imagen(tmp_path, BASE, "gpt-image-2", "1k", HOY, respuesta_json(200, fixture("pricing-gpt-image-2.json")))
    assert p.usd_por_imagen == Decimal("0.0085")


@pytest.mark.parametrize("modelo", ["../x", "a/b", "", "gpt image"])
def test_modelo_mal_escrito(tmp_path, modelo):
    with pytest.raises(ValueError):
        precio_imagen(tmp_path, BASE, modelo, "1k", HOY, explota)


def test_resolucion_mal_escrita(tmp_path):
    with pytest.raises(ValueError):
        precio_imagen(tmp_path, BASE, "gpt-image-2", "8k", HOY, explota)


def test_elegir_mas_barato():
    a, b = precio_("gpt-image-2", "0.0085"), precio_("otro", "0.0060")
    assert elegir_modelo([a, None, b]) is b and elegir_modelo([None]) is None


def test_elegir_desempata_por_orden():
    a, b = precio_("a", "0.0085"), precio_("b", "0.0085")
    assert elegir_modelo([a, b]) is a and elegir_modelo([]) is None
