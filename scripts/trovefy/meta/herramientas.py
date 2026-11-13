"""Clasificador a prueba de fallos de las herramientas del MCP oficial de Meta.

Lectura solo si está en la lista blanca compartida con el hook (`es_lectura_meta`);
todo lo demás, conocido o no, es escritura. `readOnlyHint` del servidor no basta.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trovefy.vault.escritura import escribir_atomico
from trovefy.vault.permisos import es_lectura_meta

Clase = Literal["lectura", "escritura"]

_NOMBRE = re.compile(r"[A-Za-z0-9_-]+")
_PREFIJO = re.compile(r"mcp__([^_].*?)__(.+)", re.DOTALL)


class ListaIlegible(ValueError):
    """La lista de herramientas o el documento guardado no se pueden interpretar."""


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    clase: Clase
    motivo: str
    descripcion: str
    argumentos: tuple[str, ...]
    solo_lectura_declarada: bool | None


@dataclass
class Cambios:
    nuevas: list[str]
    desaparecidas: list[str]
    cambian_de_clase: list[str]


def clasificar(nombre: str, solo_lectura_declarada: bool | None = None) -> tuple[Clase, str]:
    if es_lectura_meta(nombre.lower()):
        return "lectura", "lista blanca de lectura (§5.3)"
    if solo_lectura_declarada:
        return "escritura", (
            "el servidor la declara de solo lectura pero no está en la lista blanca: "
            "se deniega; revísala"
        )
    return "escritura", "fuera de la lista blanca: se trata como escritura"


def leer_tools_list(datos: object) -> tuple[str | None, list[dict]]:
    if isinstance(datos, dict):
        if isinstance(datos.get("result"), dict):
            datos = datos["result"]
        datos = datos.get("tools") if isinstance(datos, dict) else None
    if not isinstance(datos, list):
        raise ListaIlegible("no es una lista de herramientas")
    servidores: set[str] = set()
    salida: list[dict] = []
    for item in datos:
        if isinstance(item, str):
            crudo: dict = {"name": item}
        elif isinstance(item, dict):
            crudo = dict(item)
        else:
            raise ListaIlegible("elemento que no es nombre ni objeto")
        nombre = crudo.get("name")
        if not isinstance(nombre, str) or not nombre:
            raise ListaIlegible("herramienta sin nombre")
        m = _PREFIJO.fullmatch(nombre)
        if m:
            servidores.add(m.group(1))
            nombre = m.group(2)
        if not _NOMBRE.fullmatch(nombre):
            raise ListaIlegible(f"nombre de herramienta no válido: {nombre!r}")
        crudo["name"] = nombre
        salida.append(crudo)
    if len(servidores) > 1:
        raise ListaIlegible("la lista mezcla varios servidores")
    return (next(iter(servidores)) if servidores else None), salida


def herramientas_de(crudas: list[dict]) -> list[Herramienta]:
    res = []
    for c in crudas:
        ann = c.get("annotations")
        hint = ann.get("readOnlyHint") if isinstance(ann, dict) else None
        declarada = hint if isinstance(hint, bool) else None
        esquema = c.get("inputSchema")
        props = esquema.get("properties") if isinstance(esquema, dict) else None
        args = tuple(sorted(props)) if isinstance(props, dict) else ()
        clase, motivo = clasificar(c["name"], declarada)
        desc = c.get("description")
        res.append(Herramienta(c["name"], clase, motivo, desc if isinstance(desc, str) else "",
                               args, declarada))
    return res


def comparar(anterior: dict | None, nuevas: list[Herramienta]) -> Cambios:
    previas = {t["name"]: t.get("clase") for t in (anterior or {}).get("tools", [])}
    actuales = {h.nombre: h.clase for h in nuevas}
    return Cambios(
        nuevas=[n for n in actuales if n not in previas],
        desaparecidas=[n for n in previas if n not in actuales],
        cambian_de_clase=[n for n in actuales if n in previas and previas[n] != actuales[n]],
    )


def documento(servidor: str, herramientas: list[Herramienta], fuente: str, fecha: str) -> dict:
    return {
        "version": 1,
        "fecha": fecha,
        "servidor": servidor,
        "fuente": fuente,
        "tools": [
            {
                "name": h.nombre,
                "clase": h.clase,
                "motivo": h.motivo,
                "descripcion": h.descripcion,
                "argumentos": list(h.argumentos),
                "solo_lectura_declarada": h.solo_lectura_declarada,
            }
            for h in herramientas
        ],
    }


def escribir_meta_tools(vault: Path, doc: dict) -> Path:
    ruta = Path(vault) / "config" / "meta_tools.json"
    escribir_atomico(ruta, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return ruta


def leer_documento(vault: Path) -> dict | None:
    ruta = Path(vault) / "config" / "meta_tools.json"
    if not ruta.is_file():
        return None
    try:
        doc = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ListaIlegible(f"meta_tools.json ilegible: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        raise ListaIlegible("meta_tools.json sin lista «tools»")
    return doc
