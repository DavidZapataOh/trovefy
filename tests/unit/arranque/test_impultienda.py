import pathlib

from trovefy.arranque.verificadores.impultienda import verificar_impultienda
from trovefy.mapa import FirmaAusente, cargar, leer_pantalla
from trovefy.navegador import Captura, NavegadorError

RAIZ = pathlib.Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/arranque"
PNG = b"\x89PNG\r\n\x1a\nfake"
MAPA = cargar(RAIZ / "templates/impultienda/mapa.yaml")
CONFIRMADO = {**MAPA, "capturado": "2026-12-01"}


def _fixture(nombre):
    return (FIX / f"impultienda_{nombre}.html").read_text()


def test_mapa_real_contra_fixtures():
    mapa = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    for nombre in ["plan", "tiendas", "pasarelas"]:
        texto = _fixture(nombre)
        assert leer_pantalla(mapa["pantallas"][nombre], texto)


def test_el_mapa_es_provisional_y_dice_de_donde_sale():
    assert MAPA["capturado"] is None and "impultienda.ar" in MAPA["fuente"] and "2026-11-10" in MAPA["fuente"]


def test_fixtures_son_sinteticas_y_lo_dicen():
    assert "no es una captura real" in _fixture("plan")


def falso(textos=None, url_final="https://app.impultienda.ar/dashboard/inicio", error=None):
    textos = textos or {n: _fixture(n) for n in ("plan", "tiendas", "pasarelas")}
    por_url = {MAPA["pantallas"][n]["url"]: t for n, t in textos.items()}
    llamadas = []

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        llamadas.append((servicio, url))
        if error:
            raise NavegadorError(error)
        if captura_png is not None:
            captura_png.write_bytes(PNG)
        return Captura(url_final, "", por_url[url], captura_png)

    capturar.llamadas = llamadas
    return capturar


def test_09_mapa_sin_capturar_no_certifica_ni_con_pantalla_perfecta(tmp_path):
    cap = falso()
    r = verificar_impultienda(tmp_path, capturar=cap, mapa=MAPA)
    assert r.ok is None and r.motivo == "no medido: patrón sin confirmar con tu pantalla real"
    assert not r.datos and not r.evidencia
    assert cap.llamadas[0][0] == "impultienda"
    assert any(f.suffix == ".png" for f in (tmp_path / "config/evidencia/provisional").iterdir())
    # tampoco suspende con una pantalla mala
    mala = {n: "otra cosa" for n in ("plan", "tiendas", "pasarelas")}
    assert verificar_impultienda(tmp_path, capturar=falso(mala), mapa=MAPA).ok is None


def test_09_confirmado_plan_activo_y_tienda(tmp_path):
    r = verificar_impultienda(tmp_path, capturar=falso(), mapa=CONFIRMADO)
    assert r.ok is True
    assert r.datos == {"plan": "Free", "tiendas": "3", "pasarelas": "whop,stripe"}
    assert r.evidencia and all((tmp_path / e).is_file() for e in r.evidencia)


def test_09_firma_ausente_es_no_medido_y_sin_mas_clics(tmp_path):
    textos = {"plan": _fixture("plan"), "tiendas": "Página rediseñada", "pasarelas": _fixture("pasarelas")}
    r = verificar_impultienda(tmp_path, capturar=falso(textos), mapa=CONFIRMADO)
    assert r.ok is None and r.motivo == "no medido: mapa desactualizado (tiendas)"


def test_09_sin_tienda_o_plan_inactivo_falla(tmp_path):
    sin_tienda = {"plan": _fixture("plan"), "tiendas": "<p>0 Tiendas activas</p>", "pasarelas": _fixture("pasarelas")}
    r = verificar_impultienda(tmp_path, capturar=falso(sin_tienda), mapa=CONFIRMADO)
    assert r.ok is False and "tienda" in r.motivo and r.arreglos
    inactivo = {"plan": "Plan actual: Free\nEstado del plan: Vencido", "tiendas": _fixture("tiendas"), "pasarelas": _fixture("pasarelas")}
    r = verificar_impultienda(tmp_path, capturar=falso(inactivo), mapa=CONFIRMADO)
    assert r.ok is False and "plan" in r.motivo


def test_09_campo_ilegible_es_no_medido(tmp_path):
    textos = {"plan": "Plan actual: Free", "tiendas": _fixture("tiendas"), "pasarelas": _fixture("pasarelas")}
    assert verificar_impultienda(tmp_path, capturar=falso(textos), mapa=CONFIRMADO).ok is None


def test_09_sesion_caducada_y_error_del_navegador(tmp_path):
    r = verificar_impultienda(tmp_path, capturar=falso(url_final="https://app.impultienda.ar/login"), mapa=CONFIRMADO)
    assert r.ok is None and "inicia sesión" in r.motivo and "impultienda" in r.motivo
    assert verificar_impultienda(tmp_path, capturar=falso(error="sin navegador"), mapa=CONFIRMADO).ok is None


def test_firma_ausente_lleva_la_pantalla():
    try:
        leer_pantalla(MAPA["pantallas"]["plan"], "nada")
    except FirmaAusente as exc:
        assert exc.pantalla is MAPA["pantallas"]["plan"]
