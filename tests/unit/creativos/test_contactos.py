"""Hoja de contactos para el revisor y textos para el nativo (plan 21, Tarea 10)."""

from pathlib import Path

import pytest
from PIL import Image
from trovefy.creativos import contactos, registro

from .ejemplos import AHORA, crear_vault, tanda_buena

AGENTES = Path(__file__).resolve().parents[3] / "agents"


def _extraer(video, segundos, destino, prefijo):
    destino.mkdir(parents=True, exist_ok=True)
    salida = []
    for i, _ in enumerate(segundos, 1):
        r = destino / f"{prefijo}-{i}.jpg"
        Image.new("RGB", (1080, 1920), (30 * i, 60, 90)).save(r)
        salida.append(r)
    return salida


def _piezas(ficha):
    return [(e.ad, ficha.brief(e.ad).tipo) for e in ficha.elegidos]


@pytest.fixture
def tanda(tmp_path):
    vault = crear_vault(tmp_path)
    return (vault, *tanda_buena(vault))


def _hoja(vault, carpeta, ficha, extraidos=None):
    def extraer(video, segs, destino, prefijo):
        if extraidos is not None:
            extraidos.append(len(segs))
        return _extraer(video, segs, destino, prefijo)
    return contactos.hoja_contactos(vault, carpeta, ficha, duracion=lambda _r: 26.0, extraer=extraer)


def test_hoja_tiene_10_celdas_y_4_fotogramas_por_video(tanda):
    vault, _ctx, _cfg, ficha, carpeta = tanda
    extraidos = []
    hoja = _hoja(vault, carpeta, ficha, extraidos)
    assert hoja.name == "contactos-t1-v1.png" and oct(hoja.stat().st_mode)[-3:] == "640"
    assert extraidos == [4] * 7  # 7 vídeos con 4 fotogramas cada uno; los 3 estáticos, una celda
    with Image.open(hoja) as img:
        assert img.height > 10 * contactos.CELDA_VID[1] / 2


def test_hoja_no_pisa(tanda):
    vault, _ctx, _cfg, ficha, carpeta = tanda
    assert _hoja(vault, carpeta, ficha).name == "contactos-t1-v1.png"
    assert _hoja(vault, carpeta, ficha).name == "contactos-t1-v2.png"


def test_textos_html_ids_ad(tanda):
    vault, ctx, cfg, ficha, carpeta = tanda
    ruta = contactos.textos_html(vault, ctx, carpeta, ficha, cfg)
    texto = ruta.read_text(encoding="utf-8")
    assert all(f'<section id="ad-{n:02d}">' in texto for n in range(1, 11))
    assert 'class="voz"' in texto and "тринадесет евро" in texto.lower()


def test_textos_con_secreto_no_se_escriben(tanda, monkeypatch):
    vault, ctx, cfg, ficha, carpeta = tanda
    monkeypatch.setattr(contactos, "buscar_secreto", lambda _t: "clave")
    with pytest.raises(ValueError, match="secreto"):
        contactos.textos_html(vault, ctx, carpeta, ficha, cfg)
    assert not list((carpeta / "qc").glob("textos-*.html"))


def test_veredicto_contradictorio_no_vale(tanda):
    _vault, _ctx, _cfg, ficha, carpeta = tanda
    with pytest.raises(ValueError, match="no vale como veredicto"):
        contactos.anotar_agente(carpeta, _piezas(ficha), "revisor", "- AD03 · contraste · x\nVEREDICTO: ok",
                                "contactos-t1-v1.png", AHORA)
    assert registro.estado(carpeta, _piezas(ficha)).revisor is None


def test_anotar_guarda_version(tanda):
    _vault, _ctx, _cfg, ficha, carpeta = tanda
    v = contactos.anotar_agente(carpeta, _piezas(ficha), "revisor", "~ AD02 · imagen · más grande\nVEREDICTO: ok",
                                "qc/contactos-t1-v1.png", AHORA)
    assert v == "ok"
    e = registro.estado(carpeta, _piezas(ficha))
    assert e.revisor == "ok" and e.hoja == "qc/contactos-t1-v1.png"


def test_agentes_mencionan_tanda():
    revisor = (AGENTES / "revisor.md").read_text(encoding="utf-8")
    nativo = (AGENTES / "nativo.md").read_text(encoding="utf-8")
    assert "## Tanda de creativos" in revisor and "zona segura" in revisor and "ADnn" in revisor
    assert "## Tanda de creativos" in nativo and "ad-NN" in nativo and "en palabras" in nativo
