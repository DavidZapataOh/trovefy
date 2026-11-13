"""Claves de idioma fijadas en ``montaje.IDIOMAS_META`` (marca vivo; se ejecuta con ``-m vivo``).

Meta devuelve los nombres de ``adlocale`` localizados al idioma de la cuenta («Búlgaro»), por eso el montaje
no busca por nombre sino que usa claves fijadas. Aquí solo se comprueba que la tabla es utilizable: no vacía,
claves enteras positivas y distintas. No usa red ni token (así no hay ninguna variable local con secretos)."""
import pytest
from trovefy_ejecutor.montaje import IDIOMAS_META


@pytest.mark.vivo
def test_tabla_de_claves_bien_formada():
    assert IDIOMAS_META
    claves = list(IDIOMAS_META.values())
    assert all(type(k) is int and k > 0 for k in claves)
    assert len(set(claves)) == len(claves)
