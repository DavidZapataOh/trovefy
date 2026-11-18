"""Subcomando `trovefy tracking` (plan 19, Tareas 7 y 9): dataset guiado, píxel visto desde fuera, CAPI y límites del
ejecutor.

trovefy nunca entra en un panel (resolución 38) ni escribe en Meta: el usuario crea el dataset y pega el Pixel ID y
el token CAPI en su panel (R-d); Claude lee Meta por su MCP de solo lectura y guarda la respuesta cruda en
``~/.cache/trovefy/checkout/…``; esta CLI la interpreta y escribe solo valores normalizados en el vault.

Códigos de salida: 0 bien · 1 «no medido» o un problema · 2 error de uso o de entrada. Nunca una traza.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from trovefy.cli import registrar
from trovefy.tracking.publico import leer_pixel_publico
from trovefy.vault.escritura import ZONA_NEGOCIO

_abrir = None  # punto de inyección de los tests (urllib falso); None → el GET seguro de la landing
_PREFIJO_PIXEL = "píxel: "


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _inyectado(nombre: str):
    """El punto de inyección vigente: el del módulo que está en ``sys.modules`` (un test de registro de la CLI
    reimporta los ``*_cli`` y el registro puede quedarse con funciones de la copia anterior)."""
    return getattr(sys.modules.get(__name__), nombre, globals()[nombre])


def _reloj() -> datetime:
    return _inyectado("_ahora")()


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG, RO…)")


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", metavar="<acción>", required=True)
    _comunes(sub.add_parser("preparar", help="nombre exacto del dataset y los pasos que haces tú (Meta y tu panel)"))
    d = sub.add_parser("dataset", help="busca el dataset por su nombre en la respuesta de ads_get_datasets")
    _comunes(d)
    d.add_argument("--instantanea", required=True, help="JSON con la respuesta de ads_get_datasets (MCP de Meta)")
    t = sub.add_parser("tienda", help="mira el píxel en la tienda, la landing y el checkout públicos (sin JS)")
    _comunes(t)
    t.add_argument("--instantanea-mcp", default=None,
                   help="JSON con la respuesta de impultienda_estado_onboarding (lectura) para cruzar el Pixel ID")
    c = sub.add_parser("capi", help="registra tus palabras: ya pegaste el token CAPI en tu panel")
    _comunes(c)
    c.add_argument("--dicho", required=True, help="tus palabras literales, entre comillas (nunca el token)")
    sub.add_parser("utm", help="la plantilla de parámetros UTM para cada anuncio")
    from trovefy.tracking import ejecutor

    ejecutor.configurar(sub.add_parser("ejecutor", help="dataset y página en los límites del ejecutor: los comandos "
                                                        "que ejecutas tú y lo que dejó el ejecutor (Tarea 9)"))


def _leer_json(ruta: str) -> object:
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"no existe {ruta}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{ruta} no es JSON válido ({type(exc).__name__})") from None


def _contexto(args: argparse.Namespace):
    from trovefy.embudo.contexto import cargar_contexto
    from trovefy.vault.rutas import vault_root

    return cargar_contexto(vault_root(), args.producto, args.pais.strip().upper())


def _tracking(ctx):
    from trovefy.tracking.salida import leer_tracking

    t = leer_tracking(ctx.vault, ctx.producto, ctx.pais)
    if t is None:
        raise ValueError(f"no hay TRACKING.md: trovefy tracking preparar --producto {ctx.producto} --pais {ctx.pais}")
    return t


def _guardar(ctx, t) -> None:
    from trovefy.tracking.salida import escribir_tracking

    escribir_tracking(ctx.vault, t, _reloj())


def _receta(ctx, nombre: str, dataset_id: str | None) -> str:
    from trovefy.embudo.receta_texto import imprimir_receta
    from trovefy.tienda.mcp import cargar_catalogo
    from trovefy.tracking.dataset import receta_tracking

    pasos = receta_tracking(ctx, nombre, dataset_id, cargar_catalogo())
    return imprimir_receta(f"Tracking de {ctx.producto} en {ctx.pais}: lo haces tú", pasos)


def _preparar(args: argparse.Namespace) -> int:
    from trovefy.embudo.contexto import exigir_estado
    from trovefy.tracking.modelo import Tracking, emisores_por_defecto, nombre_dataset
    from trovefy.tracking.salida import leer_tracking

    ctx = _contexto(args)
    exigir_estado(ctx, ("con_landing", "producido"))
    nombre = nombre_dataset(ctx.marca, ctx.producto, ctx.pais)
    t = leer_tracking(ctx.vault, ctx.producto, ctx.pais)
    if t is None:
        motivos = []
        hosting = ctx.landing_hosting
        if hosting is None:
            hosting = "impultienda"
            motivos.append("no medido: hosting de la landing; se supone Impultienda (la landing va por el MCP)")
        t = Tracking(producto=ctx.producto, pais=ctx.pais, dataset_nombre=nombre, dataset_id=None,
                     emisores=emisores_por_defecto(ctx.ruta, hosting), pixel_publico=None, pixel_config=None,
                     capi=None, eventos=None, fuente_eventos=None, estado="pendiente", motivos=motivos)
        _guardar(ctx, t)
    print(f"Nombre exacto del dataset: {t.dataset_nombre}")
    print(_receta(ctx, t.dataset_nombre, t.dataset_id))
    return 0


def _dataset(args: argparse.Namespace) -> int:
    from trovefy.tracking.dataset import buscar_dataset
    from trovefy.tracking.salida import _DATASET_ID

    ctx = _contexto(args)
    t = _tracking(ctx)
    ident, motivo = buscar_dataset(_leer_json(args.instantanea), t.dataset_nombre)
    if ident is not None and not _DATASET_ID.fullmatch(ident):
        ident, motivo = None, f"no medido: el id {ident} no tiene 15 a 17 dígitos (¿es un píxel de Meta?)"
    if ident is None:
        print(motivo)
        return 1
    if ident != t.dataset_id:
        t = replace(t, dataset_id=ident, estado="dataset", pixel_publico=None, pixel_config=None)
        _guardar(ctx, t)
    print(f"Dataset «{t.dataset_nombre}»: {ident} (estado {t.estado})")
    print(_receta(ctx, t.dataset_nombre, ident))
    return 0


def _tienda(args: argparse.Namespace) -> int:
    from trovefy.landing.publicar import _abrir_seguro
    from trovefy.tracking.dataset import pixel_en_lectura_mcp

    ctx = _contexto(args)
    t = _tracking(ctx)
    if t.dataset_id is None:
        raise ValueError("aún no hay dataset_id: trovefy tracking dataset primero")
    mcp = pixel_en_lectura_mcp(_leer_json(args.instantanea_mcp), t.dataset_id) if args.instantanea_mcp else None
    estado, _ids, motivo = leer_pixel_publico(ctx, t.dataset_id, abrir=_inyectado("_abrir") or _abrir_seguro)
    problemas: list[str] = []
    if estado == "otro":
        problemas.append(motivo)
    if mcp is False:
        problemas.append(f"la lectura del MCP de Impultienda no muestra el píxel {t.dataset_id}: pégalo en «Meta / "
                         "Tracking» de tu panel")
    nuevo = t.estado
    if problemas:
        nuevo = "dataset" if t.estado in ("configurado", "verificado", "no_verificado") else t.estado
        lineas = problemas
    elif estado == "ok" or mcp is True:
        nuevo = "configurado" if t.estado in ("pendiente", "dataset", "configurado") else t.estado
        lineas = [f"píxel {t.dataset_id} " + ("visto en la tienda pública" if estado == "ok" else
                                               "confirmado por el MCP de Impultienda") + f": estado {nuevo}"]
        if motivo:
            lineas.append(motivo)
    else:
        lineas = [motivo if motivo and motivo.startswith("no medido") else f"no medido: {motivo}"]
        if args.instantanea_mcp is None:
            lineas.append("Pide a Claude la lectura de impultienda_estado_onboarding y pásala con --instantanea-mcp")
    motivos = [m for m in t.motivos if not m.startswith(_PREFIJO_PIXEL)]
    motivos += [_PREFIJO_PIXEL + x for x in (problemas or ([] if nuevo == "configurado" else lineas[:1]))]
    t = replace(t, estado=nuevo, pixel_publico=estado, motivos=motivos,
                pixel_config="mcp" if mcp is True else t.pixel_config)
    _guardar(ctx, t)
    print("\n".join(lineas))
    return 0 if not problemas and (estado == "ok" or mcp is True) else 1


def _capi(args: argparse.Namespace) -> int:
    from trovefy.embudo.pegado import dicho

    ctx = _contexto(args)
    t = _tracking(ctx)
    p = dicho(ctx.vault, ctx, "tracking-pixel", args.dicho, _reloj())
    t = replace(t, capi=t.capi if t.capi == "visto_en_meta" else "dicho", evidencia=[*t.evidencia, p.ruta])
    _guardar(ctx, t)
    print(f"CAPI: «dicho» por ti ({p.ruta}). Se da por visto solo cuando Meta reciba eventos del servidor "
          "(trovefy tracking eventos).")
    return 0


def _utm(_args: argparse.Namespace) -> int:
    from trovefy.tracking.modelo import PLANTILLA_UTM

    print(PLANTILLA_UTM)
    return 0


def _ejecutor(args: argparse.Namespace) -> int:
    from trovefy.tracking import ejecutor

    return ejecutor.ejecutar(args)


_ACCIONES = {"preparar": _preparar, "dataset": _dataset, "tienda": _tienda, "capi": _capi, "utm": _utm, "ejecutor": _ejecutor}


def _ejecutar(args: argparse.Namespace) -> int:
    try:
        return _ACCIONES[args.accion](args)
    except (ValueError, OSError) as exc:  # EstadoInesperado, CatalogoInvalido y secretos son ValueError
        return _error(exc)


registrar("tracking", _configurar, _ejecutar, "dataset, píxel, CAPI y eventos del producto-país (plan 19)")
