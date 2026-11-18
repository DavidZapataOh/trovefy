"""Evidencias que pega el usuario (plan 19, Tarea 6): capturas, textos y sus palabras literales."""

import os
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy.embudo.contexto import cargar_contexto
from trovefy.embudo.pegado import CLAVES, dicho, guardar_pegado, indice, ruta_local

from embudo.ejemplos_embudo import PAIS, P, vault_embudo

AHORA = datetime(2026, 11, 17, 10, 30, 5, tzinfo=ZoneInfo("Europe/Madrid"))
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TOKEN_FALSO = "EAA" + "Bq7" * 10


@pytest.fixture
def ctx(tmp_path):
    return cargar_contexto(vault_embudo(tmp_path), P, PAIS)


def _origen(tmp_path: Path, nombre: str, datos: bytes) -> Path:
    ruta = tmp_path / "pegar" / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return ruta


def _evidencia(ctx) -> Path:
    return ctx.vault / "productos" / P / "checkout" / PAIS / "evidencia"


def test_claves():
    assert "test-events" in CLAVES and "reembolso" in CLAVES and "tracking-pixel" in CLAVES


def test_captura_png_se_copia_0600(tmp_path, ctx):
    p = guardar_pegado(ctx.vault, ctx, "producto", _origen(tmp_path, "c.png", PNG), None, AHORA)
    destino = ctx.vault / "productos" / P / p.ruta
    assert p.ruta == f"checkout/{PAIS}/evidencia/producto-2026-11-17T103005.png"
    assert destino.read_bytes() == PNG
    assert stat.S_IMODE(os.stat(destino).st_mode) == 0o600
    assert p.tipo == "captura" and len(p.sha256) == 64
    assert indice(ctx.vault, ctx)["producto"] == [p]


def test_jpeg_y_webp_por_los_primeros_bytes(tmp_path, ctx):
    jpg = guardar_pegado(ctx.vault, ctx, "checkout", _origen(tmp_path, "a.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20),
                         None, AHORA)
    assert jpg.ruta.endswith(".jpg")
    webp = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"0" * 20
    w = guardar_pegado(ctx.vault, ctx, "market", _origen(tmp_path, "b.webp", webp), None, AHORA)
    assert w.ruta.endswith(".webp")


def test_no_imagen_rechazada(tmp_path, ctx):
    with pytest.raises(ValueError, match="imagen"):
        guardar_pegado(ctx.vault, ctx, "producto", _origen(tmp_path, "c.png", b"hola, no soy un PNG"), None, AHORA)
    assert not _evidencia(ctx).exists()


def test_imagen_demasiado_grande(tmp_path, ctx):
    grande = PNG + b"\x00" * (10 * 1024 * 1024)
    with pytest.raises(ValueError, match="10 MB"):
        guardar_pegado(ctx.vault, ctx, "producto", _origen(tmp_path, "c.png", grande), None, AHORA)


def test_extension_no_admitida(tmp_path, ctx):
    with pytest.raises(ValueError, match="extensión"):
        guardar_pegado(ctx.vault, ctx, "producto", _origen(tmp_path, "c.pdf", b"%PDF-1.7"), None, AHORA)


def test_texto_con_token_no_se_guarda(tmp_path, ctx):
    origen = _origen(tmp_path, "email.txt", f"Hola, tu token es {TOKEN_FALSO}\n".encode())
    with pytest.raises(ValueError, match=r"parece llevar un secreto \(token de Meta\): no lo guardo"):
        guardar_pegado(ctx.vault, ctx, "email-entrega", origen, None, AHORA)
    assert not _evidencia(ctx).exists()


def test_texto_eml_se_guarda(tmp_path, ctx):
    origen = _origen(tmp_path, "entrega.eml", "Subject: Tu PDF\n\nDescárgalo aquí.\n".encode())
    p = guardar_pegado(ctx.vault, ctx, "email-entrega", origen, None, AHORA)
    assert p.tipo == "texto" and p.ruta.endswith(".eml")


def test_valores_con_secreto_no_se_guardan(tmp_path, ctx):
    with pytest.raises(ValueError, match="secreto"):
        guardar_pegado(ctx.vault, ctx, "producto", _origen(tmp_path, "c.png", PNG), {"nota": TOKEN_FALSO}, AHORA)


def test_enlace_rechazado(tmp_path, ctx):
    real = _origen(tmp_path, "real.png", PNG)
    enlace = tmp_path / "pegar" / "enlace.png"
    enlace.symlink_to(real)
    with pytest.raises(ValueError, match="enlace"):
        guardar_pegado(ctx.vault, ctx, "producto", enlace, None, AHORA)
    carpeta = tmp_path / "pegar" / "carpeta.png"
    carpeta.mkdir()
    with pytest.raises(ValueError, match="archivo"):
        guardar_pegado(ctx.vault, ctx, "producto", carpeta, None, AHORA)
    with pytest.raises(ValueError, match="no existe"):
        guardar_pegado(ctx.vault, ctx, "producto", tmp_path / "nada.png", None, AHORA)


def test_clave_desconocida(tmp_path, ctx):
    with pytest.raises(ValueError, match="clave"):
        guardar_pegado(ctx.vault, ctx, "token-capi", _origen(tmp_path, "c.png", PNG), None, AHORA)
    with pytest.raises(ValueError, match="clave"):
        dicho(ctx.vault, ctx, "nada", "ya está", AHORA)


def test_no_pisa(tmp_path, ctx):
    origen = _origen(tmp_path, "c.png", PNG)
    guardar_pegado(ctx.vault, ctx, "producto", origen, None, AHORA)
    with pytest.raises(ValueError, match="ya existe"):
        guardar_pegado(ctx.vault, ctx, "producto", origen, None, AHORA)
    assert len(indice(ctx.vault, ctx)["producto"]) == 1


def test_ruta_windows(monkeypatch):
    assert ruta_local(r"C:\Users\ana\Desktop\captura.png") == Path("/mnt/c/Users/ana/Desktop/captura.png")
    assert ruta_local(r"\\wsl.localhost\Ubuntu\home\ana\c.png") == Path("/home/ana/c.png")
    assert ruta_local(r"\\wsl$\Ubuntu\tmp\c.png") == Path("/tmp/c.png")
    assert ruta_local("/home/ana/c.png") == Path("/home/ana/c.png")


def test_ruta_windows_se_usa_al_guardar(tmp_path, ctx, monkeypatch):
    origen = _origen(tmp_path, "c.png", PNG)
    ventanas = "\\\\wsl.localhost\\Ubuntu" + str(origen).replace("/", "\\")
    p = guardar_pegado(ctx.vault, ctx, "producto", ventanas, None, AHORA)
    assert p.tipo == "captura"


def test_dicho_literal(ctx):
    cita = "Ya pegué el token en Meta / Tracking y le di a Guardar «sin problema»."
    p = dicho(ctx.vault, ctx, "tracking-pixel", cita, AHORA)
    texto = (ctx.vault / "productos" / P / p.ruta).read_text(encoding="utf-8")
    assert cita in texto
    assert p.tipo == "dicho" and p.ruta.endswith(".md")
    assert stat.S_IMODE(os.stat(ctx.vault / "productos" / P / p.ruta).st_mode) == 0o600
    with pytest.raises(ValueError, match="secreto"):
        dicho(ctx.vault, ctx, "tracking-pixel", f"el token es {TOKEN_FALSO}", AHORA)
    with pytest.raises(ValueError, match="vací"):
        dicho(ctx.vault, ctx, "tracking-pixel", "   ", AHORA)


def test_valores_se_guardan(tmp_path, ctx):
    p = guardar_pegado(ctx.vault, ctx, "ver-como", _origen(tmp_path, "c.png", PNG),
                       {"precio": "13,90 €", "pais": "ZZ"}, AHORA)
    assert p.valores == {"precio": "13,90 €", "pais": "ZZ"}
    assert indice(ctx.vault, ctx)["ver-como"][0].valores == {"precio": "13,90 €", "pais": "ZZ"}
    assert "ver-como" in (ctx.vault / "log.md").read_text(encoding="utf-8")


def test_indice_vacio(ctx):
    assert indice(ctx.vault, ctx) == {}
