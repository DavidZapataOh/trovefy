"""`checkout/<PAIS>/TRACKING.md` y el bloque `paises.<PAIS>.tracking` de PRODUCTO.md (plan 19, Tarea 5;
resolución 3: lo lee el plan 20)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from embudo.ejemplos_embudo import PAIS, P, vault_embudo
from trovefy.tracking.modelo import Tracking
from trovefy.tracking.salida import escribir_tracking, leer_tracking
from trovefy.vault import frontmatter

AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))


def _t(**kw) -> Tracking:
    base = {"producto": P, "pais": PAIS, "dataset_nombre": "SOMATIX ZZ", "dataset_id": "1111111111111111",
            "emisores": {"PageView": "impultienda", "ViewContent": "impultienda",
                         "InitiateCheckout": "impultienda", "Purchase": "impultienda"},
            "pixel_publico": None, "pixel_config": None, "capi": None, "eventos": None, "fuente_eventos": None,
            "estado": "dataset", "evidencia": ["checkout/ZZ/evidencia/dataset.json"], "motivos": []}
    return Tracking(**{**base, **kw})


def _producto(v):
    meta, cuerpo = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    return meta, cuerpo


def test_leer_sin_tracking(tmp_path):
    assert leer_tracking(vault_embudo(tmp_path), P, PAIS) is None


def test_tracking_ida_y_vuelta(tmp_path):
    v = vault_embudo(tmp_path)
    t = _t(pixel_publico="ok", pixel_config="captura", capi="dicho",
           eventos={"PageView": 3, "ViewContent": 2, "InitiateCheckout": 1, "Purchase": None},
           fuente_eventos="mcp", motivos=["no medido: Purchase no llegó"])
    ruta = escribir_tracking(v, t, AHORA)
    assert ruta == v / "productos" / P / "checkout" / PAIS / "TRACKING.md"
    assert leer_tracking(v, P, PAIS) == t
    assert "tracking" in (v / "log.md").read_text(encoding="utf-8")


def test_tracking_conserva_producto(tmp_path):
    v = vault_embudo(tmp_path)
    meta_antes, cuerpo_antes = _producto(v)
    escribir_tracking(v, _t(), AHORA)
    meta, cuerpo = _producto(v)
    assert meta["entregable"] == meta_antes["entregable"]
    assert meta["paises"][PAIS]["estado"] == "con_landing"
    assert cuerpo.startswith(cuerpo_antes.rstrip("\n"))
    # Reescribir no duplica el enlace.
    escribir_tracking(v, _t(estado="configurado"), AHORA)
    assert _producto(v)[1].count("TRACKING") == 1


def test_producto_lleva_emisor_purchase_y_nombre(tmp_path):
    v = vault_embudo(tmp_path)
    escribir_tracking(v, _t(), AHORA)
    assert _producto(v)[0]["paises"][PAIS]["tracking"] == {
        "dataset_id": "1111111111111111", "dataset_nombre": "SOMATIX ZZ",
        "emisor_purchase": "impultienda", "estado": "dataset"}


def test_tracking_con_secreto_no_se_escribe(tmp_path):
    v = vault_embudo(tmp_path)
    secreto = "sk" + "-" + "q" * 24
    with pytest.raises(ValueError, match="secreto"):
        escribir_tracking(v, _t(evidencia=[f"me pasó el token {secreto}"]), AHORA)
    assert not (v / "productos" / P / "checkout" / PAIS / "TRACKING.md").exists()
    assert "tracking" not in _producto(v)[0]["paises"][PAIS]


def test_tracking_invalido_no_se_escribe(tmp_path):
    v = vault_embudo(tmp_path)
    with pytest.raises(ValueError, match="estado"):
        escribir_tracking(v, _t(estado="casi"), AHORA)
    with pytest.raises(ValueError, match="dos emisores"):
        escribir_tracking(v, _t(emisores={"PageView": "impultienda", "ViewContent": "impultienda",
                                          "InitiateCheckout": "impultienda",
                                          "Purchase": ["impultienda", "landing"]}), AHORA)
    with pytest.raises(ValueError, match="dataset_id"):
        escribir_tracking(v, _t(dataset_id="act_0000000000000000"), AHORA)
    assert not (v / "productos" / P / "checkout" / PAIS / "TRACKING.md").exists()
