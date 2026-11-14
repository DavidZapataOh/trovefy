"""Caché de medios ajenos fuera del vault, con caducidad."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from trovefy.referencia import cache

AHORA = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
P_ID = "p-0001-lampara"


@pytest.fixture
def base(tmp_path, monkeypatch):
    b = tmp_path / "cache"
    monkeypatch.setenv("TROVEFY_CACHE_REFERENCIA", str(b))
    return b


def test_base_desde_env(base):
    assert cache.base_cache() == base
    assert (base.stat().st_mode & 0o777) == 0o700


def test_base_por_defecto_en_home(tmp_path, monkeypatch):
    monkeypatch.delenv("TROVEFY_CACHE_REFERENCIA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache.base_cache() == tmp_path / ".cache/trovefy/referencia"


def test_carpeta_valida_ids(base):
    for p, lib in [
        ("../x", "123"),
        (P_ID, "../x"),
        (P_ID, "abc"),
        ("p-1-x", "1"),
        (P_ID, "1" * 26),
    ]:
        with pytest.raises(ValueError):
            cache.carpeta_anuncio(p, lib, AHORA, 30)
    carpeta = cache.carpeta_anuncio(P_ID, "123", AHORA, 30)
    assert carpeta == base / P_ID / "123"
    assert (carpeta.stat().st_mode & 0o777) == 0o700
    datos = json.loads((carpeta / "caduca.json").read_text())
    assert datos["producto"] == P_ID and datos["library_id"] == "123"
    assert datos["caduca"] == (AHORA + timedelta(days=30)).isoformat()


def test_caducidad_no_se_alarga(base):
    c = cache.carpeta_anuncio(P_ID, "123", AHORA, 30)
    antes = (c / "caduca.json").read_text()
    cache.carpeta_anuncio(P_ID, "123", AHORA + timedelta(days=10), 30)
    assert (c / "caduca.json").read_text() == antes


def test_limpiar_borra_solo_vencidos(base):
    viejo = cache.carpeta_anuncio(P_ID, "1", AHORA - timedelta(days=31), 30)
    nuevo = cache.carpeta_anuncio(P_ID, "2", AHORA - timedelta(days=29), 30)
    assert cache.vencidos(AHORA) == [viejo]
    assert cache.limpiar(AHORA) == [viejo]
    assert not viejo.exists() and nuevo.exists()


def test_limpiar_no_sigue_symlinks(base, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "caduca.json").write_text(
        json.dumps({"caduca": (AHORA - timedelta(days=1)).isoformat()})
    )
    (fuera / "dato.txt").write_text("x")
    (base / P_ID).mkdir(parents=True)
    enlace = base / P_ID / "9"
    os.symlink(fuera, enlace)
    assert cache.limpiar(AHORA) == []
    assert enlace.is_symlink()
    assert (fuera / "dato.txt").exists()


def test_sin_caduca_es_aviso(base):
    (base / P_ID / "5").mkdir(parents=True)
    (base / P_ID / "6").mkdir(parents=True)
    (base / P_ID / "6" / "caduca.json").write_text("{no json")
    assert cache.limpiar(AHORA) == []
    assert (base / P_ID / "5").exists() and (base / P_ID / "6").exists()
    avisos = cache.avisos_limpieza(AHORA)
    assert len(avisos) == 2
    assert any("5" in a for a in avisos) and any("6" in a for a in avisos)


def test_textos_path(base):
    assert cache.textos_path(P_ID) == base / P_ID / "textos.json"
    with pytest.raises(ValueError):
        cache.textos_path("../x")


def test_guardar_textos_renueva_caduca_al_reescribir(base):
    r = cache.guardar_textos(P_ID, '{"a": 1}', AHORA, 30)
    assert r == base / P_ID / "textos.json" and r.read_text() == '{"a": 1}'
    marca = base / P_ID / "caduca.json"
    assert json.loads(marca.read_text())["caduca"] == (AHORA + timedelta(days=30)).isoformat()
    cache.guardar_textos(P_ID, '{"a": 2}', AHORA + timedelta(days=10), 30)
    assert json.loads(marca.read_text())["caduca"] == (AHORA + timedelta(days=40)).isoformat()
    assert r.read_text() == '{"a": 2}'
    assert not [p for p in (base / P_ID).iterdir() if p.name.endswith(".tmp")]


def test_caduca_se_escribe_atomico(base, monkeypatch):
    usados = []
    real = os.replace
    monkeypatch.setattr(
        os, "replace", lambda a, b: (usados.append(Path(b).name), real(a, b))
    )
    cache.carpeta_anuncio(P_ID, "1", AHORA, 30)
    cache.guardar_textos(P_ID, "{}", AHORA, 30)
    assert usados.count("caduca.json") == 2


def test_limpiar_borra_textos_vencidos(base):
    r = cache.guardar_textos(P_ID, "{}", AHORA - timedelta(days=31), 30)
    assert cache.limpiar(AHORA) == [r]
    assert not r.exists() and not (r.parent / "caduca.json").exists()


def test_limpiar_conserva_textos_vigentes_o_sin_marca(base):
    r = cache.guardar_textos(P_ID, "{}", AHORA - timedelta(days=5), 30)
    otro = base / "p-0002-otro"
    otro.mkdir()
    (otro / "textos.json").write_text("{}")
    assert cache.limpiar(AHORA) == []
    assert r.exists() and (otro / "textos.json").exists()


def test_limpiar_no_borra_textos_symlink(base, tmp_path):
    fuera = tmp_path / "fuera.json"
    fuera.write_text("x")
    d = base / P_ID
    d.mkdir(parents=True)
    os.symlink(fuera, d / "textos.json")
    (d / "caduca.json").write_text(
        json.dumps({"caduca": (AHORA - timedelta(days=1)).isoformat()})
    )
    assert cache.limpiar(AHORA) == []
    assert fuera.exists() and (d / "textos.json").is_symlink()


def _lote(carpeta, nombre, dias):
    carpeta.mkdir(parents=True, exist_ok=True)
    lote = carpeta / nombre
    lote.write_text("{}")
    t = (AHORA - timedelta(days=dias)).timestamp()
    os.utime(lote, (t, t))
    return lote


def test_lotes_mcp_caducan_por_antiguedad(base):
    mcp = base / P_ID / "mcp"
    viejo = _lote(mcp, "lote-a.json", 400)
    nuevo = _lote(mcp, "lote-b.json", 1)
    assert cache.vencidos(AHORA) == [viejo]
    assert cache.avisos_limpieza(AHORA) == []
    assert cache.limpiar(AHORA, 30) == [viejo]
    assert not viejo.exists() and nuevo.exists()


def test_retencion_de_lotes_configurable(base):
    lote = _lote(base / P_ID / "mcp", "lote-a.json", 10)
    assert cache.vencidos(AHORA, retencion_dias=30) == []
    assert cache.vencidos(AHORA, retencion_dias=5) == [lote]


def test_carpeta_mcp_vacia_se_borra(base):
    mcp = base / P_ID / "mcp"
    _lote(mcp, "lote-a.json", 400)
    cache.limpiar(AHORA, 30)
    assert not mcp.exists()


def test_lotes_mcp_no_siguen_symlinks(base, tmp_path):
    fuera = tmp_path / "fuera"
    viejo = _lote(fuera, "lote-x.json", 400)
    (base / P_ID).mkdir(parents=True)
    os.symlink(fuera, base / P_ID / "mcp")
    otro = base / "p-0002-otro" / "mcp"
    otro.mkdir(parents=True)
    os.symlink(viejo, otro / "lote-y.json")
    assert cache.vencidos(AHORA) == []
    assert cache.limpiar(AHORA, 30) == []
    assert viejo.exists() and (otro / "lote-y.json").is_symlink()
    assert cache.avisos_limpieza(AHORA) == []


def test_caduca_de_anuncio(base):
    cache.carpeta_anuncio(P_ID, "7", AHORA - timedelta(days=20), 30)
    assert cache.caduca_anuncio(P_ID, "7") == (AHORA + timedelta(days=10)).date()
    assert cache.caduca_anuncio(P_ID, "8") is None
