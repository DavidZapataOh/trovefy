"""Dataset guiado (plan 19, Tarea 7): lo crea el usuario; trovefy lo busca y le dice qué pegar en su panel.

**Qué hacen los vídeos:** un píxel por tienda con nombre de producto + país (V1 1:15:20); el token CAPI se genera
en Events Manager → conjunto de datos → Configuración → «Generar identificador de acceso» y se pega a mano en
Impultienda junto al Meta Pixel ID (V1 1:15:11): «pegar las claves… nunca las toco yo» (V2 0:28:45).

- R-d: ``configurar_tracking`` es prohibida (lleva tokens). Pixel ID, token CAPI y token de UTMify los pega el
  usuario en su panel. Clarity no va en la tienda: va en la landing, tras el aviso de cookies (``clarity.py``).
- ``buscar_dataset`` lee la respuesta cruda de ``ads_get_datasets`` (MCP de Meta, solo lectura) que Claude guardó.
- ``pixel_en_lectura_mcp`` lee la respuesta de una herramienta de **lectura** del MCP de Impultienda que devuelva
  el Pixel ID de la tienda (hoy, ``impultienda_estado_onboarding``); si no trae el dato, «no medido».
"""
from __future__ import annotations

import re

from trovefy.embudo.receta_texto import LOGIN, PasoReceta

EVENTS_MANAGER = "https://business.facebook.com/events_manager2"
CLARITY = "https://clarity.microsoft.com"
UTMIFY = "https://utmify.com.br"
_ID = re.compile(r"[0-9]{1,20}")
_PIXEL = re.compile(r"[0-9]{6,20}")
_CONTENEDORES = ("structuredContent", "result")
_LISTAS = ("data", "datasets", "results", "items")


def desenvolver(instantanea: object) -> object:
    """Quita los envoltorios del cliente MCP (``structuredContent``, ``result``) hasta el dato."""
    for _ in range(4):
        if isinstance(instantanea, dict):
            dentro = next((instantanea[k] for k in _CONTENEDORES if isinstance(instantanea.get(k), (dict, list))),
                          None)
            if dentro is None:
                return instantanea
            instantanea = dentro
    return instantanea


def _lista(instantanea: object) -> list | None:
    datos = desenvolver(instantanea)
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for k in _LISTAS:
            if isinstance(datos.get(k), list):
                return datos[k]
    return None


def buscar_dataset(instantanea: object, nombre: str) -> tuple[str | None, str | None]:
    """``(id, None)`` si hay exactamente un dataset con ese nombre exacto; si no, ``(None, motivo)``."""
    lista = _lista(instantanea)
    if lista is None or not all(isinstance(d, dict) for d in lista):
        return None, "no medido: la respuesta de ads_get_datasets no tiene la forma esperada"
    iguales = [d for d in lista if d.get("name") == nombre]
    if any(not isinstance(d.get("id"), str) or not _ID.fullmatch(d["id"]) for d in iguales):
        return None, "no medido: un dataset con ese nombre trae un id que no es numérico"
    if not iguales:
        return None, f"no medido: ningún dataset se llama «{nombre}» (créalo en Events Manager con ese nombre exacto)"
    if len(iguales) > 1:
        ids = ", ".join(d["id"] for d in iguales)
        return None, f"hay {len(iguales)} datasets que se llaman «{nombre}» ({ids}): deja uno solo o renombra los demás"
    return iguales[0]["id"], None


def _pixeles(nodo: object, bajo_pixel: bool = False) -> set[str]:
    """Ids numéricos bajo una clave que dice «pixel» (``pixel_id``, ``pixels: [...]``, ``pixel: {id}``)."""
    encontrados: set[str] = set()
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            clave = str(k).lower()
            pixel = "pixel" in clave
            if isinstance(v, str):
                if (pixel or (bajo_pixel and clave == "id")) and _PIXEL.fullmatch(v):
                    encontrados.add(v)
            elif isinstance(v, (dict, list)):
                encontrados |= _pixeles(v, bajo_pixel or pixel)
    elif isinstance(nodo, list):
        for x in nodo:
            if isinstance(x, str):
                if bajo_pixel and _PIXEL.fullmatch(x):
                    encontrados.add(x)
            else:
                encontrados |= _pixeles(x, bajo_pixel)
    return encontrados


def pixel_en_lectura_mcp(instantanea: object, dataset_id: str) -> bool | None:
    """``True``/``False`` si la lectura del MCP de Impultienda trae Pixel IDs (¿está el del dataset?); ``None`` si
    no trae ninguno (forma desconocida o no lo dice)."""
    vistos = _pixeles(desenvolver(instantanea))
    if not vistos:
        return None
    return dataset_id in vistos


def _hay_escritura_de_pixel(catalogo) -> bool:
    for h in catalogo.values():
        props = (h.esquema or {}).get("properties") or {}
        if h.clase == "escritura" and "pixel_id" in props and "pixel_id" not in h.parametros_prohibidos:
            return True
    return False


def receta_tracking(ctx, nombre: str, dataset_id: str | None, catalogo) -> list[PasoReceta]:
    """Los pasos del usuario en Events Manager, en su panel de Impultienda, en UTMify y en Clarity."""
    panel = f"Tu panel ({LOGIN}) → Configuraciones → pestaña «Meta / Tracking»"
    id_texto = dataset_id or "el id de ese conjunto de datos"
    pasos: list[tuple[str, str, str, str]] = [
        (f"Events Manager ({EVENTS_MANAGER}) → Conectar orígenes de datos → Web", "Nombre", nombre,
         "Escríbelo exacto. Después: trovefy tracking dataset (Claude lee la lista por el MCP de Meta, solo lectura)."
         if dataset_id is None else "Ya existe: no crees otro."),
        (f"Events Manager → conjunto de datos «{nombre}» → Configuración", "Generar identificador de acceso", "",
         "Cópialo. Es una credencial: no lo pegues en el chat ni en trovefy."),
    ]
    if not _hay_escritura_de_pixel(catalogo):
        pasos.append((panel, "Meta Pixel ID", id_texto, ""))
    pasos += [
        (panel, "Token de la API de conversiones", "",
         "Pega ahí el identificador que copiaste en Meta y pulsa Guardar. Después dime con tus palabras que ya está."),
        (panel, "Píxeles cargados", f"solo {id_texto}",
         "Si la tienda trae otro píxel (tienda reciclada), quítalo (V1 0:31:50)."),
        (f"UTMify ({UTMIFY}) → integración con Impultienda", "Token de UTMify", "",
         "Cópialo de UTMify y pégalo en la misma pestaña «Meta / Tracking» de tu panel. No lo pegues en el chat."),
        (f"Clarity ({CLARITY}) → nuevo proyecto", "Id del proyecto", "",
         ("No lo pegues en Impultienda: la tienda lo cargaría sin preguntar. Dime el id (no es secreto) y va en la "
          "landing, que solo carga Clarity tras el aviso de cookies.")),
    ]
    return [PasoReceta(n, donde, campo, valor, nota) for n, (donde, campo, valor, nota) in enumerate(pasos, 1)]
