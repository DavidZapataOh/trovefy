"""Paso guiado del dataset y la página en los límites del ejecutor, del lado de Claude (plan 19, Tarea 9).

Claude nunca edita ``limites.yaml``: imprime los comandos que ejecuta el usuario y lee ``estado/dataset.json``.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from embudo.ejemplos_embudo import PAIS, P, arranque, vault_embudo
from trovefy.aprobaciones.fuentes import ESTADOS, Lectura, leer_estado
from trovefy.tracking import ejecutor
from trovefy.tracking.ejecutor import (
    comandos_para_usuario,
    evaluar_dataset_json,
    pagina_de_arranque,
)
from trovefy.tracking.modelo import Tracking
from trovefy.tracking.salida import escribir_tracking, leer_tracking

DATASET = "1111111111111111"
PAGINA = "2222222222222222"
AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
BIN = "sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor"


def _dataset_json(**kw) -> dict:
    return {"fecha": AHORA.isoformat(), "dataset_id": DATASET, "pagina_id": PAGINA, "nombre": "PRUEBA ZZ",
            "lectura_ok": True, "motivo": None, "en_limites": True, "pagina_en_limites": True, **kw}


def test_comandos_exactos():
    assert comandos_para_usuario(DATASET, PAGINA) == [
        f"{BIN} permitir --dataset {DATASET}",
        f"{BIN} permitir --pagina {PAGINA}",
        f"{BIN} comprobar-dataset {DATASET} --pagina {PAGINA}",
    ]


@pytest.mark.parametrize("malo", ["12ab", "1; rm -rf ~", "", "act_1"])
def test_comandos_ids_invalidos(malo):
    with pytest.raises(ValueError):
        comandos_para_usuario(malo, PAGINA)
    with pytest.raises(ValueError):
        comandos_para_usuario(DATASET, malo)


def test_estados_incluye_dataset():
    assert "dataset" in ESTADOS


def test_dataset_json_ausente_no_medido():
    ok, texto = evaluar_dataset_json(Lectura(None, "no medido: el ejecutor no ha escrito dataset.json"), DATASET,
                                     ahora=AHORA)
    assert ok is None and texto.startswith("no medido")


def test_dataset_json_viejo_no_medido():
    viejo = _dataset_json(fecha=(AHORA - timedelta(hours=25)).isoformat())
    ok, texto = evaluar_dataset_json(Lectura(viejo, None), DATASET, ahora=AHORA)
    assert ok is None and texto.startswith("no medido") and "24 h" in texto


def test_dataset_json_de_otro_dataset():
    ok, texto = evaluar_dataset_json(Lectura(_dataset_json(dataset_id="3333333333333333"), None), DATASET,
                                     ahora=AHORA)
    assert ok is None and "otro dataset" in texto


def test_dataset_json_sin_lectura():
    ok, texto = evaluar_dataset_json(Lectura(_dataset_json(lectura_ok=False), None), DATASET, ahora=AHORA)
    assert ok is False
    assert "Asignar usuarios › trovefy-ejecutor" in texto


def test_dataset_json_fuera_de_limites():
    ok, texto = evaluar_dataset_json(Lectura(_dataset_json(en_limites=False), None), DATASET, ahora=AHORA,
                                     pagina_id=PAGINA)
    assert ok is False and "falta añadirlo a los límites" in texto
    assert f"permitir --dataset {DATASET}" in texto


def test_dataset_json_bien():
    ok, _ = evaluar_dataset_json(Lectura(_dataset_json(), None), DATASET, ahora=AHORA, pagina_id=PAGINA)
    assert ok is True


def test_dataset_json_de_otra_pagina_no_medido():
    """L1: pagina_en_limites vale solo para la página que se comprobó."""
    for d in (_dataset_json(pagina_id="3333333333333333"), {k: v for k, v in _dataset_json().items()
                                                            if k != "pagina_id"}):
        ok, texto = evaluar_dataset_json(Lectura(d, None), DATASET, ahora=AHORA, pagina_id=PAGINA)
        assert ok is None and "otra página" in texto


def _vault_con_tracking(tmp_path: Path, monkeypatch) -> Path:
    v = vault_embudo(tmp_path)
    datos = arranque({"05": "verificado", "09": "verificado", "10": "hecho"})
    datos["pasos"][0]["datos"] = {"page_id": PAGINA}
    (v / "config" / "arranque.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")
    escribir_tracking(v, Tracking(
        producto=P, pais=PAIS, dataset_nombre="SOMATIX ZZ", dataset_id=DATASET,
        emisores={e: "impultienda" for e in ("PageView", "ViewContent", "InitiateCheckout", "Purchase")},
        pixel_publico=None, pixel_config=None, capi=None, eventos=None, fuente_eventos=None, estado="dataset"),
        AHORA)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    return v


def test_pagina_de_arranque(tmp_path, monkeypatch):
    v = _vault_con_tracking(tmp_path, monkeypatch)
    assert pagina_de_arranque(v) == PAGINA
    (v / "config" / "arranque.yaml").write_text(yaml.safe_dump(arranque({"09": "hecho"})), encoding="utf-8")
    assert pagina_de_arranque(v) is None


def test_tracking_ejecutor_sin_estado_solo_guia(tmp_path, monkeypatch, capsys):
    v = _vault_con_tracking(tmp_path, monkeypatch)
    assert ejecutor.ejecutar(argparse.Namespace(producto=P, pais=PAIS)) == 0
    out = capsys.readouterr().out
    assert "Asignar usuarios" in out and "trovefy-ejecutor" in out
    for c in comandos_para_usuario(DATASET, PAGINA):
        assert c in out
    assert "no medido" in out
    assert leer_tracking(v, P, PAIS).ejecutor is None


def test_tracking_ejecutor_anota(tmp_path, monkeypatch, capsys):
    v = _vault_con_tracking(tmp_path, monkeypatch)
    estado = tmp_path / "spool" / "estado"
    estado.mkdir(parents=True)
    ahora = datetime.now(UTC)
    (estado / "dataset.json").write_text(json.dumps(_dataset_json(fecha=ahora.isoformat())), encoding="utf-8")
    assert leer_estado("dataset").datos["dataset_id"] == DATASET
    assert ejecutor.ejecutar(argparse.Namespace(producto=P, pais=PAIS)) == 0
    t = leer_tracking(v, P, PAIS)
    assert t.ejecutor == {"dataset_permitido": True, "pagina_permitida": True, "lectura_ok": True,
                          "fecha": ahora.isoformat()}
    assert t.estado == "dataset"  # el resto del tracking no cambia
    assert "listo" in capsys.readouterr().out.lower()


def test_tracking_ejecutor_sin_dataset(tmp_path, monkeypatch, capsys):
    v = vault_embudo(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    assert ejecutor.ejecutar(argparse.Namespace(producto=P, pais=PAIS)) == 2
    assert "dataset" in capsys.readouterr().err
