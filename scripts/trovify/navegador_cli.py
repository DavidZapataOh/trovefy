"""Subcomando `trovify navegador`."""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from trovify import navegador
from trovify.cli import registrar


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    a = sub.add_parser("abrir", help="abre una ventana con el perfil del servicio para que inicies sesión")
    a.add_argument("servicio", metavar="SERVICIO")
    a.add_argument("url", metavar="URL")
    c = sub.add_parser("capturar", help="abre la URL con el perfil y guarda una captura de pantalla")
    c.add_argument("servicio", metavar="SERVICIO")
    c.add_argument("url", metavar="URL")
    c.add_argument("--png", required=True, metavar="RUTA", help="dónde guardar la captura")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _ejecutar(args: argparse.Namespace) -> int:
    u = urlparse(args.url)
    if u.scheme not in ("http", "https") or not u.netloc:
        return _error("la URL debe empezar por http:// o https://")
    try:
        navegador.perfil(args.servicio)
    except ValueError as exc:
        return _error(str(exc))
    try:
        if args.accion == "abrir":
            print(f"Abriendo {args.servicio}: inicia sesión tú mismo y cierra la ventana cuando termines.")
            navegador.abrir(args.servicio, args.url)
            print("Ventana cerrada; el perfil queda guardado.")
            return 0
        c = navegador.capturar(args.servicio, args.url, captura_png=Path(args.png))
    except navegador.NavegadorError as exc:
        return _error(str(exc), 1)
    except OSError as exc:
        return _error(f"no se pudo escribir: {exc.strerror or exc}", 1)
    print(f"Captura guardada en {c.png}.")
    if navegador.sesion_caducada(c.url_final):
        print("Aviso: parece que la sesión ha caducado (pantalla de inicio de sesión). Ejecuta «trovify navegador abrir».")
    return 0


registrar("navegador", _configurar, _ejecutar)
