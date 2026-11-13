"""Subcomando `trovefy aprobaciones`: listar, estado, probar y explicar (solo lectura salvo `probar`)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from trovefy.aprobaciones import fuentes, listado
from trovefy.cli import registrar


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    ls = sub.add_parser("listar", help="lista las propuestas por grupo")
    ls.add_argument("--todas", action="store_true", help="incluye ejecutadas, caducadas y otras")
    sub.add_parser("estado", help="estado del ejecutor, STOP, límites y auditoría")
    sub.add_parser("probar", help="deposita un noop inofensivo para probar el circuito")
    ex = sub.add_parser("explicar", help="explica una propuesta")
    ex.add_argument("id", help="id de la propuesta, P-AAAAMMDD-NNN")


def _vault():
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _listar(args: argparse.Namespace) -> int:
    filas, avisos = listado.listar(_vault())
    for a in avisos:
        print(fuentes.enmascarar_cuentas(f"Aviso: {a}"), file=sys.stderr)
    if not filas:
        print("No hay propuestas.")
        return 0
    for grupo in listado.GRUPOS:
        if not args.todas and grupo != "pendientes":
            continue
        sel = [f for f in filas if listado.grupo_de(f.estado) == grupo]
        print(f"{grupo} ({len(sel)})")
        for f in sel:
            print(fuentes.enmascarar_cuentas(f"  {f.id}  {f.tipo}  {f.estado}  {f.creada}  {f.origen}  {f.motivo}"))
    if not args.todas:
        resto = sum(1 for f in filas if listado.grupo_de(f.estado) != "pendientes")
        if resto:
            print(f"({resto} más: usa --todas; caducadas, ejecutadas y otras)")
    return 0


def _estado(_args: argparse.Namespace) -> int:
    for linea in listado.resumen_estado(_vault(), datetime.now(listado.COT), fuentes.ruta_spool()):
        print(linea)
    return 0


def _probar(_args: argparse.Namespace) -> int:
    ahora = datetime.now(listado.COT)
    try:
        id_ = fuentes.depositar(_vault(), listado.propuesta_noop(ahora), lambda: ahora)
    except fuentes.BuzonNoDisponible as e:
        print(fuentes.enmascarar_cuentas(f"No se pudo depositar la prueba: {e}"), file=sys.stderr)
        return 1
    print(f"Prueba depositada: {id_}. Debería llegarte a Telegram; pulsa Aceptar o Rechazar. No cambia nada en Meta.")
    return 0


def _explicar(args: argparse.Namespace) -> int:
    try:
        print(listado.explicar(_vault(), args.id))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    return {"listar": _listar, "estado": _estado, "probar": _probar, "explicar": _explicar}[args.accion](args)


registrar("aprobaciones", _configurar, _ejecutar, ayuda="consulta y prueba el aprobador de Telegram")
