import os
import pathlib
import shutil

from trovify.arranque.estado import marcar_hecho
from trovify.arranque.verificadores.base import Confirmacion
from trovify.arranque.verificadores.cuenta import (
    CONFIRMACION_06,
    evaluar_cuenta,
    extraer_act,
    leer_ajustes_cuenta,
    mercado_elegido,
    verificar_cuenta,
)
from trovify.navegador import Captura, NavegadorError

RAIZ = pathlib.Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/arranque/ajustes_cuenta.txt"
CONF = Confirmacion(fecha="2026-11-11", fuente="prueba")
PNG = b"\x89PNG\r\n\x1a\nfake"
ACT = "https://www.facebook.com/ads/manager/account_settings/account_billing/?act=987654321"

BIEN = {"moneda": "USD", "zona": "Europe/Bucharest", "limite_gasto": "250"}


def test_cuenta_sin_mercado_elegido():
    r = evaluar_cuenta(BIEN, None, 250)
    assert r.ok is None and "auditar" in r.motivo


def test_zona_distinta_falla():
    r = evaluar_cuenta({**BIEN, "zona": "America/Bogota"}, "Europe/Bucharest", 250)
    assert r.ok is False and "zona" in r.motivo


def test_moneda_y_limite():
    assert evaluar_cuenta({**BIEN, "moneda": "COP"}, "Europe/Bucharest", 250).ok is False
    assert evaluar_cuenta({**BIEN, "limite_gasto": None}, "Europe/Bucharest", 250).ok is None  # no se ve el rótulo
    assert evaluar_cuenta({**BIEN, "limite_gasto": "sin_limite"}, "Europe/Bucharest", 250).ok is False
    assert evaluar_cuenta({**BIEN, "limite_gasto": "250.01"}, "Europe/Bucharest", 250).ok is False
    assert evaluar_cuenta({**BIEN, "limite_gasto": "100"}, "Europe/Bucharest", 250).ok is True
    assert evaluar_cuenta(BIEN, "Europe/Bucharest", 250).ok is True


def test_act():
    assert extraer_act("https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=987654321") == "987654321"
    assert extraer_act("https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=abc") is None
    assert extraer_act("https://adsmanager.facebook.com/adsmanager/manage/campaigns") is None


def test_leer_ajustes_de_la_fixture():
    assert leer_ajustes_cuenta(FIX.read_text()) == {"moneda": "USD", "zona": "Europe/Bucharest", "limite_gasto": "250.00"}
    assert leer_ajustes_cuenta("nada") == {"moneda": None, "zona": None, "limite_gasto": None}
    t = "Currency: COP\nTime zone: (GMT-05:00) America/Bogota\nAccount spending limit: US$1,250.50 USD\n"
    assert leer_ajustes_cuenta(t) == {"moneda": "COP", "zona": "America/Bogota", "limite_gasto": "1250.50"}


def _vault(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    for n in ("umbrales.yaml", "mercados.yaml"):
        shutil.copy(RAIZ / "templates/cerebro/config" / n, cfg / n)
    return tmp_path


def _eleccion(vault, producto, nombre, pais, mtime=None):
    d = vault / "productos" / producto / "decisiones"
    d.mkdir(parents=True, exist_ok=True)
    f = d / nombre
    f.write_text(f"---\npais: {pais}\n---\ncuerpo\n", encoding="utf-8")
    if mtime:
        os.utime(f, (mtime, mtime))
    return f


def test_mercado_elegido(tmp_path):
    v = _vault(tmp_path)
    assert mercado_elegido(v) is None
    _eleccion(v, "a", "2026-11-12-eleccion.md", "RO")
    assert mercado_elegido(v) == "Europe/Bucharest"
    _eleccion(v, "b", "2026-11-20-eleccion.md", "CZ")
    assert mercado_elegido(v) == "Europe/Prague"
    _eleccion(v, "a", "2026-11-01-eleccion.md", "MD")  # más antiguo: no cuenta
    assert mercado_elegido(v) == "Europe/Prague"


def test_mercado_elegido_pais_desconocido_o_sin_pais(tmp_path):
    v = _vault(tmp_path)
    _eleccion(v, "a", "2026-11-12-eleccion.md", "ZZ")
    assert mercado_elegido(v) is None
    (v / "productos/a/decisiones/2026-11-13-eleccion.md").write_text("sin frontmatter", encoding="utf-8")
    assert mercado_elegido(v) is None


def falso(url_final=ACT, texto="", png=PNG, error=None):
    llamadas = []

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        llamadas.append((servicio, url))
        if error:
            raise NavegadorError(error)
        if captura_png is not None and png is not None:
            captura_png.write_bytes(png)
        return Captura(url_final, "", texto, captura_png)

    capturar.llamadas = llamadas
    return capturar


def test_06_sin_confirmar_no_certifica_ni_con_pantalla_perfecta(tmp_path):
    v = _vault(tmp_path)
    _eleccion(v, "a", "2026-11-12-eleccion.md", "RO")
    assert CONFIRMACION_06.fecha is None
    cap = falso(texto=FIX.read_text())
    r = verificar_cuenta(v, capturar=cap)
    assert r.ok is None and r.motivo == "no medido: patrón sin confirmar con tu pantalla real" and not r.datos and not r.evidencia
    assert cap.llamadas[0][0] == "meta"
    assert any(f.suffix == ".png" for f in (v / "config/evidencia/provisional").iterdir())
    # tampoco suspende con una pantalla mala
    assert verificar_cuenta(v, capturar=falso(texto="Currency: COP")).ok is None


def test_06_sesion_caducada_o_error(tmp_path):
    v = _vault(tmp_path)
    r = verificar_cuenta(v, capturar=falso("https://www.facebook.com/login/?next=x"), confirmacion=CONF)
    assert r.ok is None and "inicia sesión" in r.motivo
    assert verificar_cuenta(v, capturar=falso(error="sin navegador"), confirmacion=CONF).ok is None


def test_06_confirmado_verifica_y_guarda_act(tmp_path):
    v = _vault(tmp_path)
    _eleccion(v, "a", "2026-11-12-eleccion.md", "RO")
    r = verificar_cuenta(v, capturar=falso(texto=FIX.read_text()), confirmacion=CONF)
    assert r.ok is True and r.datos == {"act_id": "987654321"} and len(r.evidencia) == 2
    assert all((v / e).is_file() for e in r.evidencia)


def test_06_confirmado_casos_negativos(tmp_path):
    v = _vault(tmp_path)
    texto = FIX.read_text()
    assert verificar_cuenta(v, capturar=falso(texto=texto), confirmacion=CONF).ok is None  # sin mercado elegido
    _eleccion(v, "a", "2026-11-12-eleccion.md", "CZ")
    assert verificar_cuenta(v, capturar=falso(texto=texto), confirmacion=CONF).ok is False  # zona distinta
    _eleccion(v, "a", "2026-11-13-eleccion.md", "RO")
    assert verificar_cuenta(v, capturar=falso(texto=texto.replace("$250.00", "$900.00")), confirmacion=CONF).ok is False
    assert verificar_cuenta(v, capturar=falso(texto="nada"), confirmacion=CONF).ok is None
    assert verificar_cuenta(v, capturar=falso(url_final="https://www.facebook.com/ads/x", texto=texto), confirmacion=CONF).ok is None


def test_06_usa_el_act_guardado(tmp_path):
    v = _vault(tmp_path)
    marcar_hecho(v, "06", datos={"act_id": "555"})
    cap = falso()
    verificar_cuenta(v, capturar=cap)
    assert cap.llamadas[0][1].endswith("?act=555")


import pytest


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("250,00", "250.00"), ("1.000,00", "1000.00"), ("1,000.00", "1000.00"), ("250,00 US$", "250.00"),
        ("US$250.00", "250.00"), ("250 USD", "250"), ("$1,250.50", "1250.50"), ("1,000", "1000"), ("1.000.000", "1000000"),
        ("1.000", ilegible := "ilegible"), ("12,345,6", ilegible), ("1.000,000", ilegible), ("abc", "sin_limite"), ("—", "sin_limite"),
    ],
)
def test_numeros_en_formato_local(bruto, esperado):
    assert leer_ajustes_cuenta(f"Account spending limit: {bruto}")["limite_gasto"] == esperado


def test_etiquetas_en_espanol_y_zonas_utc():
    t = "Moneda: USD\nZona horaria: (GMT+02:00) Europe/Bucharest\nLímite de gasto de la cuenta: 250,00 US$\n"
    assert leer_ajustes_cuenta(t) == {"moneda": "USD", "zona": "Europe/Bucharest", "limite_gasto": "250.00"}
    assert leer_ajustes_cuenta("Time zone: UTC")["zona"] == "UTC"
    assert leer_ajustes_cuenta("Time zone: GMT+3")["zona"] == "GMT+3"
    r = evaluar_cuenta({**BIEN, "zona": "UTC"}, "Europe/Bucharest", 250)
    assert r.ok is False and "UTC" in r.motivo


def test_limite_ilegible_es_no_medido_y_cero_es_invalido():
    assert evaluar_cuenta({**BIEN, "limite_gasto": "ilegible"}, "Europe/Bucharest", 250).ok is None
    r = evaluar_cuenta({**BIEN, "limite_gasto": "0"}, "Europe/Bucharest", 250)
    assert r.ok is False and "inválido" in r.motivo


def test_sin_limite_menciona_prepago():
    r = evaluar_cuenta({**BIEN, "limite_gasto": "sin_limite"}, "Europe/Bucharest", 250)
    assert r.ok is False and "pago automático con tarjeta" in " ".join(r.arreglos)


def test_moneda_se_mira_antes_que_el_mercado():
    r = evaluar_cuenta({**BIEN, "moneda": "COP"}, None, 250)
    assert r.ok is False and "COP" in r.motivo
    assert evaluar_cuenta(BIEN, None, 250).ok is None


def test_rotulo_del_limite_sin_cantidad_es_sin_limite_y_sin_rotulo_es_none():
    base = "Currency: USD\nTime zone: Europe/Bucharest\n"
    assert leer_ajustes_cuenta(base + "Account spending limit\nSet limit\n")["limite_gasto"] == "sin_limite"
    assert leer_ajustes_cuenta(base)["limite_gasto"] is None
    r = evaluar_cuenta({**BIEN, "limite_gasto": None}, "Europe/Bucharest", 250)
    assert r.ok is None and "límite" in r.motivo
