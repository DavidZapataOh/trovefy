"""Leer la tanda aprobada del 21 y elegir los 5 del test (plan 22, Tarea 1)."""
from __future__ import annotations

import os

import pytest
from trovefy.montar import TandaInvalida
from trovefy.montar.tanda import elegir, leer_tanda
from trovefy.tracking.modelo import PLANTILLA_UTM

from .ejemplos import PAIS, P, manifest_filas, reescribir_manifest


def test_tanda_ok_elige_cinco_con_un_video(vault_zz):
    t = leer_tanda(vault_zz, P, PAIS, "t1")
    assert t.aprobada, t.motivo
    assert t.grupo == 1 and len(t.piezas) == 10
    e = elegir(t.piezas, n=5)
    assert [p.id for p in e] == ["AD01", "AD02", "AD03", "AD04", "AD05"]
    assert any(p.tipo == "video" for p in e)
    assert e[0].nombre.startswith("AD01 G1 ")


def test_elegir_por_ids_respeta_orden(vault_zz):
    t = leer_tanda(vault_zz, P, PAIS, "t1")
    assert [p.id for p in elegir(t.piezas, ids=["AD03", "AD01"])] == ["AD03", "AD01"]
    with pytest.raises(TandaInvalida, match="AD99"):
        elegir(t.piezas, ids=["AD99"])


def test_texto_de_501_caracteres(vault_zz):
    _, filas = manifest_filas(vault_zz)
    filas[1]["texto"] = "x" * 501
    reescribir_manifest(vault_zz, filas)
    with pytest.raises(TandaInvalida, match="AD02: texto 501 > 500"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_url_sin_la_utm_literal(vault_zz):
    _, filas = manifest_filas(vault_zz)
    filas[0]["url"] = "https://prueba.example/?utm_source=facebook"
    reescribir_manifest(vault_zz, filas)
    with pytest.raises(TandaInvalida, match="plantilla UTM"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_url_de_otro_host(vault_zz):
    _, filas = manifest_filas(vault_zz)
    filas[0]["url"] = "https://otra.example/?" + PLANTILLA_UTM
    reescribir_manifest(vault_zz, filas)
    with pytest.raises(TandaInvalida, match="no a la landing"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_medio_sin_lectura_de_grupo(vault_zz):
    _, filas = manifest_filas(vault_zz)
    os.chmod(vault_zz / filas[0]["archivo"], 0o600)
    with pytest.raises(TandaInvalida, match="el ejecutor no puede leer"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_medio_enlace_simbolico(vault_zz, tmp_path):
    _, filas = manifest_filas(vault_zz)
    real = vault_zz / filas[0]["archivo"]
    copia = tmp_path / "fuera.jpg"
    copia.write_bytes(real.read_bytes())
    real.unlink()
    real.symlink_to(copia)
    with pytest.raises(TandaInvalida, match="enlace"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_video_sin_miniatura(vault_zz):
    _, filas = manifest_filas(vault_zz)
    video = next(f for f in filas if f["tipo"] == "video")
    video["miniatura"] = ""
    reescribir_manifest(vault_zz, filas)
    with pytest.raises(TandaInvalida, match="vídeo sin miniatura"):
        leer_tanda(vault_zz, P, PAIS, "t1")


def test_tanda_cambiada_no_aprobada(vault_zz):
    _, filas = manifest_filas(vault_zz)
    filas[0]["titulo"] = "Otro título"
    reescribir_manifest(vault_zz, filas)
    t = leer_tanda(vault_zz, P, PAIS, "t1")
    assert not t.aprobada and "cambió" in t.motivo


def test_url_tags_separados(vault_zz):
    t = leer_tanda(vault_zz, P, PAIS, "t1")
    assert t.piezas[0].url_tags == PLANTILLA_UTM and "?" not in t.piezas[0].url_base
    assert t.piezas[0].url_base == "https://prueba.example/"


def test_miniatura_de_la_tanda(vault_zz):
    t = leer_tanda(vault_zz, P, PAIS, "t1")
    for p in t.piezas:
        assert p.miniatura.startswith(f"productos/{P}/creativos/{PAIS}/t1/")
        if p.tipo == "imagen":
            assert p.miniatura == p.ruta
