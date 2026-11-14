"""Subcomando `trovefy ver-anuncios`: ve los anuncios del original (ranking, /watch local y ficha propia)."""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from trovefy.cli import registrar

_RE_PID = re.compile(r"^p-\d{4}-[a-z0-9-]+$")
_RE_PAIS = re.compile(r"^[A-Z]{2}$")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("comprobar", help="comprueba ffmpeg, vendor/claude-video y WhisperX local")
    sub.add_parser("preparar", help="añade al cerebro los umbrales y la regla de la referencia")
    v = sub.add_parser("ver", help="lista, ordena y descarga a la caché los medios del top")
    v.add_argument("--producto", required=True, metavar="P", help="p-id del producto (productos/<P>/)")
    v.add_argument("--pais", metavar="XX", help="país a leer (por defecto el de la ficha con más C8)")
    v.add_argument("--page-id", metavar="ID", dest="page_id", help="página de la oferta (por defecto original_page_id de la ficha; si no, la primera de page_ids)")
    v.add_argument("--top", type=int, metavar="N", help="cuántos ganadores ver (por defecto el umbral)")
    v.add_argument("--desde-mcp", metavar="ARCHIVO", dest="desde_mcp",
                   help="lote del MCP (~/.cache/trovefy/referencia/<P>/mcp/…) para el listado")
    v.add_argument("--sin-navegador", action="store_true", dest="sin_navegador",
                   help="no abre la Biblioteca pública: sin medios")
    a = sub.add_parser("anotar", help="guarda el análisis propio de Claude (con guarda anti-copia)")
    a.add_argument("--producto", required=True, metavar="P")
    a.add_argument("--desde", required=True, metavar="ARCHIVO.json", help="data/referencia/analisis-*.json")
    sub.add_parser("limpiar", help="borra de la caché lo que pasó la retención")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _ahora() -> datetime:
    from trovefy.vault.escritura import ZONA_NEGOCIO

    return datetime.now(ZONA_NEGOCIO)


def _comprobar() -> int:
    from trovefy.referencia.watch import comprobar_entorno, pasos_instalacion

    e = comprobar_entorno()
    print(f"ffmpeg: {e.ffmpeg or 'falta'}")
    print(f"ffprobe: {e.ffprobe or 'falta'}")
    print(f"vendor/claude-video: {'ok' if e.vendor_ok else 'no cuadra con su MANIFEST'}")
    print(f"WhisperX local: {'listo' if e.whisperx else 'no listo'} ({e.whisperx_detalle})")
    pasos = pasos_instalacion(e)
    if pasos:
        print("Pasos para completar el entorno:")
        for s in pasos:
            print(f"- {s}")
    else:
        print("Entorno completo.")
    return 0


def _resumen(r) -> None:
    ref = r.ref
    gan = [f for f in ref.fichas if f.estado == "ganador"]
    nm = [f for f in ref.fichas if f.estado == "no_medido"]
    print(f"Referencia de {ref.producto} · {ref.pais} · {ref.fecha}")
    print(f"- listado: {ref.via} ({'completo' if ref.completo else 'muestra'}); medios: {ref.via_medios or 'sin medios'}")
    en_top = sum(1 for f in gan if f.puesto is not None)
    print(f"- leídos {len(ref.fichas)}: {len(gan)} ganadores ({en_top} en el top), "
          f"{sum(1 for f in ref.fichas if f.estado == 'en_test')} en test, {len(nm)} no medidos")
    for m in ref.motivos:
        print(f"- {m}")
    print("- búsquedas usadas hoy: " + (str(r.busquedas_hoy) if r.busquedas_hoy is not None else "no medido"))
    for a in r.avisos:
        print(f"Aviso: {a}")
    if r.trabajo:
        print("Lista de trabajo (lee estos archivos y escribe tu análisis):")
        for t in r.trabajo:
            print(f"* anuncio {t['library_id']} (puesto {t['puesto']}, {t['formato'] or 'formato no medido'})")
            for f in t["fotogramas"]:
                print(f"    fotograma: {f}")
            if t["transcripcion"]:
                print(f"    transcripción: {t['transcripcion']}")
            if t["imagen"]:
                print(f"    imagen: {t['imagen']}")
            if t["motivo"]:
                print(f"    {t['motivo']}")
    print("Siguiente paso: `trovefy ver-anuncios anotar --producto "
          f"{ref.producto} --desde data/referencia/analisis-<fecha>.json`")


def _validar_producto(producto: str) -> str | None:
    return None if _RE_PID.fullmatch(producto or "") else f"producto inválido: {producto!r} (p. ej. p-0001-nombre)"


def _ver(args: argparse.Namespace) -> int:
    from trovefy.caza.mcp import LoteInvalido
    from trovefy.config.umbrales import UmbralFaltante
    from trovefy.referencia import orquestador
    from trovefy.vault.rutas import vault_root

    if msg := _validar_producto(args.producto):
        return _error(msg)
    if args.pais is not None:
        args.pais = args.pais.strip().upper()
        if not _RE_PAIS.fullmatch(args.pais):
            return _error(f"país inválido: {args.pais!r} (dos letras, p. ej. MX)")
    if args.top is not None and args.top < 1:
        return _error("--top debe ser al menos 1")
    vault = vault_root()
    try:
        obj = orquestador.resolver_objetivo(vault, args.producto, args.pais, args.page_id)
        r = orquestador.ver(
            vault, obj, top=args.top, lote=Path(args.desde_mcp) if args.desde_mcp else None,
            sin_navegador=args.sin_navegador, ahora=_ahora(),
        )  # fmt: skip
    except (FileNotFoundError, ValueError, LoteInvalido, UmbralFaltante) as e:
        return _error(str(e.args[0]) if isinstance(e, UmbralFaltante) and e.args else str(e))
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"no se pudo leer la referencia ({type(e).__name__})", 3)
    _resumen(r)
    if r.tipo_parada == "meta":
        print(f"PARADA: {r.parada}. No se reintenta; vuelve mañana o usa --desde-mcp.", file=sys.stderr)
        return 1
    if r.tipo_parada == "errores":
        print(f"INTERRUMPIDA: {r.parada}.", file=sys.stderr)
        return 3
    return 0


def _anotar(args: argparse.Namespace) -> int:
    from trovefy.referencia.analisis import AnalisisInvalido, anotar
    from trovefy.vault.rutas import vault_root

    if msg := _validar_producto(args.producto):
        return _error(msg)
    try:
        ids = anotar(vault_root(), args.producto, Path(args.desde), _ahora())
    except AnalisisInvalido as e:
        print("Análisis no válido:", file=sys.stderr)
        for pr in e.problemas:
            print(f"- {pr}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as e:
        return _error(str(e))
    print(f"Análisis guardado para {len(ids)} anuncios: {', '.join(ids)}")
    return 0


def _preparar() -> int:
    from trovefy.referencia.config import preparar_vault
    from trovefy.vault.rutas import vault_root

    try:
        lineas = preparar_vault(vault_root())
    except (OSError, ValueError, KeyError) as e:
        return _error(f"no se pudo preparar el cerebro ({type(e).__name__}: {e})")
    print("\n".join(lineas) if lineas else "El cerebro ya estaba preparado.")
    return 0


def _limpiar() -> int:
    from trovefy.referencia import cache
    from trovefy.vault.escritura import anadir_log
    from trovefy.vault.rutas import vault_root

    ahora = _ahora()
    try:
        avisos = cache.avisos_limpieza(ahora)
        borradas = cache.limpiar(ahora)
    except OSError as e:
        return _error(f"no se pudo limpiar la caché ({type(e).__name__})")
    for b in borradas:
        print(f"borrado: {b}")
    for a in avisos:
        print(f"Aviso: {a}")
    if not borradas:
        print("Nada que borrar.")
    else:
        anadir_log(vault_root(), "ver-anuncios", f"limpiar caché ({len(borradas)} carpetas)", [], ahora=ahora)
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    try:
        return {
            "comprobar": lambda: _comprobar(),
            "preparar": lambda: _preparar(),
            "ver": lambda: _ver(args),
            "anotar": lambda: _anotar(args),
            "limpiar": lambda: _limpiar(),
        }[args.accion]()
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - sin traceback ante el usuario
        return _error(f"{type(e).__name__}", 3)


registrar("ver-anuncios", _configurar, _ejecutar,
          ayuda="ve los anuncios del original: ranking, /watch local y ficha propia")
