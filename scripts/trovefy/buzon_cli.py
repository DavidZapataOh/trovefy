"""Subcomando `trovefy buzon`: deposita propuestas para el ejecutor y muestra su estado."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from trovefy_ejecutor.esquema import PropuestaInvalida

from trovefy import buzon
from trovefy.cli import registrar

MAX_BYTES = 64 * 1024


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    d = sub.add_parser("depositar", help="deposita una propuesta en el buzón del ejecutor")
    d.add_argument("archivo", help="archivo JSON de la propuesta, o - para stdin")
    sub.add_parser("estado", help="muestra el estado del ejecutor")


def _depositar(args: argparse.Namespace) -> int:
    from trovefy.vault.rutas import vault_root

    try:
        if args.archivo == "-":
            crudo = sys.stdin.read(MAX_BYTES + 1)
        else:
            with open(args.archivo, encoding="utf-8") as f:
                crudo = f.read(MAX_BYTES + 1)
        if len(crudo) > MAX_BYTES:
            raise PropuestaInvalida("más de 64 KiB")
        try:
            datos = json.loads(crudo)
        except ValueError:
            raise PropuestaInvalida("no es JSON válido") from None
        ruta = buzon.depositar(datos, spool=buzon.raiz_spool(), vault=vault_root(),
                               ahora=datetime.now(UTC))
    except buzon.StopActivo as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except (PropuestaInvalida, buzon.CupoAgotado, buzon.IdDuplicado) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Error: no se pudo depositar ({type(exc).__name__}: {getattr(exc, 'strerror', None) or ''})",
              file=sys.stderr)
        return 1
    print(f"{ruta.stem} {ruta}")
    return 0


def _si_no(valor: object) -> str:
    return "sí" if valor is True else "no" if valor is False else "no medido"


def _estado(_args: argparse.Namespace) -> int:
    from trovefy.vault.rutas import vault_root

    ahora = datetime.now(UTC)
    e = buzon.estado(buzon.raiz_spool(), ahora)
    latido = e["latido"]
    if latido is None:
        print("Ejecutor: sin latido (ejecutor parado o WSL dormido)")
    elif e["latido_viejo"]:
        print(f"Ejecutor: latido viejo, último {latido.get('fecha')} (ejecutor parado o WSL dormido)")
    else:
        print(f"Ejecutor: activo, latido {latido.get('fecha')}, versión {latido.get('version')}, "
              f"modo {latido.get('modo')}")
    stop_vault = (Path(vault_root()) / ".trovefy" / "STOP").exists()
    stop = e["stop"]
    print(f"STOP: {'ACTIVO' if stop_vault or (stop and stop.get('activo') is True) else 'no'}"
          + (" (archivo del vault)" if stop_vault else ""))
    emp = e["emparejamiento"]
    print(f"Telegram emparejado: {_si_no(emp.get('emparejado') if emp else None)}")
    meta = e["meta"]
    if meta is None:
        print("Meta: no medido")
    else:
        vo = meta.get("validate_only") if isinstance(meta.get("validate_only"), dict) else {}
        print(f"Meta: moneda {meta.get('currency')}, estado de cuenta {meta.get('account_status')}, "
              f"validate_only {_si_no(vo.get('ok'))}, medido {meta.get('fecha')}")
    lim = e["limites"]
    if lim is None:
        print("Límites: no medido")
    else:
        for cid, c in sorted((lim.get("cuentas") or {}).items()) if isinstance(lim.get("cuentas"), dict) else []:
            if not isinstance(c, dict):
                continue
            print(f"Límites {cid}: {c.get('moneda')} tope diario {c.get('tope_gasto_diario_total')}, "
                  f"máx. conjunto {c.get('max_presupuesto_conjunto')} (unidades mínimas)")
    p = e["pendientes"]
    print(f"Propuestas pendientes en entrada: {p if p is not None else 'no medido'}")
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    return _depositar(args) if args.accion == "depositar" else _estado(args)


registrar("buzon", _configurar, _ejecutar, ayuda="deposita propuestas para el ejecutor y muestra su estado")
