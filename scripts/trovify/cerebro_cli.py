"""Subcomando `trovify cerebro`."""

import argparse
from pathlib import Path

from trovify.cli import registrar
from trovify.vault.andamio import crear_vault
from trovify.vault.permisos import escribir_settings
from trovify.vault.rutas import vault_root


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    init = sub.add_parser("init", help="crea el vault Cerebro desde la plantilla")
    init.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    perm = sub.add_parser("permisos", help="regenera .claude/settings.json del vault")
    perm.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    if args.accion == "permisos":
        escribir_settings(destino, sobrescribir=True)
        print(f"Permisos regenerados en {destino / '.claude' / 'settings.json'}.")
        return 0
    creados = crear_vault(destino)
    escribir_settings(destino, sobrescribir=False)
    if not creados:
        print(f"El vault de {destino} ya estaba completo: no se creó nada.")
    else:
        print(f"Vault listo en {destino}: {len(creados)} archivos creados.")
    return 0


registrar("cerebro", _configurar, _ejecutar)
