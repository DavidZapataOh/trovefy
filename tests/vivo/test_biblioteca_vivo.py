"""Prueba semanal contra la Biblioteca real (marca vivo; se ejecuta con ``-m vivo``)."""

import warnings

import pytest
from trovify.caza.cliente import ClienteBibliotecaPublica
from trovify.caza.presupuesto import Presupuesto


@pytest.mark.vivo
def test_therapy_toolkit_sigue_anunciando():
    r = ClienteBibliotecaPublica(Presupuesto(3, 2, 5)).buscar("ALL", page_id="102506312071455", estado="all", completa=True)
    resumen = (f"estado={r.estado} anuncios={len(r.anuncios)} total={r.total_aprox} "
               f"completo={r.completo} motivo={r.motivo!r}")
    warnings.warn(resumen, stacklevel=1)  # visible en el resumen de pytest
    assert r.estado == "ok" and (r.total_aprox or len(r.anuncios)) > 0, resumen
    # Con max_anuncios=60 por defecto: o se llegó a 60 desplazando, o Meta dijo que no había más.
    assert len(r.anuncios) == 60 or r.completo, resumen
    if r.completo:
        assert r.total_aprox is None or r.total_aprox <= len(r.anuncios), resumen
