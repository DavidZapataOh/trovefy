"""Subcomando `trovify cerebro`."""

import argparse
import json
import sys
from pathlib import Path

from trovify.cli import registrar
from trovify.vault.andamio import crear_vault
from trovify.vault.permisos import escribir_settings
from trovify.vault.reglas import ConflictoDeReglas, nueva_regla
from trovify.vault.rutas import vault_root


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    init = sub.add_parser("init", help="crea el vault Cerebro desde la plantilla")
    init.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    perm = sub.add_parser("permisos", help="regenera .claude/settings.json del vault")
    perm.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    reg = sub.add_parser("regla", help="crea una regla fechada R-nnn desde un JSON")
    reg.add_argument("--json", required=True, metavar="ARCHIVO",
                     help="JSON con titulo, regla, porque, como, fuente (+ umbrales, reemplaza, fecha); «-» lee de stdin")
    reg.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")


def _error(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _regla(args: argparse.Namespace, destino: Path) -> int:
    try:
        crudo = sys.stdin.read() if args.json == "-" else Path(args.json).expanduser().read_text(encoding="utf-8")
        campos = json.loads(crudo)
    except OSError as exc:
        return _error(f"no se pudo leer {args.json}: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        return _error(f"el JSON no es válido ({exc})")
    if not isinstance(campos, dict):
        return _error("el JSON debe ser un objeto con los campos de la regla")
    requeridos = ("titulo", "regla", "porque", "como", "fuente")
    faltan = [c for c in requeridos if not isinstance(campos.get(c), str) or not campos[c].strip()]
    if faltan:
        return _error(f"faltan campos de texto en el JSON: {', '.join(faltan)}")
    permitidos = {*requeridos, "umbrales", "reemplaza", "fecha"}
    sobran = sorted(set(campos) - permitidos)
    if sobran:
        return _error(f"campos desconocidos en el JSON: {', '.join(sobran)}")
    try:
        ruta = nueva_regla(destino, **campos)
    except ConflictoDeReglas as exc:
        print("Conflicto con reglas vigentes: " + " ".join(exc.ids))
        return 3
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc))
    print(ruta)
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    if args.accion == "regla":
        return _regla(args, destino)
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
