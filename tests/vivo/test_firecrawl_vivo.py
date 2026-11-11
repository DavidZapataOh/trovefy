"""Prueba contra Firecrawl real (marca vivo; se salta si no hay FIRECRAWL_API_KEY en claude.env)."""

import warnings

import pytest
from trovefy.caza.cliente import ClienteBibliotecaPublica
from trovefy.caza.firecrawl import NavegadorFirecrawl, clave_firecrawl
from trovefy.caza.presupuesto import Presupuesto


@pytest.mark.vivo
def test_therapy_toolkit_por_firecrawl():
    clave = clave_firecrawl()
    if clave is None:
        pytest.skip("falta FIRECRAWL_API_KEY en ~/.config/trovefy/claude.env")
    nav = NavegadorFirecrawl(clave)
    c = ClienteBibliotecaPublica(Presupuesto(3, 2, 5), firecrawl=nav)
    r = c.buscar("ALL", page_id="102506312071455", estado="all")
    resumen = (f"estado={r.estado} anuncios={len(r.anuncios)} total={r.total_aprox} "
               f"via={r.via} creditos={r.creditos} motivo={r.motivo!r}")
    warnings.warn(resumen, stacklevel=1)
    assert r.estado == "ok" and len(r.anuncios) >= 20 and (r.total_aprox or 0) > 0, resumen
    assert r.via == "firecrawl", resumen
