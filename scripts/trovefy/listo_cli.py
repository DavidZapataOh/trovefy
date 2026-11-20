"""Subcomando `trovefy listo` (plan 20, Tarea 5): los once gates del producto-país, su informe en ``PRODUCTO.md`` y
el paso ``con_checkout → listo``.

Uso: ``trovefy listo <p-id> --pais XX [--para-activar] [--vault RUTA]``.
Salidas: 0 pasa (con ``--para-activar``: los once en ok, sin excepciones) · 1 rojo · 2 error de uso, ``PRODUCTO.md``
ausente o ilegible, o un secreto en lo que se iba a escribir. Nunca una traza.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _configurar(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("producto", metavar="P-ID", help="p-id del producto (p-0001-…)")
    parser.add_argument("--pais", required=True, help="código del país en mayúsculas (BG, RO…)")
    parser.add_argument("--para-activar", action="store_true",
                        help="exige los once gates en ok, salvo las excepciones que admitiste para activar (fase 3)")
    parser.add_argument("--vault", help="ruta del cerebro (por defecto TROVEFY_VAULT o ~/trovefy-cerebro)")


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.listo import veredicto
    from trovefy.listo.ficha import FichaIlegible, leer_ficha, registrar_listo
    from trovefy.vault.rutas import vault_root

    vault = Path(args.vault).expanduser() if args.vault else vault_root()
    try:
        antes = leer_ficha(vault, args.producto, args.pais).estado
        ahora = getattr(sys.modules.get(__name__), "_ahora", _ahora)()
        informe = veredicto.evaluar(vault, args.producto, args.pais, ahora, veredicto.fuentes_por_defecto(vault))
        despues = registrar_listo(vault, informe)
    except (FileNotFoundError, FichaIlegible, ValueError, OSError) as exc:
        return _error(exc)
    print(f"/listo · {args.producto} · {args.pais}")
    print(veredicto.texto_informe(informe))
    print(f"Estado de {args.pais}: {antes or 'sin estado'} → {despues}")
    excepciones = [g.clave for g in informe.gates if g.estado == "excepcion"]
    if informe.pasa and excepciones:
        print("Ojo: " + ", ".join(excepciones) + " no está en verde; pasa por tu excepción aprobada.")
    if informe.pasa and antes not in ("con_checkout", "listo"):
        print(f"El estado no avanza: /listo solo pasa a listo desde con_checkout (ahora está en {antes or 'sin estado'}).")
    if not informe.pasa:
        faltan = [f"- {g.clave}: {g.arreglo or g.texto}" for g in informe.gates
                  if g.estado in ("falla", "no_medido") or (g.estado == "no_aplica" and g.clave != "creativos")]
        print("Lo que falta:")
        print("\n".join(faltan))
    if args.para_activar:
        from trovefy.montar.precondiciones import excepciones_para_activar

        admitidas = frozenset(excepciones_para_activar(vault, args.producto, args.pais))
        if veredicto.listo_para_activar(informe, admitidas):
            if admitidas & {g.clave for g in informe.gates if g.estado == "excepcion"}:
                print("Para activar: pasa con las excepciones que admitiste para activar ("
                      + ", ".join(sorted(admitidas)) + ").")
            return 0
        print("Para activar faltan los once gates en ok (solo las excepciones que admitiste con `trovefy montar "
              "excepcion`, creativos revisados) y el BE medido.")
        return 1
    return 0 if informe.pasa else 1


registrar("listo", _configurar, _ejecutar, "gates antes de gastar: ¿se puede comprar? (plan 20)")
