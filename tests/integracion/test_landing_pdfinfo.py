"""Plan 18: el único test que mide el PDF fijo con el ``pdfinfo`` real (los unitarios inyectan uno falso)."""

import shutil

import pytest

pytestmark = pytest.mark.integracion


def test_cargar_datos_con_pdfinfo_real(tmp_path):
    if shutil.which("pdfinfo") is None:
        pytest.skip("sin pdfinfo (poppler-utils)")
    from trovefy.landing.entrada import cargar_datos
    from unit.landing.conftest import P, vault_demo

    d = cargar_datos(vault_demo(tmp_path), P, "ZZ")
    assert d.pdf_paginas == 3 and d.pdf.name == "demo-bg-v1.pdf"
