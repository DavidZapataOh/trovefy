"""Ayudas comunes de los tests de APIMart: env de prueba en 0600 y fixtures de la documentación."""

import json
import os
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "apimart"
CLAVE = "sk-prueba-" + "x" * 24


def fixture(nombre: str):
    ruta = FIXTURES / nombre
    if nombre.endswith(".json"):
        return json.loads(ruta.read_text(encoding="utf-8"))
    return ruta.read_bytes()


def escribir_env(tmp_path: pathlib.Path, texto: str, modo: int = 0o600) -> pathlib.Path:
    ruta = tmp_path / "claude.env"
    ruta.write_text(texto + "\n", encoding="utf-8")
    os.chmod(ruta, modo)
    return ruta
