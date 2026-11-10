import pathlib

import pytest
from trovify.arranque.estado import cargar as cargar_pasos
from trovify.arranque.estado import marcar_hecho, siguiente
from trovify.arranque.verificadores.pagos import (
    URL_DOCS_WHOP,
    evaluar_hotmart,
    evaluar_whop,
    medir_pago_a_co,
    verificar_hotmart,
    verificar_whop,
)
from trovify.mapa import cargar
from trovify.navegador import Captura

RAIZ = pathlib.Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/arranque"
PNG = b"\x89PNG\r\n\x1a\nfake"


def test_whop_sin_pago_a_colombia_manda_a_hotmart():
    r = evaluar_whop(False, None, None)
    assert r.ok is False and "10b" in r.arreglos[0]


def test_whop_completo():
    assert evaluar_whop(True, "aprobado", True).ok is True
    assert evaluar_whop(True, "pendiente", True).ok is False
    assert evaluar_whop(True, None, True).ok is None


def test_whop_no_conectado_en_impultienda_y_kyc_raro():
    r = evaluar_whop(True, "aprobado", False)
    assert r.ok is False and "Impultienda" in r.arreglos[0]
    assert evaluar_whop(True, "algo raro", True).ok is None
    assert evaluar_whop(None, "aprobado", True).ok is None


def test_hotmart():
    assert evaluar_hotmart(True, True).ok is True
    assert evaluar_hotmart(True, False).ok is False
    assert evaluar_hotmart(None, True).ok is None
    assert evaluar_hotmart(False, None).ok is None


# --- pago_a_co desde la documentación pública de Whop ---
PAISES = "".join(f'<span data-as="p">{p}</span>' for p in ["Chile", "Mexico", "Peru", "Brazil", "Colombia", "Cook Islands"])


def _docs(paises=PAISES):
    return f"<h2>Supported countries</h2><div>{paises}</div><p>Note that different payout options will be available</p>"


def test_pago_a_co_lee_la_lista_publica():
    pidio = []

    def fetch(url):
        pidio.append(url)
        return _docs()

    assert medir_pago_a_co(fetch) is True and pidio == [URL_DOCS_WHOP]


def test_pago_a_co_exclusion_clara_solo_si_la_lista_se_reconoce():
    sin_co = PAISES.replace('<span data-as="p">Colombia</span>', "")
    assert medir_pago_a_co(lambda u: _docs(sin_co)) is False
    # página sin la lista, o con la lista truncada: no medido, no «no paga»
    assert medir_pago_a_co(lambda u: "<p>Página rediseñada</p>") is None
    assert medir_pago_a_co(lambda u: _docs('<span data-as="p">Chile</span>')) is None


def test_pago_a_co_error_de_red_es_none():
    def roto(url):
        raise OSError("sin red")

    assert medir_pago_a_co(roto) is None


# --- verificador 10 ---
MAPA_WHOP = cargar(RAIZ / "templates/whop/mapa.yaml")
MAPA_IMP = cargar(RAIZ / "templates/impultienda/mapa.yaml")
WHOP_OK = {**MAPA_WHOP, "capturado": "2026-12-01"}
IMP_OK = {**MAPA_IMP, "capturado": "2026-12-01"}


def _vault_con_pasos(tmp_path):
    cargar_pasos(tmp_path)  # crea config/arranque.yaml
    return tmp_path


def falso(whop=None, pasarelas=None):
    textos = {
        MAPA_WHOP["pantallas"]["balances"]["url"]: whop or (FIX / "whop_balances.html").read_text(),
        MAPA_IMP["pantallas"]["pasarelas"]["url"]: pasarelas or (FIX / "impultienda_pasarelas.html").read_text(),
        MAPA_IMP["pantallas"]["plan"]["url"]: "x",
    }
    llamadas = []

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        llamadas.append((servicio, url))
        if captura_png is not None:
            captura_png.write_bytes(PNG)
        return Captura("https://whop.com/dashboard/balance/", "", textos[url], captura_png)

    capturar.llamadas = llamadas
    return capturar


def _docs_ok(url):
    return _docs()


def test_10_whop_no_paga_a_colombia_bloquea_10_y_propone_10b(tmp_path):
    v = _vault_con_pasos(tmp_path)
    cap = falso()
    sin_co = _docs(PAISES.replace('<span data-as="p">Colombia</span>', ""))
    r = verificar_whop(v, capturar=cap, fetch=lambda u: sin_co, mapa=WHOP_OK, mapa_impultienda=IMP_OK)
    assert r.ok is False and "10b" in r.arreglos[0] and cap.llamadas == []  # ni abre el panel
    pasos = cargar_pasos(v)
    assert next(p for p in pasos if p.id == "10").estado == "bloqueado"
    # con todo lo anterior verificado, el siguiente es 10b
    for i in ("00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "16"):
        marcar_hecho(v, i)
    assert siguiente(cargar_pasos(v)).id == "10b"


def test_10_mapa_sin_capturar_no_certifica(tmp_path):
    v = _vault_con_pasos(tmp_path)
    cap = falso()
    r = verificar_whop(v, capturar=cap, fetch=_docs_ok, mapa=MAPA_WHOP, mapa_impultienda=IMP_OK)
    assert r.ok is None and r.motivo == "no medido: patrón sin confirmar con tu pantalla real"
    assert any("Colombia" in ln for ln in r.lineas)  # lo medido en la documentación pública se muestra
    assert cap.llamadas[0][0] == "whop"
    assert next(p for p in cargar_pasos(v) if p.id == "10").estado == "pendiente"


def test_10_confirmado_todo_bien(tmp_path):
    v = _vault_con_pasos(tmp_path)
    r = verificar_whop(v, capturar=falso(), fetch=_docs_ok, mapa=WHOP_OK, mapa_impultienda=IMP_OK)
    assert r.ok is True and r.evidencia and all((v / e).is_file() for e in r.evidencia)
    assert r.datos["pago_a_co"] == "si"


def test_10_kyc_pendiente_o_whop_sin_conectar(tmp_path):
    v = _vault_con_pasos(tmp_path)
    pend = "<h1>Balances</h1><a>Payout methods</a><p>Identity verification: Pending</p>"
    assert verificar_whop(v, capturar=falso(whop=pend), fetch=_docs_ok, mapa=WHOP_OK, mapa_impultienda=IMP_OK).ok is False
    sin_whop = "<h2>Pasarelas de pago</h2><p>Pasarelas conectadas: Stripe</p>"
    assert verificar_whop(v, capturar=falso(pasarelas=sin_whop), fetch=_docs_ok, mapa=WHOP_OK, mapa_impultienda=IMP_OK).ok is False


def test_10_firma_ausente_y_docs_ilegibles(tmp_path):
    v = _vault_con_pasos(tmp_path)
    r = verificar_whop(v, capturar=falso(whop="rediseñada"), fetch=_docs_ok, mapa=WHOP_OK, mapa_impultienda=IMP_OK)
    assert r.ok is None and "mapa desactualizado (balances)" in r.motivo
    r = verificar_whop(v, capturar=falso(), fetch=lambda u: "nada", mapa=WHOP_OK, mapa_impultienda=IMP_OK)
    assert r.ok is None  # sin pago_a_co medido no se certifica


# --- verificador 10b ---
MAPA_HOT = cargar(RAIZ / "templates/hotmart/mapa.yaml")
HOT_OK = {**MAPA_HOT, "capturado": "2026-12-01"}


def falso_hotmart(productos=None, financieros=None):
    textos = {
        MAPA_HOT["pantallas"]["productos"]["url"]: productos or (FIX / "hotmart_productos.html").read_text(),
        MAPA_HOT["pantallas"]["datos_financieros"]["url"]: financieros or (FIX / "hotmart_datos_financieros.html").read_text(),
    }

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        assert servicio == "hotmart"
        if captura_png is not None:
            captura_png.write_bytes(PNG)
        return Captura("https://app.hotmart.com/x", "", textos[url], captura_png)

    return capturar


def test_10b_sin_capturar_no_certifica(tmp_path):
    r = verificar_hotmart(tmp_path, capturar=falso_hotmart(), mapa=MAPA_HOT)
    assert r.ok is None and "sin confirmar" in r.motivo


def test_10b_confirmado(tmp_path):
    r = verificar_hotmart(tmp_path, capturar=falso_hotmart(), mapa=HOT_OK)
    assert r.ok is True and r.evidencia
    sin_cuenta = "<h1>Datos financieros</h1><p>Cuentas registradas: 0</p>"
    r = verificar_hotmart(tmp_path, capturar=falso_hotmart(financieros=sin_cuenta), mapa=HOT_OK)
    assert r.ok is False and "primera venta" in " ".join(r.arreglos)
    otro_pais = (FIX / "hotmart_datos_financieros.html").read_text().replace("Colombia", "Brasil")
    assert verificar_hotmart(tmp_path, capturar=falso_hotmart(financieros=otro_pais), mapa=HOT_OK).ok is False
    pend = (FIX / "hotmart_datos_financieros.html").read_text().replace("Aprobada", "En análisis")
    assert verificar_hotmart(tmp_path, capturar=falso_hotmart(financieros=pend), mapa=HOT_OK).ok is False
    sin_prod = "<h1>Productos</h1><p>0 productos</p>"
    assert verificar_hotmart(tmp_path, capturar=falso_hotmart(productos=sin_prod), mapa=HOT_OK).ok is False


def test_10b_firma_ausente(tmp_path):
    r = verificar_hotmart(tmp_path, capturar=falso_hotmart(productos="rediseñada"), mapa=HOT_OK)
    assert r.ok is None and "mapa desactualizado (productos)" in r.motivo


@pytest.mark.parametrize("servicio", ["impultienda", "whop", "hotmart"])
def test_mapas_reales_validan(servicio):
    assert cargar(RAIZ / f"templates/{servicio}/mapa.yaml")["capturado"] is None
