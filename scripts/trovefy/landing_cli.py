"""Subcomando `trovefy landing`: landing propia por país (plan 18).

Claude escribe el texto y el diseño en un borrador fuera del vault; aquí solo lo determinista: entrada,
medios, esqueleto, comprobación, QA y publicación.

Códigos de salida: 0 bien · 1 una puerta no pasa (estado, validación) · 2 error de uso o de entrada ·
3 fallo inesperado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trovefy.cli import registrar


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG, RO…)")


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", metavar="<acción>", required=True)
    _comunes(sub.add_parser("estado", help="estado del país, PDF vigente y lo que falta"))


# --- acciones ------------------------------------------------------------------------------------


def _faltan(vault: Path, p_id: str, pais: str) -> list[str]:
    import yaml

    from trovefy.landing.entrada import ruta_landing

    raiz = ruta_landing(vault, p_id, pais)
    faltan = []
    if not (raiz / "assets" / "vistas.json").is_file():
        faltan.append(f"medios (trovefy landing medios --producto {p_id} --pais {pais})")
    if not (raiz / "landing.yaml").is_file():
        faltan.append(f"borrador (trovefy landing preparar --producto {p_id} --pais {pais})")
    if not (raiz / "index.html").is_file():
        faltan.append(f"landing guardada (trovefy landing guardar --producto {p_id} --pais {pais})")
    if not (raiz / "QA.md").is_file():
        faltan.append("QA")
    if not (raiz / "nativo.md").is_file():
        faltan.append("veredicto del nativo")
    url = None
    if (raiz / "landing.yaml").is_file():
        datos = yaml.safe_load((raiz / "landing.yaml").read_text(encoding="utf-8")) or {}
        url = datos.get("url") if isinstance(datos, dict) else None
    if not url:
        faltan.append("publicar")
    return faltan


def _estado(args: argparse.Namespace, vault: Path) -> int:
    from trovefy.landing.entrada import EstadoNoPermite, cargar_datos

    try:
        d = cargar_datos(vault, args.producto, args.pais)
    except EstadoNoPermite as e:
        print(f"{args.pais.upper()}: no puede tener landing aún")
        print(str(e))
        return 1
    print(f"{d.pais}: {d.estado}")
    print(f"PDF vigente: {d.pdf.name} ({d.pdf_paginas} páginas)")
    print(f"Precio: {d.precio} {d.moneda} · secciones: {len(d.secciones)} · marca: {d.marca}")
    print(f"Dominio: {d.dominio or 'no medido: falta el paso 07'} · tienda: {d.tienda or 'no medida'}")
    faltan = _faltan(vault, d.p_id, d.pais)
    print("falta: " + ("; ".join(faltan) if faltan else "nada"))
    return 0

_ACCIONES = {"estado": _estado}


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.landing.entrada import EntradaInvalida, EstadoNoPermite
    from trovefy.secretos import RevisionSecretosNoDisponible
    from trovefy.vault.rutas import vault_root

    try:
        return _ACCIONES[args.accion](args, vault_root())
    except EstadoNoPermite as e:
        return _error(e, 1)
    except (EntradaInvalida, RevisionSecretosNoDisponible, ValueError, FileNotFoundError) as e:
        return _error(e)
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)


registrar("landing", _configurar, _ejecutar, ayuda="landing propia por país: preparar, QA y publicar")
