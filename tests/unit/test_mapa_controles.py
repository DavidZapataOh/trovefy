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


def test_capturado_por_pantalla_hereda_de_la_raiz(tmp_path):
    pantallas = {
        "producto": dict(PANTALLA_PRODUCTO),
        "nueva": {**PANTALLA_PRODUCTO, "capturado": None},
        "otra": {**PANTALLA_PRODUCTO, "capturado": "2026-11-21"},
    }
    ruta = escribir(tmp_path, pantallas, capturado="2026-11-20")
    m = cargar(ruta)
    assert capturado_de(m, "producto") == "2026-11-20"
    assert capturado_de(m, "nueva") is None
    assert capturado_de(m, "otra") == "2026-11-21"


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
    assert prohibida(m, "solo_lectura") is False and prohibida(m, "prohibida") is True


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
