"""Plan 22, Tarea 6: «Activar campaña» con miniaturas (álbum) antes del mensaje con botones ([D-33])."""
from __future__ import annotations

import os

import pytest
from ejecutor.fabricas_graph import anuncio, conjunto, estructura
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from ejecutor.test_servicio import RUTA_IMG, _montaje
from ejecutor.test_servicio import estructura as estructura_dict
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor.montaje import montar
from trovefy_ejecutor.telegram import ClienteTelegram

NADA = lambda s: None
ACTIVAR = "P-20261112-800"


# -- evidencia del montaje -------------------------------------------------------------------------------------------
def test_activar_trae_anuncios_en_evidencia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    conjuntos = [conjunto(nombre=f"AD0{i} G1 x", anuncios=(anuncio(nombre=f"AD0{i} G1 x"),)) for i in range(1, 6)]
    r = montar(estructura(origen="/montar", conjuntos=conjuntos), g, alm, aud, vault, esperar=NADA)
    anuncios = r.nueva_propuesta["evidencia"]["anuncios"]
    assert len(anuncios) == 5 and [a["nombre"] for a in anuncios] == [f"AD0{i} G1 x" for i in range(1, 6)]


# -- cliente: sendPhoto / sendMediaGroup -----------------------------------------------------------------------------
def test_album_por_multipart_y_url():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base, dormir=NADA)
        mids = c.enviar_album(42, [("AD01 G1 x", b"\xff\xd8 jpg"), ("AD02\n G1", "https://scontent.example/a.jpg")])
        assert len(mids) == 2
        ll = next(x for x in tg.llamadas if x.metodo == "sendMediaGroup")
        assert ll.params["_archivos"] == {"foto0": 6} and ll.params["chat_id"] == 42
        assert [m["media"] for m in ll.params["media"]] == ["attach://foto0", "https://scontent.example/a.jpg"]
        assert ll.params["media"][1]["caption"] == "AD02 G1"
        assert len(c.enviar_album(42, [("AD01", b"jpg")])) == 1
        assert [x.metodo for x in tg.llamadas][-1] == "sendPhoto"
        assert c.enviar_album(42, [("AD01", "https://scontent.example/b.jpg")])


def test_album_maximo_diez():
    with TelegramFalso() as tg:
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base, dormir=NADA)
        with pytest.raises(ValueError, match="máximo 10"):
            c.enviar_album(42, [(f"AD{i}", b"x") for i in range(11)])
        with pytest.raises(ValueError):
            c.enviar_album(42, [("AD1", "http://inseguro.example/a.jpg")])
        assert len(c.enviar_album(42, [(f"AD{i}", b"x") for i in range(10)])) == 10
        assert not [x for x in tg.llamadas if x.metodo == "sendMediaGroup" and len(x.params["media"]) > 10]


def test_album_error_no_lleva_el_token():
    with TelegramFalso() as tg:
        tg.fallar("sendMediaGroup", codigo=400)
        c = ClienteTelegram(TOKEN_PRUEBA, tg.base, dormir=NADA)
        with pytest.raises(Exception) as e:
            c.enviar_album(42, [("a", b"x"), ("b", b"y")])
        assert TOKEN_PRUEBA not in str(e.value) and TOKEN_PRUEBA not in repr(e.value)


# -- servicio --------------------------------------------------------------------------------------------------------
@pytest.fixture
def servicio(tmp_path):
    m = _montaje(tmp_path)
    try:
        yield m
    finally:
        m.ej.almacen.cerrar()
        _ejecutar._EMITIDOS.clear()


def _montar(m, **cambios):
    d = estructura_dict(**cambios)
    m.depositar(d)
    m.ej.ciclo()
    assert m.estado("P-20261112-002") == "ejecutada"
    return m.ej.almacen.obtener(ACTIVAR)


def test_album_antes_del_mensaje_con_botones(servicio):
    m = servicio
    _montar(m)
    assert m.estado(ACTIVAR) == "enviada"
    assert m.tg.orden[-2:] == ["album", "mensaje"]
    (foto,) = m.tg.albumes[0]
    assert foto[0] == "AD01" and foto[1] == (m.vault / RUTA_IMG).read_bytes()
    texto = m.mensaje_de(ACTIVAR)["texto"]
    assert "AD01 · “Titulo” · Texto · vista previa: https://fb.me/" in texto
    assert m.mensaje_de(ACTIVAR)["botones"]


def test_album_ruta_fuera_del_vault_se_omite(servicio):
    m = servicio
    fuera = m.tmp / "fuera.jpg"
    fuera.write_bytes(b"\xff\xd8 ajena")
    enlace = m.vault / "productos/p-0001/creativos/BG/t1/miniaturas/AD01.jpg"
    enlace.parent.mkdir(parents=True)
    os.symlink(fuera, enlace)
    anuncios = estructura_dict()["conjuntos"][0]["anuncios"]
    anuncios[0]["miniatura"] = "productos/p-0001/creativos/BG/t1/miniaturas/AD01.jpg"
    conjuntos = estructura_dict()["conjuntos"]
    conjuntos[0]["anuncios"] = anuncios
    _montar(m, conjuntos=conjuntos)
    assert m.tg.albumes == [] and m.estado(ACTIVAR) == "enviada"
    assert m.tg.orden[-1] == "mensaje"


def test_album_falla_y_el_mensaje_sale(servicio):
    m = servicio
    m.tg.fallar_album = True
    _montar(m)
    assert m.estado(ACTIVAR) == "enviada" and m.mensaje_de(ACTIVAR)["botones"]
    assert m.eventos("error", donde="telegram")


def test_activar_sin_anuncios_no_manda_album(servicio):
    from ejecutor.test_servicio import C1

    m = servicio
    m.depositar({"version": 1, "id": "P-20261112-020", "tipo": "activar",
                 "creada": estructura_dict()["creada"], "origen": "/montar", "cuenta": "act_0000000000000000",
                 "operaciones": [{"entidad": "campaign", "id": C1, "campo": "status", "de_esperado": "PAUSED",
                                  "a": "ACTIVE"}], "motivo": "prueba"})
    m.ej.ciclo()
    assert m.tg.albumes == []
