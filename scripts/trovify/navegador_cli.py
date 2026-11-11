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
    a.add_argument("servicio", metavar="SERVICIO", help="nombre del perfil (p. ej. impultienda)")
    a.add_argument("url", metavar="URL", help="página que se abre")
    c = sub.add_parser("capturar", help="abre la URL con el perfil y guarda una captura de pantalla")
    c.add_argument("servicio", metavar="SERVICIO", help="nombre del perfil (p. ej. impultienda)")
    c.add_argument("url", metavar="URL", help="página que se captura")
    c.add_argument("--png", required=True, metavar="RUTA",
                   help="dónde guardar la captura; si está en config/evidencia/provisional/ del vault, el texto de la página se guarda "
                   "al lado (.txt) salvo si parece llevar un secreto")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _provisional() -> Path:
    from trovify.vault.rutas import vault_root

    return vault_root() / "config" / "evidencia" / "provisional"


def _en_provisional(destino: Path) -> bool:
    """El texto de una pantalla con sesión solo se guarda en config/evidencia/provisional/ del vault."""
    try:
        destino.resolve().relative_to(_provisional().resolve())
    except ValueError:
        return False
    return True


def _guardar_texto(destino: Path, url_final: str, texto: str) -> str:
    """Guarda el texto visible (nunca el HTML) con modo 0600; nada si parece llevar un secreto."""
    from trovify.arranque.verificadores.base import (
        PantallaProvisional,
        documento_de_texto,
        escribir_privado,
    )
    from trovify.secretos import RevisionSecretosNoDisponible, buscar_secreto

    documento = documento_de_texto([PantallaProvisional("pagina", url_final, None, texto)])
    try:
        patron = buscar_secreto(documento)
    except RevisionSecretosNoDisponible as exc:
        return f"Texto no guardado: {exc}."
    if patron:
        return f"Texto no guardado: parece llevar un secreto ({patron}); solo se guardó la captura."
    escribir_privado(destino, documento.encode("utf-8"))
    return f"Texto guardado en {destino}."


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
    destino = Path(args.png).with_suffix(".txt")
    if _en_provisional(destino):
        print(_guardar_texto(destino, c.url_final, c.texto))
    else:
        print(f"Texto no guardado: solo se guarda dentro de {_provisional()}/ (fuera del vault no se deja texto de tu sesión).")
    if navegador.sesion_caducada(c.url_final):
        print("Aviso: parece que la sesión ha caducado (pantalla de inicio de sesión). Ejecuta «trovify navegador abrir».")
    return 0


registrar("navegador", _configurar, _ejecutar, ayuda="abre o captura páginas con un perfil de Chromium por servicio")
