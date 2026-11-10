"""Registro de verificadores: cada paso de /arranque verificable tiene el suyo."""

from collections.abc import Callable
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion

REGISTRO: dict[str, Callable[[Path], ResultadoVerificacion]] = {}


def verificador(id_: str) -> Callable[[Callable[[Path], ResultadoVerificacion]], Callable[[Path], ResultadoVerificacion]]:
    """Registra la función como verificador del paso `id_`."""

    def registrar(f: Callable[[Path], ResultadoVerificacion]) -> Callable[[Path], ResultadoVerificacion]:
        REGISTRO[id_] = f
        return f

    return registrar


from trovify.arranque.verificadores import (  # noqa: F401  (registran los verificadores)
    apimart,
    caza,
    cerebro,
    checklist,
    cuenta,
    dominio,
    entorno,
    impultienda,
    meta_ids,
)
