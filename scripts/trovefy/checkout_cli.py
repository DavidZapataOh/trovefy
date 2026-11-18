"""Subcomando `trovefy checkout` (plan 19): el checkout se arma por el MCP o, de respaldo, a mano por el usuario.

trovefy nunca entra al panel (resolución 38). Este módulo empieza con `evidencia` (Tarea 6): registrar lo que el
usuario pega (una captura, un texto) o dice, como prueba de lo que hizo en su propio navegador.

Códigos de salida: 0 bien · 1 una puerta no pasa · 2 error de uso o de entrada. Nunca una traza.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG, RO…)")


def _configurar(parser: argparse.ArgumentParser) -> None:
    from trovefy.embudo.pegado import CLAVES

    sub = parser.add_subparsers(dest="accion", metavar="<acción>", required=True)
    ev = sub.add_parser("evidencia", help="registra una captura, un texto o tus palabras como prueba de un paso")
    _comunes(ev)
    ev.add_argument("--clave", required=True, choices=CLAVES, help="qué prueba (producto, ver-como, reembolso…)")
    fuente = ev.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--desde", help="la captura (.png/.jpg/.webp) o el texto (.txt/.eml); vale una ruta de Windows")
    fuente.add_argument("--dicho", help="las palabras literales del usuario, entre comillas")
    ev.add_argument("--valor", action="append", default=[], metavar="NOMBRE=VALOR",
                    help="lo que se lee en la captura y el usuario confirmó (se puede repetir)")


def _parsear_valores(pares: list[str]) -> dict[str, str]:
    valores: dict[str, str] = {}
    for par in pares:
        nombre, igual, valor = par.partition("=")
        if not igual or not nombre.strip() or not valor.strip():
            raise ValueError(f"--valor «{par}»: escribe nombre=valor")
        valores[nombre.strip()] = valor.strip()
    return valores


def _evidencia(args: argparse.Namespace) -> int:
    from trovefy.embudo.contexto import cargar_contexto
    from trovefy.embudo.pegado import dicho, guardar_pegado
    from trovefy.vault.rutas import vault_root

    if args.dicho is not None and args.valor:
        return _error("--valor va con --desde (lo que se lee en una captura), no con --dicho")
    vault = vault_root()
    try:
        ctx = cargar_contexto(vault, args.producto, args.pais.strip().upper())
        if args.dicho is not None:
            p = dicho(vault, ctx, args.clave, args.dicho, _ahora())
        else:
            p = guardar_pegado(vault, ctx, args.clave, args.desde, _parsear_valores(args.valor), _ahora())
    except (ValueError, OSError) as exc:
        return _error(exc)
    print(f"Evidencia {p.clave} ({p.tipo}) guardada: productos/{args.producto}/{p.ruta}")
    if p.valores:
        print("Valores: " + ", ".join(f"{k}={v}" for k, v in p.valores.items()))
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    if args.accion == "evidencia":
        return _evidencia(args)
    return _error(f"acción desconocida: {args.accion}")


registrar("checkout", _configurar, _ejecutar, "checkout en Impultienda: evidencias que pegas tú (plan 19)")
