"""Lecturas normalizadas de Meta y de la tienda en USD con TRM (plan 23, Tarea 2)."""
from datetime import date
from decimal import Decimal

import pytest
from trovefy.fx import Cambio
from trovefy.leer import importar
from trovefy.leer.importar import (
    a_usd_tienda,
    cargar_lectura,
    construir_lectura,
    guardar_lectura,
    importar_carritos,
    importar_meta,
    importar_utm,
)
from trovefy.meta.insights import FORMA_DESCONOCIDA, leer_cuenta, leer_insights

from .ejemplos import (
    AHORA,
    CAMPANA,
    PAIS,
    TRAFICO,
    P,
    fx,
    meta_adsets,
    sin_trm,
    trm_de,
    utm,
    vault_test,
)

DIA = date(2026, 11, 19)
CAMBIO = Cambio({"EUR": 1.0, "USD": 1.08}, "2026-11-19")


def _inst(**extra):
    return {"meta-adset": fx("meta-adset.json"), "meta-ad": fx("meta-ad.json"),
            "utm-anuncio": fx("impultienda-utm-anuncio.json"), "carritos": fx("impultienda-carritos.json"), **extra}


def _lectura(trm=trm_de, **extra):
    return construir_lectura(TRAFICO, P, PAIS, _inst(**extra), AHORA, DIA, intradia=False, trm_de=trm,
                             cambio_de=lambda _d: CAMBIO)


def test_importa_fixture_de_adsets():
    filas, motivos = importar_meta(fx("meta-adset.json"), "adset")
    assert len(filas) == 3 and not motivos and all(f.id and f.nivel == "conjunto" for f in filas)
    assert filas[2].pagos_iniciados == 4 and filas[2].compras_pixel == 1 and filas[2].presupuesto_diario == 20000


def test_acciones_dentro_de_actions():
    filas, _ = leer_insights(fx("meta-ad.json"), "ad")
    assert filas[2].compras_pixel == 1 and filas[1].estado_meta == "DISAPPROVED"


def test_forma_rara_no_medido():
    assert leer_insights({"otra": 1}) == ([], [FORMA_DESCONOCIDA])


def test_cuenta_moneda_y_zona():
    datos = {"data": [{"id": "act_0000000000000000", "currency": "COP", "timezone_name": "America/Bogota"}]}
    c = leer_cuenta(datos, "act_0000000000000000")
    assert c.moneda == "COP" and c.zona == "America/Bogota"
    assert leer_cuenta(datos, "act_1") is None


def test_gasto_cop_a_usd_al_alza():
    # 12.345 COP con TRM 4.000 → 3,08625 USD → 309 centavos
    datos = meta_adsets([{"id": "4000000000000001", "insights": {"amount_spent": "12345"}}])
    o = _lectura(**{"meta-adset": datos})
    assert o.conjuntos[0].metricas.gasto_usd_c == 309


def test_gasto_cop_sin_trm_no_medido():
    o = _lectura(trm=sin_trm)
    assert o.gasto_usd_c is None
    assert any(m == "no medido: sin TRM del 2026-11-19" for m in o.motivos)


def test_ventas_de_la_tienda_por_utm_campaign():
    u = importar_utm(fx("impultienda-utm-anuncio.json"), CAMPANA)
    assert u.ventas == 1 and u.bruto == Decimal("13.9") and u.moneda == "EUR"  # la otra campaña no cuenta
    assert u.por_anuncio == {"5000000000000003": (1, Decimal("13.9"))}


def test_dos_monedas_en_la_tienda_no_medido():
    datos = utm([("AD01 G1 mapa", 1, 13.9)])
    datos["structuredContent"]["utm"]["moneda"] = None
    u = importar_utm(datos, CAMPANA)
    assert u.ventas is None and u.motivos[0].startswith("no medido")


def test_carritos_de_la_campana():
    ses, fal, zona, _ = importar_carritos(fx("impultienda-carritos.json"), CAMPANA)
    assert (ses, fal, zona) == (7, 1, "America/Bogota")


def test_eur_a_usd_a_la_baja():
    assert a_usd_tienda(Decimal("13.90"), "EUR", CAMBIO) == Decimal("15.01")  # 15,012
    assert a_usd_tienda(Decimal("13.90"), "EUR", None) is None


def test_angulo_y_ventas_por_anuncio():
    o = _lectura()
    c = {x.nombre: x for x in o.conjuntos}
    assert c["AD03 G1 sueño"].angulo == "sueño" and c["AD03 G1 sueño"].ventas == 1
    assert c["AD01 G1 mapa"].ventas == 0 and c["AD02 G1 villano"].estado_anuncio == "DISAPPROVED"
    assert o.ventas_tienda == 1 and o.bruto_tienda_usd == Decimal("15.01") and o.pi_tienda == 7


def test_lectura_ida_y_vuelta(tmp_path):
    v = vault_test(tmp_path)
    o = _lectura()
    ruta = guardar_lectura(v, o)
    assert ruta.name == "2026-11-19.json"
    assert cargar_lectura(ruta) == o


def test_respuesta_con_token_no_se_guarda(tmp_path, monkeypatch):
    v = vault_test(tmp_path)
    monkeypatch.setattr("trovefy.secretos.buscar_secreto", lambda _t: "token de Meta")
    with pytest.raises(ValueError, match="secreto"):
        guardar_lectura(v, _lectura())
    assert not importar.carpeta_lecturas(v, P, PAIS).exists()
