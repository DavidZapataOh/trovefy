import hashlib
import json
from datetime import UTC, datetime

import pytest
from trovefy.arranque.ensayo import (
    CARPETA_MONTAJE,
    DATASET_DE_RELLENO,
    preparar_montaje,
)
from trovefy.arranque.estado import marcar_hecho
from trovefy.cli import main
from trovefy.vault.andamio import crear_vault
from trovefy_ejecutor.esquema import cargar_propuesta

AHORA = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    crear_vault(v)
    return v


def pasos(vault, moneda="COP"):
    marcar_hecho(vault, "05", datos={"page_id": "123456"})
    marcar_hecho(vault, "06", datos={"act_id": "0000000000000000", "moneda": moneda, "zona": "America/Bogota"})


def test_montaje_minimo_valido_con_imagen_y_su_sha(vault):
    pasos(vault)
    ruta = preparar_montaje(vault, AHORA)
    assert ruta.parent == vault / CARPETA_MONTAJE
    d = json.loads(ruta.read_text())
    assert d["tipo"] == "crear_estructura_pausada" and d["solo_validar"] is True
    assert d["cuenta"] == "act_0000000000000000" and d["pagina_id"] == "123456" and d["moneda"] == "COP"
    assert "id" not in d and "creada" not in d  # los pone `trovefy buzon depositar`
    (medio,) = d["medios"]
    img = vault / medio["ruta"]
    assert img.parent == vault / CARPETA_MONTAJE and img.suffix == ".png"
    assert hashlib.sha256(img.read_bytes()).hexdigest() == medio["sha256"]
    assert img.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    p = cargar_propuesta({**d, "id": "P-20261113-001", "creada": AHORA.isoformat()})
    assert p.estructura.solo_validar is True


def test_dataset_de_config_o_relleno_marcado(vault):
    pasos(vault)
    d = json.loads(preparar_montaje(vault, AHORA).read_text())
    assert d["dataset_id"] == DATASET_DE_RELLENO and d["dataset_id"].isdigit()
    assert "solo_validar no lo usa" in d["origen"]
    marcar_hecho(vault, "11", datos={"dataset_id": "987654"})
    d = json.loads(preparar_montaje(vault, AHORA).read_text())
    assert d["dataset_id"] == "987654" and "relleno" not in d["origen"]


def test_usd_importes_en_centavos(vault):
    pasos(vault, "USD")
    d = json.loads(preparar_montaje(vault, AHORA).read_text())
    assert d["moneda"] == "USD" and d["campana"]["spend_cap"] == 500


@pytest.mark.parametrize("falta", ["05", "06"])
def test_sin_pagina_o_cuenta_falla_sin_escribir(vault, falta):
    if falta != "05":
        marcar_hecho(vault, "05", datos={"page_id": "123456"})
    if falta != "06":
        marcar_hecho(vault, "06", datos={"act_id": "0000000000000000", "moneda": "COP"})
    with pytest.raises(ValueError, match=f"paso {falta}"):
        preparar_montaje(vault, AHORA)
    assert not (vault / CARPETA_MONTAJE).exists()


def test_cli_imprime_la_ruta(vault, capsys):
    pasos(vault)
    assert main(["arranque", "ensayo", "montaje", "--vault", str(vault)]) == 0
    out = capsys.readouterr().out
    ruta = next(x for x in out.split() if x.endswith(".json"))
    assert (vault / CARPETA_MONTAJE).as_posix() in ruta
    assert "trovefy buzon depositar" in out
    assert "0000000000000000" not in out  # la cuenta sale enmascarada o no sale
