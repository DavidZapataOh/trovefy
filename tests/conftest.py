"""Fixtures compartidos (los reutilizan otros planes)."""

import io
import json
import urllib.error
from typing import Self

import pytest


class _Respuesta:
    def __init__(self, codigo: int, cuerpo: bytes) -> None:
        self.status = codigo
        self._cuerpo = cuerpo

    def read(self, *_a: object) -> bytes:
        return self._cuerpo

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


@pytest.fixture
def respuesta_json():
    """`respuesta_json(codigo, cuerpo)` devuelve un `abrir` falso de urllib.

    Con código >= 400 lanza `HTTPError`, como hace `urlopen`. Guarda la última petición en `.peticiones`.
    """

    def fabrica(codigo: int, cuerpo: object):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode("utf-8")
        peticiones: list = []

        def abrir(req, timeout=None):
            peticiones.append((req, timeout))
            if codigo >= 400:
                url = getattr(req, "full_url", str(req))
                raise urllib.error.HTTPError(url, codigo, "error", {}, io.BytesIO(datos))
            return _Respuesta(codigo, datos)

        abrir.peticiones = peticiones
        return abrir

    return fabrica
