"""Subcomando `trovefy tracking` (plan 19, Tareas 7–9): dataset guiado, píxel visto desde fuera, CAPI, Test Events y
límites del ejecutor.

trovefy nunca entra en un panel (resolución 38) ni escribe en Meta: el usuario crea el dataset y pega el Pixel ID y
el token CAPI en su panel (R-d); Claude lee Meta por su MCP de solo lectura y guarda la respuesta cruda en
``~/.cache/trovefy/checkout/…``; esta CLI la interpreta y escribe solo valores normalizados en el vault.

Códigos de salida: 0 bien · 1 «no medido» o un problema · 2 error de uso o de entrada. Nunca una traza.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trovefy.cli import registrar
from trovefy.tracking.publico import leer_pixel_publico
from trovefy.vault.escritura import ZONA_NEGOCIO

_abrir = None  # punto de inyección de los tests (urllib falso); None → el GET seguro de la landing
_esperar = None  # punto de inyección de los tests; None → 5–8 s entre GETs al mismo dominio (contrato 8)
_PREFIJO_PIXEL = "píxel: "
_PREFIJO_EVENTOS = "eventos: "
_MAX_PEDIDOS = 5
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DESFASE = timedelta(minutes=5)


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
    t.add_argument("--tienda-id", default=None,
                   help="con --instantanea-mcp: el id (uuid) de la tienda de este país (impultienda_listar_tiendas)")
    c = sub.add_parser("capi", help="registra tus palabras: ya pegaste el token CAPI en tu panel")
    _comunes(c)
    c.add_argument("--dicho", required=True, help="tus palabras literales, entre comillas (nunca el token)")
    e = sub.add_parser("eventos", help="Test Events: los cuatro eventos y Purchase una sola vez (MCP de Meta)")
    _comunes(e)
    e.add_argument("--antes", help="JSON de ads_get_dataset_stats antes de la prueba")
    e.add_argument("--despues", help="JSON de ads_get_dataset_stats después de la prueba")
    e.add_argument("--detalles", help="JSON de ads_get_dataset_details del dataset (¿llega la CAPI después de «antes»?)")
    e.add_argument("--antes-hora", help="hora ISO 8601 con zona de la lectura «antes» (por defecto, la del archivo de "
                                        "--antes); obligatoria con --manual")
    e.add_argument("--manual", help="respaldo: PageView=N,ViewContent=N,InitiateCheckout=N,Purchase=N leídos en tu "
                                    "captura de «Probar eventos»")
    e.add_argument("--captura", help="con --manual: la clave de la captura registrada (test-events)")
    e.add_argument("--pedidos", type=int, default=1,
                   help=f"pedidos de prueba hechos entre «antes» y «después» (1 a {_MAX_PEDIDOS})")
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
    from trovefy.tracking.dataset import pixel_en_lectura_mcp, pixeles_de_tienda

    if args.instantanea_mcp is not None and (args.tienda_id is None or not _UUID.fullmatch(args.tienda_id)):
        raise ValueError("--instantanea-mcp va con --tienda-id <uuid de la tienda de este país> (los píxeles de "
                         "otras tiendas de la cuenta no cuentan)")
    ctx = _contexto(args)
    t = _tracking(ctx)
    if t.dataset_id is None:
        raise ValueError("aún no hay dataset_id: trovefy tracking dataset primero")
    mcp = None
    ajenos_mcp: list[str] = []
    if args.instantanea_mcp:
        leido = _leer_json(args.instantanea_mcp)
        mcp = pixel_en_lectura_mcp(leido, t.dataset_id, args.tienda_id)
        ajenos_mcp = sorted((pixeles_de_tienda(leido, args.tienda_id) or set()) - {t.dataset_id})
    estado, _ids, motivo = leer_pixel_publico(ctx, t.dataset_id, abrir=_inyectado("_abrir") or _abrir_seguro,
                                              esperar=_inyectado("_esperar"))
    problemas: list[str] = []
    if estado == "otro":
        problemas.append(motivo)
    if mcp is False and ajenos_mcp:
        problemas.append(f"según el MCP de Impultienda tu tienda carga otro píxel ({', '.join(ajenos_mcp)}): quítalo "
                         f"en «Meta / Tracking» de tu panel y deja solo el {t.dataset_id}")
    elif mcp is False:
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


def _manual(texto: str) -> dict[str, int]:
    from trovefy.tracking.modelo import EVENTOS

    conteo: dict[str, int] = {}
    for par in texto.split(","):
        nombre, igual, valor = par.strip().partition("=")
        if not igual or nombre not in EVENTOS or nombre in conteo or not valor.strip().isdigit():
            raise ValueError(f"--manual «{texto}»: escribe {','.join(e + '=N' for e in EVENTOS)}")
        conteo[nombre] = int(valor)
    if set(conteo) != set(EVENTOS):
        raise ValueError(f"--manual: faltan {', '.join(e for e in EVENTOS if e not in conteo)}")
    return conteo


def _captura_test_events(ctx, clave: str | None, desde: datetime) -> str:
    """La captura de «Probar eventos» registrada después de la lectura «antes» (una vieja no prueba esta compra)."""
    from trovefy.embudo.pegado import indice
    from trovefy.tracking.eventos import hora

    if clave != "test-events":
        raise ValueError("--manual va con --captura test-events: registra antes tu captura de «Probar eventos» con "
                         "trovefy checkout evidencia --clave test-events --desde <captura>")
    capturas = [p for p in indice(ctx.vault, ctx).get(clave, []) if p.tipo == "captura"]
    if not capturas:
        raise ValueError("no hay captura de «Probar eventos» registrada: trovefy checkout evidencia --clave "
                         "test-events --desde <captura>")
    nuevas = [p for p in capturas if (h := hora(p.fecha)) is not None and h > desde]
    if not nuevas:
        raise ValueError(f"la última captura de «Probar eventos» es de antes de la lectura «antes» ({desde.isoformat()}"
                         "): haz la prueba, captura «Probar eventos» y regístrala de nuevo")
    return nuevas[-1].ruta


def _antes_hora(args: argparse.Namespace) -> datetime:
    """La hora de la lectura «antes»: ``--antes-hora`` o, con ``--antes``, la del archivo que guardó Claude."""
    from trovefy.tracking.eventos import hora

    if args.antes_hora is not None:
        h = hora(args.antes_hora)
        if h is None:
            raise ValueError(f"--antes-hora «{args.antes_hora}»: escribe una hora ISO 8601 con zona "
                             "(2026-11-17T11:30:00+00:00)")
    elif args.antes is not None:
        try:
            h = datetime.fromtimestamp(Path(args.antes).stat().st_mtime, UTC)
        except FileNotFoundError:
            raise ValueError(f"no existe {args.antes}") from None
    else:
        raise ValueError("--manual va con --antes-hora: la hora en que leíste los eventos antes de la prueba")
    if h > _reloj() + _DESFASE:
        raise ValueError(f"--antes-hora {h.isoformat()} es del futuro")
    return h


def _resumen_eventos(ctx, datos: dict) -> str:
    from trovefy.embudo.contexto import ruta_pais
    from trovefy.secretos import buscar_secreto
    from trovefy.vault.escritura import escribir_atomico

    ruta = ruta_pais(ctx) / "compra" / "events-manager.json"
    texto = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    patron = buscar_secreto(texto)
    if patron:
        raise ValueError(f"el resumen de eventos lleva algo con forma de secreto ({patron}): no lo guardo")
    escribir_atomico(ruta, texto)
    return ruta.relative_to(ruta_pais(ctx).parent.parent).as_posix()


def _eventos(args: argparse.Namespace) -> int:
    from trovefy.tracking.eventos import (
        capi_en_meta,
        cubos_de_eventos,
        diferencia,
        evaluar_eventos,
    )

    mcp = args.antes is not None or args.despues is not None
    if mcp and (args.manual is not None or args.captura is not None):
        raise ValueError("o --antes/--despues (MCP de Meta) o --manual con --captura, no las dos")
    if not mcp and args.manual is None:
        raise ValueError("falta la fuente: --antes y --despues (MCP de Meta) o --manual con --captura")
    if mcp and (args.antes is None or args.despues is None):
        raise ValueError("--antes y --despues van juntos (dos lecturas de ads_get_dataset_stats)")
    if isinstance(args.pedidos, bool) or not 1 <= args.pedidos <= _MAX_PEDIDOS:
        raise ValueError(f"--pedidos: de 1 a {_MAX_PEDIDOS} pedidos de prueba")
    desde = _antes_hora(args)
    ctx = _contexto(args)
    t = _tracking(ctx)
    if t.dataset_id is None:
        raise ValueError("aún no hay dataset_id: trovefy tracking dataset primero")
    evidencia = list(t.evidencia)
    if mcp:
        conteo = diferencia(cubos_de_eventos(_leer_json(args.antes)), cubos_de_eventos(_leer_json(args.despues)))
        fuente = "mcp"
    else:
        conteo = _manual(args.manual)
        evidencia.append(_captura_test_events(ctx, args.captura, desde))
        fuente = "captura"
    capi = capi_en_meta(_leer_json(args.detalles), t.dataset_id, desde) if args.detalles else None
    capi_vista = capi is True or (capi is None and t.capi == "visto_en_meta")
    veredicto, motivos = evaluar_eventos(conteo, args.pedidos, t.emisores)
    if capi is False:
        motivos.append("no verificado: Meta no ve eventos del servidor (API de conversiones) desde la lectura «antes»: "
                       "revisa el token en «Meta / Tracking» de tu panel")
    elif not capi_vista:
        motivos.append("no verificado: falta CAPI (pide a Claude ads_get_dataset_details del dataset y pásalo con "
                       "--detalles)")
    if conteo is None or veredicto == "no_medido":
        estado = t.estado
    elif veredicto == "no_verificado" or capi is False:
        estado = "no_verificado"
    elif capi_vista:
        estado = "verificado"
    else:
        estado = t.estado  # los eventos cuadran, pero sin la CAPI vista no hay verde (ruling)
    if conteo is not None:
        evidencia.append(_resumen_eventos(ctx, {
            "fuente": fuente, "fecha": _reloj().isoformat(timespec="seconds"), "antes": desde.isoformat(),
            "pedidos": args.pedidos, "conteo": conteo, "veredicto": veredicto, "capi": capi, "motivos": motivos}))
    t = replace(t, estado=estado, eventos=conteo if conteo is not None else t.eventos,
                fuente_eventos=fuente if conteo is not None else t.fuente_eventos,
                capi="visto_en_meta" if capi is True else t.capi,
                evidencia=list(dict.fromkeys(evidencia)),
                motivos=[m for m in t.motivos if not m.startswith(_PREFIJO_EVENTOS)]
                + [_PREFIJO_EVENTOS + m for m in motivos])
    _guardar(ctx, t)
    if conteo is not None:
        print("Eventos (" + fuente + "): " + ", ".join(f"{e}={n}" for e, n in conteo.items()))
    print("\n".join([f"Tracking: {estado}", *motivos]))
    return 0 if estado == "verificado" else 1


def _ejecutor(args: argparse.Namespace) -> int:
    from trovefy.tracking import ejecutor

    return ejecutor.ejecutar(args)


_ACCIONES = {"preparar": _preparar, "dataset": _dataset, "tienda": _tienda, "capi": _capi, "utm": _utm, "ejecutor": _ejecutor,
             "eventos": _eventos}


def _ejecutar(args: argparse.Namespace) -> int:
    try:
        return _ACCIONES[args.accion](args)
    except (ValueError, OSError) as exc:  # EstadoInesperado, CatalogoInvalido y secretos son ValueError
        return _error(exc)


registrar("tracking", _configurar, _ejecutar, "dataset, píxel, CAPI y eventos del producto-país (plan 19)")
