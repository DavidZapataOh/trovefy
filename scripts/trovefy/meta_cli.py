"""`trovefy meta herramientas preparar|importar|mostrar`: inventario de las herramientas del MCP de Meta."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from trovefy.cli import registrar
from trovefy.meta.herramientas import (
    ListaIlegible,
    comparar,
    documento,
    escribir_meta_tools,
    herramientas_de,
    leer_documento,
    leer_tools_list,
)
from trovefy.secretos import RevisionSecretosNoDisponible, buscar_secreto
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log
from trovefy.vault.permisos import SettingsIlegible, escribir_settings, servidor_valido
from trovefy.vault.rutas import vault_root

MAX_BYTES = 2 * 1024 * 1024


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="grupo", metavar="<grupo>", required=True)
    h = sub.add_parser("herramientas", help="herramientas del MCP oficial de Meta")
    acc = h.add_subparsers(dest="accion", metavar="<accion>", required=True)
    imp = acc.add_parser("importar", help="importa el volcado de tools/list y regenera permisos")
    imp.add_argument("archivo", metavar="ARCHIVO")
    imp.add_argument("--servidor", help="nombre del servidor MCP (si no se deduce del volcado)")
    imp.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    pre = acc.add_parser("preparar", help="quita el deny general de la fase 0 para poder volcar las herramientas")
    pre.add_argument("--servidor", default=None, help="nombre del servidor MCP (por defecto, el de meta_tools.json o meta-ads)")
    pre.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")
    mos = acc.add_parser("mostrar", help="muestra las herramientas guardadas")
    mos.add_argument("--vault", help="ruta del vault (por defecto, TROVEFY_VAULT o ~/trovefy-cerebro)")


def _err(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 2


def _tabla(tools: list[dict]) -> None:
    for t in tools:
        dudosa = " (dudosa: el servidor la declara de solo lectura, sin lista blanca)" if (
            t.get("solo_lectura_declarada") and t["clase"] == "escritura") else ""
        print(f"{t['clase']} · {t['name']} · {t['motivo']}{dudosa}")


def _importar(args: argparse.Namespace, vault: Path) -> int:
    ruta = Path(args.archivo).expanduser()
    try:
        if ruta.stat().st_size > MAX_BYTES:
            return _err("el archivo es demasiado grande (más de 2 MB)")
        texto = ruta.read_text(encoding="utf-8")
        datos = json.loads(texto)
    except (OSError, ValueError) as exc:
        return _err(f"no se puede leer el archivo: {type(exc).__name__}")
    try:
        if buscar_secreto(texto):
            return _err("el archivo lleva algo que parece un secreto; no se importa")
    except RevisionSecretosNoDisponible as exc:
        return _err(str(exc))
    try:
        deducido, crudas = leer_tools_list(datos)
    except ListaIlegible as exc:
        return _err(f"lista ilegible: {exc}")
    servidor = args.servidor if args.servidor is not None else deducido
    if not crudas:
        print("La lista está vacía: no se importa nada.", file=sys.stderr)
        return 1
    if servidor is None:
        print("No se deduce el servidor del volcado: usa --servidor.", file=sys.stderr)
        return 1
    if not servidor_valido(servidor):
        return _err(_SERVIDOR_MALO)
    try:
        anterior = leer_documento(vault)
    except ListaIlegible:
        anterior = None
    hs = herramientas_de(crudas)
    cambios = comparar(anterior, hs)
    doc = documento(servidor, hs, ruta.name, datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d"))
    _tabla(doc["tools"])
    for etiqueta, lista in (("Nuevas", cambios.nuevas),
                            ("Desaparecidas o renombradas", cambios.desaparecidas),
                            ("Cambian de clase", cambios.cambian_de_clase)):
        if anterior is not None and lista:
            print(f"{etiqueta}: {', '.join(lista)}")
    if not any(h.nombre == "ads_library_search" for h in hs):
        print("Aviso: no hay ads_library_search; /cazar no podrá usar el MCP.")
    escribir_meta_tools(vault, doc)
    try:
        escribir_settings(vault, sobrescribir=True)
    except SettingsIlegible as exc:
        return _err(f"meta_tools.json guardado, pero no se tocó .claude/settings.json: {exc}")
    n_l = sum(h.clase == "lectura" for h in hs)
    anadir_log(vault, "meta", f"herramientas importadas: {n_l} lectura, {len(hs) - n_l} escritura",
               ["config/meta_tools.json", ".claude/settings.json"])
    return 0


_SERVIDOR_MALO = "nombre de servidor MCP no válido: usa solo letras, números, «_» o «-»"


def _preparar(args: argparse.Namespace, vault: Path) -> int:
    if args.servidor is not None and not servidor_valido(args.servidor):
        return _err(_SERVIDOR_MALO)
    try:
        escribir_settings(vault, sobrescribir=True, preparar=True, servidor=args.servidor)
    except SettingsIlegible as exc:
        return _err(f"no se tocó .claude/settings.json: {exc}")
    except (ValueError, KeyError, TypeError, OSError) as exc:  # meta_tools.json roto: no se escribe nada
        return _err(f"no se tocó .claude/settings.json: config/meta_tools.json ilegible ({type(exc).__name__}); vuelve a importar")
    args.servidor = args.servidor or "el servidor de Meta"
    anadir_log(vault, "meta", f"permisos preparados para volcar las herramientas de {args.servidor}",
               [".claude/settings.json"])
    print(f"Quitado el deny general de la fase 0 ({args.servidor}); las escrituras las sigue parando el hook "
          "meta_guard. Ahora reinicia Claude Code, conecta con /mcp y vuelca las herramientas.")
    return 0


def _mostrar(vault: Path) -> int:
    try:
        doc = leer_documento(vault)
    except ListaIlegible as exc:
        return _err(str(exc))
    if doc is None:
        print("No hay config/meta_tools.json: importa el volcado con «trovefy meta herramientas importar».")
        return 1
    print(f"Servidor {doc.get('servidor')} · {doc.get('fecha')} · fuente {doc.get('fuente')}")
    _tabla([t for t in doc["tools"] if isinstance(t, dict)])
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser() if args.vault else vault_root()
    if args.accion == "importar":
        return _importar(args, vault)
    if args.accion == "preparar":
        return _preparar(args, vault)
    return _mostrar(vault)


registrar("meta", _configurar, _ejecutar, ayuda="inventario y permisos de las herramientas del MCP de Meta")
