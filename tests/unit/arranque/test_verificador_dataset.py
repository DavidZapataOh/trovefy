"""Verificador del paso 11 de /arranque (Dataset/píxel; plan 19, Tarea 16): lee `TRACKING.md` del vault, sin red,
sin navegador y sin ningún panel."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy.arranque.verificadores import REGISTRO
from trovefy.arranque.verificadores.dataset import verificar_dataset
from trovefy.tracking.modelo import Tracking, emisores_por_defecto
from trovefy.tracking.salida import escribir_tracking
from unit.embudo.ejemplos_embudo import PAIS, P, vault_embudo

AHORA = datetime(2026, 11, 18, 12, 0, 0, tzinfo=ZoneInfo("America/Bogota"))
DATASET = "1111111111111111"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def _tracking(v, estado: str, dataset_id: str | None = DATASET, ejecutor: dict | None = None, motivos=()):
    t = Tracking(producto=P, pais=PAIS, dataset_nombre="SOMATIX ZZ", dataset_id=dataset_id,
                 emisores=emisores_por_defecto("impultienda", "impultienda"), pixel_publico=None, pixel_config=None,
                 capi=None, eventos=None, fuente_eventos=None, estado=estado, motivos=list(motivos), ejecutor=ejecutor)
    escribir_tracking(v, t, AHORA)


def test_registrado():
    assert REGISTRO["11"] is verificar_dataset


def test_verificador_11_ok(tmp_path):
    v = vault_embudo(tmp_path)
    _tracking(v, "verificado", ejecutor={"dataset_permitido": True, "pagina_permitida": True, "lectura_ok": True,
                                         "fecha": "2026-11-17"})
    r = verificar_dataset(v)
    assert r.ok is True
    assert r.datos["dataset_id"] == DATASET and r.datos["producto"] == P and r.datos["pais"] == PAIS
    assert r.datos["estado"] == "verificado"
    assert any(e.startswith("config/evidencia/11-dataset-") for e in r.evidencia)
    assert (v / r.evidencia[-1]).is_file()


def test_verificador_11_configurado_vale_con_lo_no_medido_dicho(tmp_path):
    v = vault_embudo(tmp_path)
    _tracking(v, "configurado", motivos=["eventos: no medido: InitiateCheckout no llegó"])
    r = verificar_dataset(v)
    assert r.ok is True and r.datos["estado"] == "configurado"
    assert "no medido: InitiateCheckout no llegó" in r.motivo


def test_verificador_11_sin_tracking_no_medido(tmp_path):
    v = vault_embudo(tmp_path)
    r = verificar_dataset(v)
    assert r.ok is None and r.motivo.startswith("no medido")
    assert any("/trovefy:tracking" in a for a in r.arreglos)


def test_verificador_11_sin_dataset_falla(tmp_path):
    v = vault_embudo(tmp_path)
    _tracking(v, "pendiente", dataset_id=None)
    r = verificar_dataset(v)
    assert r.ok is False and "dataset" in r.motivo


def test_verificador_11_pixel_sin_poner_falla(tmp_path):
    v = vault_embudo(tmp_path)
    _tracking(v, "dataset")
    r = verificar_dataset(v)
    assert r.ok is False and "píxel" in r.motivo and r.datos["dataset_id"] == DATASET
