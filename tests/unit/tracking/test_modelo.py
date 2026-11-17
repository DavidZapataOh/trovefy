"""Modelo de tracking (plan 19, Tarea 5): dataset «MARCA PAÍS», plantilla UTM literal y un único emisor por evento.

Ruta Hotmart fuera y UTMify sí («DESVÍOS RESUELTOS», cabecera del plan 19): `worker` no es emisor válido.
"""

import pytest
from trovefy.landing.qa import PARES_PUBLICADA
from trovefy.tracking.modelo import (
    EVENTOS,
    PLANTILLA_UTM,
    emisores_por_defecto,
    nombre_dataset,
    utm_de_prueba,
    validar_emisores,
)

P = "p-0099-prueba-abc123"


def test_plantilla_utm_literal():
    assert PLANTILLA_UTM == (
        "utm_source=fb&utm_medium=paid&utm_campaign={{campaign.name}}|{{campaign.id}}"
        "&utm_term={{adset.name}}|{{adset.id}}&utm_content={{ad.name}}|{{ad.id}}"
    )
    assert EVENTOS == ("PageView", "ViewContent", "InitiateCheckout", "Purchase")


def test_utm_de_prueba_igual_a_utm_publicada():
    pares = utm_de_prueba()
    assert pares == PARES_PUBLICADA
    assert "fbclid" not in pares
    pares["utm_source"] = "otro"  # copia: no toca la constante del 18
    assert utm_de_prueba() == PARES_PUBLICADA


def test_nombre_dataset():
    assert nombre_dataset("Somatix", P, "BG") == "SOMATIX BG"
    # Cirílico con la tabla oficial búlgara (2009): щ → sht, ъ → a, ж → zh, ю → yu, я → ya.
    assert nombre_dataset("Щастливо тяло", P, "bg") == "SHTASTLIVO TYALO BG"
    assert nombre_dataset("Жълт юг", P, "BG") == "ZHALT YUG BG"
    assert nombre_dataset("  Sôma—Lab!! ", P, "BG") == "SOMA LAB BG"
    largo = nombre_dataset("Палитра " * 20, P, "BG")
    assert len(largo) <= 50 and largo.endswith(" BG") and "  " not in largo


def test_nombre_dataset_sin_marca():
    assert nombre_dataset(None, P, "ZZ") == "PRUEBA ABC123 ZZ"
    assert nombre_dataset("   ", P, "ZZ") == "PRUEBA ABC123 ZZ"
    with pytest.raises(ValueError):
        nombre_dataset("Somatix", P, "Bulgaria")


def test_emisores_landing_en_impultienda():
    tabla = emisores_por_defecto("impultienda", "impultienda")
    assert tabla == {e: "impultienda" for e in EVENTOS}
    assert validar_emisores(tabla) == []


def test_emisores_landing_cloudflare():
    tabla = emisores_por_defecto("impultienda", "cloudflare")
    assert tabla == {"PageView": "landing", "ViewContent": "landing",
                     "InitiateCheckout": "impultienda", "Purchase": "impultienda"}
    assert validar_emisores(tabla) == []


def test_emisores_sin_hosting():
    with pytest.raises(ValueError, match="hosting"):
        emisores_por_defecto("impultienda", None)


def test_dos_emisores_es_problema():
    tabla = {**emisores_por_defecto("impultienda", "cloudflare"), "Purchase": ["impultienda", "landing"]}
    problemas = validar_emisores(tabla)
    assert any("Purchase" in p and "dos emisores" in p for p in problemas)


def test_worker_fuera_de_hotmart():
    tabla = {**emisores_por_defecto("impultienda", "impultienda"), "Purchase": "worker"}
    assert any("worker" in p for p in validar_emisores(tabla))
    with pytest.raises(ValueError, match="Hotmart"):
        emisores_por_defecto("hotmart", "cloudflare")


def test_falta_evento_o_emisor_raro():
    tabla = emisores_por_defecto("impultienda", "impultienda")
    del tabla["InitiateCheckout"]
    assert any("InitiateCheckout" in p for p in validar_emisores(tabla))
    assert any("pixel_propio" in p for p in validar_emisores({**tabla, "InitiateCheckout": "pixel_propio"}))
    assert any("Purchase" in p for p in validar_emisores({**tabla, "InitiateCheckout": "impultienda",
                                                          "Purchase": "ninguno"}))
    assert any("Otro" in p for p in validar_emisores({**tabla, "InitiateCheckout": "impultienda",
                                                      "Otro": "impultienda"}))


# --- ronda de revisión (L-7, L-8) ----------------------------------------------------------------------------------


def test_ия_final_es_ia():
    # Ley de transliteración búlgara: «-ия» a final de palabra → «ia» (София → Sofia).
    assert nombre_dataset("София", P, "BG") == "SOFIA BG"
    assert nombre_dataset("Енергия плюс", P, "BG") == "ENERGIA PLYUS BG"
    assert nombre_dataset("Ияна", P, "BG") == "IYANA BG"  # dentro de palabra, la regla general


@pytest.mark.parametrize("marca", ["Ёжик", "Мысль", "Київ", "Ґанок", "Эра", "Њива", "Ўсход"])
def test_cirilico_no_bulgaro_se_rechaza(marca):
    with pytest.raises(ValueError, match="cirílic"):
        nombre_dataset(marca, P, "BG")


def test_llamadas_pixel_en_html():
    from trovefy.tracking.modelo import llamadas_pixel

    html = """<script>!function(f,b,e,v,n,t,s){}(window,document,'script',
    'https://connect.facebook.net/en_US/fbevents.js');
    fbq('init', '1111111111111111'); fbq ( "track", "PageView" );</script>
    <noscript><img src="https://www.facebook.com/tr?id=1111111111111111&ev=PageView&noscript=1"/></noscript>
    <p>fbqueue no es una llamada</p>"""
    llamadas = llamadas_pixel(html)
    assert len([x for x in llamadas if x.startswith("fbq(")]) == 2
    assert any("fbevents.js" in x for x in llamadas)
    assert any("facebook.com/tr" in x for x in llamadas)
    assert llamadas_pixel("<p>Hola, fbqueue y fbq sin paréntesis</p>") == []
