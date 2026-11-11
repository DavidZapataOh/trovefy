"""Subcomando `trovify caza`: ejecutar una caza y medir el hueco por país."""

import argparse
import re
import sys
from pathlib import Path

import yaml

from trovify.cli import registrar

_PAIS = re.compile(r"^(ALL|[A-Z]{2}):(.+)$")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    e = sub.add_parser("ejecutar", help="caza en la Biblioteca de anuncios y escribe informe y fichas")
    e.add_argument("--modo", required=True, choices=["nicho", "barrido", "vigilar", "oferta"])
    e.add_argument("--region", required=True, help="región de config/caza.yaml (eeuu_gb, br, latam_es, europa)")
    e.add_argument("--consulta", action="append", default=[], metavar="PAIS:FRASE",
                   help="búsqueda por palabra, por ejemplo RO:fise de lucru (se repite)")
    e.add_argument("--page-id", action="append", default=[], dest="page_ids", metavar="ID",
                   help="página de la Biblioteca a medir (modo oferta; se repite)")
    e.add_argument("--pais", action="append", default=[], metavar="XX",
                   help="países donde medir las páginas (por defecto ALL en oferta; las de la ficha en vigilar)")
    e.add_argument("--perfil", help="perfil de umbral (por defecto el de config/caza.yaml)")
    e.add_argument("--max", type=int, dest="max_nuevas", help="ofertas nuevas por ejecución (tope R14)")
    e.add_argument("--rutina", action="store_true",
                   help="deja el resumen en rutinas/log/<día>/caza.md y el archivo ok si no hubo parada")
    h = sub.add_parser("hueco", help="mide el hueco de una oferta en un país y recalcula la decisión")
    h.add_argument("--oferta", required=True, metavar="ID")
    h.add_argument("--pais", required=True, metavar="XX")
    h.add_argument("--frase", action="append", required=True, metavar="FRASE",
                   help="frase corta en el idioma local (se repite; hacen falta al menos dos)")
    h.add_argument("--idioma", help="idioma local si el país no está en config/mercados.yaml")
    h.add_argument("--perfil", help="perfil de umbral (por defecto el de config/caza.yaml)")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _config(vault: Path) -> dict:
    ruta = vault / "config/caza.yaml"
    if not ruta.exists():
        from trovify.vault.andamio import PLANTILLA
        from trovify.vault.escritura import escribir_atomico

        escribir_atomico(ruta, (PLANTILLA / "config/caza.yaml").read_text(encoding="utf-8"))
        print("Aviso: no había config/caza.yaml; se creó desde la plantilla.", file=sys.stderr)
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    if not isinstance(datos, dict):
        raise ValueError("config/caza.yaml no es un mapa")  # noqa: TRY004 - error de configuración para el usuario
    return datos


def _rutina(config: dict) -> tuple[int, int]:
    """Cuotas de la rutina (ronda 1, I3): ``rutina.max_busquedas`` y ``rutina.max_vigiladas_por_dia``."""
    r = config.get("rutina")
    try:
        return int(r["max_busquedas"]), int(r["max_vigiladas_por_dia"])
    except (TypeError, KeyError, ValueError):
        raise ValueError("falta la sección rutina (max_busquedas, max_vigiladas_por_dia) en config/caza.yaml; "
                         "cópiala de la plantilla del cerebro") from None


def _consultas(valores: list[str]) -> list[tuple[str, str]]:
    out = []
    for v in valores:
        m = _PAIS.match(v.strip())
        if not m or not m.group(2).strip():
            raise ValueError(f"consulta mal formada: «{v}»; usa PAIS:FRASE (por ejemplo RO:fise de lucru)")
        out.append((m.group(1), m.group(2).strip()))
    return out


def _ejecutar_caza(args: argparse.Namespace) -> int:
    from trovify.caza import orquestador
    from trovify.caza.presupuesto import Presupuesto
    from trovify.config.umbrales import cargar
    from trovify.vault.rutas import vault_root

    vault = vault_root()
    try:
        config = _config(vault)
        regiones = config.get("regiones") or {}
        if args.region not in regiones:
            return _error(f"región desconocida: «{args.region}»; las de config/caza.yaml son "
                          f"{', '.join(sorted(regiones)) or 'ninguna'}")
        consultas = _consultas(args.consulta)
        u = cargar(vault / "config/umbrales.yaml")
        tope = int(u["caza.max_nuevas_por_ejecucion"].valor)
        max_nuevas = tope if args.max_nuevas is None else args.max_nuevas
        if max_nuevas > tope:
            print(f"Aviso: --max {max_nuevas} supera el tope de R14; se usan {tope}.", file=sys.stderr)
            max_nuevas = tope
        perfil = args.perfil or config.get("perfil") or "tomi"
        cuota_rutina, max_vigiladas = _rutina(config)
        dia = orquestador.hoy_negocio()
        e = orquestador.ejecutar(vault, args.modo, consultas, perfil, max_nuevas, page_ids=args.page_ids or None,
                                 hoy=dia, region=args.region, paises=args.pais or None,
                                 max_vigiladas=max_vigiladas,
                                 max_busquedas_rutina=cuota_rutina if args.rutina else None)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return _error(str(exc))
    usadas = None
    try:
        p = Presupuesto.desde_umbrales(vault, e.dia)
        usadas = (p.usadas_hoy(), p.max_busquedas)
    except Exception:  # noqa: BLE001 - el contador solo informa; si falla, no se muestra
        usadas = None
    texto = orquestador.resumen(e, u["caza.palabra.min_resultados"].valor, usadas)
    print(texto)
    if args.rutina:
        from trovify import rutinas

        rutinas.registrar_ejecucion(vault, "caza", e.dia, texto, ok=e.parada is None)
    return 0 if e.parada is None else 1


def _ejecutar_hueco(args: argparse.Namespace) -> int:
    from trovify.caza import orquestador
    from trovify.caza.salida import formatear_medida
    from trovify.vault.rutas import vault_root

    vault = vault_root()
    if len(args.frase) < 2:
        print("Aviso: con una sola frase el «sin competencia» no se puede confirmar (hacen falta dos).",
              file=sys.stderr)
    try:
        h, parada = orquestador.medir_hueco(vault, args.oferta, args.pais.upper(), args.frase,
                                            idioma=args.idioma, perfil=args.perfil)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return _error(str(exc))
    texto = {True: "sí", False: "no", None: "no comprobado"}[h.hueco]
    print(f"Hueco de {args.oferta} en {h.pais}: {texto}")
    print(f"Competencia local: {formatear_medida(h.competencia)} · original: {h.original}")
    if h.motivo:
        print(f"Por qué: {h.motivo}")
    for enlace in h.enlaces:
        print(f"- {enlace}")
    print(f"Ficha actualizada: wiki/ofertas/{args.oferta}.md")
    if parada:
        print(f"PARADA: {parada}. No se buscó nada más; lo que faltaba quedó «no medido». "
              "No lances más búsquedas hoy.")
        return 1
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    if args.accion == "ejecutar":
        return _ejecutar_caza(args)
    return _ejecutar_hueco(args)


registrar("caza", _configurar, _ejecutar)
