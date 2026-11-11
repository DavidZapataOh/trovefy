"""Subcomando `trovefy rutinas`."""

import argparse
import subprocess
import sys

from trovefy import rutinas
from trovefy.cli import registrar


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    i = sub.add_parser("instalar", help="instala el timer de systemd de una rutina")
    i.add_argument("rutina", choices=["caza"], help="rutina a instalar")


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.vault.rutas import vault_root

    claude = rutinas.buscar_claude()
    if not claude:
        print("Error: no encuentro el comando claude en el PATH; instala Claude Code antes de la rutina.",
              file=sys.stderr)
        return 2
    try:
        rutas = rutinas.instalar_caza(vault_root(), claude)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: no se pudo instalar la rutina ({type(exc).__name__}). Si WSL no mantiene vivos los "
              "servicios de usuario, ejecuta en una terminal de Ubuntu aparte: sudo loginctl enable-linger $USER",
              file=sys.stderr)
        return 1
    for r in rutas:
        print(f"Escrito: {r}")
    print("Rutina de caza activa: de lunes a sábado a las 06:30 (hora de Colombia).")
    print("Compruébalo con: systemctl --user list-timers | grep trovefy-caza")
    return 0


registrar("rutinas", _configurar, _ejecutar, ayuda="instala rutinas programadas (timers de systemd de usuario)")
