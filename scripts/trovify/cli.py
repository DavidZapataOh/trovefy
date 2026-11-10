"""CLI de Trovify: `main` y el registro de subcomandos."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from trovify import __version__

Configurar = Callable[[argparse.ArgumentParser], None]
Ejecutar = Callable[[argparse.Namespace], int]

_REGISTRO: dict[str, tuple[Configurar, Ejecutar]] = {}


def registrar(nombre: str, configurar: Configurar, ejecutar: Ejecutar) -> None:
    """Registra un subcomando; `main` lo añade al construir el parser."""
    _REGISTRO[nombre] = (configurar, ejecutar)


def _ejecutar_version(_args: argparse.Namespace) -> int:
    print(f"trovify {__version__}")
    return 0


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trovify", description="Trovify: CLI del negocio.")
    sub = parser.add_subparsers(dest="comando", metavar="<comando>")
    sub.add_parser("version", help="muestra la versión")
    for nombre, (configurar, _) in _REGISTRO.items():
        configurar(sub.add_parser(nombre))
    return parser


def main(argv: list[str] | None = None) -> int:
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
