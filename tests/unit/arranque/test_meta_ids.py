import pathlib

import pytest
from trovify.arranque.estado import marcar_hecho
from trovify.arranque.verificadores.base import Confirmacion
from trovify.arranque.verificadores.meta_ids import (
    extraer_business_id,
    extraer_page_id,
    verificar_business,
    verificar_pagina,
)
from trovify.cli import main
from trovify.navegador import Captura, NavegadorError

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures/arranque/pagina_publica.html"
CONF = Confirmacion(fecha="2026-11-11", fuente="prueba")
PNG = b"\x89PNG\r\n\x1a\nfake"


def falso(url_final="https://business.facebook.com/latest/settings?business_id=1234567890123", html="", png=PNG):
    llamadas = []

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        llamadas.append((servicio, url))
        if captura_png is not None and png is not None:
            captura_png.write_bytes(png)
        return Captura(url_final, html, "", captura_png)

    capturar.llamadas = llamadas
    return capturar


def test_business_id_de_la_url():
    assert extraer_business_id("https://business.facebook.com/settings/info?business_id=1234567890123") == "1234567890123"
    assert extraer_business_id("https://business.facebook.com/overview") is None
    assert extraer_business_id("https://business.facebook.com/x?business_id=abc") is None


def test_page_id_del_html():
    assert extraer_page_id(FIX.read_text()) == "102506312071455"
    assert extraer_page_id("<html></html>") is None


def test_04_sin_confirmar_no_certifica_y_guarda_provisional(tmp_path):
    for url in ("https://business.facebook.com/latest/settings?business_id=1234567890123&token=x", "https://business.facebook.com/overview"):
        r = verificar_business(tmp_path, capturar=falso(url))
        assert r.ok is None and r.motivo == "no medido: patrón sin confirmar con tu pantalla real" and not r.datos and not r.evidencia
    prov = tmp_path / "config/evidencia/provisional"
    assert any(f.suffix == ".png" for f in prov.iterdir())
    js = next(f for f in prov.iterdir() if f.suffix == ".json").read_text()
    assert "?" not in js and "business_id" not in js and "token" not in js


def test_05_sin_confirmar_con_sesion_no_certifica(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/102506312071455"})
    r = verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/102506312071455", FIX.read_text()))
    assert r.ok is None and "sin confirmar" in r.motivo and not r.datos
    assert (tmp_path / "config/evidencia/provisional").is_dir()


def test_05_id_distinto_al_de_la_url(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/999"})
    r = verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/999", FIX.read_text()), confirmacion=CONF)
    assert r.ok is False and "no coincide" in r.motivo


def test_04_con_id(tmp_path):
    cap = falso()
    r = verificar_business(tmp_path, capturar=cap, confirmacion=CONF)
    assert r.ok is True and r.datos == {"business_id": "1234567890123"}
    assert cap.llamadas == [("meta", "https://business.facebook.com/settings/")]
    assert any(e.endswith(".png") and (tmp_path / e).read_bytes() == PNG for e in r.evidencia)


def test_04_sesion_caducada(tmp_path):
    r = verificar_business(tmp_path, capturar=falso("https://www.facebook.com/login/?next=x"), confirmacion=CONF)
    assert r.ok is None and r.motivo.startswith("no medido: inicia sesión")
    assert "trovify navegador abrir meta https://business.facebook.com/" in r.motivo and not r.evidencia


def test_04_sin_id(tmp_path):
    r = verificar_business(tmp_path, capturar=falso("https://business.facebook.com/overview"), confirmacion=CONF)
    assert r.ok is False and r.arreglos and not r.evidencia


def test_04_navegador_roto(tmp_path):
    def roto(*a, **k):
        raise NavegadorError("ya hay un navegador de Trovify abierto")

    r = verificar_business(tmp_path, capturar=roto)
    assert r.ok is None and "navegador" in r.motivo


def test_05_necesita_url(tmp_path):
    cap = falso()
    r = verificar_pagina(tmp_path, capturar=cap)
    assert r.ok is None and "--dato url=" in r.arreglos[0] and not cap.llamadas


def test_05_url_ajena_no_se_abre(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://evil.example.com/x"})
    cap = falso()
    assert verificar_pagina(tmp_path, capturar=cap).ok is None and not cap.llamadas


def test_05_con_url(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/102506312071455"})
    cap = falso("https://www.facebook.com/102506312071455", FIX.read_text())
    r = verificar_pagina(tmp_path, capturar=cap, confirmacion=CONF)
    assert r.ok is True and r.datos == {"page_id": "102506312071455"}
    assert cap.llamadas[0][0] == "meta"


def test_05_sin_id_y_sesion(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/x"})
    assert verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/x", "<html/>"), confirmacion=CONF).ok is False
    assert verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/checkpoint/1")).ok is None


def test_cli_hecho_con_datos(tmp_path):
    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", "url=https://www.facebook.com/x", "--dato", "otro=1"]) == 0
    from trovify.arranque.estado import cargar

    assert next(p for p in cargar(tmp_path) if p.id == "05").datos == {"url": "https://www.facebook.com/x", "otro": "1"}


@pytest.mark.parametrize("dato", ["sin-igual", "URL=x", "a b=1", "url=", "k=sk-ant-api03-" + "a" * 40, "k=EAA" + "a" * 30])
def test_cli_hecho_rechaza_datos_malos(tmp_path, dato):
    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", dato]) == 2


def test_cli_dato_url_se_limpia(tmp_path):
    from trovify.arranque.estado import cargar

    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", "url=https://www.facebook.com/profile.php?id=5&ref=x#a"]) == 0
    assert next(p for p in cargar(tmp_path) if p.id == "05").datos["url"] == "https://www.facebook.com/profile.php?id=5"


def test_cli_dato_url_profile_php_solo_id_numerico(tmp_path):
    from trovify.arranque.estado import cargar

    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", "url=https://www.facebook.com/profile.php?id=abc&x=1"]) == 0
    assert next(p for p in cargar(tmp_path) if p.id == "05").datos["url"] == "https://www.facebook.com/profile.php"
    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", "url=https://www.facebook.com/otra?id=5"]) == 0
    assert next(p for p in cargar(tmp_path) if p.id == "05").datos["url"] == "https://www.facebook.com/otra"


def test_05_url_profile_php_exige_el_mismo_id(tmp_path):
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/profile.php?id=999"})
    r = verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/profile.php?id=999", FIX.read_text()), confirmacion=CONF)
    assert r.ok is False and "no coincide" in r.motivo
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/profile.php?id=102506312071455"})
    r = verificar_pagina(tmp_path, capturar=falso("https://www.facebook.com/profile.php?id=102506312071455", FIX.read_text()), confirmacion=CONF)
    assert r.ok is True


@pytest.mark.parametrize("url", ["http://www.facebook.com/x", "https://evil.com/x", "https://facebook.com.evil.com/x",
                                 "https://www.facebook.com/x?access_token=1", "https://www.facebook.com/x?code=1",
                                 "https://www.facebook.com/x?sig=1", "https://www.facebook.com/x#fb_dtsg=1", "https://www.facebook.com/x?token=1"])
def test_cli_dato_url_rechazada(tmp_path, url):
    assert main(["arranque", "hecho", "05", "--vault", str(tmp_path), "--dato", f"url={url}"]) == 2
