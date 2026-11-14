from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fixtures.referencia.anuncios_ranking import HOY, A, B, C, F, anuncio
from trovefy.referencia.config import UmbralesReferencia
from trovefy.referencia.fuente import Listado
from trovefy.referencia.medios import MediosAnuncio
from trovefy.referencia.ranking import rankear
from trovefy.referencia.salida import (
    Analisis,
    FichaReferencia,
    Referencia,
    cargar_referencia,
    construir_referencia,
    escribir_referencia,
    referencia_lista,
)
from trovefy.referencia.watch import InformeWatch
from trovefy.vault.frontmatter import escribir as fm_escribir
from trovefy.vault.frontmatter import leer as fm_leer

GOLD = Path(__file__).resolve().parents[2] / "golden/referencia"
AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
U = UmbralesReferencia(
    min_dias=7, max_variantes=30, peso_variantes=2, en_test_min_variantes=3, top=10, retencion_dias=30
)
G = anuncio("G", date(2026, 11, 1), activo=False)  # inactivo sin fin: no medido


def _medios(**fmt):
    return {k: MediosAnuncio(k, v, (), ()) for k, v in fmt.items()}


def _listado(anuncios, medios):
    return Listado(anuncios, "publica", True, "https://x.test/", None, medios=medios)


def _informe(dur, texto="hola"):
    return InformeWatch(Decimal(dur) if dur else None, (), texto, "whisperx" if texto else None, None)


def _an(n):
    return Analisis(f"resumen {n}", f"sujeto {n}", f"dolor {n}", f"ángulo {n}", f"cta {n}", f"objeción {n}")


def _ref(analisis=None, anuncios=None, medios=None, informes=None):
    anuncios = anuncios or [A, B, C, F, G]
    medios = medios or _medios(A="video", B="imagen", C="video", F="video")
    informes = informes or {"A": _informe("32.4"), "F": _informe("14")}
    puestos = rankear(anuncios, HOY, U)
    return construir_referencia(
        "p-001", "o-001", "800000000001", "MX", HOY,
        _listado(anuncios, medios), puestos, informes=informes,
        analisis=analisis if analisis is not None else {"A": _an("a"), "B": _an("b")},
        medios_hasta=date(2026, 12, 13), top_n=10,
    )  # fmt: skip


def test_anuncios_md_golden(tmp_path):
    escribir_referencia(tmp_path, _ref(), AHORA)
    out = (tmp_path / "productos/p-001/referencia/anuncios.md").read_text()
    assert out == (GOLD / "anuncios.md").read_text()


def _ficha(lib, formato, dur=None, estado="ganador"):
    return FichaReferencia(
        None, lib, estado, 10, 1, False, 1, formato, Decimal(dur) if dur else None,
        False, f"https://www.facebook.com/ads/library/?id={lib}", None, None, [],
    )  # fmt: skip


def test_mezcla_golden(tmp_path):
    fichas = [
        _ficha("V1", "video", "32.4"),
        _ficha("V2", "video", "14"),
        _ficha("I1", "imagen"),
        _ficha("N1", None),
        _ficha("X1", "imagen", estado="en_test"),
    ]
    ref = Referencia("p-001", "o-001", "800000000001", "MX", HOY, "publica", None, True, fichas, [])
    escribir_referencia(tmp_path, ref, AHORA)
    out = (tmp_path / "productos/p-001/referencia/mezcla.md").read_text()
    assert "vídeo 67 %" in out and "imagen 33 %" in out and "1 no medido" in out
    assert out == (GOLD / "mezcla.md").read_text()


def test_mezcla_sin_duraciones(tmp_path):
    ref = Referencia("p-001", "o-001", "8", "MX", HOY, "publica", None, True, [_ficha("I1", "imagen")], [])
    escribir_referencia(tmp_path, ref, AHORA)
    assert "no medido:" in (tmp_path / "productos/p-001/referencia/mezcla.md").read_text()


def test_vault_sin_material_ajeno(tmp_path):
    ajeno = "Texto ajeno del anuncio ficticio"
    a = anuncio("Z", date(2026, 9, 1), collation_id="cz", count=3)
    object.__setattr__(a, "texto", ajeno)
    med = {"Z": MediosAnuncio("Z", "video", ("https://video.fbcdn.net/v.mp4?oe=1",), ("https://scontent.fbcdn.net/i.jpg?oe=2",))}
    puestos = rankear([a], HOY, U)
    ref = construir_referencia("p-001", "o-001", "8", "MX", HOY, _listado([a], med), puestos, top_n=10)
    escribir_referencia(tmp_path, ref, AHORA)
    for f in (tmp_path / "productos").rglob("*"):
        if f.is_file():
            t = f.read_text()
            assert ajeno not in t and "fbcdn" not in t and "oe=" not in t and ".mp4" not in t


def test_galeria_nunca_guarda_access_token(tmp_path):
    ref = _ref()
    ref.fichas[0].enlace = "https://www.facebook.com/ads/library/render_ad/?id=A&access_token=EAAB" + "x" * 30
    escribir_referencia(tmp_path, ref, AHORA)
    g = (tmp_path / "productos/p-001/referencia/galeria.html").read_text()
    assert "access_token" not in g and "render_ad" not in g and "ads/library/?id=A" in g


def test_galeria_escapa_html(tmp_path):
    an = _an("a")
    an.hook_sujeto = "<script>alert(1)</script>"
    ref = _ref(analisis={"A": an})
    escribir_referencia(tmp_path, ref, AHORA)
    g = (tmp_path / "productos/p-001/referencia/galeria.html").read_text()
    assert "&lt;script&gt;" in g and "<script" not in g and "<img" not in g
    assert "default-src 'none'; style-src 'unsafe-inline'" in g
    assert "medios locales hasta 2026-12-13" in g


def test_producto_md_conserva_todo(tmp_path):
    p = tmp_path / "productos/p-001/PRODUCTO.md"
    fm_escribir(p, {"id": "p-001", "paises": {"BG": {"estado": "aprobado"}}}, "# Producto\n\nCuerpo previo.\n")
    escribir_referencia(tmp_path, _ref(), AHORA)
    escribir_referencia(tmp_path, _ref(), AHORA)
    meta, cuerpo = fm_leer(p)
    assert meta["paises"]["BG"]["estado"] == "aprobado" and meta["id"] == "p-001"
    r = meta["referencia"]
    assert r["archivo"] == "referencia/anuncios.md" and r["ganadores"] == 3 and r["en_test"] == 1
    assert r["analizados"] == 2 and r["leidos"] == 5 and r["via"] == "publica"
    assert cuerpo.startswith("# Producto\n\nCuerpo previo.\n")
    assert cuerpo.count("- Referencia: [[productos/p-001/referencia/anuncios]]") == 1
    assert "referencia/anuncios.md" in (tmp_path / "log.md").read_text()


def test_ranking_json_ida_y_vuelta(tmp_path):
    ref = _ref()
    escribir_referencia(tmp_path, ref, AHORA)
    raw = json.loads((tmp_path / "productos/p-001/referencia/ranking.json").read_text())
    assert raw["version"] == 1 and raw["fichas"][0]["duracion_s"] == "32.4"
    assert cargar_referencia(tmp_path, "p-001") == ref


def test_secreto_bloquea_escritura(tmp_path):
    an = _an("a")
    an.angulo = "EAA" + "B" * 30
    with pytest.raises(ValueError):
        escribir_referencia(tmp_path, _ref(analisis={"A": an}), AHORA)
    assert not (tmp_path / "productos").exists() and not (tmp_path / "log.md").exists()


def test_referencia_lista(tmp_path):
    assert referencia_lista(tmp_path, "p-001") == (False, "falta referencia/")
    escribir_referencia(tmp_path, _ref(analisis={"A": _an("a")}), AHORA)
    assert referencia_lista(tmp_path, "p-001") == (False, "faltan 2 análisis: /trovefy:ver-anuncios")
    escribir_referencia(tmp_path, _ref(analisis={"A": _an("a"), "B": _an("b"), "F": _an("f")}), AHORA)
    assert referencia_lista(tmp_path, "p-001") == (True, "")
