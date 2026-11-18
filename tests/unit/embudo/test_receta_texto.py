"""Receta imprimible del respaldo manual (plan 19, Tarea 6): lo que el usuario hace en su propio navegador."""

import pytest
from trovefy.embudo.receta_texto import LOGIN, PasoReceta, imprimir_receta

TOKEN_FALSO = "EAA" + "Bq7" * 10  # se arma aquí para no dejar un token literal en el repo


def _pasos() -> list[PasoReceta]:
    return [
        PasoReceta(1, "Panel → Configuraciones → Meta / Tracking", "Meta Pixel ID", "1111111111111111"),
        PasoReceta(2, "Panel → Configuraciones → Meta / Tracking", "Token de API de conversiones", "",
                   nota="lo pegas tú; no lo pegues en el chat"),
    ]


def test_receta_numerada_con_valor_entre_comillas():
    texto = imprimir_receta("Tracking de ZZ", _pasos())
    assert texto.splitlines()[0] == "Tracking de ZZ"
    assert LOGIN in texto
    assert "1. Panel → Configuraciones → Meta / Tracking → «Meta Pixel ID»: «1111111111111111»" in texto
    assert "2. Panel → Configuraciones → Meta / Tracking → «Token de API de conversiones»" in texto
    assert "   lo pegas tú; no lo pegues en el chat" in texto


def test_imprimir_receta_rechaza_secreto():
    pasos = [PasoReceta(1, "Panel", "Token", TOKEN_FALSO)]
    with pytest.raises(ValueError, match="secreto"):
        imprimir_receta("Tracking", pasos)


def test_receta_sin_app_impultienda():
    assert "app.impultienda.ar" not in imprimir_receta("Tracking", _pasos())
    with pytest.raises(ValueError, match="app.impultienda.ar"):
        imprimir_receta("Tracking", [PasoReceta(1, "https://app.impultienda.ar/ajustes", "Pixel", "1")])


def test_receta_vacia_o_numeracion_rota():
    with pytest.raises(ValueError):
        imprimir_receta("Tracking", [])
    with pytest.raises(ValueError, match="numer"):
        imprimir_receta("Tracking", [PasoReceta(1, "a", "b", "c"), PasoReceta(3, "a", "b", "c")])
