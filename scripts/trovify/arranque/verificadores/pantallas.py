"""Lectura de las pantallas de un mapa.yaml con el navegador de Trovify (solo lectura, sin clics)."""

from collections.abc import Callable

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores.meta_ids import leer_pagina
from trovify.mapa import FirmaAusente, leer_pantalla


def capturar_pantallas(servicio: str, mapa: dict, nombres: list[str], capturar: Callable) -> tuple[dict, str | None]:
    """{nombre: (captura, png)} de cada pantalla, o (parcial, motivo «no medido») al primer fallo."""
    salida: dict = {}
    for nombre in nombres:
        cap, png, motivo = leer_pagina(mapa["pantallas"][nombre]["url"], capturar, servicio)
        if cap is None:
            return salida, motivo
        salida[nombre] = (cap, png)
    return salida, None


def campos_de(mapa: dict, capturas: dict) -> dict[str, dict[str, str | None]]:
    """Campos de cada pantalla capturada; `FirmaAusente(<nombre>)` si alguna no coincide con su firma."""
    leidos = {}
    for nombre, (cap, _png) in capturas.items():
        try:
            leidos[nombre] = leer_pantalla(mapa["pantallas"][nombre], cap.texto)
        except FirmaAusente:
            raise FirmaAusente(nombre) from None
    return leidos


def desactualizado(nombre: str) -> ResultadoVerificacion:
    motivo = f"no medido: mapa desactualizado ({nombre})"
    return ResultadoVerificacion(
        None, [], motivo, ["la pantalla cambió: avisa para actualizar el mapa; Trovify no hace clics en tu cuenta"], {}, [f"? {motivo}"]
    )
