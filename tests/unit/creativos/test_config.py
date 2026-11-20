"""config/creativos.yaml y su lector (plan 21, Tarea 1)."""

from decimal import Decimal

import pytest
from trovefy.creativos.config import (
    PLANTILLA,
    ConfigInvalida,
    cargar_config,
    cargar_plantilla,
    cargar_texto,
    iniciar_config,
)

TEXTO = PLANTILLA.read_text(encoding="utf-8")


def test_plantilla_carga():
    cfg = cargar_plantilla()
    assert cfg.piezas == 10 and cfg.al_test == 5 and cfg.reserva == 5 and cfg.briefs_candidatos == 20
    assert cfg.cta_por_defecto == "LEARN_MORE"
    assert cfg.whisper_similitud_min == Decimal("0.925")
    assert cfg.duracion_s == (20, 30) and cfg.corte_broll_s == Decimal("1.5")
    assert len(cfg.hooks) == 7


def test_importe_float_rechazado():
    with pytest.raises(ConfigInvalida, match="importe sin comillas"):
        cargar_texto(TEXTO.replace('tope_tanda_usd: {valor: "6.00"', "tope_tanda_usd: {valor: 6.0"))


def test_falta_fuente_rechazada():
    roto = TEXTO.replace('piezas: {valor: 10, fuente: "L1 0:43:47: 10 anuncios por país", ', "piezas: {valor: 10, ")
    with pytest.raises(ConfigInvalida, match="fuente"):
        cargar_texto(roto)


def test_al_test_mas_reserva_igual_a_piezas():
    with pytest.raises(ConfigInvalida, match="al_test"):
        cargar_texto(TEXTO.replace("al_test: {valor: 5", "al_test: {valor: 4"))


def test_iniciar_no_pisa(tmp_path):
    ruta = iniciar_config(tmp_path)
    assert cargar_config(tmp_path).piezas == 10
    ruta.write_text("tocado", encoding="utf-8")
    with pytest.raises(FileExistsError):
        iniciar_config(tmp_path)
    assert ruta.read_text(encoding="utf-8") == "tocado"


def test_modelos_tts_vacio_es_no_medido():
    cfg = cargar_plantilla()
    assert cfg.precio_tts_usd_1000 is None  # no medido: no se envía nada hasta medirlo
    assert cfg.precio_video_usd_segundo is None and cfg.precio_musica_usd_pista is None
    assert cfg.modelo_video is None


def test_sin_mezcla_7_videos_3_imagenes():
    cfg = cargar_plantilla()
    assert cfg.mezcla(None) == (3, 7)
    assert cfg.mezcla(85) == (8, 2)  # L1 46:54
    assert cfg.mezcla(100) == (9, 1)  # al menos un vídeo


def test_cuatro_plantillas_con_coste():
    cfg = cargar_plantilla()
    assert {n: p.coste_tanda_usd for n, p in cfg.plantillas.items()} == {
        "broll_voz": Decimal("1.00"), "ugc": Decimal("1.30"), "claymation": Decimal("1.10"), "3d": Decimal("1.10")}
    assert "L2 16:01" in TEXTO


def test_topes_6_y_2_con_fuente():
    cfg = cargar_plantilla()
    assert cfg.tope_tanda_usd == Decimal("6.00") and cfg.tope_renovacion_usd == Decimal("2.00")
    assert "L1 56:40" in TEXTO.split("tope_tanda_usd")[1].split("\n")[0]
