"""`productos/<p-id>/checkout/<PAIS>/TRACKING.md` y el bloque `paises.<PAIS>.tracking` de `PRODUCTO.md`
(plan 19, Tarea 5; resolución 3: el plan 20 lee `{dataset_id, dataset_nombre, emisor_purchase, estado}`).

Nada se escribe si aparece un secreto (`buscar_secreto`) o si la tabla de emisores tiene un problema.
"""
from __future__ import annotations

import re
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from trovefy.secretos import buscar_secreto
from trovefy.tracking.modelo import _PAIS, ESTADOS, EVENTOS, Tracking, validar_emisores
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import actualizar_producto, ruta_producto, secreto_en

_DATASET_ID = re.compile(r"[0-9]{15,17}")
_OPCIONES = {
    "pixel_publico": ("ok", "otro", "no_visto"),
    "pixel_config": ("mcp", "captura", "dicho"),
    "capi": ("dicho", "visto_en_meta"),
    "fuente_eventos": ("mcp", "captura"),
}


def ruta_tracking(vault: Path, producto: str, pais: str) -> Path:
    return ruta_producto(vault, producto).parent / "checkout" / pais / "TRACKING.md"


def _validar(t: Tracking) -> None:
    if t.estado not in ESTADOS:
        raise ValueError(f"estado de tracking desconocido: «{t.estado}» ({', '.join(ESTADOS)})")
    for campo, validos in _OPCIONES.items():
        valor = getattr(t, campo)
        if valor is not None and valor not in validos:
            raise ValueError(f"{campo}: «{valor}» no es {'/'.join(validos)}")
    if t.dataset_id is not None and not _DATASET_ID.fullmatch(str(t.dataset_id)):
        raise ValueError(f"dataset_id no válido: «{t.dataset_id}» (15 a 17 dígitos)")
    if not isinstance(t.dataset_nombre, str) or not t.dataset_nombre.strip():
        raise ValueError("falta el nombre del dataset")
    problemas = validar_emisores(t.emisores)
    if problemas:
        raise ValueError("emisores: " + "; ".join(problemas))
    if t.eventos is not None:
        for evento, n in t.eventos.items():
            if evento not in EVENTOS or (n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 0)):
                raise ValueError(f"eventos: «{evento}: {n}» no es un conteo de {', '.join(EVENTOS)}")


def _cuerpo(t: Tracking) -> str:
    lineas = [f"# Tracking {t.producto} · {t.pais}", "",
              f"- Dataset: {t.dataset_nombre} ({t.dataset_id or 'no medido: sin crear'})",
              f"- Estado: {t.estado}", "", "| Evento | Emisor | Conteo |", "|---|---|---|"]
    for e in EVENTOS:
        n = (t.eventos or {}).get(e)
        lineas.append(f"| {e} | {t.emisores.get(e)} | {'no medido' if n is None else n} |")
    if t.motivos:
        lineas += ["", "## Motivos", *(f"- {m}" for m in t.motivos)]
    if t.evidencia:
        lineas += ["", "## Evidencia", *(f"- {x}" for x in t.evidencia)]
    return "\n".join(lineas) + "\n"


def _emisor_purchase(t: Tracking) -> str:
    """El emisor de Purchase como texto (L-6): una lista de emisores iguales ya validada vale por uno."""
    purchase = t.emisores.get("Purchase")
    if isinstance(purchase, (list, tuple, set)):
        purchase = min({str(x) for x in purchase})
    return str(purchase)


def escribir_tracking(vault: Path, t: Tracking, ahora: datetime) -> Path:
    """Escribe ``TRACKING.md`` y fusiona ``paises.<PAIS>.tracking`` en ``PRODUCTO.md``, con una sola línea en
    ``log.md``. Antes de escribir nada: normaliza y valida el país, exige ``PRODUCTO.md`` y renderiza y revisa en
    busca de secretos todo lo que se va a escribir. ``ValueError`` (``FileNotFoundError`` sin ``PRODUCTO.md``)
    sin tocar nada si algo falla."""
    vault = Path(vault)
    pais = t.pais.strip().upper() if isinstance(t.pais, str) else ""
    if not _PAIS.fullmatch(pais):
        raise ValueError(f"país mal escrito: «{t.pais}»; usa su código de dos letras")
    t = replace(t, pais=pais)
    producto = ruta_producto(vault, t.producto)
    if not producto.is_file():
        raise FileNotFoundError(f"no existe productos/{t.producto}/PRODUCTO.md: el producto sale de /trovefy:auditar")
    _validar(t)
    meta = {"tipo": "tracking", **asdict(t)}
    texto = frontmatter.renderizar(meta, _cuerpo(t))
    ruta = ruta_tracking(vault, t.producto, pais)
    rel = ruta.relative_to(producto.parent).as_posix()
    bloque = {"dataset_id": t.dataset_id, "dataset_nombre": t.dataset_nombre, "emisor_purchase": _emisor_purchase(t),
              "estado": t.estado}
    enlace = f"- Tracking {pais}: {rel}"
    nombre = secreto_en(meta) or buscar_secreto(texto) or secreto_en(bloque) or buscar_secreto(enlace)
    if nombre:
        raise ValueError(f"TRACKING.md: aparece un secreto ({nombre}); no se escribe nada")
    escribir_atomico(ruta, texto)
    rel_vault = ruta.relative_to(vault).as_posix()
    antes = producto.read_bytes()
    actualizar_producto(vault, t.producto, {"paises": {pais: {"tracking": bloque}}}, [enlace], "tracking", ahora,
                        archivos_log=[rel_vault])
    if producto.read_bytes() == antes:  # PRODUCTO.md no cambió: la línea del log la pone TRACKING.md
        anadir_log(vault, "tracking", f"TRACKING {pais}: {t.estado}", [rel_vault], ahora=ahora)
    return ruta


def leer_tracking(vault: Path, producto: str, pais: str) -> Tracking | None:
    ruta = ruta_tracking(Path(vault), producto, pais)
    if not ruta.is_file():
        return None
    meta, _ = frontmatter.leer(ruta)
    if not isinstance(meta, dict):
        raise ValueError(f"{ruta.name} no tiene frontmatter")  # noqa: TRY004 - dato del vault mal escrito
    campos = {k: meta.get(k) for k in Tracking.__dataclass_fields__}
    campos["emisores"] = dict(campos["emisores"] or {})
    campos["evidencia"] = list(campos["evidencia"] or [])
    campos["motivos"] = list(campos["motivos"] or [])
    t = Tracking(**campos)
    _validar(t)
    return t
