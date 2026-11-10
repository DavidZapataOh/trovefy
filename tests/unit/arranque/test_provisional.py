"""Evidencia provisional: el texto que leen los patrones se guarda junto al PNG (I-3, M-4)."""

import pathlib
import re
import stat

from trovify.arranque.estado import marcar_hecho
from trovify.arranque.verificadores.base import (
    PantallaProvisional,
    extracto,
    guardar_provisional,
    leer_texto_provisional,
    ultimo_texto_provisional,
)
from trovify.arranque.verificadores.impultienda import verificar_impultienda
from trovify.arranque.verificadores.meta_ids import verificar_pagina
from trovify.arranque.verificadores.pagos import verificar_hotmart
from trovify.mapa import cargar
from trovify.navegador import Captura

RAIZ = pathlib.Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/arranque"
PNG = b"\x89PNG\r\n\x1a\nfake"


def _sk():
    return "sk" + "-" + "q" * 24


def _prov(v):
    return v / "config/evidencia/provisional"


def test_guarda_texto_0600_y_url_sin_query(tmp_path):
    p = PantallaProvisional("pagina", "https://x.com/a?token=1#f", PNG, "Currency: USD\nTime zone: UTC\n")
    rutas, avisos = guardar_provisional(tmp_path, "06", [p])
    assert not avisos
    txt = ultimo_texto_provisional(tmp_path, "06")
    assert txt is not None and txt.relative_to(tmp_path).as_posix() in rutas
    assert stat.S_IMODE(txt.stat().st_mode) == 0o600
    contenido = txt.read_text()
    assert "token" not in contenido and "https://x.com/a" in contenido
    assert leer_texto_provisional(txt) == {"pagina": "Currency: USD\nTime zone: UTC\n"}
    png = next(_prov(tmp_path).glob("06-captura-*.png"))
    assert stat.S_IMODE(png.stat().st_mode) == 0o600


def test_secreto_en_el_texto_solo_guarda_el_png(tmp_path):
    p = PantallaProvisional("pagina", "https://x.com/a", PNG, "Currency: USD\nclave " + _sk())
    rutas, avisos = guardar_provisional(tmp_path, "06", [p])
    assert ultimo_texto_provisional(tmp_path, "06") is None
    assert any(r.endswith(".png") for r in rutas)
    assert avisos and "secreto" in avisos[0] and _sk() not in avisos[0]
    assert not any(_sk() in f.read_bytes().decode("latin-1") for f in _prov(tmp_path).iterdir())


def test_extracto_solo_lineas_cercanas_y_trozos_de_lineas_largas():
    patron = re.compile(r"Currency: ([A-Z]{3})")
    lineas = [f"linea {i}" for i in range(20)]
    lineas[10] = "Currency: USD"
    e = extracto("\n".join(lineas), [patron])
    assert e.splitlines() == [f"linea {i}" for i in (8, 9)] + ["Currency: USD"] + [f"linea {i}" for i in (11, 12)]
    largo = "fb_dtsg" + "x" * 5000 + '"delegate_page":{"id":"123"}' + "y" * 5000
    pid = re.compile(r'"delegate_page":\{[^{}]*?"id":"(\d+)"')
    e = extracto(largo, [pid])
    assert "fb_dtsg" not in e and pid.search(e).group(1) == "123" and len(e) < 200


def test_05_guarda_solo_fragmentos_del_html(tmp_path):
    html = (FIX / "pagina_publica.html").read_text()
    marcar_hecho(tmp_path, "05", datos={"url": "https://www.facebook.com/102506312071455"})

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        captura_png.write_bytes(PNG)
        return Captura(url, "fb_dtsg_sesion " + html, "texto visible", captura_png)

    r = verificar_pagina(tmp_path, capturar=capturar)
    assert r.ok is None
    txt = ultimo_texto_provisional(tmp_path, "05")
    contenido = txt.read_text()
    assert "fb_dtsg_sesion" not in contenido and "<!DOCTYPE" not in contenido and "</body>" not in contenido
    assert "102506312071455" in contenido


def _falso_por_url(textos):
    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        captura_png.write_bytes(PNG)
        return Captura(url, "", textos[url], captura_png)

    return capturar


def test_09_guarda_todas_las_capturas_y_textos(tmp_path):
    mapa = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    textos = {mapa["pantallas"][n]["url"]: (FIX / f"impultienda_{n}.html").read_text() for n in ("plan", "tiendas", "pasarelas")}
    r = verificar_impultienda(tmp_path, capturar=_falso_por_url(textos), mapa=mapa)
    assert r.ok is None
    pngs = sorted(f.name for f in _prov(tmp_path).glob("09-captura-*.png"))
    assert len(pngs) == 3 and any("plan" in n for n in pngs) and any("pasarelas" in n for n in pngs)
    secciones = leer_texto_provisional(ultimo_texto_provisional(tmp_path, "09"))
    assert set(secciones) == {"plan", "tiendas", "pasarelas"}


def test_10b_guarda_las_dos_capturas(tmp_path):
    mapa = cargar(RAIZ / "templates/hotmart/mapa.yaml")
    textos = {mapa["pantallas"][n]["url"]: (FIX / f"hotmart_{n}.html").read_text() for n in ("productos", "datos_financieros")}
    verificar_hotmart(tmp_path, capturar=_falso_por_url(textos), mapa=mapa)
    assert len(list(_prov(tmp_path).glob("10b-captura-*.png"))) == 2
    assert set(leer_texto_provisional(ultimo_texto_provisional(tmp_path, "10b"))) == {"productos", "datos_financieros"}


def test_navegador_capturar_guarda_el_texto(tmp_path, monkeypatch, capsys):
    from trovify import navegador
    from trovify.cli import main

    monkeypatch.setenv("HOME", str(tmp_path))

    def capturar(servicio, url, captura_png=None, **kw):
        captura_png.parent.mkdir(parents=True, exist_ok=True)
        captura_png.write_bytes(PNG)
        return Captura(url + "?token=1", "<html>", "Plan actual: Free", captura_png)

    monkeypatch.setattr(navegador, "capturar", capturar)
    destino = tmp_path / "c" / "pantalla.png"
    assert main(["navegador", "capturar", "impultienda", "https://app.impultienda.ar/x", "--png", str(destino)]) == 0
    txt = destino.with_suffix(".txt")
    assert "Plan actual: Free" in txt.read_text() and "token" not in txt.read_text()
    assert stat.S_IMODE(txt.stat().st_mode) == 0o600
    assert str(txt) in capsys.readouterr().out


def test_navegador_capturar_no_guarda_texto_con_secreto(tmp_path, monkeypatch, capsys):
    from trovify import navegador
    from trovify.cli import main

    monkeypatch.setenv("HOME", str(tmp_path))

    def capturar(servicio, url, captura_png=None, **kw):
        captura_png.write_bytes(PNG)
        return Captura(url, "", "clave " + _sk(), captura_png)

    monkeypatch.setattr(navegador, "capturar", capturar)
    destino = tmp_path / "pantalla.png"
    assert main(["navegador", "capturar", "impultienda", "https://app.impultienda.ar/x", "--png", str(destino)]) == 0
    assert not destino.with_suffix(".txt").exists()
    out = capsys.readouterr().out
    assert "secreto" in out and _sk() not in out
