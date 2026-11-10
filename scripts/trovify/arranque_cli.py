"""Subcomando `trovify arranque`."""

import argparse
import sys
from pathlib import Path

from trovify.arranque.estado import (
    ArranqueCorrupto,
    PasoDesconocido,
    cargar,
    marcar_bloqueado,
    marcar_hecho,
    porcentaje_fase,
    siguiente,
)
from trovify.cli import registrar
from trovify.vault.rutas import vault_root

_VAULT_AYUDA = "ruta del vault (por defecto, TROVIFY_VAULT o ~/trovify-cerebro)"


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("estado", help="tabla de pasos y avance de la fase 0").add_argument("--vault", help=_VAULT_AYUDA)
    sub.add_parser("siguiente", help="el próximo paso de la fase 0").add_argument("--vault", help=_VAULT_AYUDA)
    h = sub.add_parser("hecho", help="marca un paso como hecho (no verificado)")
    h.add_argument("id", metavar="ID")
    h.add_argument("--nota", help="nota breve")
    h.add_argument("--vault", help=_VAULT_AYUDA)
    b = sub.add_parser("bloqueado", help="marca un paso como bloqueado")
    b.add_argument("id", metavar="ID")
    b.add_argument("--motivo", required=True, help="por qué está bloqueado")
    b.add_argument("--vault", help=_VAULT_AYUDA)


def _error(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    try:
        if args.accion == "hecho":
            p = marcar_hecho(destino, args.id, args.nota)
            print(f"Paso {p.id} ({p.nombre}): {p.estado}.")
            return 0
        if args.accion == "bloqueado":
            if not args.motivo.strip():
                return _error("--motivo no puede estar vacío")
            p = marcar_bloqueado(destino, args.id, args.motivo)
            print(f"Paso {p.id} ({p.nombre}): {p.estado}.")
            return 0
        pasos = cargar(destino)
    except PasoDesconocido as exc:
        return _error(str(exc))
    except ArranqueCorrupto as exc:
        return _error(str(exc))
    except OSError as exc:
        return _error(f"no se pudo escribir en el vault: {exc.strerror or exc}")
    if args.accion == "siguiente":
        s = siguiente(pasos)
        if s is not None:
            print(f"Siguiente: {s.id} · {s.nombre} ({s.estado})")
            return 0
        bloqueados = [p for p in pasos if p.fase == 0 and p.estado == "bloqueado"]
        if not bloqueados:
            print("Fase 0 completa: todos los pasos están verificados.")
        else:
            print("No hay un paso siguiente: lo que falta de la fase 0 está bloqueado.")
            for p in bloqueados:
                print(f"  {p.id} · {p.nombre}: {p.nota or 'sin motivo'}")
        return 0
    print(f"{'ID':<4} {'Paso':<40} {'Estado':<11} Fecha")
    for p in pasos:
        print(f"{p.id:<4} {p.nombre:<40} {p.estado:<11} {p.fecha or '—'}")
    frac = porcentaje_fase(pasos, 0)
    print(f"\nFase 0: {round(frac * 12)}/12 verificados ({frac * 100:.0f} %)")
    return 0


registrar("arranque", _configurar, _ejecutar)
