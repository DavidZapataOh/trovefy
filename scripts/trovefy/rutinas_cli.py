"""Subcomando `trovefy rutinas`: instala, quita y mira las rutinas (timers de systemd de usuario, sin sudo)."""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

from trovefy import rutinas
from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO

FASE3 = ("vigia", "parte", "cierre", "cierre-noche", "intradia", "base", "renovacion")
_PAIS = re.compile(r"^[A-Z]{2}$")
_ESTADO_LOG = re.compile(r"^## .* · (.+?)\s*$", re.MULTILINE)
LINGER = ("Si WSL no mantiene vivos los servicios de usuario, ejecuta en una terminal de Ubuntu aparte: "
          "sudo loginctl enable-linger $USER")


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    i = sub.add_parser("instalar", help="instala el timer de una rutina (o «fase3»: las de la fase 3)")
    i.add_argument("rutina", help="caza, vigia, parte, cierre, cierre-noche, intradia, base, renovacion o fase3")
    i.add_argument("--pais", action="append", default=[], help="país de las rutinas por país (repetible)")
    d = sub.add_parser("desinstalar", help="quita el timer de una rutina (p. ej. cierre o intradia-bg)")
    d.add_argument("rutina")
    sub.add_parser("ver", help="rutinas instaladas, su próxima hora y el último estado de hoy")
    c = sub.add_parser("condicion", help="(lo usa systemd) 0 si toca lanzar la rutina, 1 si no")
    c.add_argument("rutina")
    c.add_argument("--pais")
    f = sub.add_parser("fin", help="(lo usa systemd) deja constancia y avisa si la rutina falló")
    f.add_argument("rutina")
    f.add_argument("--pais")


def _vault():
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _paises(vault, pedidos: list[str]) -> list[str]:
    if pedidos:
        return [p.strip().upper() for p in pedidos]
    return list(dict.fromkeys(p for _, p in rutinas.en_marcha(vault)))


def _instalar(args) -> int:
    vault = _vault()
    claude = rutinas.buscar_claude()
    if not claude:
        print("Error: no encuentro el comando claude en el PATH; instala Claude Code antes de la rutina.",
              file=sys.stderr)
        return 2
    if args.rutina == "caza":
        try:
            rutas = rutinas.instalar_caza(vault, claude)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Error: no se pudo instalar la rutina ({type(exc).__name__}). {LINGER}", file=sys.stderr)
            return 1
        for r in rutas:
            print(f"Escrito: {r}")
        print("Rutina de caza activa: de lunes a sábado a las 06:30 (hora de Colombia).")
        print("Compruébalo con: systemctl --user list-timers | grep trovefy-caza")
        return 0
    catalogo = rutinas.cargar_catalogo()
    paises = _paises(vault, args.pais)
    if any(not _PAIS.match(p) for p in paises):
        print("Error: --pais es un código de dos letras (BG, RO…)", file=sys.stderr)
        return 2
    if args.rutina == "fase3":
        nombres = []
        for n in FASE3:
            r = catalogo[n]
            if rutinas.allowed_de_skill(r.skill) is None:
                print(f"Aviso: la skill /{r.skill} aún no está: no se instala «{n}».")
                continue
            if r.por_pais and not paises:
                print(f"Aviso: «{n}» va por país y aún no hay ningún país montado o en test: se instala al montar "
                      "(vuelve a ejecutar `trovefy rutinas instalar fase3`).")
                continue
            nombres.append(n)
    elif args.rutina in catalogo:
        nombres = [args.rutina]
    else:
        print(f"Error: no conozco la rutina «{args.rutina}» (mira templates/systemd/rutinas.yaml)", file=sys.stderr)
        return 2
    try:
        rutas = rutinas.instalar(nombres, vault, claude, paises, catalogo=catalogo)
    except rutinas.RutinaInvalida as exc:
        print("No se instaló nada. Problemas:", file=sys.stderr)
        for p in str(exc).split("; "):
            print(f"  - {p}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: no se pudo instalar ({type(exc).__name__}). {LINGER}", file=sys.stderr)
        return 1
    for r in rutas:
        print(f"Escrito: {r}")
    for n in nombres:
        r = catalogo[n]
        print(f"Activa: {n}{' (' + ', '.join(paises) + ')' if r.por_pais else ''} · {r.calendario}")
    print("Compruébalo con: trovefy rutinas ver  (o systemctl --user list-timers | grep trovefy)")
    return 0


def _desinstalar(args) -> int:
    try:
        borradas = rutinas.desinstalar([args.rutina.strip().lower()])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: no se pudo quitar ({type(exc).__name__})", file=sys.stderr)
        return 1
    if not borradas:
        print(f"No estaba instalada: {args.rutina}")
        return 1
    for r in borradas:
        print(f"Quitado: {r}")
    return 0


def _ver(_args) -> int:
    vault, hoy = _vault(), datetime.now(ZONA_NEGOCIO).date()
    catalogo = rutinas.cargar_catalogo()
    insts = rutinas.instaladas()
    if not insts:
        print("No hay rutinas instaladas: `trovefy rutinas instalar fase3`.")
        return 0
    try:
        timers = subprocess.run(["systemctl", "--user", "list-timers", "--all", "--no-pager", "trovefy-*"],
                                capture_output=True, text=True, check=False, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        timers = ""
    for inst in insts:
        par = rutinas.rutina_de_instancia(inst, catalogo)
        log = rutinas.nombre_log(*par) if par else inst
        ruta = vault / "rutinas" / "log" / hoy.isoformat() / f"{log}.md"
        try:
            estados = _ESTADO_LOG.findall(ruta.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            estados = []
        proxima = next((ln.split("  ")[0] for ln in timers.splitlines() if f"trovefy-{inst}.timer" in ln), None)
        print(f"- {inst}: próxima {proxima or 'no medido (systemctl)'} · hoy {estados[-1] if estados else 'sin log'}")
    return 0


def _condicion(args) -> int:
    try:
        return rutinas.condicion(args.rutina, _vault(), (args.pais or "").upper() or None)
    except KeyError:
        print(f"Error: rutina desconocida {args.rutina}", file=sys.stderr)
        return 2


def _fin(args) -> int:
    try:
        linea = rutinas.fin(args.rutina, _vault(), os.environ.get("SERVICE_RESULT", ""),
                            os.environ.get("EXIT_STATUS") or os.environ.get("EXIT_CODE", ""),
                            pais=(args.pais or "").upper() or None)
    except KeyError:
        print(f"Error: rutina desconocida {args.rutina}", file=sys.stderr)
        return 2
    if linea:
        print(linea)
    return 0


_ACCIONES = {"instalar": _instalar, "desinstalar": _desinstalar, "ver": _ver, "condicion": _condicion, "fin": _fin}


def _ejecutar(args: argparse.Namespace) -> int:
    return _ACCIONES[args.accion](args)


registrar("rutinas", _configurar, _ejecutar, ayuda="instala rutinas programadas (timers de systemd de usuario)")
