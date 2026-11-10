"""Prueba semanal contra la Biblioteca real (marca vivo; se ejecuta con ``-m vivo``)."""

import pytest
from trovify.caza.cliente import ClienteBibliotecaPublica
from trovify.caza.presupuesto import Presupuesto


@pytest.mark.vivo
def test_therapy_toolkit_sigue_anunciando():
    r = ClienteBibliotecaPublica(Presupuesto(3, 2, 5)).buscar("ALL", page_id="102506312071455", estado="all")
    assert r.estado == "ok" and (r.total_aprox or len(r.anuncios)) > 0
