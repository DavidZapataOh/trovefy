"""Subcomando `trovefy checkout` (plan 19): el checkout se arma por el MCP o, de respaldo, a mano por el usuario.

trovefy nunca entra al panel (resolución 38). Este módulo empieza con `evidencia` (Tarea 6): registrar lo que el
usuario pega (una captura, un texto) o dice, como prueba de lo que hizo en su propio navegador.

Códigos de salida: 0 bien · 1 una puerta no pasa · 2 error de uso o de entrada. Nunca una traza.
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


def _reloj() -> datetime:
    """``_ahora`` del módulo que está en ``sys.modules`` (un test de registro de la CLI reimporta los ``*_cli``)."""
    return getattr(sys.modules.get(__name__), "_ahora", _ahora)()


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
    _configurar_fuera(sub)


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
            p = dicho(vault, ctx, args.clave, args.dicho, _reloj())
        else:
            p = guardar_pegado(vault, ctx, args.clave, args.desde, _parsear_valores(args.valor), _reloj())
    except (ValueError, OSError) as exc:
        return _error(exc)
    print(f"Evidencia {p.clave} ({p.tipo}) guardada: productos/{args.producto}/{p.ruta}")
    if p.valores:
        print("Valores: " + ", ".join(f"{k}={v}" for k, v in p.valores.items()))
    return 0


# --- comprobación desde fuera, respaldo manual y demo (Tareas 12–13) ------------------------------------------

_RUTA_MAPA = Path(__file__).resolve().parents[2] / "templates" / "impultienda" / "mapa.yaml"
_ESTADOS_FUERA = ("con_landing", "con_checkout")


def _configurar_fuera(sub) -> None:
    co = sub.add_parser("comprobar", help="mira el checkout público como un comprador (sin panel) y escribe "
                                          "COMPROBACION.md")
    ma = sub.add_parser("manual", help="imprime y guarda la receta de lo que haces tú en tu panel (no lo abre)")
    de = sub.add_parser("demo", help="recorrido de comprador con perfil vacío, sin pagar; escribe embudo.md")
    for p in (co, ma, de):
        _comunes(p)
        p.add_argument("--plan", default="Max", help="plan de Impultienda con el que se calcula la receta (Max)")
    de.add_argument("--upsell-demo", default=None, metavar="URL",
                    help="enlace demo del post-compra (https://<tienda>/post-purchase/demo?t=…)")


def _contexto_y_ajustes(args: argparse.Namespace):
    from trovefy.checkout.emails import CLAVES_EMAIL, ruta_email
    from trovefy.checkout.receta import OpcionesReceta, ajustes_de_checkout
    from trovefy.embudo.contexto import cargar_contexto, exigir_estado, ruta_pais
    from trovefy.mapa import cargar, limites_de_plan
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    ctx = cargar_contexto(vault, args.producto, args.pais.strip().upper())
    exigir_estado(ctx, _ESTADOS_FUERA)
    emails = {c: r for c in CLAVES_EMAIL if (r := ruta_email(ruta_pais(ctx), c)).is_file()}
    ajustes, avisos = ajustes_de_checkout(ctx, limites_de_plan(cargar(_RUTA_MAPA), args.plan), emails,
                                          OpcionesReceta(args.plan))
    return vault, ctx, ajustes, avisos


def _comprobar(args: argparse.Namespace) -> int:
    import importlib

    from trovefy.checkout.manual import cerrar_manual
    from trovefy.embudo.pegado import indice

    fuera = importlib.import_module("trovefy.checkout.fuera")
    try:
        vault, ctx, ajustes, _ = _contexto_y_ajustes(args)
        pagina = fuera.leer_checkout_publico(ctx)
        ver_como = None
        if not (fuera._es_checkout(pagina, ctx) and pagina.moneda_vista == ctx.moneda
                and pagina.pais_visto in (None, ctx.pais)):
            ver_como = fuera.leer_ver_como(ctx)
        idx = indice(vault, ctx)
        estados = fuera.comprobar_fuera(ctx, ajustes, pagina, idx, ver_como=ver_como)
        manuales = [cerrar_manual(a, idx) for a in ajustes if not a.llamadas]
        ruta = fuera.escribir_comprobacion(vault, ctx, estados, manuales, _reloj())
    except (ValueError, OSError) as exc:
        return _error(exc)
    estado = fuera.estado_global([*estados, *manuales])
    print(f"Checkout {ctx.pais} visto desde fuera: {estado} → productos/{args.producto}/"
          f"{ruta.relative_to(ruta.parents[2]).as_posix()}")
    for e in [*estados, *manuales]:
        print(f"  [{e.estado}] {e.clave}: {e.detalle}")
    return 0 if estado == "completo" else 1


def _manual(args: argparse.Namespace) -> int:
    from trovefy.checkout.manual import plan_manual
    from trovefy.embudo.contexto import ruta_pais
    from trovefy.vault.escritura import anadir_log, escribir_atomico

    try:
        vault, ctx, ajustes, avisos = _contexto_y_ajustes(args)
        texto = plan_manual([a for a in ajustes if not a.llamadas], producto=ctx.producto, pais=ctx.pais)
        ruta = ruta_pais(ctx) / "RECETA-manual.md"
        escribir_atomico(ruta, texto)
        anadir_log(vault, "checkout", f"{ctx.producto} {ctx.pais}: receta manual del checkout",
                   [ruta.relative_to(vault).as_posix()], ahora=_reloj())
    except (ValueError, OSError) as exc:
        return _error(exc)
    print(texto, end="")
    for aviso in avisos:
        print(f"Aviso: {aviso}")
    return 0


def _demo(args: argparse.Namespace) -> int:
    import importlib

    from trovefy.embudo.contexto import ruta_pais
    from trovefy.embudo.pegado import indice

    demo = importlib.import_module("trovefy.checkout.demo")
    try:
        vault, ctx, ajustes, _ = _contexto_y_ajustes(args)
        if args.upsell_demo:
            demo.validar_upsell_demo(args.upsell_demo, ctx)
    except (ValueError, OSError) as exc:
        return _error(exc)
    try:
        pasos = demo.ejecutar_demo(ctx, ruta_pais(ctx) / "demo", args.upsell_demo, ajustes=ajustes,
                                   indice=indice(vault, ctx))
        ruta = demo.escribir_embudo(vault, ctx, pasos, _reloj())
    except (ValueError, OSError) as exc:
        return _error(exc, 1)
    estado = demo.estado_embudo(pasos)
    print(f"Recorrido demo {ctx.pais}: {estado} → productos/{args.producto}/"
          f"{ruta.relative_to(ruta.parents[2]).as_posix()}")
    for p in pasos:
        print(f"  [{p.estado}] {p.clave}: {p.detalle}")
    return 0 if estado == "ok" else 1


_ACCIONES_FUERA = {"comprobar": _comprobar, "manual": _manual, "demo": _demo}


def _ejecutar(args: argparse.Namespace) -> int:
    if args.accion == "evidencia":
        return _evidencia(args)
    if args.accion in _ACCIONES_FUERA:
        return _ACCIONES_FUERA[args.accion](args)
    return _error(f"acción desconocida: {args.accion}")


registrar("checkout", _configurar, _ejecutar, "checkout en Impultienda: evidencias que pegas tú (plan 19)")
