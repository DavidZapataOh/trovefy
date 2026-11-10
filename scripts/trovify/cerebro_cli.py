"""Subcomando `trovify cerebro`."""

import argparse
import json
import sys
from pathlib import Path

import yaml

from trovify.cli import registrar
from trovify.vault.andamio import crear_vault
from trovify.vault.lint import lint
from trovify.vault.permisos import escribir_settings
from trovify.vault.reglas import ConflictoDeReglas, aplicar_plan, planear_regla
from trovify.vault.rutas import vault_root
from trovify.vault.sesiones import escribir_traspaso, ultimo_traspaso


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    init = sub.add_parser("init", help="crea el vault Cerebro desde la plantilla")
    init.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    perm = sub.add_parser("permisos", help="regenera .claude/settings.json del vault")
    perm.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    reg = sub.add_parser("regla", help="crea una regla fechada R-nnn desde un JSON")
    reg.add_argument("--json", required=True, metavar="ARCHIVO",
                     help="JSON con titulo, regla, porque, como, fuente (+ umbrales, reemplaza, fecha); «-» lee de stdin")
    reg.add_argument("--simular", action="store_true",
                     help="valida y muestra qué cambiaría, sin escribir nada")
    reg.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    tra = sub.add_parser("traspaso", help="escribe el traspaso de la sesión en sesiones/")
    tra.add_argument("--json", required=True, metavar="ARCHIVO",
                     help="JSON con hecho, pendiente, decisiones, archivos (listas de texto); «-» lee de stdin")
    tra.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    ret = sub.add_parser("retomar", help="imprime el último traspaso de sesión")
    ret.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")
    lin = sub.add_parser("lint", help="revisa enlaces rotos, páginas huérfanas y frontmatter")
    lin.add_argument("--vault", help="ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)")


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
        plan = planear_regla(destino, **campos)
        if not args.simular:
            aplicar_plan(plan)
    except ConflictoDeReglas as exc:
        print("Conflicto con reglas vigentes: " + " ".join(exc.ids))
        return 3
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc))
    except yaml.YAMLError as exc:
        return _error(f"un archivo del vault no es YAML válido ({exc})")
    except OSError as exc:
        return _error(f"no se pudo leer o escribir en el vault: {exc.strerror or exc}")
    if args.simular:
        print("Simulación: no se escribió nada.")
    for linea in plan.resumen():
        print(linea)
    if not args.simular:
        print(plan.ruta)
    return 0


_LISTAS = ("hecho", "pendiente", "decisiones", "archivos")


def _traspaso(args: argparse.Namespace, destino: Path) -> int:
    try:
        crudo = sys.stdin.read() if args.json == "-" else Path(args.json).expanduser().read_text(encoding="utf-8")
        campos = json.loads(crudo)
    except OSError as exc:
        return _error(f"no se pudo leer {args.json}: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        return _error(f"el JSON no es válido ({exc})")
    if not isinstance(campos, dict):
        return _error("el JSON debe ser un objeto con hecho, pendiente, decisiones y archivos")
    sobran = sorted(set(campos) - set(_LISTAS))
    if sobran:
        return _error(f"campos desconocidos en el JSON: {', '.join(sobran)}")
    listas = {}
    for c in _LISTAS:
        v = campos.get(c, [])
        if not isinstance(v, list) or not all(isinstance(i, str) for i in v):
            return _error(f"«{c}» debe ser una lista de textos")
        listas[c] = [i.strip() for i in v if i.strip()]
    try:
        ruta = escribir_traspaso(destino, listas["hecho"], listas["pendiente"],
                                 listas["decisiones"], listas["archivos"])
    except OSError as exc:
        return _error(f"no se pudo escribir en el vault: {exc.strerror or exc}")
    print(ruta)
    return 0


def _retomar(destino: Path) -> int:
    ruta = ultimo_traspaso(destino)
    if ruta is None:
        print("No hay traspasos de sesión todavía.")
        return 0
    print(f"# {ruta.relative_to(destino)}\n")
    print(ruta.read_text(encoding="utf-8"))
    return 0


def _lint(destino: Path) -> int:
    if not destino.is_dir():
        return _error(f"no existe el vault {destino}")
    problemas = lint(destino)
    for p in problemas:
        print(f"{p.tipo}: {p.ruta}: {p.detalle}")
    if problemas:
        print(f"{len(problemas)} problema(s).")
        return 1
    print("Vault sin problemas.")
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    if args.accion == "regla":
        return _regla(args, destino)
    if args.accion == "traspaso":
        return _traspaso(args, destino)
    if args.accion == "retomar":
        return _retomar(destino)
    if args.accion == "lint":
        return _lint(destino)
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
