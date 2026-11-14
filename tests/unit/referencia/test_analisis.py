from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from trovefy.referencia import cache
from trovefy.referencia.analisis import (
    LIMITES,
    AnalisisInvalido,
    anotar,
    copia_literal,
    normalizar,
)
from trovefy.referencia.salida import FichaReferencia, Referencia, escribir_referencia
from trovefy.vault.frontmatter import escribir as fm_escribir

AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
P = "p-0001-demo"
TRANSCRIPCION = "hoy te enseño cómo calmar tu sistema nervioso en solo cinco minutos al día"
WATCH_MD = (
    "# watch: video report\n\n- **Transcript:** 2 segments (via whisperx)\n\n## Frames\n\n"
    "- `/w/frames/f_0001.jpg` (t=0:00, reason=scene)\n\n## Transcript\n\n_Source: whisperx._\n\n```\n"
    "[0:00] hoy te enseño cómo calmar tu sistema nervioso\n[0:04] en solo cinco minutos al día\n```\n\n---\n"
    "_Work dir: `/w` — delete when done._\n"
)
TEXTO = "Texto ajeno ficticio para el anuncio uno con palabras que nadie copiará jamás"
PROPIO = {
    "transcripcion_resumida": "Promete calma rápida con una rutina corta diaria",
    "hook_sujeto": "una persona estresada",
    "hook_dolor_o_resultado": "el cansancio de no desconectar",
    "angulo": "calma en cinco minutos",
    "cta": "descargar la guía",
    "objecion": "no medido: el anuncio no ataca ninguna objeción visible",
}


def _ficha(lib):
    return FichaReferencia(
        1, lib, "ganador", 10, 1, False, 1, "video", Decimal(30), True,
        f"https://www.facebook.com/ads/library/?id={lib}", None, None, [],
    )  # fmt: skip


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_CACHE_REFERENCIA", str(tmp_path / "cache"))
    v = tmp_path / "vault"
    fm_escribir(v / f"productos/{P}/PRODUCTO.md", {"id": P}, "# Producto\n")
    ref = Referencia(P, "o-001", "8", "MX", date(2026, 11, 13), "publica", None, True, [_ficha("111"), _ficha("222")], [])
    escribir_referencia(v, ref, AHORA)
    textos = {
        "111": {"texto": TEXTO, "titulo": "Título ajeno"},
        "222": {"texto": "otro texto", "titulo": None},
    }
    cache.guardar_textos(P, json.dumps(textos), AHORA, 30)
    c = cache.carpeta_anuncio(P, "111", AHORA, 30)
    (c / "watch.md").write_text(WATCH_MD, encoding="utf-8")
    return v


def _json(tmp_path, entradas):
    r = tmp_path / "analisis.json"
    r.write_text(json.dumps(entradas), encoding="utf-8")
    return r


def _e(lib="111", **cambios):
    return {"library_id": lib, **PROPIO, **cambios}


def test_normalizar_y_copia():
    assert normalizar("¡Cómo, CALMAR!") == ["como", "calmar"]
    assert copia_literal("a b c d e f g h", ["x a b c d e f g h y"])
    assert not copia_literal("a b c d e f g", ["a b c d e f g"])


def test_anotar_rechaza_copia_literal(vault, tmp_path):
    r = _json(tmp_path, [_e(transcripcion_resumida="calmar tu sistema nervioso en solo cinco minutos al día")])
    with pytest.raises(AnalisisInvalido) as ei:
        anotar(vault, P, r, AHORA)
    assert "111" in str(ei.value) and "transcripcion_resumida" in str(ei.value)


def test_anotar_acepta_texto_propio(vault, tmp_path):
    anotar(vault, P, _json(tmp_path, [_e()]), AHORA)
    out = (vault / f"productos/{P}/referencia/anuncios.md").read_text()
    assert "Promete calma rápida con una rutina corta diaria" in out
    assert "no medido: el anuncio no ataca" in out
    assert TRANSCRIPCION not in out and TEXTO not in out
    assert "anotar" in (vault / "log.md").read_text()


def test_anotar_rechaza_url(vault, tmp_path):
    for v in ("mira https://x.test", "en www.x.test"):
        with pytest.raises(AnalisisInvalido):
            anotar(vault, P, _json(tmp_path, [_e(cta=v)]), AHORA)


def test_anotar_rechaza_id_desconocido(vault, tmp_path):
    with pytest.raises(AnalisisInvalido, match="999"):
        anotar(vault, P, _json(tmp_path, [_e("999")]), AHORA)


def test_anotar_limites(vault, tmp_path):
    with pytest.raises(AnalisisInvalido, match="cta"):
        anotar(vault, P, _json(tmp_path, [_e(cta="x" * (LIMITES["cta"] + 1))]), AHORA)


def test_anotar_campos_y_tipos(vault, tmp_path):
    e = _e(angulo="dos\nlíneas")
    del e["cta"]
    with pytest.raises(AnalisisInvalido) as ei:
        anotar(vault, P, _json(tmp_path, [e]), AHORA)
    assert len(ei.value.problemas) == 2


def test_anotar_sin_textos_en_cache(vault, tmp_path):
    cache.textos_path(P).unlink()
    with pytest.raises(AnalisisInvalido, match="vuelve a ejecutar"):
        anotar(vault, P, _json(tmp_path, [_e()]), AHORA)


def test_anotar_acumula_problemas(vault, tmp_path):
    r = _json(tmp_path, [_e("111", cta="ver https://x.test"), _e("222", angulo="y" * 500)])
    with pytest.raises(AnalisisInvalido) as ei:
        anotar(vault, P, r, AHORA)
    assert len(ei.value.problemas) == 2


def test_anotar_no_medido_permitido(vault, tmp_path):
    assert anotar(vault, P, _json(tmp_path, [_e()]), AHORA) == ["111"]


def test_anotar_secreto(vault, tmp_path):
    with pytest.raises(AnalisisInvalido):
        anotar(vault, P, _json(tmp_path, [_e(cta="EAA" + "B" * 30)]), AHORA)


def test_anotar_json_grande_o_mal_formado(vault, tmp_path):
    r = tmp_path / "g.json"
    r.write_text("x" * (1024 * 1024 + 1))
    with pytest.raises(AnalisisInvalido):
        anotar(vault, P, r, AHORA)
    r.write_text('{"a": 1}')
    with pytest.raises(AnalisisInvalido):
        anotar(vault, P, r, AHORA)


def test_anotar_detecta_copia_entre_segmentos_reales(vault, tmp_path):
    r = _json(tmp_path, [_e(angulo="calmar tu sistema nervioso en solo cinco minutos al día")])
    with pytest.raises(AnalisisInvalido, match="copia literal"):
        anotar(vault, P, r, AHORA)


@pytest.mark.parametrize("invisible", ["\u00ad", "\u200b"])
def test_anotar_invisibles_no_burlan_la_guarda(vault, tmp_path, invisible):
    v = f"calmar tu sis{invisible}tema ner{invisible}vioso en solo cinco minutos al día"
    with pytest.raises(AnalisisInvalido, match="copia literal"):
        anotar(vault, P, _json(tmp_path, [_e(angulo=v)]), AHORA)


def test_anotar_rechaza_caracteres_de_control(vault, tmp_path):
    with pytest.raises(AnalisisInvalido, match="control"):
        anotar(vault, P, _json(tmp_path, [_e(cta="descargar\x07 la guía")]), AHORA)


def test_anotar_sin_texto_ajeno_del_anuncio_no_pasa(vault, tmp_path):
    cache.guardar_textos(P, json.dumps({"111": {"texto": TEXTO, "titulo": ""}, "222": {"texto": "", "titulo": None}}), AHORA, 30)
    assert anotar(vault, P, _json(tmp_path, [_e("222")]), AHORA) == ["222"]
    copia = " ".join(TEXTO.split()[:9])
    with pytest.raises(AnalisisInvalido, match="222.angulo: copia literal"):
        anotar(vault, P, _json(tmp_path, [_e("222", angulo=copia)]), AHORA)


def test_anotar_anuncio_ausente_de_textos_no_pasa(vault, tmp_path):
    cache.guardar_textos(P, json.dumps({"111": {"texto": TEXTO, "titulo": ""}}), AHORA, 30)
    with pytest.raises(AnalisisInvalido, match="222: no se puede comprobar que el texto sea propio"):
        anotar(vault, P, _json(tmp_path, [_e("222")]), AHORA)


def test_anotar_compara_con_todos_los_anuncios(vault, tmp_path):
    copia = " ".join(TEXTO.split()[:9])
    with pytest.raises(AnalisisInvalido, match="222.angulo: copia literal"):
        anotar(vault, P, _json(tmp_path, [_e("222", angulo=copia)]), AHORA)


def test_anotar_una_sola_linea_de_log(vault, tmp_path):
    antes = (vault / "log.md").read_text().count("ver-anuncios")
    anotar(vault, P, _json(tmp_path, [_e()]), AHORA)
    assert (vault / "log.md").read_text().count("ver-anuncios") == antes + 1


def test_anotar_borra_el_borrador_del_vault(vault):
    borrador = vault / "data/referencia" / f"analisis-{P}.json"
    borrador.parent.mkdir(parents=True)
    borrador.write_text(json.dumps([_e()]), encoding="utf-8")
    anotar(vault, P, borrador, AHORA)
    assert not borrador.exists()


def test_anotar_no_borra_fuera_de_data_referencia(vault, tmp_path):
    r = _json(tmp_path, [_e()])
    anotar(vault, P, r, AHORA)
    assert r.exists()


def test_anotar_rechazado_conserva_el_borrador(vault):
    borrador = vault / "data/referencia" / f"analisis-{P}.json"
    borrador.parent.mkdir(parents=True)
    borrador.write_text(json.dumps([_e(cta="mira https://x.test")]), encoding="utf-8")
    with pytest.raises(AnalisisInvalido):
        anotar(vault, P, borrador, AHORA)
    assert borrador.exists()
