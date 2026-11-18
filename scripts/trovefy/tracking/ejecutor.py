"""Dataset y página en los límites del ejecutor, del lado de Claude (plan 19, Tarea 9; §5.1: ``limites.yaml`` solo
lo cambia el usuario).

Los vídeos montan las campañas con el conector de Meta (V1 0:58:29). Aquí Claude nunca escribe en Meta: las monta
el ejecutor en la fase 3, y para eso necesita el dataset y la página en sus límites. Claude no toca nada de eso:

1. el usuario asigna el dataset al usuario del sistema ``trovefy-ejecutor`` en su navegador (Configuración del
   negocio);
2. en una terminal aparte ejecuta los tres comandos de `comandos_para_usuario` (como ``trovefy-exec``);
3. Claude lee ``estado/dataset.json`` (lo escribe ``comprobar-dataset``) y lo anota en ``TRACKING.md``.

``trovefy tracking ejecutor``: `configurar` y `ejecutar` (el subcomando lo registra ``trovefy.tracking_cli``).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from trovefy.aprobaciones.fuentes import Lectura, leer_estado
from trovefy.tracking.salida import escribir_tracking, leer_tracking
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.rutas import vault_root

EJECUTOR = "sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor"
ASIGNAR = ("Configuración del negocio › Orígenes de datos › Datasets › Asignar usuarios › trovefy-ejecutor")
VIGENCIA = timedelta(hours=24)
_ID = re.compile(r"[0-9]{1,20}")


def _id(valor: object, que: str) -> str:
    if not isinstance(valor, str) or not _ID.fullmatch(valor):
        raise ValueError(f"id de {que} no válido: {valor!r} (solo dígitos)")
    return valor


def comandos_para_usuario(dataset_id: str, pagina_id: str) -> list[str]:
    """Los tres comandos que el usuario ejecuta en una terminal aparte (Claude no los ejecuta)."""
    d, p = _id(dataset_id, "dataset"), _id(pagina_id, "página")
    return [f"{EJECUTOR} permitir --dataset {d}", f"{EJECUTOR} permitir --pagina {p}",
            f"{EJECUTOR} comprobar-dataset {d}"]


def evaluar_dataset_json(lectura: Lectura, dataset_id: str, *, ahora: datetime | None = None,
                         pagina_id: str | None = None) -> tuple[bool | None, str]:
    """``(None, «no medido: …»)`` sin archivo, de otro dataset o con más de 24 h; ``(False, qué falta)``;
    ``(True, …)`` si el ejecutor lee el dataset y tiene el dataset y la página en sus límites."""
    ahora = ahora or datetime.now(UTC)
    d = lectura.datos
    if d is None:
        return None, lectura.motivo or "no medido: el ejecutor no ha escrito dataset.json"
    if str(d.get("dataset_id")) != dataset_id:
        return None, "no medido: dataset.json es de otro dataset; ejecuta comprobar-dataset con el de este producto"
    try:
        fecha = datetime.fromisoformat(str(d.get("fecha")))
        if fecha.utcoffset() is None:
            raise ValueError("sin zona")
    except ValueError:
        return None, "no medido: dataset.json sin fecha válida"
    if ahora - fecha > VIGENCIA or fecha - ahora > timedelta(minutes=5):
        return None, "no medido: dataset.json tiene más de 24 h; vuelve a ejecutar comprobar-dataset"
    if d.get("lectura_ok") is not True:
        return False, f"el usuario del sistema no ve el dataset: asígnalo en {ASIGNAR}"
    faltan = []
    if d.get("en_limites") is not True:
        faltan.append(f"{EJECUTOR} permitir --dataset {dataset_id}")
    if d.get("pagina_en_limites") is not True:
        faltan.append(f"{EJECUTOR} permitir --pagina {pagina_id or '<id de la página>'}")
    if faltan:
        return False, "falta añadirlo a los límites: ejecuta " + " y ".join(faltan)
    return True, "el ejecutor lee el dataset y tiene el dataset y la página en sus límites"


def pagina_de_arranque(vault: Path) -> str | None:
    """``page_id`` del paso 05 de ``config/arranque.yaml`` (la página de Facebook), o None."""
    try:
        crudo = yaml.safe_load((Path(vault) / "config" / "arranque.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    pasos = crudo.get("pasos") if isinstance(crudo, dict) else None
    for p in pasos if isinstance(pasos, list) else []:
        if isinstance(p, dict) and str(p.get("id")) == "05":
            datos = p.get("datos")
            pid = str(datos.get("page_id") or "") if isinstance(datos, dict) else ""
            return pid if _ID.fullmatch(pid) else None
    return None


def pasos_guiados(dataset_nombre: str, dataset_id: str, pagina_id: str) -> list[str]:
    comandos = comandos_para_usuario(dataset_id, pagina_id)
    return [
        "Para que el ejecutor pueda montar campañas (fase 3) necesita el dataset y la página en sus límites.",
        "Claude no toca ni Meta ni limites.yaml: lo haces tú.",
        "",
        f"1. En tu navegador, asigna el dataset «{dataset_nombre}» ({dataset_id}) al usuario del sistema:",
        f"   {ASIGNAR} (permiso de gestión).",
        "2. En una terminal aparte (no aquí), ejecuta estos tres comandos; pedirán tu contraseña de sudo:",
        *(f"   {c}" for c in comandos),
        "3. Vuelve aquí y repite este paso: leo lo que dejó el ejecutor y lo anoto en TRACKING.md.",
    ]


def configurar(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto")
    p.add_argument("--pais", required=True, help="código del país (dos letras)")


def ejecutar(args: argparse.Namespace) -> int:
    vault = vault_root()
    pais = str(args.pais).strip().upper()
    t = leer_tracking(vault, args.producto, pais)
    if t is None or not t.dataset_id:
        print("no medido: falta el dataset de este producto y país; créalo antes (trovefy tracking dataset)",
              file=sys.stderr)
        return 2
    pagina = pagina_de_arranque(vault)
    if pagina is None:
        print("no medido: falta la página de Facebook (page_id del paso 05 de /arranque)", file=sys.stderr)
        return 2
    print("\n".join(pasos_guiados(t.dataset_nombre, t.dataset_id, pagina)))
    lectura = leer_estado("dataset")
    ok, texto = evaluar_dataset_json(lectura, t.dataset_id, pagina_id=pagina)
    print()
    if ok is None:
        print(texto)
        return 0
    d = lectura.datos or {}
    bloque = {"dataset_permitido": d.get("en_limites") is True, "pagina_permitida": d.get("pagina_en_limites") is True,
              "lectura_ok": d.get("lectura_ok") is True, "fecha": str(d.get("fecha"))}
    escribir_tracking(vault, replace(t, ejecutor=bloque), datetime.now(ZONA_NEGOCIO))
    print(f"Listo: {texto}." if ok else f"Falta: {texto}.")
    print("Anotado en TRACKING.md.")
    return 0 if ok else 1
