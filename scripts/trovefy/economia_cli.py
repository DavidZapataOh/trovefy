"""Subcomando `trovefy economia`: comisiones, take rates y reglas de la economía del embudo."""

import argparse
import re
import sys
from datetime import date

from trovefy.cli import registrar


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    sub.add_parser("iniciar", help="crea config/economia.yaml desde la plantilla (nunca sobrescribe)")
    f = sub.add_parser("fijar", help="cambia el valor de una clave, con su fuente y la fecha de hoy")
    f.add_argument("--clave", required=True, metavar="K", help="clave con puntos, p. ej. plataformas.whop.comision_pct")
    f.add_argument("--valor", required=True, metavar="V", help="el valor nuevo; «null» vuelve a no medido")
    f.add_argument("--fuente", required=True, metavar="F", help="de dónde sale (URL de la página oficial, etc.)")
    sub.add_parser("ver", help="muestra cada valor con su fuente y su fecha")


def _error(msg: str, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _hoy() -> date:
    from trovefy.caza.orquestador import hoy_negocio

    return hoy_negocio()


def _iniciar() -> int:
    from trovefy.economia.config import RELATIVA, iniciar_economia
    from trovefy.vault.rutas import vault_root

    try:
        iniciar_economia(vault_root())
    except FileExistsError:
        print(f"{RELATIVA.as_posix()} ya existe: no se toca. Cambia valores con `trovefy economia fijar`.")
        return 0
    print(f"Creado {RELATIVA.as_posix()}. Las comisiones salen «no medido» hasta que las fijes con su fuente.")
    return 0


_URL = re.compile(r"^https?://\S", re.IGNORECASE)


def _fijar(args: argparse.Namespace) -> int:
    from trovefy.config.yaml_config import cargar_yaml
    from trovefy.economia.config import RELATIVA, fijar
    from trovefy.vault.rutas import vault_root

    if not args.valor.strip():
        raise ValueError(f"{args.clave}: el valor está en blanco; usa `null` para no medido")
    valor = None if args.valor.strip().lower() in ("null", "~") else args.valor
    if args.clave.startswith("plataformas.") and valor is not None and not _URL.match(args.fuente.strip()):
        raise ValueError(f"{args.clave}: la fuente de una plataforma es la URL de su página oficial "
                         "(empieza por http:// o https://)")
    vault = vault_root()
    hoy = _hoy()
    try:
        fijar(vault, args.clave, valor, args.fuente, hoy)
    except KeyError as e:  # la clave no es una hoja de config/economia.yaml
        raise ValueError(str(e.args[0]) if e.args else "clave desconocida") from None
    nodo = cargar_yaml((vault / RELATIVA).read_text(encoding="utf-8"))
    for parte in args.clave.split("."):
        nodo = nodo[parte]
    print(f"{args.clave} = {_valor(nodo['valor'])} (fuente: {nodo['fuente']}; fecha: {nodo['fecha']})")
    return 0


def _valor(v: object) -> str:
    if v is None:
        return "no medido"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, list):
        return "[" + ", ".join(_valor(x) for x in v) + "]"
    return str(v).replace(".", ",") if isinstance(v, (int, float)) else str(v)


def _hojas(nodo: object, clave: str):
    from trovefy.economia.config import CAMPOS_HOJA

    if isinstance(nodo, dict) and set(nodo) == set(CAMPOS_HOJA):
        yield clave, nodo
    elif isinstance(nodo, dict):
        for k, v in nodo.items():
            yield from _hojas(v, f"{clave}.{k}" if clave else str(k))


def _ver() -> int:
    from trovefy.config.yaml_config import cargar_yaml
    from trovefy.economia.config import RELATIVA, cargar_economia
    from trovefy.vault.rutas import vault_root

    vault = vault_root()
    cargar_economia(vault)  # valida antes de enseñar
    datos = cargar_yaml((vault / RELATIVA).read_text(encoding="utf-8"))
    print(f"{RELATIVA.as_posix()} (valor · fuente · fecha):")
    for clave, hoja in _hojas(datos, ""):
        print(f"{clave}: {_valor(hoja['valor'])} · {hoja['fuente']} · {hoja['fecha']}")
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    from trovefy.secretos import RevisionSecretosNoDisponible

    try:
        return {"iniciar": _iniciar, "fijar": lambda: _fijar(args), "ver": _ver}[args.accion]()
    except RevisionSecretosNoDisponible as e:
        return _error(str(e))
    except (ValueError, FileNotFoundError) as e:  # EconomiaInvalida es un ValueError
        return _error(str(e))
    except KeyboardInterrupt:
        print("INTERRUMPIDA: cancelado por el usuario (Ctrl-C).", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - la CLI nunca muestra un traceback
        return _error(f"fallo inesperado ({type(e).__name__})", 3)


registrar("economia", _configurar, _ejecutar, ayuda="comisiones, take rates y reglas de la economía del embudo")
