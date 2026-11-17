"""El conductor es el único que hace clics, y se para ante cualquier discrepancia sin tocar nada más."""

import copy
import stat

import pytest
from trovefy import navegador
from trovefy.tienda.conductor import (
    Conductor,
    ControlSecreto,
    FirmaNoCasa,
    HostNoPermitido,
    MapaSinConfirmar,
    Parada,
    SelectorAusente,
    SesionCaducada,
    ZonaProhibida,
)

from tienda.pagina_falsa import ElementoFalso, PaginaFalsa

BASE = "https://app.impultienda.ar/dashboard"
URL_PRODUCTO = f"{BASE}/productos/p-0099-prueba-abc123"
MAPA = {
    "capturado": "2026-11-20",
    "fuente": "pantallas de prueba",
    "pantallas": {
        "producto": {
            "url": BASE + "/productos/{id}",
            "firma": ["Editar producto"],
            "capturado": "2026-11-20",
            "controles": {
                "precio": {"etiqueta": "Precio", "rol": "textbox", "tipo": "precio"},
                "nombre": {"etiqueta": "Nombre", "tipo": "texto"},
                "moneda": {"etiqueta": "Moneda", "tipo": "select"},
                "entrega": {"css": "input[type=file]", "tipo": "archivo"},
                "guardar": {"etiqueta": "Guardar", "rol": "button", "tipo": "boton"},
            },
        },
        "bump": {
            "url": BASE + "/bump",
            "firma": ["Order bump"],
            "capturado": "2026-11-20",
            "controles": {"activo": {"etiqueta": "Activar bump", "tipo": "interruptor"}},
        },
        "tracking": {
            "url": BASE + "/tracking",
            "firma": ["Píxel de Meta"],
            "capturado": "2026-11-20",
            "controles": {
                "capi_token": {"etiqueta": "Token de acceso", "tipo": "texto", "secreto": True},
                "dataset": {"etiqueta": "ID del dataset", "tipo": "texto"},
            },
        },
        "pasarelas": {
            "url": BASE + "/configuraciones/pasarelas",
            "firma": ["Pasarelas de pago"],
            "prohibida": True,
            "controles": {"conectar": {"etiqueta": "Conectar", "rol": "button", "tipo": "boton"}},
        },
    },
}


class Reloj:
    def __init__(self):
        self.t = 1000.0
        self.dormido: list[float] = []

    def ahora(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.dormido.append(s)
        self.t += s


@pytest.fixture(autouse=True)
def _sin_esperas_previas():
    navegador._ULTIMA_NAVEGACION.clear()
    yield
    navegador._ULTIMA_NAVEGACION.clear()


def no_duerme(_s):
    pass


def pagina_producto(**elementos):
    base = {"Precio": [ElementoFalso("13.90")], "Nombre": [ElementoFalso("Guía")], "Moneda": [ElementoFalso(opcion="EUR")],
            "input[type=file]": [ElementoFalso()], "Guardar": [ElementoFalso()]}
    base.update(elementos)
    return PaginaFalsa(texto="Editar producto · Precio", elementos=base)


def conductor(p, mapa=MAPA, **kw):
    kw.setdefault("dormir", no_duerme)
    return Conductor(p, mapa, "impultienda", **kw)


def en_producto(p=None, mapa=MAPA):
    p = p or pagina_producto()
    c = conductor(p, mapa)
    c.ir("producto", id="p-0099-prueba-abc123")
    return p, c


def test_ir_devuelve_el_texto_y_navega_a_la_url_del_mapa():
    p = pagina_producto()
    assert conductor(p).ir("producto", id="p-0099-prueba-abc123") == "Editar producto · Precio"
    assert p.visitas == [URL_PRODUCTO] and p.acciones == []


def test_firma_no_casa_para_sin_clic():
    p = PaginaFalsa(texto="Otra cosa")
    c = conductor(p)
    with pytest.raises(FirmaNoCasa) as exc:
        c.ir("producto", id="x")
    assert exc.value.pantalla == "producto" and "Editar producto" in exc.value.motivo
    with pytest.raises(Parada):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_selector_ausente_para_sin_clic():
    p, c = en_producto(pagina_producto(Precio=[]))
    with pytest.raises(SelectorAusente, match="no encuentro"):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_selector_ambiguo_para():
    p, c = en_producto(pagina_producto(Precio=[ElementoFalso(), ElementoFalso()]))
    with pytest.raises(SelectorAusente, match="2"):
        c.poner("producto", "precio", "13.90")
    with pytest.raises(Parada):  # tras una parada de pantalla, nada más hasta volver a ir()
        c.pulsar("producto", "guardar")
    c.ir("producto", id="p-0099-prueba-abc123")
    with pytest.raises(SelectorAusente):
        c.leer("producto", "precio")
    assert p.acciones == []


def test_sesion_caducada_para_sin_clic():
    p = pagina_producto()
    p.destinos[URL_PRODUCTO] = "https://app.impultienda.ar/login?next=/dashboard"
    c = conductor(p)
    with pytest.raises(SesionCaducada) as exc:
        c.ir("producto", id="p-0099-prueba-abc123")
    assert "trovefy navegador abrir impultienda" in exc.value.motivo
    with pytest.raises(Parada):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_host_no_permitido():
    p = pagina_producto()
    p.destinos[URL_PRODUCTO] = "https://evil.example/dashboard/productos/x"
    c = conductor(p)
    with pytest.raises(HostNoPermitido, match="evil.example"):
        c.ir("producto", id="p-0099-prueba-abc123")
    with pytest.raises(Parada):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_host_no_permitido_ni_siquiera_navega():
    mapa = copy.deepcopy(MAPA)
    mapa["hosts"] = ["tienda.impultienda.ar"]
    p = pagina_producto()
    with pytest.raises(HostNoPermitido):
        conductor(p, mapa).ir("producto", id="x")
    assert p.visitas == []


def test_valores_url_no_cambian_el_host():
    p = pagina_producto()
    with pytest.raises(ValueError):
        conductor(p).ir("producto", id="x@evil.example/")
    assert p.visitas == []


def test_pantalla_prohibida_no_escribe():
    p = PaginaFalsa(texto="Pasarelas de pago · Impul Pay", elementos={"Conectar": [ElementoFalso()]})
    c = conductor(p)
    assert "Impul Pay" in c.ir("pasarelas")  # leer qué pasarela cobra sí se puede
    with pytest.raises(ZonaProhibida):
        c.pulsar("pasarelas", "conectar")
    with pytest.raises(ZonaProhibida):
        c.poner("pasarelas", "conectar", "x")
    assert p.acciones == []


def test_url_actual_de_cobro_para_aunque_la_firma_case():
    p, c = en_producto()
    p.url = "https://app.impultienda.ar/dashboard/impul-pay?desde=producto"
    with pytest.raises(ZonaProhibida):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_mapa_sin_confirmar_lee_pero_no_escribe():
    mapa = copy.deepcopy(MAPA)
    mapa["capturado"] = None
    mapa["pantallas"]["producto"]["capturado"] = None
    p, c = en_producto(mapa=mapa)
    assert c.leer("producto", "precio") == "13.90"
    with pytest.raises(MapaSinConfirmar, match=r"no medido: mapa sin confirmar \(producto\)"):
        c.poner("producto", "precio", "13.90")
    with pytest.raises(MapaSinConfirmar):
        c.pulsar("producto", "guardar")
    assert p.acciones == []


def test_pantalla_sin_confirmar_aunque_la_raiz_lo_este():
    mapa = copy.deepcopy(MAPA)
    mapa["pantallas"]["producto"]["capturado"] = None
    p, c = en_producto(mapa=mapa)
    with pytest.raises(MapaSinConfirmar):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_pantalla_con_controles_no_hereda_el_capturado_de_la_raiz():
    # R-1: la raíz confirmada (paso 09) no basta; la pantalla con controles necesita su propio `capturado`
    mapa = copy.deepcopy(MAPA)
    del mapa["pantallas"]["producto"]["capturado"]
    p, c = en_producto(mapa=mapa)
    assert c.leer("producto", "precio") == "13.90"  # leer sí
    with pytest.raises(MapaSinConfirmar):
        c.poner("producto", "precio", "14.90")
    with pytest.raises(MapaSinConfirmar):
        c.pulsar("producto", "guardar")
    assert p.acciones == []


def test_control_secreto_no_se_lee():
    p = PaginaFalsa(texto="Píxel de Meta", elementos={"Token de acceso": [ElementoFalso("EAABprueba123")],
                                                       "ID del dataset": [ElementoFalso("1111111111111111")]})
    c = conductor(p)
    c.ir("tracking")
    with pytest.raises(ControlSecreto):
        c.leer("tracking", "capi_token")
    with pytest.raises(ControlSecreto):
        c.poner("tracking", "capi_token", "EAABotro")
    assert c.configurado("tracking", "capi_token") is True
    assert c.leer("tracking", "dataset") == "1111111111111111"
    assert "EAAB" not in repr(p.acciones) and p.acciones == []
    p.elementos["Token de acceso"] = [ElementoFalso("  ")]
    assert c.configurado("tracking", "capi_token") is False


def test_captura_enmascara_secretos(tmp_path):
    p = PaginaFalsa(texto="Píxel de Meta", elementos={"Token de acceso": [ElementoFalso("EAABprueba123")]})
    c = conductor(p)
    c.ir("tracking")
    ruta = c.capturar(tmp_path / "capturas" / "t.png")
    assert ruta == tmp_path / "capturas" / "t.png" and ruta.read_bytes() == b"\x89PNG falso"
    # los secretos de todo el mapa y, por defecto, todos los campos (input incluye las contraseñas)
    assert p.mascaras == ["Token de acceso", CAMPOS]
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


# --- M-1: capturar tiene las mismas guardas que leer ------------------------------------------------------

CAMPOS = "input, textarea, [contenteditable]"


def pagina_tracking(**kw):
    return PaginaFalsa(texto="Píxel de Meta", elementos={"Token de acceso": [ElementoFalso("EAABprueba123")]}, **kw)


def test_capturar_sin_ir_antes_para(tmp_path):
    p = pagina_tracking()
    with pytest.raises(Parada, match="ir"):
        conductor(p).capturar(tmp_path / "t.png")
    assert p.capturas == [] and not (tmp_path / "t.png").exists()


def test_capturar_tras_una_parada_para(tmp_path):
    p, c = en_producto(pagina_producto(Precio=[]))
    with pytest.raises(SelectorAusente):
        c.leer("producto", "precio")
    with pytest.raises(Parada):
        c.capturar(tmp_path / "t.png")
    assert p.capturas == []


def test_capturar_pantalla_prohibida_para(tmp_path):
    p = PaginaFalsa(texto="Pasarelas de pago", elementos={"Conectar": [ElementoFalso()]})
    c = conductor(p)
    c.ir("pasarelas")
    with pytest.raises(ZonaProhibida):
        c.capturar(tmp_path / "t.png")
    assert p.capturas == [] and not (tmp_path / "t.png").exists()


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("https://app.impultienda.ar/dashboard/medios-de-pago", ZonaProhibida),
        ("https://app.impultienda.ar/dashboard/impul%2Dpay", ZonaProhibida),
        ("https://evil.example/dashboard/tracking", HostNoPermitido),
    ],
)
def test_capturar_con_la_url_cambiada_para(tmp_path, url, error):
    p = pagina_tracking()
    c = conductor(p)
    c.ir("tracking")
    p.url = url
    with pytest.raises(error):
        c.capturar(tmp_path / "t.png")
    assert p.capturas == []


@pytest.mark.parametrize("tokens", [[], [ElementoFalso("a"), ElementoFalso("b")]])
def test_capturar_si_el_secreto_no_casa_con_un_elemento_para(tmp_path, tokens):
    p = pagina_tracking()
    c = conductor(p)
    c.ir("tracking")
    p.elementos["Token de acceso"] = tokens
    with pytest.raises(SelectorAusente):
        c.capturar(tmp_path / "t.png")
    assert p.capturas == []


def test_capturar_si_la_pagina_cambia_durante_la_captura_no_guarda(tmp_path):
    def se_va(pagina):
        pagina.url = "https://app.impultienda.ar/dashboard/pasarelas"

    p = pagina_tracking(al_capturar=se_va)
    c = conductor(p)
    c.ir("tracking")
    with pytest.raises(ZonaProhibida):
        c.capturar(tmp_path / "t.png")
    assert not (tmp_path / "t.png").exists() and list(tmp_path.iterdir()) == []


def test_capturar_no_sigue_enlaces_simbolicos(tmp_path):
    # L-3: la captura no escribe a través de un enlace plantado en la ruta, y queda 0600
    victima = tmp_path / "victima.txt"
    victima.write_text("intacto")
    ruta = tmp_path / "capturas" / "t.png"
    ruta.parent.mkdir()
    ruta.symlink_to(victima)
    p = pagina_tracking()
    c = conductor(p)
    c.ir("tracking")
    c.capturar(ruta)
    assert victima.read_text() == "intacto"
    assert not ruta.is_symlink() and ruta.read_bytes() == b"\x89PNG falso"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert sorted(x.name for x in ruta.parent.iterdir()) == ["t.png"]  # sin temporales


# --- H-1: el elemento se fija, se vuelve a comprobar todo y se actúa sobre él --------------------------------


def test_fija_el_elemento_y_actua_sobre_el_con_tiempo_corto():
    p, c = en_producto()
    c.poner("producto", "precio", "14.90")
    c.pulsar("producto", "guardar")
    assert [clave for clave, _t in p.fijados] == ["Precio", "Guardar"]
    assert all(t is not None and t <= 2000 for _c, t in p.fijados)
    assert p.timeouts and all(t is not None and t <= 5000 for t in p.timeouts)
    assert p.timeout_por_defecto is not None and p.timeout_por_defecto <= 10_000


@pytest.mark.parametrize(
    ("cambio", "error"),
    [
        ({"url": "https://app.impultienda.ar/dashboard/impul-pay"}, ZonaProhibida),
        ({"url": "https://app.impultienda.ar/dashboard/medios_de_cobro"}, ZonaProhibida),
        ({"url": "https://evil.example/dashboard/productos/x"}, HostNoPermitido),
        ({"url": "http://app.impultienda.ar/dashboard/productos/p-0099-prueba-abc123"}, HostNoPermitido),
        ({"url": "https://app.impultienda.ar/login"}, SesionCaducada),
        ({"texto": "Otra pantalla"}, FirmaNoCasa),
    ],
)
def test_la_pagina_cambia_entre_comprobar_y_fijar(cambio, error):
    def cambia(pagina, _clave):
        for k, v in cambio.items():
            setattr(pagina, k, v)

    p, c = en_producto()
    p.al_fijar = cambia
    with pytest.raises(error):
        c.poner("producto", "precio", "99.00")
    assert p.acciones == []
    with pytest.raises(Parada):  # parada de pantalla: nada más hasta volver a ir()
        c.pulsar("producto", "guardar")
    assert p.acciones == []


def test_la_pagina_sustituye_el_elemento_tras_fijarlo():
    # la otra pantalla tiene un campo con la misma etiqueta: el elemento fijado ya no existe y no se escribe en el nuevo
    nuevo = ElementoFalso("B-original")

    def otra_pantalla(pagina, clave):
        pagina.elementos[clave] = [nuevo]

    p, c = en_producto()
    p.al_fijar = otra_pantalla
    with pytest.raises(Parada, match="no sé si se aplicó"):
        c.poner("producto", "precio", "99.00")
    assert nuevo.valor == "B-original" and p.acciones == []
    with pytest.raises(Parada):
        c.leer("producto", "precio")


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("https://app.impultienda.ar/dashboard/impul-pay", ZonaProhibida),
        ("https://evil.example/x", HostNoPermitido),
    ],
)
def test_tras_actuar_la_url_cambia_a_zona_prohibida_o_fuera(url, error):
    def se_va(pagina, _clave, _accion):
        pagina.url = url

    p, c = en_producto()
    p.al_actuar = se_va
    with pytest.raises(error):
        c.poner("producto", "precio", "14.90")
    assert p.acciones == [("fill", "Precio", "14.90")]
    p.al_actuar = None
    p.url = URL_PRODUCTO
    with pytest.raises(Parada):  # _actual se borró
        c.poner("producto", "nombre", "Guía nueva")
    assert len(p.acciones) == 1


# --- L-2: si Playwright falla a mitad, no sé si se aplicó --------------------------------------------------


@pytest.mark.parametrize(("accion", "nombre", "valor"), [("poner", "precio", "14.90"), ("pulsar", "guardar", None)])
def test_error_de_playwright_a_mitad(accion, nombre, valor):
    p, c = en_producto()
    p.fallar.add("Precio" if nombre == "precio" else "Guardar")
    with pytest.raises(Parada, match="no sé si se aplicó"):
        c.poner("producto", nombre, valor) if accion == "poner" else c.pulsar("producto", nombre)
    with pytest.raises(Parada):
        c.leer("producto", "nombre")


def test_error_al_fijar_no_toca_nada():
    p, c = en_producto()

    def rompe(pagina, clave):
        raise RuntimeError("Target closed")

    p.al_fijar = rompe
    with pytest.raises(Parada):
        c.poner("producto", "precio", "14.90")
    assert p.acciones == []


# --- L-1: orígenes ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_final",
    [
        "http://app.impultienda.ar/dashboard/productos/p-0099-prueba-abc123",  # sin https
        "https://app.impultienda.ar:8443/dashboard/productos/p-0099-prueba-abc123",  # otro puerto
    ],
)
def test_origen_distinto_para(url_final):
    p = pagina_producto()
    p.destinos[URL_PRODUCTO] = url_final
    with pytest.raises(HostNoPermitido):
        conductor(p).ir("producto", id="p-0099-prueba-abc123")


def test_http_solo_en_127_0_0_1():
    mapa = copy.deepcopy(MAPA)
    mapa["pantallas"]["bump"]["url"] = "http://localhost:8000/bump"
    mapa["hosts"] = ["localhost", "app.impultienda.ar"]
    p = PaginaFalsa(texto="Order bump")
    with pytest.raises(HostNoPermitido):
        conductor(p, mapa).ir("bump")
    assert p.visitas == []
    mapa["pantallas"]["bump"]["url"] = "http://127.0.0.1:8000/bump"
    mapa["hosts"] = ["127.0.0.1"]
    conductor(p, mapa).ir("bump")
    assert p.visitas == ["http://127.0.0.1:8000/bump"]


# --- L-4: la espera también tras un clic que navega ----------------------------------------------------------


def test_pulsar_que_navega_respeta_la_espera():
    def navega(pagina, _clave):
        pagina.url = "https://app.impultienda.ar/dashboard/productos"

    reloj = Reloj()
    p = pagina_producto()
    p.al_pulsar = navega
    c = conductor(p, dormir=reloj.dormir, ahora=reloj.ahora, azar=lambda a, b: 6.0)
    c.ir("producto", id="p-0099-prueba-abc123")
    assert reloj.dormido == []
    c.pulsar("producto", "guardar")
    assert reloj.dormido == [6.0]


def test_pulsar_sin_navegar_no_espera():
    reloj = Reloj()
    p = pagina_producto()
    c = conductor(p, dormir=reloj.dormir, ahora=reloj.ahora, azar=lambda a, b: 6.0)
    c.ir("producto", id="p-0099-prueba-abc123")
    c.pulsar("producto", "guardar")
    assert reloj.dormido == []


def test_poner_interruptor_y_archivo(tmp_path):
    p = PaginaFalsa(texto="Order bump", elementos={"Activar bump": [ElementoFalso(marcado=True)]})
    c = conductor(p)
    c.ir("bump")
    c.poner("bump", "activo", False)
    assert c.leer("bump", "activo") is False
    c.poner("bump", "activo", True)
    pdf = tmp_path / "entrega.pdf"
    pdf.write_bytes(b"%PDF")
    p2, c2 = en_producto()
    c2.poner("producto", "entrega", pdf)
    assert p.acciones == [("uncheck", "Activar bump"), ("check", "Activar bump")]
    assert p2.acciones == [("set_input_files", "input[type=file]", str(pdf))]


def test_poner_texto_select_y_pulsar():
    p, c = en_producto()
    c.poner("producto", "precio", "14.90")
    c.poner("producto", "moneda", "EUR")
    c.pulsar("producto", "guardar")
    assert p.acciones == [("fill", "Precio", "14.90"), ("select_option", "Moneda", "EUR"), ("click", "Guardar")]
    assert c.leer("producto", "precio") == "14.90" and c.leer("producto", "moneda") == "EUR"


@pytest.mark.parametrize(
    ("accion", "nombre", "valor"),
    [
        ("poner", "guardar", "x"),  # un botón se pulsa, no se pone
        ("poner", "precio", 13.9),  # nunca float
        ("poner", "precio", True),
        ("poner", "entrega", "entrega.pdf"),  # archivo: Path
        ("pulsar", "precio", None),
    ],
)
def test_tipo_de_valor_incorrecto_no_toca(accion, nombre, valor):
    p, c = en_producto()
    with pytest.raises(TypeError):
        c.poner("producto", nombre, valor) if accion == "poner" else c.pulsar("producto", nombre)
    assert p.acciones == []


def test_interruptor_exige_bool():
    p = PaginaFalsa(texto="Order bump", elementos={"Activar bump": [ElementoFalso()]})
    c = conductor(p)
    c.ir("bump")
    with pytest.raises(TypeError):
        c.poner("bump", "activo", "no")
    assert p.acciones == []


def test_archivo_inexistente_no_toca(tmp_path):
    p, c = en_producto()
    with pytest.raises(FileNotFoundError):
        c.poner("producto", "entrega", tmp_path / "no-existe.pdf")
    assert p.acciones == []


def test_poner_sin_ir_antes_para():
    p = pagina_producto()
    with pytest.raises(FirmaNoCasa, match="producto"):
        conductor(p).poner("producto", "precio", "13.90")
    assert p.acciones == []


def test_firma_cambia_antes_de_escribir():
    p, c = en_producto()
    c.poner("producto", "precio", "14.90")
    p.texto = "Panel rediseñado"
    with pytest.raises(FirmaNoCasa):
        c.poner("producto", "nombre", "Guía nueva")
    p.texto = "Editar producto"  # aunque vuelva, tras una parada hay que volver a ir()
    with pytest.raises(FirmaNoCasa):
        c.pulsar("producto", "guardar")
    assert p.acciones == [("fill", "Precio", "14.90")]


def test_pulsar_que_lleva_al_login_para_lo_siguiente():
    def caduca(pagina, _clave):
        pagina.url = "https://app.impultienda.ar/login"

    p, c = en_producto(PaginaFalsa(texto="Editar producto", elementos={"Guardar": [ElementoFalso()], "Precio": [ElementoFalso()]},
                                   al_pulsar=caduca))
    c.pulsar("producto", "guardar")
    with pytest.raises(SesionCaducada):
        c.poner("producto", "precio", "13.90")
    assert p.acciones == [("click", "Guardar")]


def test_control_o_pantalla_desconocidos():
    p, c = en_producto()
    with pytest.raises(KeyError):
        c.poner("producto", "nada", "x")
    with pytest.raises(KeyError):
        c.ir("nada")
    assert p.acciones == []


def test_parada_tiene_pantalla_y_motivo_en_espanol():
    for cls in (FirmaNoCasa, SelectorAusente, HostNoPermitido, ZonaProhibida, SesionCaducada, MapaSinConfirmar, ControlSecreto):
        e = cls("producto", "motivo de prueba")
        assert isinstance(e, Parada) and e.pantalla == "producto" and e.motivo == "motivo de prueba"
        assert "motivo de prueba" in str(e)


def test_espera_entre_navegaciones():
    reloj = Reloj()
    pedidos = []

    def azar(a, b):
        pedidos.append((a, b))
        return 7.25

    p = pagina_producto()
    c = conductor(p, dormir=reloj.dormir, ahora=reloj.ahora, azar=azar)
    c.ir("producto", id="a")
    assert reloj.dormido == []
    c.ir("producto", id="b")
    assert reloj.dormido == [7.25] and pedidos[-1] == (5.0, 8.0)


def test_esperar_entre_navegaciones_por_dominio():
    reloj = Reloj()

    def esperar(dominio):
        navegador.esperar_entre_navegaciones(dominio, ahora=reloj.ahora, dormir=reloj.dormir, azar=lambda a, b: 6.5)

    esperar("a.test")
    esperar("b.test")
    assert reloj.dormido == []
    reloj.t += 2.0
    esperar("a.test")
    assert reloj.dormido == [4.5]
    reloj.t += 10.0
    esperar("a.test")
    assert reloj.dormido == [4.5]


def test_espera_aleatoria_entre_5_y_8_s():
    # R-3: sin azar inyectado, el intervalo cae en [5, 8] y no siempre es el mismo
    import random

    random.seed(19)
    esperas = []
    for i in range(40):
        reloj = Reloj()
        navegador._ULTIMA_NAVEGACION.clear()
        navegador.esperar_entre_navegaciones(f"d{i}.test", ahora=reloj.ahora, dormir=reloj.dormir)
        navegador.esperar_entre_navegaciones(f"d{i}.test", ahora=reloj.ahora, dormir=reloj.dormir)
        esperas.extend(reloj.dormido)
    assert len(esperas) == 40 and all(5.0 <= s <= 8.0 for s in esperas) and len(set(esperas)) > 1


def test_azar_fuera_de_rango_se_acota():
    reloj = Reloj()
    for azar in (lambda a, b: 0.0, lambda a, b: 99.0):
        navegador._ULTIMA_NAVEGACION.clear()
        reloj.dormido.clear()
        navegador.esperar_entre_navegaciones("a.test", ahora=reloj.ahora, dormir=reloj.dormir, azar=azar)
        navegador.esperar_entre_navegaciones("a.test", ahora=reloj.ahora, dormir=reloj.dormir, azar=azar)
        assert 5.0 <= reloj.dormido[0] <= 8.0


@pytest.mark.parametrize(
    ("host", "dominio"),
    [
        ("app.impultienda.ar", "impultienda.ar"),
        ("impultienda.ar", "impultienda.ar"),
        ("Tienda.Impultienda.AR.", "impultienda.ar"),
        ("mi-tienda.impultienda.com.ar", "impultienda.com.ar"),
        ("app.hotmart.com", "hotmart.com"),
        ("pay.hotmart.com.br", "hotmart.com.br"),
        ("shop.example.co.uk", "example.co.uk"),
        ("127.0.0.1", "127.0.0.1"),
        ("localhost", "localhost"),
    ],
)
def test_dominio_registrable(host, dominio):
    assert navegador.dominio_registrable(host) == dominio


def test_la_espera_es_por_dominio_registrable():
    # L-4: app.impultienda.ar y la tienda pública comparten espera
    reloj = Reloj()
    kw = {"ahora": reloj.ahora, "dormir": reloj.dormir, "azar": lambda a, b: 5.0}
    navegador.esperar_entre_navegaciones("app.impultienda.ar", **kw)
    reloj.t += 1.0
    navegador.esperar_entre_navegaciones("mitienda.impultienda.ar", **kw)
    assert reloj.dormido == [4.0]
