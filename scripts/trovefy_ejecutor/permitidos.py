"""Dataset y página en los límites del ejecutor (plan 19, Tarea 9; §5.1 y §5.6: ``limites.yaml`` solo lo cambia el
usuario).

``paginas_permitidas`` y ``datasets_permitidos`` son listas: ``/limites`` de Telegram y ``limite_ejecutor`` solo
cambian claves enteras. Este módulo las amplía editando el archivo por líneas (conserva los comentarios), y lo usa
el subcomando ``trovefy-ejecutor permitir`` que el usuario ejecuta con ``sudo -u trovefy-exec``. Claude nunca lo
ejecuta. ``comprobar_dataset`` deja en ``estado/dataset.json`` la evidencia que Claude sí puede leer.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from .esquema import CUENTA_RE, ENTIDAD_ID_RE
from .graph import ErrorGraph, ErrorRed, clasificar
from .instalacion import _leer_regular, _linea_del_bloque
from .limites import Limites, LimitesInvalidos, cargar_limites

Clave = Literal["paginas_permitidas", "datasets_permitidos"]
CLAVES: tuple[str, ...] = ("paginas_permitidas", "datasets_permitidos")
_FLUJO = re.compile(r"(?P<pre>\s*\w+:[ \t]*)(?P<lista>\[[^\]#]*\])(?P<post>[ \t]*(#.*)?)")
_VACIA = re.compile(r"(?P<pre>\s*\w+:)(?P<post>[ \t]*(#.*)?)")


def _validar(act_id: str, clave: str, id_: str) -> None:
    if clave not in CLAVES:
        raise ValueError(f"clave no válida: {clave!r} (solo {' o '.join(CLAVES)})")
    if not isinstance(act_id, str) or not re.fullmatch(CUENTA_RE, act_id):
        raise ValueError("cuenta: debe ser act_<dígitos>")
    if not isinstance(id_, str) or not re.fullmatch(ENTIDAD_ID_RE, id_):
        raise ValueError(f"id no válido: {id_!r} (solo dígitos, hasta 20)")


def _actuales(texto: str, act_id: str, clave: str) -> list[str]:
    try:
        crudo = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise ValueError(f"limites.yaml: YAML no válido ({type(e).__name__})") from None
    cuentas = crudo.get("cuentas") if isinstance(crudo, dict) else None
    seccion = cuentas.get(act_id) if isinstance(cuentas, dict) else None
    if not isinstance(seccion, dict):
        raise ValueError(f"limites.yaml: no se encuentra la sección de {act_id}")  # noqa: TRY004 - dato mal escrito
    valor = seccion.get(clave)
    if valor is None and clave in seccion:
        return []
    if not isinstance(valor, list):
        raise ValueError(f"limites.yaml: «{clave}» de {act_id} no es una lista")  # noqa: TRY004 - dato mal escrito
    return [str(x) for x in valor]


def _lista(ids: list[str]) -> str:
    return "[" + ", ".join(json.dumps(x) for x in ids) + "]"


def anadir_permitido(texto: str, act_id: str, clave: Clave, id_: str) -> tuple[str, bool]:
    """``(texto_nuevo, cambiado)``: añade ``id_`` a ``cuentas.<act_id>.<clave>``; si ya está, ``cambiado=False``.

    Solo toca la línea de la lista (estilo ``[a, b]``) o añade un elemento a la lista en bloque (``- a``); el resto
    del archivo, comentarios incluidos, queda igual. ``ValueError`` si el id, la clave o el archivo no valen."""
    _validar(act_id, clave, id_)
    actuales = _actuales(texto, act_id, clave)
    if id_ in actuales:
        return texto, False
    lineas = texto.split("\n")
    i = _linea_del_bloque(lineas, act_id, clave)
    m = _FLUJO.fullmatch(lineas[i])
    if m is not None:
        viejo = m.group("lista")
        nuevo = _lista([*actuales, id_])
        post = m.group("post")
        if post.strip():  # el comentario se queda en su columna si cabe
            hueco = len(post) - len(post.lstrip()) - (len(nuevo) - len(viejo))
            post = " " * max(1, hueco) + post.lstrip()
        lineas[i] = m.group("pre") + nuevo + post
    elif _VACIA.fullmatch(lineas[i]):
        sangria = len(lineas[i]) - len(lineas[i].lstrip())
        fin = i
        for j in range(i + 1, len(lineas)):
            ln = lineas[j]
            if ln.strip() and not ln.lstrip().startswith("#") and len(ln) - len(ln.lstrip()) <= sangria:
                break
            if ln.lstrip().startswith("- "):
                fin = j
        if fin == i:
            raise ValueError(f"limites.yaml: formato de «{clave}» no reconocido")
        elemento = lineas[fin][: len(lineas[fin]) - len(lineas[fin].lstrip())]
        lineas.insert(fin + 1, f"{elemento}- {json.dumps(id_)}")
    else:
        raise ValueError(f"limites.yaml: formato de «{clave}» no reconocido")
    nuevo_texto = "\n".join(lineas)
    if _actuales(nuevo_texto, act_id, clave) != [*actuales, id_]:
        raise ValueError(f"limites.yaml: «{clave}» no se lee de vuelta como se escribió")
    return nuevo_texto, True


def permitir_en_archivo(ruta: Path, act_id: str, clave: Clave, id_: str) -> bool:
    """Añade el id en ``limites.yaml`` con reemplazo atómico. ``True`` si cambió, ``False`` si ya estaba.

    Lee sin seguir enlaces (``O_NOFOLLOW``), escribe un temporal 0600 en el mismo directorio, lo valida con
    ``cargar_limites`` y solo entonces lo pone en su sitio con ``os.replace``: nunca deja un archivo inválido
    (``LimitesInvalidos`` o ``ValueError`` dejan el original intacto)."""
    ruta = Path(ruta)
    texto = _leer_regular(ruta)
    nuevo, cambiado = anadir_permitido(texto, act_id, clave, id_)
    if not cambiado:
        return False
    tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(nuevo)
            f.flush()
            os.fsync(f.fileno())
        lim = cargar_limites(tmp)
        cuenta = lim.cuentas.get(act_id)
        if cuenta is None or id_ not in getattr(cuenta, clave):
            raise LimitesInvalidos(f"{clave}: el id escrito no se lee de vuelta")
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return True


def comprobar_dataset(graph, dataset_id: str, lim: Limites, act_id: str, ahora: datetime) -> dict:
    """Lo que ``trovefy-ejecutor comprobar-dataset`` deja en ``estado/dataset.json``.

    ``lectura_ok``: Graph devolvió el dataset al pedir ``id`` y ``name`` (el usuario del sistema lo tiene asignado).
    Un error de Graph o de red da ``lectura_ok=False`` con un motivo que nunca lleva el mensaje de Meta (ni, por
    tanto, el token). ``pagina_en_limites``: la cuenta tiene al menos una página permitida."""
    if not isinstance(dataset_id, str) or not re.fullmatch(ENTIDAD_ID_RE, dataset_id):
        raise ValueError(f"id de dataset no válido: {dataset_id!r}")
    nombre: str | None = None
    motivo: str | None = None
    lectura_ok = False
    try:
        r = graph.leer(dataset_id, ["id", "name"])
    except ErrorGraph as e:
        tipo = {"token": "el token del ejecutor no vale", "permiso": "sin permiso",
                "limite_meta": "límite de Meta"}.get(clasificar(e), "sin acceso")
        motivo = f"Meta {e.codigo}: {tipo} (¿el usuario del sistema tiene el dataset asignado?)"
    except ErrorRed:
        motivo = "sin conexión con Meta: vuelve a intentarlo"
    else:
        if isinstance(r, dict) and str(r.get("id")) == dataset_id:
            lectura_ok = True
            nombre = r["name"] if isinstance(r.get("name"), str) else None
        else:
            motivo = "Meta no devolvió ese dataset"
    lc = lim.cuentas.get(act_id)
    return {
        "fecha": ahora.isoformat(),
        "dataset_id": dataset_id,
        "nombre": nombre,
        "lectura_ok": lectura_ok,
        "motivo": motivo,
        "en_limites": lc is not None and dataset_id in lc.datasets_permitidos,
        "pagina_en_limites": lc is not None and bool(lc.paginas_permitidas),
    }
