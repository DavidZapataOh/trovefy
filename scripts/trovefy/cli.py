"""CLI de Trovefy: `main` y el registro de subcomandos."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Callable

import trovefy
from trovefy import __version__

Configurar = Callable[[argparse.ArgumentParser], None]
Ejecutar = Callable[[argparse.Namespace], int]

_REGISTRO: dict[str, tuple[Configurar, Ejecutar, str]] = {}


def registrar(nombre: str, configurar: Configurar, ejecutar: Ejecutar, ayuda: str = "") -> None:
    """Registra un subcomando; `main` lo añade al construir el parser.

    `ayuda` es la línea que muestra `trovefy --help` junto al subcomando.

    Lanza ValueError si el nombre ya existe o es el reservado `version`.
    """
    if nombre == "version" or nombre in _REGISTRO:
        raise ValueError(f"el subcomando «{nombre}» ya está registrado")
    _REGISTRO[nombre] = (configurar, ejecutar, ayuda)


def _ejecutar_version(_args: argparse.Namespace) -> int:
    print(f"trovefy {__version__}")
    return 0


def _descubrir_subcomandos() -> None:
    """Importa cada módulo `trovefy.*_cli`; al importarse llaman a `registrar`."""
    for info in pkgutil.iter_modules(trovefy.__path__):
        if info.name.endswith("_cli"):
            try:
                importlib.import_module(f"trovefy.{info.name}")
            except Exception as exc:  # noqa: BLE001 - un módulo roto no debe tumbar la CLI
                print(f"aviso: no se pudo cargar trovefy.{info.name}: {type(exc).__name__}", file=sys.stderr)


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trovefy", description="Trovefy: CLI del negocio.")
    sub = parser.add_subparsers(dest="comando", metavar="<comando>")
    sub.add_parser("version", help="muestra la versión")
    for nombre, (configurar, _, ayuda) in _REGISTRO.items():
        configurar(sub.add_parser(nombre, help=ayuda, description=ayuda or None))
    return parser


def main(argv: list[str] | None = None) -> int:
    _descubrir_subcomandos()
    parser = _construir_parser()
    args = parser.parse_args(argv)
    if args.comando is None:
        parser.print_help(sys.stderr)
        return 2
    if args.comando == "version":
        return _ejecutar_version(args)
    return _REGISTRO[args.comando][1](args)


if __name__ == "__main__":
    raise SystemExit(main())
