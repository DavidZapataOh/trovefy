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


# --- ronda de revisión (M-6, L-6) ----------------------------------------------------------------------------------


def _lineas_log(v) -> list[str]:
    ruta = v / "log.md"
    return [x for x in ruta.read_text(encoding="utf-8").splitlines() if x.startswith("- ")] if ruta.exists() else []


@pytest.mark.parametrize("pais", ["../../../../fuera", "Z/", "ZZZ", "", "ζζ"])
def test_pais_con_rutas_raras_no_escribe(tmp_path, pais):
    v = vault_embudo(tmp_path)
    with pytest.raises(ValueError, match="país"):
        escribir_tracking(v, _t(pais=pais), AHORA)
    assert list(tmp_path.rglob("TRACKING.md")) == []
    assert _lineas_log(v) == []


def test_pais_en_minusculas_se_normaliza(tmp_path):
    v = vault_embudo(tmp_path)
    ruta = escribir_tracking(v, _t(pais="zz"), AHORA)
    assert ruta == v / "productos" / P / "checkout" / PAIS / "TRACKING.md"
    t = leer_tracking(v, P, PAIS)
    assert t is not None and t.pais == PAIS
    assert [p.relative_to(v).as_posix() for p in v.rglob("TRACKING.md")] == [f"productos/{P}/checkout/ZZ/TRACKING.md"]


def test_sin_producto_no_escribe_nada(tmp_path):
    v = vault_embudo(tmp_path)
    (v / "productos" / P / "PRODUCTO.md").unlink()
    with pytest.raises(FileNotFoundError, match="PRODUCTO.md"):
        escribir_tracking(v, _t(), AHORA)
    assert not (v / "productos" / P / "checkout").exists()
    assert _lineas_log(v) == []


def test_una_sola_linea_de_log(tmp_path):
    v = vault_embudo(tmp_path)
    escribir_tracking(v, _t(), AHORA)
    lineas = _lineas_log(v)
    assert len(lineas) == 1
    assert "TRACKING.md" in lineas[0] and "PRODUCTO.md" in lineas[0]
    # Reescribir lo mismo (PRODUCTO.md no cambia) también deja una sola línea más.
    escribir_tracking(v, _t(), AHORA)
    assert len(_lineas_log(v)) == 2
    escribir_tracking(v, _t(estado="configurado"), AHORA)
    assert len(_lineas_log(v)) == 3


def test_secreto_en_el_enlace_o_el_bloque_no_escribe(tmp_path):
    v = vault_embudo(tmp_path)
    secreto = "EAAB" + "x7Yq2ZbC9" * 12
    for campo in ("dataset_nombre", "motivos"):
        valor = [secreto] if campo == "motivos" else secreto
        with pytest.raises(ValueError, match="secreto"):
            escribir_tracking(v, _t(**{campo: valor}), AHORA)
    assert list(v.rglob("TRACKING.md")) == []
    assert _lineas_log(v) == []


def test_dataset_id_solo_digitos_ascii(tmp_path):
    v = vault_embudo(tmp_path)
    with pytest.raises(ValueError, match="dataset_id"):
        escribir_tracking(v, _t(dataset_id="١" * 16), AHORA)


def test_emisor_purchase_es_texto(tmp_path):
    v = vault_embudo(tmp_path)
    emisores = {"PageView": "impultienda", "ViewContent": "impultienda", "InitiateCheckout": "impultienda",
                "Purchase": ["impultienda", "impultienda"]}
    escribir_tracking(v, _t(emisores=emisores), AHORA)
    assert _producto(v)[0]["paises"][PAIS]["tracking"]["emisor_purchase"] == "impultienda"


def test_home_aislado(tmp_path):
    from pathlib import Path
    assert Path.home() == tmp_path
