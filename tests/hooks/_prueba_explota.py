"""Hook de prueba: su decidir() siempre lanza RuntimeError."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "hooks"))

from _comun import ejecutar_guardia


def decidir(entrada):
    raise RuntimeError("explota a propósito")


if __name__ == "__main__":
    ejecutar_guardia(decidir)
