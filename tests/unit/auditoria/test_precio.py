import io
import pathlib
from datetime import date

from trovify.auditoria.precio import precio_local, precio_soportable
from trovify.caza.senales import Medida
from trovify.config.mercados import cargar
from trovify.fx import a_eur, cambios

XML = (pathlib.Path(__file__).resolve().parents[2] / "fixtures/fx/eurofxref-daily.xml").read_bytes()
M = cargar(pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/mercados.yaml")
HOY = date(2026, 11, 10)


def abrir_falso(url, timeout=15):
    return io.BytesIO(XML)


def test_cambio_y_banda(tmp_path):
    t = cambios(tmp_path, HOY, abrir=abrir_falso)
    eur = a_eur(79, "RON", t)
    assert eur.valor is not None and 14 < eur.valor < 17  # 79 lei ≈ 15,9 € con un cambio ~4,97
    assert precio_soportable(Medida(13.90), (11.90, 15.90)).valor == 1
    assert precio_soportable(Medida(17.90), (11.90, 15.90)).valor == 0.5
    assert precio_soportable(Medida(30.0), (11.90, 15.90)).valor == 0


def test_moneda_sin_cambio_no_medido(tmp_path):
    t = cambios(tmp_path, HOY, abrir=abrir_falso)
    m = a_eur(199, "MDL", t)
    assert m.valor is None and "sin cambio de referencia para MDL" in m.motivo
    assert a_eur(13.9, "EUR", None).valor is None


def test_eur_con_tasas():
    assert a_eur(13.9, "EUR", {"EUR": 1.0}).valor == 13.9


def test_bulgaria_en_euros():
    assert M["BG"].moneda == "EUR"


def test_precio_sin_medir_no_soportable():
    r = precio_soportable(Medida(None, "no medido: x"), (11.9, 15.9))
    assert r.valor is None and r.motivo == "no medido: x"


def test_precio_local(tmp_path):
    t = cambios(tmp_path, HOY, abrir=abrir_falso)
    ron = precio_local(15.9, M["RO"], t)
    assert ron.valor is not None and 70 < ron.valor < 90
    assert precio_local(15.9, M["BG"], None).valor == 15.9
    assert precio_local(15.9, M["RO"], None).valor is None
    assert precio_local(15.9, M["MD"], t).valor is None


def test_cache_del_dia_y_sin_red(tmp_path):
    cambios(tmp_path, HOY, abrir=abrir_falso)
    assert (tmp_path / "data/cache/fx-2026-11-10.json").exists()

    def sin_red(url, timeout=15):
        raise OSError("sin red")

    assert cambios(tmp_path, HOY, abrir=sin_red)["EUR"] == 1.0  # caché del mismo día
    assert cambios(tmp_path / "otro", HOY, abrir=sin_red) is None


def test_xml_hostil_o_invalido_es_none(tmp_path):
    def con(xml):
        return lambda url, timeout=15: io.BytesIO(xml)

    ent = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a/>'
    assert cambios(tmp_path / "a", HOY, abrir=con(ent)) is None
    assert cambios(tmp_path / "b", HOY, abrir=con(b"<no xml")) is None
    malo = XML.replace(b"rate='1.1214'", b"rate='-3'")
    assert cambios(tmp_path / "c", HOY, abrir=con(malo)) is None
    nan = XML.replace(b"rate='1.1214'", b"rate='nan'")
    assert cambios(tmp_path / "d", HOY, abrir=con(nan)) is None


def test_xml_utf16_con_doctype_es_none(tmp_path):
    hostil = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "y">]><a/>'.encode("utf-16")
    assert cambios(tmp_path, HOY, abrir=lambda url, timeout=15: io.BytesIO(hostil)) is None
    assert cambios(tmp_path / "u", HOY, abrir=lambda url, timeout=15: io.BytesIO(XML.replace(b"UTF-8", b"UTF-16"))) is None


def test_cambio_del_dia_con_fecha_y_fuente(tmp_path):
    from trovify.fx import URL, cambio_del_dia

    c = cambio_del_dia(tmp_path, HOY, abrir=abrir_falso)
    assert c.fecha == "2026-11-10" and c.url == URL and c.tasas["RON"] == 5.3442

    def sin_red(url, timeout=15):
        raise OSError("sin red")

    c2 = cambio_del_dia(tmp_path, HOY, abrir=sin_red)  # de la caché del día, con su fecha
    assert c2.fecha == "2026-11-10" and c2.tasas == c.tasas


def test_cache_antigua_sin_fecha_sigue_valiendo(tmp_path):
    import json

    from trovify.fx import cambio_del_dia

    ruta = tmp_path / "data/cache/fx-2026-11-10.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"RON": 5.0}), encoding="utf-8")
    c = cambio_del_dia(tmp_path, HOY, abrir=lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert c.tasas["RON"] == 5.0 and c.fecha is None
