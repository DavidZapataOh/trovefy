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
            "controles": {"activo": {"etiqueta": "Activar bump", "tipo": "interruptor"}},
        },
        "tracking": {
            "url": BASE + "/tracking",
            "firma": ["Píxel de Meta"],
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
    mapa = {**MAPA, "capturado": None}
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
    assert ruta == tmp_path / "capturas" / "t.png" and ruta.exists()
    assert p.mascaras == ["Token de acceso", "input[type=password]"]
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


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
    p = pagina_producto()
    c = conductor(p, dormir=reloj.dormir, ahora=reloj.ahora)
    c.ir("producto", id="a")
    assert reloj.dormido == []
    c.ir("producto", id="b")
    assert reloj.dormido and reloj.dormido[0] >= 5.0


def test_esperar_entre_navegaciones_por_dominio():
    reloj = Reloj()
    esperar = navegador.esperar_entre_navegaciones
    esperar("a.test", ahora=reloj.ahora, dormir=reloj.dormir)
    esperar("b.test", ahora=reloj.ahora, dormir=reloj.dormir)
    assert reloj.dormido == []
    reloj.t += 2.0
    esperar("a.test", ahora=reloj.ahora, dormir=reloj.dormir)
    assert reloj.dormido == [3.0]
    reloj.t += 10.0
    esperar("a.test", ahora=reloj.ahora, dormir=reloj.dormir)
    assert reloj.dormido == [3.0]
