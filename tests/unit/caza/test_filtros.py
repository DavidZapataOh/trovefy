import dataclasses
import pathlib
from datetime import date

import pytest
from ayudas import anuncio, destino_impultienda
from trovefy import fx
from trovefy.caza import palabras
from trovefy.caza.filtros import ContextoFiltros, banderas, filtrar, precio_bajo
from trovefy.caza.oferta import agrupar, marcar_original
from trovefy.config.umbrales import cargar

U = cargar(pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml")
CTX = ContextoFiltros(set(), set(), U)
D = destino_impultienda()


def oferta(texto="Fișe de terapie PDF, acces imediat", destino=D, ads=None, **kw):
    if ads is None:
        a = dataclasses.replace(anuncio("1", "100", date(2026, 9, 1)), texto=texto)
        ads = [a]
    destinos = {a.enlace_destino: destino for a in ads if destino is not None}
    return marcar_original(agrupar(ads, destinos)[0])


def test_digital_pasa():
    assert filtrar(oferta(), CTX) is None


def test_fisico_se_descarta():
    assert filtrar(oferta("Cápsulas 500 mg, envío gratis, stock limitado"), CTX).codigo == "producto_fisico"


def test_una_palabra_ambigua_no_descarta():
    assert filtrar(oferta("Guía en PDF con envío inmediato por email"), CTX) is None


def test_fisico_sin_acentos_y_mayusculas_en_otros_idiomas():
    assert filtrar(oferta("CAPSULE 500 MG, LIVRAISON GRATUITE"), CTX).codigo == "producto_fisico"
    assert filtrar(oferta("Capsule 500 mg, spedizione gratuita"), CTX).codigo == "producto_fisico"


def test_palabra_dentro_de_otra_no_cuenta():
    # «mg» dentro de «imagen» y «stock» dentro de «livestock» no son señales
    assert filtrar(oferta("Imagen de livestock, mgmt"), CTX) is None


def test_tienda_necesita_tres_senales():
    dos = "Añadir al carrito y pago contra reembolso"
    tres = dos + ", devolución gratuita"
    assert filtrar(oferta(dos), CTX) is None
    assert filtrar(oferta(tres), CTX).codigo == "producto_fisico"


def test_texto_de_la_landing_suma():
    ctx = ContextoFiltros(set(), set(), U, landings={D.url_anuncio: "Tallas disponibles, envío en 24 h"})
    assert filtrar(oferta("Nueva colección"), ctx).codigo == "producto_fisico"


def test_academia_es_bandera_no_descarte():
    o = oferta("Curso con certificado oficial y titulación universitaria")
    assert filtrar(o, CTX) is None and "academia" in banderas(o, CTX)


def test_marca_personal_dos_senales():
    assert filtrar(oferta("Mi método de mentoría personal"), CTX).codigo == "marca_personal"
    assert filtrar(oferta("Mi método para dormir mejor"), CTX) is None


def test_cebo_backend_en_la_landing():
    ctx = ContextoFiltros(set(), set(), U, landings={D.url_anuncio: "Reserva tu llamada de diagnóstico gratuita"})
    assert filtrar(oferta(), ctx).codigo == "cebo_backend"


def test_whatsapp_se_descarta():
    wa = dataclasses.replace(D, red_social=True, url_final="https://wa.me/123")
    assert filtrar(oferta(destino=wa), CTX).codigo == "destino_social"


def test_cloaker_se_documenta():
    assert filtrar(oferta(destino=dataclasses.replace(D, cloaker=True)), CTX).codigo == "cloaker"


def test_cloaker_desconocido_no_descarta():
    assert filtrar(oferta(destino=dataclasses.replace(D, cloaker=None)), CTX) is None


def test_tracker_no_medible():
    assert filtrar(oferta(destino=dataclasses.replace(D, tracker="voluum")), CTX).codigo == "tracker"


def test_no_medido_no_es_valido():
    nm = dataclasses.replace(D, estado="no_medido", motivo="pide login")
    d = filtrar(oferta(destino=nm), CTX)
    assert d.codigo == "embudo_no_verificable" and "pide login" in d.detalle


def test_sin_destino_es_embudo_no_verificable():
    d = filtrar(oferta(destino=None), CTX)
    assert d.codigo == "embudo_no_verificable" and "sin destino" in d.detalle


def test_sin_destino_aun_descarta_por_texto_fisico():
    d = filtrar(oferta("Cápsulas 500 mg, envío gratis", destino=None), CTX)
    assert d.codigo == "producto_fisico"


def test_posible_copia():
    ads = [anuncio("1", "100", date(2026, 8, 1)), anuncio("2", "200", date(2026, 9, 1))]
    o = oferta(ads=ads)
    assert o.origen == "original"
    assert filtrar(o, CTX) is None  # el original pasa
    copia = dataclasses.replace(o, origen="copia")
    assert filtrar(copia, CTX).codigo == "posible_copia"


def test_ya_visto():
    o = oferta()
    assert filtrar(o, ContextoFiltros({o.oferta_id}, set(), U)).codigo == "ya_visto"
    assert filtrar(o, ContextoFiltros(set(), {o.clave}, U)).codigo == "ya_visto"


def test_orden_social_antes_que_fisico():
    wa = dataclasses.replace(D, red_social=True)
    assert filtrar(oferta("Cápsulas 500 mg, envío gratis", destino=wa), CTX).codigo == "destino_social"


def test_saturado_es_bandera():
    ads = [anuncio(str(i), "100", date(2026, 9, 1)) for i in range(150)]
    o = oferta(ads=ads)
    assert "saturado" in banderas(o, CTX) and filtrar(o, CTX) is None
    assert "saturado" not in banderas(oferta(ads=ads[:149]), CTX)


def test_saturado_solo_cuenta_activos():
    ads = [anuncio(str(i), "100", date(2026, 9, 1), activo=(i < 100)) for i in range(150)]
    assert "saturado" not in banderas(oferta(ads=ads), CTX)


def test_estacional():
    assert "estacional" in banderas(oferta("Regalos de Navidad en PDF"), CTX)
    assert "estacional" not in banderas(oferta(), CTX)


@pytest.mark.parametrize("nombre", ["FISICO", "TIENDA", "ACADEMIA", "MARCA_PERSONAL", "BACKEND", "TEMPORADA"])
def test_listas_no_vacias_y_en_seis_idiomas(nombre):
    lista = getattr(palabras, nombre)
    assert isinstance(lista, list) and len(lista) >= 12


@pytest.mark.parametrize("texto", [
    "Envío inmediato por email del PDF. Talla única digital",
    "Kit digital con envío inmediato, stock ilimitado",
    "Patrón de costura PDF, tallas, unidades",
    "Stock photos pack descargable, size 4000px",
    "Planner PDF para tablets, size A4",
    "Ebook de recetas: crema, gotas de limón, unidades",
    "Livraison instantanée du PDF, taille unique",
    "Spedizione immediata via email, taglia unica, PDF",
    "Livrare imediată pe email, marime A4, stoc nelimitat, PDF",
    "Frete imediato por email, tamanho A4, estoque ilimitado, ebook",
    "Garantía de devolución de 30 días. Money back guarantee. Free returns. Ebook PDF",
    "Garantía de 7 días, money back, reembolso total",
])
def test_ofertas_digitales_no_se_descartan(texto):
    assert filtrar(oferta(texto), CTX) is None


def test_camiseta_se_descarta_por_tienda():
    d = filtrar(oferta("Camiseta talla M, devolución gratuita, añadir al carrito"), CTX)
    assert d.codigo == "producto_fisico"


def test_ya_visto_va_primero():
    o = oferta("Cápsulas 500 mg, envío gratis")
    assert filtrar(o, ContextoFiltros({o.oferta_id}, set(), U)).codigo == "ya_visto"
    nm = oferta(destino=dataclasses.replace(D, estado="no_medido", motivo="x"))
    assert filtrar(nm, ContextoFiltros(set(), {nm.clave}, U)).codigo == "ya_visto"


def test_programa_suelto_no_es_marca_personal():
    assert filtrar(oferta("Mi programa y mentoría con plantilla"), CTX) is None


@pytest.mark.parametrize("texto", [
    "Patrón de costura PDF: talla S, talla M, talla L, talla XL incluidas",
    "Cápsulas del tiempo imprimibles, envío inmediato",
    "Stock photos pack con licencia, size 4000px",
    "Plantillas editables en Canva, envío inmediato, stock ilimitado",
    "Printables for kids, free shipping on orders of 3 downloads",
    "Time capsules printables, tablets, size A4",
])
def test_digitales_con_plurales_y_frases_no_senal(texto):
    assert filtrar(oferta(texto), CTX) is None


def test_app_y_zoom_no_son_marcador_digital():
    assert filtrar(oferta("Cápsulas 500 mg, envío, app, zoom"), CTX).codigo == "producto_fisico"
    assert filtrar(oferta("Talla única, envío, app y zoom"), CTX).codigo == "producto_fisico"


# --- mayorista y ropa (caza Brasil 2026-11-11: jeniffermodafitness.com.br pasó como B) --------

JENIFFER = ("Atacado · Leggings · Shorts · Regatas dry fit · Blusas · Macacões · Lançamentos · "
            "Mais vendidos · Promoções")


def test_ropa_al_por_mayor_se_descarta():
    ctx = ContextoFiltros(set(), set(), U, landings={D.url_anuncio: JENIFFER})
    d = filtrar(oferta("Garanta já!"), ctx)
    assert d.codigo == "producto_fisico"
    assert d.detalle == "señales de producto físico o retail: atacado, leggings"


@pytest.mark.parametrize("texto", [
    "Vente en gros de leggings et shorts", "Wholesale leggings and tank tops",
    "Calzas y shorts al por mayor", "Leggings all'ingrosso", "Colanți și blusas en-gros",
    "Mayoreo de blusas y enterizos",
])
def test_mayorista_mas_ropa_en_otros_idiomas(texto):
    assert filtrar(oferta(texto), CTX).codigo == "producto_fisico"


@pytest.mark.parametrize("texto", [
    "Molde de legging em PDF, do 36 ao 46", "Moldes digitais de shorts, regatas e blusas",
    "Lista de fornecedores de atacado em PDF",  # una sola señal fuerte con marcador digital
    "Curso online: viraliza con YouTube Shorts", "Aprenda a gravar shorts do YouTube",
    "En gros, ce PDF t'explique tout",  # «en gros» suelto es «en resumen»: no es señal
])
def test_moldes_digitales_y_frases_ambiguas_pasan(texto):
    assert filtrar(oferta(texto), CTX) is None


def test_una_prenda_sola_no_descarta():
    assert filtrar(oferta("Leggings de regalo para tus alumnas"), CTX) is None


# --- precio de entrada bajo: bandera, nunca descarte (figurinhaspro.online a R$ 5,99) -----------
# La copia se relanza a nuestro precio (banda de mercados.yaml): el precio espiado solo informa.

CAMBIO = fx.Cambio({"EUR": 1.0, "USD": 1.08, "BRL": 6.2}, "2026-11-10")
CTX_FX = ContextoFiltros(set(), set(), U, cambio=CAMBIO)


def _con_precio(precio, moneda, texto="Pacote de figurinhas em PDF para imprimir"):
    return oferta(texto, destino=dataclasses.replace(D, precio=precio, moneda=moneda))


def test_precio_bajo_es_bandera_con_detalle():
    o = _con_precio(5.99, "BRL")
    assert filtrar(o, CTX_FX) is None
    assert "precio_bajo" in banderas(o, CTX_FX)
    assert precio_bajo(o, CTX_FX) == (
        "5,99 BRL ≈ 1,04 USD (cambio de referencia del BCE del 2026-11-10) < 10 USD "
        "(caza.precio.min_usd): la comisión fija de la pasarela se lleva entre 1/6 y 1/3 del precio"
    )


def test_precio_suficiente_sin_bandera():
    assert "precio_bajo" not in banderas(_con_precio(13.9, "EUR"), CTX_FX)  # ≈ 15,01 USD
    assert "precio_bajo" not in banderas(_con_precio(10, "USD"), CTX_FX)  # justo el umbral no es bajo


@pytest.mark.parametrize("precio,moneda,ctx", [
    (5.99, None, CTX_FX),  # «$» ambiguo: moneda desconocida
    (None, None, CTX_FX),  # sin precio visible
    (9000, "COP", CTX_FX),  # el BCE no publica COP: no se inventa un cambio
    (5.99, "BRL", CTX),  # sin cambio del BCE (sin red)
])
def test_precio_no_medido_sin_bandera(precio, moneda, ctx):
    o = _con_precio(precio, moneda)
    assert precio_bajo(o, ctx) is None and "precio_bajo" not in banderas(o, ctx)


def test_precio_bajo_sin_destino_sin_bandera():
    assert "precio_bajo" not in banderas(oferta(destino=None), CTX_FX)


def test_umbral_de_precio_ausente_usa_el_de_la_plantilla():
    # Los cerebros creados antes del 2026-11-11 no tienen caza.precio.min_usd: no rompe y vale 10.
    viejo = {k: v for k, v in U.items() if k != "caza.precio.min_usd"}
    ctx = ContextoFiltros(set(), set(), viejo, cambio=CAMBIO)
    assert "precio_bajo" in banderas(_con_precio(5.99, "BRL"), ctx)
    assert "precio_bajo" not in banderas(_con_precio(9.5, "EUR"), ctx)  # ≈ 10,26 USD


def test_umbral_de_precio_del_cerebro_manda():
    otro = {**U, "caza.precio.min_usd": dataclasses.replace(U["caza.precio.min_usd"], valor=20)}
    ctx = ContextoFiltros(set(), set(), otro, cambio=CAMBIO)
    assert "precio_bajo" in banderas(_con_precio(13.9, "EUR"), ctx)


# --- aparatos (caza EE. UU. 2026-11-11: trymodernhearing.com, audífonos a 249 USD, salió como B) ----

# Extracto saneado del anuncio y de la landing reales (sin nombres de personas).
MODERNHEARING_ANUNCIO = (
    "Same Tech, 95% Less Cost. Thirty-four cents per day. That's what Modern Hearing hearing aids cost "
    "over two years. $249, divided by 730 days. Same Knowles receivers. Same processing chips. "
    "Try Modern Hearing for 45 days at home. Medicare doesn't cover hearing aids."
)
MODERNHEARING_LANDING = (
    "OTC Wireless Hearing Aids · $249 · No doctor visit needed · Wireless charging case · "
    "Battery life 30+ hours · FDA-registered · 45-day risk-free trial · One-year warranty · "
    "Complete package with all accessories"
)


def test_audifonos_se_descartan_por_fisico():
    ctx = ContextoFiltros(set(), set(), U, landings={D.url_anuncio: MODERNHEARING_LANDING})
    d = filtrar(oferta(MODERNHEARING_ANUNCIO), ctx)
    assert d is not None and d.codigo == "producto_fisico"
    assert "hearing aid" in d.detalle and "battery life" in d.detalle


@pytest.mark.parametrize("texto", [
    "OTC wireless hearing aids with wireless charging case",
    "Audífonos recargables: batería recargable y garantía de un año",
    "Aparelhos auditivos com carregamento sem fio e todos os acessórios",
    "Appareils auditifs, boîtier de charge, garantie d'un an",
    "Apparecchi acustici con custodia di ricarica e garanzia di un anno",
    "Aparate auditive cu baterie reîncărcabilă, garanție de un an",
])
def test_aparatos_en_seis_idiomas(texto):
    assert filtrar(oferta(texto), CTX).codigo == "producto_fisico"


@pytest.mark.parametrize("texto", [
    "Battery of tests for speech therapists, printable PDF, instant access",
    "Batería de pruebas de lenguaje en PDF, garantía de 30 días",
    "Bateria de testes em PDF com garantia de 7 dias e acesso imediato",
    "45-day risk-free trial, 30-day money-back guarantee, online course",
    "Curso online para técnicos en audífonos, plantillas descargables",
    "Ebook: how to extend your phone's battery life, instant download",
    "Plantillas digitales de por vida, garantía de 30 días, acceso inmediato",
])
def test_digitales_con_bateria_garantia_o_prueba_pasan(texto):
    assert filtrar(oferta(texto), CTX) is None
