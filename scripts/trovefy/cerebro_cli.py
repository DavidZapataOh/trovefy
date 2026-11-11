"""Subcomando `trovefy cerebro`."""

import argparse
import json
import sys
from pathlib import Path

import yaml

from trovefy.cerebro.canarios import cargar as cargar_canarios
from trovefy.cerebro.canarios import correr as correr_canarios
from trovefy.cerebro.canarios import sha256_de as sha_canarios
from trovefy.cerebro.destilado import pendientes, validar_todo
from trovefy.cerebro.ingesta import ingerir
from trovefy.cli import registrar
from trovefy.vault.andamio import crear_vault
from trovefy.vault.escritura import anadir_log
from trovefy.vault.lint import lint
from trovefy.vault.permisos import escribir_settings
from trovefy.vault.reglas import ConflictoDeReglas, aplicar_plan, planear_regla
from trovefy.vault.rutas import vault_root
from trovefy.vault.sesiones import escribir_traspaso, ultimo_traspaso


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    init = sub.add_parser("init", help="crea el vault Cerebro desde la plantilla")
    init.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    perm = sub.add_parser("permisos", help="regenera .claude/settings.json del vault")
    perm.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    reg = sub.add_parser("regla", help="crea una regla fechada R-nnn desde un JSON")
    reg.add_argument("--json", required=True, metavar="ARCHIVO",
                     help="JSON con titulo, regla, porque, como, fuente (+ umbrales, reemplaza, fecha); «-» lee de stdin")
    reg.add_argument("--simular", action="store_true",
                     help="valida y muestra qué cambiaría, sin escribir nada")
    reg.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    tra = sub.add_parser("traspaso", help="escribe el traspaso de la sesión en sesiones/")
    tra.add_argument("--json", required=True, metavar="ARCHIVO",
                     help="JSON con hecho, pendiente, decisiones, archivos (listas de texto); «-» lee de stdin")
    tra.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    ret = sub.add_parser("retomar", help="imprime el último traspaso de sesión")
    ret.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    lin = sub.add_parser("lint", help="revisa enlaces rotos, páginas huérfanas y frontmatter")
    lin.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    ing = sub.add_parser("ingerir", help="copia fuentes (.md/.html) a raw/ sin duplicar")
    ing.add_argument("rutas", nargs="+", metavar="RUTA", help="archivos .md o .html a ingerir")
    ing.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    des = sub.add_parser("destilar", help="lista fuentes pendientes o valida las citas de wiki/metodo/")
    grupo = des.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pendientes", action="store_true", help="lista las fuentes de raw/ sin destilar")
    grupo.add_argument("--validar", action="store_true", help="valida las citas de todo wiki/metodo/")
    des.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    can = sub.add_parser("canarios", help="hace las preguntas canario al cerebro (claude -p) y evalúa las respuestas")
    can.add_argument("--solo", metavar="ID", help="corre solo el canario con ese id")
    can.add_argument("--canarios", metavar="ARCHIVO", help="YAML de canarios (por defecto, tests/canarios.yaml del repo)")
    can.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    lg = sub.add_parser("log", help="añade una línea a log.md")
    lg.add_argument("--skill", required=True, help="nombre de la skill (p. ej. destilar)")
    lg.add_argument("--que", required=True, help="qué se hizo, en una frase")
    lg.add_argument("--archivo", action="append", default=[], help="archivo tocado (repetible)")
    lg.add_argument("--tokens", type=int, help="tokens aproximados")
    lg.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")


def _error(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _regla(args: argparse.Namespace, destino: Path) -> int:
    try:
        crudo = sys.stdin.read() if args.json == "-" else Path(args.json).expanduser().read_text(encoding="utf-8")
        campos = json.loads(crudo)
    except OSError as exc:
        return _error(f"no se pudo leer {args.json}: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        return _error(f"el JSON no es válido ({exc})")
    if not isinstance(campos, dict):
        return _error("el JSON debe ser un objeto con los campos de la regla")
    requeridos = ("titulo", "regla", "porque", "como", "fuente")
    faltan = [c for c in requeridos if not isinstance(campos.get(c), str) or not campos[c].strip()]
    if faltan:
        return _error(f"faltan campos de texto en el JSON: {', '.join(faltan)}")
    permitidos = {*requeridos, "umbrales", "reemplaza", "fecha"}
    sobran = sorted(set(campos) - permitidos)
    if sobran:
        return _error(f"campos desconocidos en el JSON: {', '.join(sobran)}")
    try:
        plan = planear_regla(destino, **campos)
        if not args.simular:
            aplicar_plan(plan)
    except ConflictoDeReglas as exc:
        print("Conflicto con reglas vigentes: " + " ".join(exc.ids))
        return 3
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc))
    except yaml.YAMLError as exc:
        return _error(f"un archivo del vault no es YAML válido ({exc})")
    except OSError as exc:
        return _error(f"no se pudo leer o escribir en el vault: {exc.strerror or exc}")
    if args.simular:
        print("Simulación: no se escribió nada.")
    for linea in plan.resumen():
        print(linea)
    if not args.simular:
        print(plan.ruta)
    return 0


_LISTAS = ("hecho", "pendiente", "decisiones", "archivos")


def _traspaso(args: argparse.Namespace, destino: Path) -> int:
    try:
        crudo = sys.stdin.read() if args.json == "-" else Path(args.json).expanduser().read_text(encoding="utf-8")
        campos = json.loads(crudo)
    except OSError as exc:
        return _error(f"no se pudo leer {args.json}: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        return _error(f"el JSON no es válido ({exc})")
    if not isinstance(campos, dict):
        return _error("el JSON debe ser un objeto con hecho, pendiente, decisiones y archivos")
    sobran = sorted(set(campos) - set(_LISTAS))
    if sobran:
        return _error(f"campos desconocidos en el JSON: {', '.join(sobran)}")
    listas = {}
    for c in _LISTAS:
        v = campos.get(c, [])
        if not isinstance(v, list) or not all(isinstance(i, str) for i in v):
            return _error(f"«{c}» debe ser una lista de textos")
        listas[c] = [i.strip() for i in v if i.strip()]
    try:
        ruta = escribir_traspaso(destino, listas["hecho"], listas["pendiente"],
                                 listas["decisiones"], listas["archivos"])
        anadir_log(destino, "cerrar", "traspaso de sesión", [ruta.relative_to(destino).as_posix()])
    except OSError as exc:
        return _error(f"no se pudo escribir en el vault: {exc.strerror or exc}")
    print(ruta)
    return 0


def _retomar(destino: Path) -> int:
    ruta = ultimo_traspaso(destino)
    if ruta is None:
        print("No hay traspasos de sesión todavía.")
        return 0
    print(f"# {ruta.relative_to(destino)}\n")
    print(ruta.read_text(encoding="utf-8"))
    return 0


def _lint(destino: Path) -> int:
    if not destino.is_dir():
        return _error(f"no existe el vault {destino}")
    problemas = lint(destino)
    for p in problemas:
        print(f"{p.tipo}: {p.ruta}: {p.detalle}")
    if problemas:
        print(f"{len(problemas)} problema(s).")
        return 1
    print("Vault sin problemas.")
    return 0


def _ingerir(args: argparse.Namespace, destino: Path) -> int:
    nuevos, repetidos, faltan, archivos = 0, 0, 0, []
    for crudo in args.rutas:
        ruta = Path(crudo).expanduser()
        if not ruta.is_file():
            print(f"Error: no existe el archivo {crudo}", file=sys.stderr)
            faltan += 1
            continue
        try:
            en_raw, creado = ingerir(destino, ruta)
        except OSError as exc:
            print(f"Error: no se pudo ingerir {crudo}: {exc.strerror or exc}", file=sys.stderr)
            faltan += 1
            continue
        except ValueError as exc:
            print(f"Error: {crudo}: {exc}", file=sys.stderr)
            faltan += 1
            continue
        print(f"{'nuevo' if creado else 'ya estaba'}: {crudo}")
        if creado:
            nuevos += 1
            archivos.append(en_raw.relative_to(destino).as_posix())
        else:
            repetidos += 1
    if nuevos or repetidos or faltan:
        pasos = f"{nuevos} nuevo(s), {repetidos} ya estaba(n), {faltan} fallo(s)"
        anadir_log(destino, "ingerir", pasos, archivos or ["—"])
    return 2 if faltan else 0


def _destilar(args: argparse.Namespace, destino: Path) -> int:
    if not destino.is_dir():
        return _error(f"no existe el vault {destino}")
    if args.pendientes:
        lista = pendientes(destino)
        for f in lista:
            print(f.relative_to(destino).as_posix())
        if not lista:
            print("No hay fuentes pendientes.")
        return 0
    if not (destino / "wiki" / "metodo").is_dir() or not list((destino / "wiki" / "metodo").rglob("*.md")):
        print("No hay páginas del método que validar.")
        return 0
    problemas = validar_todo(destino)
    for p in problemas:
        print(p)
    if problemas:
        return 1
    print("Método sin problemas de citas.")
    return 0


def _canarios(args: argparse.Namespace, destino: Path) -> int:
    if not destino.is_dir():
        return _error(f"no existe el vault {destino}")
    try:
        lista = cargar_canarios(Path(args.canarios).expanduser() if args.canarios else None)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return _error(f"no se pudieron cargar los canarios: {exc}")
    parcial = bool(args.solo or args.canarios)
    if args.solo:
        lista = [c for c in lista if c.id == args.solo]
        if not lista:
            return _error(f"no hay ningún canario con id «{args.solo}»")
    try:
        sha = sha_canarios(Path(args.canarios).expanduser() if args.canarios else None)
        resultados = correr_canarios(destino, lista, actualizar_ultimo=not parcial, canarios_sha256=sha)
    except OSError as exc:
        return _error(f"no se pudo escribir en el vault: {exc.strerror or exc}")
    for r in resultados:
        detalle = f"faltan: {', '.join(r.faltan)}" if r.faltan else ("" if r.estado == "ok" else r.respuesta[:120])
        print(f"{r.id}\t{r.estado}\t{detalle}".rstrip())
    return 0 if resultados and all(r.estado == "ok" for r in resultados) else 1


def _log(args: argparse.Namespace, destino: Path) -> int:
    if not destino.is_dir():
        return _error(f"no existe el vault {destino}")
    if not args.skill.strip() or not args.que.strip():
        return _error("--skill y --que no pueden estar vacíos")
    if args.tokens is not None and args.tokens < 0:
        return _error("--tokens debe ser un entero no negativo")
    try:
        linea = anadir_log(destino, args.skill.strip(), args.que.strip(), args.archivo or ["—"], args.tokens)
    except OSError as exc:
        return _error(f"no se pudo escribir en log.md: {exc.strerror or exc}")
    print(linea)
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    destino = Path(args.vault).expanduser() if args.vault else vault_root()
    if args.accion == "regla":
        return _regla(args, destino)
    if args.accion == "traspaso":
        return _traspaso(args, destino)
    if args.accion == "retomar":
        return _retomar(destino)
    if args.accion == "lint":
        return _lint(destino)
    if args.accion == "ingerir":
        return _ingerir(args, destino)
    if args.accion == "canarios":
        return _canarios(args, destino)
    if args.accion == "log":
        return _log(args, destino)
    if args.accion == "destilar":
        return _destilar(args, destino)
    if args.accion == "permisos":
        escribir_settings(destino, sobrescribir=True)
        print(f"Permisos regenerados en {destino / '.claude' / 'settings.json'}.")
        return 0
    creados = crear_vault(destino)
    escribir_settings(destino, sobrescribir=False)
    if not creados:
        print(f"El vault de {destino} ya estaba completo: no se creó nada.")
    else:
        print(f"Vault listo en {destino}: {len(creados)} archivos creados.")
    return 0


registrar("cerebro", _configurar, _ejecutar, ayuda="gestiona el vault (cerebro): crear, lint, ingesta, reglas, traspasos y log")
