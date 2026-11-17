"""Mapa con controles por pantalla, pantallas prohibidas, confirmación por pantalla y límites del plan."""

from pathlib import Path

import pytest
import yaml
from trovefy.mapa import (
    PALABRAS_PROHIBIDAS,
    Control,
    MapaInvalido,
    capturado_de,
    cargar,
    control,
    hosts_de,
    limites_de_plan,
    origen,
    origenes_de,
    palabra_prohibida,
    prohibida,
)

RAIZ = Path(__file__).resolve().parents[2]

PANTALLA_PRODUCTO = {
    "url": "https://app.ejemplo.test/productos/{id}",
    "firma": ["Editar producto"],
    "controles": {
        "precio": {"etiqueta": "Precio", "rol": "textbox", "tipo": "precio"},
        "entrega": {"css": "input[type=file]", "tipo": "archivo"},
        "guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"},
    },
}

LIMITES = {
    "Free": {"tiendas": 1, "bumps": 1, "upsells": 1, "downsell": False},
    "Pro": {"tiendas": 3, "bumps": 3, "upsells": 3, "downsell": True},
}


def escribir(tmp_path, pantallas, **raiz):
    base = {"capturado": None, "fuente": "documentación https://ejemplo.test 2026-11-10", "pantallas": pantallas}
    base.update(raiz)
    ruta = tmp_path / "mapa.yaml"
    ruta.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    return ruta


def con_controles(**controles):
    return {"producto": {**PANTALLA_PRODUCTO, "controles": controles}}


def test_mapa_fase0_carga_igual():
    m = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    assert capturado_de(m, "plan") is None
    for servicio in ("hotmart", "whop"):
        cargar(RAIZ / f"templates/{servicio}/mapa.yaml")


def test_control_por_etiqueta(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}))
    c = control(m, "producto", "precio")
    assert isinstance(c, Control)
    assert (c.pantalla, c.nombre, c.etiqueta, c.rol, c.css, c.tipo, c.secreto) == (
        "producto", "precio", "Precio", "textbox", None, "precio", False
    )


def test_control_por_css(tmp_path):
    c = control(cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO})), "producto", "entrega")
    assert (c.etiqueta, c.rol, c.css, c.tipo) == (None, None, "input[type=file]", "archivo")


def test_control_secreto(tmp_path):
    m = cargar(escribir(tmp_path, con_controles(token={"etiqueta": "Token", "tipo": "texto", "secreto": True})))
    assert control(m, "producto", "token").secreto is True


def test_control_inexistente_keyerror_en_espanol(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}))
    with pytest.raises(KeyError, match="no tiene el control"):
        control(m, "producto", "nada")
    with pytest.raises(KeyError, match="no hay pantalla"):
        control(m, "otra", "precio")


@pytest.mark.parametrize(
    "malo",
    [
        {"etiqueta": "Precio", "css": "#precio", "tipo": "precio"},  # las dos
        {"tipo": "precio"},  # ninguna
        {"css": "#precio", "rol": "textbox", "tipo": "precio"},  # rol sin etiqueta
        {"etiqueta": "", "tipo": "precio"},
        {"etiqueta": "Precio", "tipo": "precio", "secreto": "sí"},
        {"etiqueta": "Precio", "tipo": "precio", "selector": "#x"},  # clave desconocida
        "Precio",
    ],
)
def test_control_con_estructura_mala_invalido(tmp_path, malo):
    with pytest.raises(MapaInvalido):
        cargar(escribir(tmp_path, con_controles(precio=malo)))


def test_control_con_etiqueta_y_css_invalido(tmp_path):
    with pytest.raises(MapaInvalido, match="etiqueta"):
        cargar(escribir(tmp_path, con_controles(precio={"etiqueta": "Precio", "css": "#p", "tipo": "precio"})))


def test_tipo_desconocido_invalido(tmp_path):
    with pytest.raises(MapaInvalido, match="tipo"):
        cargar(escribir(tmp_path, con_controles(precio={"etiqueta": "Precio", "tipo": "slider"})))


def test_capturado_de_pantalla_con_controles_no_hereda_de_la_raiz(tmp_path):
    # R-1: confirmar el mapa (la raíz, p. ej. con el paso 09) no vuelve escribible una pantalla con controles
    # que nadie ha visto: solo su propio `capturado` cuenta. Las pantallas de solo lectura sí heredan.
    pantallas = {
        "producto": dict(PANTALLA_PRODUCTO),
        "nueva": {**PANTALLA_PRODUCTO, "capturado": None},
        "otra": {**PANTALLA_PRODUCTO, "capturado": "2026-11-21"},
        "lectura": {"url": "https://app.ejemplo.test/inicio", "firma": ["Inicio"]},
    }
    ruta = escribir(tmp_path, pantallas, capturado="2026-11-20")
    m = cargar(ruta)
    assert capturado_de(m, "producto") is None
    assert capturado_de(m, "nueva") is None
    assert capturado_de(m, "otra") == "2026-11-21"
    assert capturado_de(m, "lectura") == "2026-11-20"


def test_capturado_por_pantalla_fecha_yaml_y_mala(tmp_path):
    ruta = escribir(tmp_path, {"producto": {**PANTALLA_PRODUCTO, "capturado": "2026-11-21"}})
    ruta.write_text(ruta.read_text().replace("capturado: '2026-11-21'", "capturado: 2026-11-21"), encoding="utf-8")
    assert capturado_de(cargar(ruta), "producto") == "2026-11-21"
    with pytest.raises(MapaInvalido, match="capturado"):
        cargar(escribir(tmp_path, {"producto": {**PANTALLA_PRODUCTO, "capturado": "ayer"}}))


def test_pantalla_de_cobro_con_controles_sin_prohibida(tmp_path):
    cobro = {"url": "https://app.ejemplo.test/configuracion/impul-pay", "firma": ["Cobros"], "controles": {
        "conectar": {"etiqueta": "Conectar", "rol": "button", "tipo": "boton"}}}
    with pytest.raises(MapaInvalido, match="prohibida"):
        cargar(escribir(tmp_path, {"cobro": cobro}))


@pytest.mark.parametrize("palabra", PALABRAS_PROHIBIDAS)
def test_palabra_prohibida_en_la_firma(tmp_path, palabra):
    pantalla = {**PANTALLA_PRODUCTO, "firma": ["Editar producto", f"Tu {palabra.upper()}"]}
    with pytest.raises(MapaInvalido, match="prohibida"):
        cargar(escribir(tmp_path, {"producto": pantalla}))


def test_pantalla_de_cobro_prohibida_o_sin_controles_carga(tmp_path):
    base = {"url": "https://app.ejemplo.test/configuracion/impul-pay", "firma": ["Pasarelas de pago"]}
    m = cargar(escribir(tmp_path, {
        "solo_lectura": base,
        "prohibida": {**base, "prohibida": True, "controles": {"x": {"css": "button", "tipo": "boton"}}},
    }))
    # M-a (segunda ronda): una pantalla de cobro es prohibida aunque no lo diga ni tenga controles
    assert prohibida(m, "solo_lectura") is True and prohibida(m, "prohibida") is True


def test_prohibida_no_booleana_invalida(tmp_path):
    with pytest.raises(MapaInvalido, match="prohibida"):
        cargar(escribir(tmp_path, {"producto": {**PANTALLA_PRODUCTO, "prohibida": "sí"}}))


def test_hosts_por_defecto_y_explicitos(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}))
    assert hosts_de(m) == {"app.ejemplo.test"}
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, hosts=["app.ejemplo.test", "tienda.ejemplo.test"]))
    assert hosts_de(m) == {"app.ejemplo.test", "tienda.ejemplo.test"}
    with pytest.raises(MapaInvalido, match="hosts"):
        cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, hosts=[""]))


def test_limites_plan_exige_fuente(tmp_path):
    with pytest.raises(MapaInvalido, match="fuente_limites"):
        cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, limites_plan=LIMITES))


@pytest.mark.parametrize(
    "malo",
    [
        {"Free": {"tiendas": 1, "bumps": 1, "upsells": 1}},
        {"Free": {"tiendas": "1", "bumps": 1, "upsells": 1, "downsell": False}},
        {"Free": {"tiendas": True, "bumps": 1, "upsells": 1, "downsell": False}},
        {"Free": {"tiendas": 1, "bumps": 1, "upsells": 1, "downsell": "no"}},
        ["Free"],
    ],
)
def test_limites_plan_mal_formados(tmp_path, malo):
    with pytest.raises(MapaInvalido, match="limites_plan"):
        cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, limites_plan=malo, fuente_limites="https://x.test"))


def test_limites_de_plan(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, limites_plan=LIMITES,
                        fuente_limites="https://ejemplo.test/planes (leída el 2026-11-10)"))
    assert limites_de_plan(m, "Free") == {"tiendas": 1, "bumps": 1, "upsells": 1, "downsell": False}


def test_limites_de_plan_desconocido(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, limites_plan=LIMITES, fuente_limites="https://x.test"))
    assert limites_de_plan(m, "Max") is None
    assert limites_de_plan(cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO})), "Free") is None


def test_mapa_impultienda_tiene_diseno_contenido():
    m = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    html = control(m, "diseno_contenido", "html")
    guardar = control(m, "diseno_contenido", "guardar")
    assert (html.css, html.etiqueta, html.tipo, html.secreto) == ("textarea", None, "area", False)
    assert (guardar.etiqueta, guardar.rol, guardar.tipo) == ("Guardar cambios", "button", "boton")
    assert capturado_de(m, "diseno_contenido") is None  # sin confirmar: el conductor lee pero no escribe


# Huellas de las pantallas publicadas en main antes de este cambio (plan 19, Tarea 1). Las confirmaciones del
# usuario guardan esta huella: si `cargar` inyectara claves nuevas o el paso 09 contara pantallas nuevas,
# el usuario tendría que volver a confirmar sin que nada haya cambiado en sus pantallas.
HUELLAS_PUBLICADAS = {
    ("impultienda", ("plan", "tiendas", "pasarelas")): "87343697a0a51dd32c73062a4ff14a1d474b535276f764387935339b26e9ef79",
    ("whop", None): "35e794d916655bca5be63b59c91ead4a5e98de45fba40cc4dd13b99045b6c44c",
    ("hotmart", None): "d93ecaf6425d304dd4229a1f768a233df907695a63eb332b2578abbf2dc2e0f9",
}


@pytest.mark.parametrize(("servicio", "pantallas"), list(HUELLAS_PUBLICADAS))
def test_huella_de_los_mapas_publicados_no_cambia(servicio, pantallas):
    from trovefy.arranque.verificadores.base import huella_mapa

    m = cargar(RAIZ / f"templates/{servicio}/mapa.yaml")
    assert huella_mapa(m, pantallas) == HUELLAS_PUBLICADAS[(servicio, pantallas)]


# --- M-2: palabras prohibidas que no se esquivan con mayúsculas, acentos, separadores ni %-codificación -----

TERMINOS_MINIMOS = (
    "pasarela", "impul pay", "retir", "tarjeta", "banco", "contraseña", "password", "payout", "withdraw",
    "datos financieros",
)
TERMINOS_NUEVOS = (
    "pago", "cobro", "payment", "billing", "bank", "bancari", "card", "tarjeta", "cbu", "cvu", "iban",
    "mercadopago", "stripe", "paypal", "retiro", "withdraw", "payout", "impulpay",
)


def test_lista_minima_del_plan_y_terminos_nuevos():
    for termino in TERMINOS_MINIMOS + TERMINOS_NUEVOS:
        assert termino in PALABRAS_PROHIBIDAS, termino


@pytest.mark.parametrize(
    "texto",
    [
        "https://app.impultienda.ar/dashboard/impul%2Dpay",
        "https://app.impultienda.ar/dashboard/impul%252Dpay",  # doble codificación
        "https://app.impultienda.ar/dashboard/Impul_Pay",
        "https://app.impultienda.ar/dashboard/impul.pay",
        "https://app.impultienda.ar/dashboard/IMPULPAY",
        "https://app.impultienda.ar/dashboard/impul%20pay",
        "Tu CONTRASENA",
        "Tu contraseña",  # ñ descompuesta (NFD)
        "Tárjeta de crédito",
        "ｐａｇｏｓ",  # ancho completo
        "pa" + chr(0x200B) + "gos",  # espacio de ancho cero
        "Datos-financieros",
        "https://app.impultienda.ar/config/Mercado-Pago",
        "https://app.impultienda.ar/config/medios_de_cobro",
        "/settings/billing",
        "Tu CBU o CVU",
        "IBAN",
        "/connect/stripe",
        "PayPal",
        "/account/payment-methods",
        "Cuenta bancaria",
    ],
)
def test_palabra_prohibida_normaliza(texto):
    assert palabra_prohibida(texto) is not None, texto


@pytest.mark.parametrize(
    "texto",
    [
        "https://app.impultienda.ar/dashboard/diseno/contenido",
        "Diseño de tienda HTML completo de la tienda Guardar cambios",
        "https://app.impultienda.ar/dashboard/productos/p-0099-prueba-abc123",
        "Editar producto Precio Moneda Guardar",
    ],
)
def test_palabra_prohibida_no_salta_en_pantallas_normales(texto):
    assert palabra_prohibida(texto) is None


@pytest.mark.parametrize(
    "control_malo",
    [
        {"etiqueta": "Conectar Mercado Pago", "rol": "button", "tipo": "boton"},
        {"etiqueta": "Número de tarjeta", "tipo": "texto"},
        {"css": "#stripe-key", "tipo": "texto"},
        {"css": "input[name=cbu]", "tipo": "texto"},
    ],
)
def test_palabra_prohibida_en_un_control(tmp_path, control_malo):
    with pytest.raises(MapaInvalido, match="prohibida"):
        cargar(escribir(tmp_path, con_controles(precio=control_malo)))


def test_palabra_prohibida_codificada_en_la_url(tmp_path):
    pantalla = {**PANTALLA_PRODUCTO, "url": "https://app.ejemplo.test/configuracion/impul%2Dpay"}
    with pytest.raises(MapaInvalido, match="prohibida"):
        cargar(escribir(tmp_path, {"producto": pantalla}))


@pytest.mark.parametrize("servicio", ["impultienda", "whop", "hotmart"])
def test_mapas_plantilla_siguen_cargando(servicio):
    cargar(RAIZ / f"templates/{servicio}/mapa.yaml")


# --- M-3: la huella del paso 09 es la de {url, firma, campos} de sus pantallas -----------------------------


@pytest.mark.parametrize("extra", [{"prohibida": True}, {"capturado": "2026-11-20"}, {"prohibida": True, "capturado": None}])
def test_huella_09_no_cambia_al_anotar_pasarelas(tmp_path, extra):
    from trovefy.arranque.verificadores.base import huella_mapa

    plantilla = yaml.safe_load((RAIZ / "templates/impultienda/mapa.yaml").read_text(encoding="utf-8"))
    plantilla["pantallas"]["pasarelas"].update(extra)
    ruta = tmp_path / "mapa.yaml"
    ruta.write_text(yaml.safe_dump(plantilla, allow_unicode=True), encoding="utf-8")
    pantallas = ("plan", "tiendas", "pasarelas")
    assert huella_mapa(cargar(ruta), pantallas) == HUELLAS_PUBLICADAS[("impultienda", pantallas)]


def test_huella_ignora_controles_pero_no_la_firma():
    from trovefy.arranque.verificadores.base import huella_mapa

    base = {"url": "https://app.ejemplo.test/inicio", "firma": ["Inicio"], "campos": {"n": {"patron": r"(\d+)"}}}
    h = huella_mapa({"pantallas": {"inicio": base}})
    assert huella_mapa({"pantallas": {"inicio": {**base, "controles": {"x": {"css": "a", "tipo": "boton"}}}}}) == h
    assert huella_mapa({"pantallas": {"inicio": {**base, "firma": ["Otra"]}}}) != h
    assert huella_mapa({"pantallas": {"inicio": {**base, "url": "https://app.ejemplo.test/otra"}}}) != h


# --- L-1: orígenes (esquema, host, puerto); https salvo en 127.0.0.1 -------------------------------------


def test_origen():
    assert origen("https://app.ejemplo.test/x?y=1") == ("https", "app.ejemplo.test", 443)
    assert origen("https://App.Ejemplo.test:8443/x") == ("https", "app.ejemplo.test", 8443)
    assert origen("http://127.0.0.1:8123/a.html") == ("http", "127.0.0.1", 8123)
    assert origen("http://app.ejemplo.test/x") is None  # http solo en 127.0.0.1
    assert origen("http://localhost:8000/x") is None
    assert origen("about:blank") is None
    assert origen("https://app.ejemplo.test:99999/") is None


def test_origenes_de(tmp_path):
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}))
    assert origenes_de(m) == {("https", "app.ejemplo.test", 443)}
    m = cargar(escribir(tmp_path, {"producto": PANTALLA_PRODUCTO}, hosts=["tienda.ejemplo.test"]))
    assert origenes_de(m) == {("https", "tienda.ejemplo.test", 443)}  # la url de producto queda fuera de hosts
    local = {"capturado": None, "fuente": "x", "hosts": ["127.0.0.1"],
             "pantallas": {"a": {"url": "http://127.0.0.1:8123/a.html", "firma": ["A"]}}}
    assert ("http", "127.0.0.1", 8123) in origenes_de(local)


# --- Segunda ronda, M-a: prohibida = marcada o con aspecto de cobro (url, firma, etiquetas, css) -------------


@pytest.mark.parametrize(
    "pantalla",
    [
        {"url": "https://app.ejemplo.test/configuracion/impul%2Dpay", "firma": ["Ajustes"]},
        {"url": "https://app.ejemplo.test/configuracion", "firma": ["Pasarelas de pago"]},
        {"url": "https://app.ejemplo.test/configuracion", "firma": ["Ajustes"], "prohibida": True,
         "controles": {"x": {"css": "input[name=cbu]", "tipo": "texto"}}},
    ],
)
def test_prohibida_sin_marca_si_parece_de_cobro(tmp_path, pantalla):
    m = cargar(escribir(tmp_path, {"p": pantalla}))
    assert prohibida(m, "p") is True


def test_prohibida_en_un_mapa_en_memoria_sin_marca():
    m = {"pantallas": {"p": {"url": "https://x.test/a", "firma": ["Ajustes"],
                             "controles": {"x": {"etiqueta": "Número de tarjeta", "tipo": "texto"}}}}}
    assert prohibida(m, "p") is True
    m["pantallas"]["p"]["controles"]["x"]["etiqueta"] = "Precio"
    assert prohibida(m, "p") is False


@pytest.mark.parametrize(("servicio", "pantalla"),
                         [("impultienda", "pasarelas"), ("whop", "balances"), ("hotmart", "datos_financieros")])
def test_plantillas_marcan_sus_pantallas_de_pago(servicio, pantalla):
    crudo = yaml.safe_load((RAIZ / f"templates/{servicio}/mapa.yaml").read_text(encoding="utf-8"))
    assert crudo["pantallas"][pantalla].get("prohibida") is True
    assert prohibida(cargar(RAIZ / f"templates/{servicio}/mapa.yaml"), pantalla) is True


@pytest.mark.parametrize(("servicio", "pantalla"),
                         [("impultienda", "plan"), ("impultienda", "tiendas"), ("impultienda", "diseno_contenido"),
                          ("hotmart", "productos")])
def test_plantillas_pantallas_normales_no_prohibidas(servicio, pantalla):
    assert prohibida(cargar(RAIZ / f"templates/{servicio}/mapa.yaml"), pantalla) is False


# --- Segunda ronda, L-c: más términos, homoglifos y términos cortos solo como palabra entera ------------------

TERMINOS_SEGUNDA_RONDA = (
    "financial", "balance", "pagamento", "saque", "senha", "cartao", "clave", "facturacion", "credencial",
    "apikey", "wallet", "saldo",
)


def test_terminos_de_la_segunda_ronda():
    for termino in TERMINOS_SEGUNDA_RONDA:
        assert termino in PALABRAS_PROHIBIDAS, termino


def test_checkout_no_es_palabra_prohibida(tmp_path):
    # Las pantallas `checkout` / `checkout_hotmart` de los planes 18/19 se configuran con el conductor (idioma,
    # campos, temporizador…): «checkout» como palabra prohibida las haría imposibles de cargar con controles.
    assert "checkout" not in PALABRAS_PROHIBIDAS
    pantalla = {**PANTALLA_PRODUCTO, "url": "https://app.ejemplo.test/dashboard/checkout", "firma": ["Diseño de checkout"]}
    m = cargar(escribir(tmp_path, {"checkout": pantalla}))
    assert prohibida(m, "checkout") is False


@pytest.mark.parametrize(
    "texto",
    [
        # lista de la segunda revisión (palabras.py, con Chromium real)
        "Impul-Pay", "impul%2Dpay", "impul%252Dpay", "IMPUL_PAY", "impul pay", "impul.pay", "impul\u200bpay",
        "contrase%C3%B1a", "Contrasena", "CONTRASE\u00d1A", "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44", "p%61ssword", "pass\u00adword",
        "/settings/payments", "/billing", "/retiros", "/withdrawals", "/payouts", "/datos-financieros",
        "/cuenta-bancaria", "/tarjetas", "/mercado-pago", "/mercado_pago", "/MercadoPago", "/pagamentos", "/saque",
        "/senha", "/cartao", "/cartão", "/clave", "/cambiar-clave", "/facturacion", "/facturación", "/wallet",
        "/saldo", "/credenciales", "/api-keys", "/account/financial", "/dashboard/balance/",
        # homoglifos cirílicos y griegos
        "p\u0430ssword", "\u0440\u0430ssword", "\u0456mpul p\u0430y", "\u0441ard", "/s\u0435tting/\u0441ard",
        "\u0391PI-KEY", "B\u0391NK", "c\u0430rtao",
        # términos cortos como palabra entera (también en plural)
        "/connect/stripe", "Tu CBU o CVU", "IBAN", "/settings/cards", "card-number", "Bank account", "c%61rd",
    ],
)
def test_palabra_prohibida_casa_tras_la_segunda_ronda(texto):
    assert palabra_prohibida(texto) is not None, texto


@pytest.mark.parametrize(
    "texto",
    [
        "/productos/cardio-max/editar", "/store/ScoreCard", "/p/7xCbUq9", "Ibáñez", "/striped-tee", "/discard",
        "Mi cardigan", "/tienda/ivan-k", "/pagina/inicio", "https://app.hotmart.com/products/manage",
        "https://whop.com/dashboard/biz_x/", "Plan actual", "Tiendas activas",
    ],
)
def test_terminos_cortos_no_casan_dentro_de_otras_palabras(texto):
    assert palabra_prohibida(texto) is None, texto
