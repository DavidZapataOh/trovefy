"""El bloque ``paises.<PAIS>`` de ``productos/<p-id>/PRODUCTO.md`` para `/listo` (plan 20, Tareas 1 y 4).

Lectura: `leer_ficha`, `campo` y `ruta_evidencia` (una evidencia vale solo si es un archivo regular dentro de
``productos/<p-id>/``, sin enlaces simbólicos). Escritura: `registrar_listo`, la única que escribe; sustituye entera la
clave ``paises.<PAIS>.listo`` (resolución 2), añade una sección al final del cuerpo y, si toca, avanza el estado con
``trovefy.vault.producto.avanzar_estado`` (resolución 1). Nunca retrocede.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import avanzar_estado, secreto_en

_P_ID = re.compile(r"p-\d{4}-[a-z0-9-]+")
_PAIS = re.compile(r"[A-Z]{2}")
_SKILL = "listo"


@dataclass(frozen=True)
class FichaPais:
    producto: str
    pais: str
    carpeta: Path  # productos/<p-id>/
    estado: str | None
    datos: dict  # paises.<PAIS> tal cual; {} si falta


class FichaIlegible(ValueError):
    """``PRODUCTO.md`` existe pero su frontmatter no se puede leer como se espera."""


def _validar_ids(producto: object, pais: object) -> None:
    if not isinstance(producto, str) or not _P_ID.fullmatch(producto):
        raise ValueError(f"producto mal escrito: «{producto}»; usa su p-id (por ejemplo p-0001-…)")
    if not isinstance(pais, str) or not _PAIS.fullmatch(pais):
        raise ValueError(f"país mal escrito: «{pais}»; usa su código de dos letras en mayúsculas (por ejemplo BG)")


def leer_ficha(vault: Path, producto: str, pais: str) -> FichaPais:
    """``FichaPais`` del producto-país. ``ValueError`` si los ids están mal escritos, ``FileNotFoundError`` sin
    ``PRODUCTO.md`` y `FichaIlegible` si su frontmatter está roto o ``paises`` no es un mapa."""
    _validar_ids(producto, pais)
    carpeta = Path(vault) / "productos" / producto
    ruta = carpeta / "PRODUCTO.md"
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe productos/{producto}/PRODUCTO.md")
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FichaIlegible(f"productos/{producto}/PRODUCTO.md no se puede leer ({type(exc).__name__})") from None
    if not isinstance(meta, dict):
        raise FichaIlegible(f"productos/{producto}/PRODUCTO.md no tiene un frontmatter con claves")
    paises = meta.get("paises")
    if paises is None:
        paises = {}
    if not isinstance(paises, dict):
        raise FichaIlegible(f"productos/{producto}/PRODUCTO.md: «paises» no es un mapa")
    bloque = paises.get(pais)
    if bloque is None:
        bloque = {}
    if not isinstance(bloque, dict):
        raise FichaIlegible(f"productos/{producto}/PRODUCTO.md: «paises.{pais}» no es un mapa")
    estado = bloque.get("estado")
    return FichaPais(producto, pais, carpeta, estado if isinstance(estado, str) else None, bloque)


def campo(datos: dict, ruta: str) -> object | None:
    """``campo(d, "compra_prueba.events_manager.purchase")``; cualquier tramo ausente o que no es un mapa → None."""
    actual: object = datos
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return None
        actual = actual[parte]
    return actual


def ruta_evidencia(ficha: FichaPais, rel: object) -> str | None:
    """``rel`` normalizada si es un texto relativo, sin ``..``, dentro de ``ficha.carpeta``, existente, archivo
    regular y sin ningún tramo que sea un enlace simbólico; None en otro caso."""
    if not isinstance(rel, str) or not rel.strip() or "\\" in rel or "\x00" in rel:
        return None
    pura = PurePosixPath(rel.strip())
    if pura.is_absolute() or any(p in ("..", "") for p in pura.parts) or not pura.parts:
        return None
    pura = PurePosixPath(*(p for p in pura.parts if p != "."))
    if not pura.parts:
        return None
    base = ficha.carpeta
    actual = base
    try:
        if base.is_symlink():
            return None
        for parte in pura.parts:
            actual = actual / parte
            if actual.is_symlink():
                return None
        resuelta = actual.resolve(strict=True)
        resuelta.relative_to(base.resolve(strict=True))
    except (OSError, ValueError, RuntimeError):
        return None
    return pura.as_posix() if resuelta.is_file() else None


# --- escritura (Tarea 4) ---------------------------------------------------------------------------------------------


def _bloque_listo(informe) -> dict:
    from trovefy.listo.veredicto import resumen_gates

    return {"fecha": informe.fecha.astimezone(ZONA_NEGOCIO).isoformat(timespec="seconds"),
            "verde": informe.verde, "pasa": informe.pasa,
            "excepciones": [g.clave for g in informe.gates if g.estado == "excepcion"],
            "gates": resumen_gates(informe)}


def registrar_listo(vault: Path, informe) -> str:
    """Escribe el informe en ``PRODUCTO.md`` y devuelve el estado resultante del país.

    Sustituye solo ``paises.<PAIS>.listo``; si el informe pasa (todo verde, o con excepciones aprobadas donde se
    admiten) y el estado era ``con_checkout``, lo avanza a ``listo``; con ``listo`` lo deja (nunca retrocede); con
    otro estado no lo toca. Añade ``## /listo · <PAIS> · <fecha>`` al cuerpo y una línea en ``log.md``. Si algo de
    lo que se va a escribir tiene forma de secreto, ``ValueError`` sin escribir nada."""
    from trovefy.listo.veredicto import texto_informe

    vault = Path(vault)
    ficha = leer_ficha(vault, informe.producto, informe.pais)
    ruta = ficha.carpeta / "PRODUCTO.md"
    antes = ficha.estado
    avanza = informe.pasa and antes == "con_checkout"
    despues = "listo" if avanza else antes
    fecha = informe.fecha.astimezone(ZONA_NEGOCIO)
    bloque = _bloque_listo(informe)
    seccion = f"## /listo · {informe.pais} · {fecha.isoformat(timespec='seconds')}\n\n{texto_informe(informe)}\n"
    resultado = "verde" if informe.verde else ("pasa con excepciones" if informe.pasa else "rojo")
    que = f"{informe.producto} {informe.pais}: {resultado} (estado {antes or 'sin estado'} → {despues or 'sin estado'})"
    patron = secreto_en(bloque) or secreto_en(seccion) or secreto_en(que)
    if patron:
        raise ValueError(f"el informe de /listo lleva algo con forma de secreto ({patron}); no se escribe nada")
    previo, _ = frontmatter.leer(ruta)
    if secreto_en(previo):
        raise ValueError("PRODUCTO.md ya lleva algo con forma de secreto; no se escribe el informe (quítalo antes)")
    if avanza:
        evidencia = [f"/listo {fecha.isoformat(timespec='seconds')}: {resultado}"]
        evidencia += [f"{g.clave}: excepción aprobada por el usuario, no es verde ({g.texto})"
                      for g in informe.gates if g.estado == "excepcion"]
        avanzar_estado(vault, informe.producto, informe.pais, desde="con_checkout", hacia="listo",
                       evidencia=evidencia, skill=_SKILL, ahora=fecha)
    meta, cuerpo = frontmatter.leer(ruta)
    meta = copy.deepcopy(meta)
    paises = meta.get("paises") if isinstance(meta.get("paises"), dict) else {}
    pais_bloque = dict(paises.get(informe.pais) or {})
    pais_bloque["listo"] = bloque
    meta["paises"] = {**paises, informe.pais: pais_bloque}
    cuerpo = cuerpo.rstrip("\n") + "\n\n" + seccion
    texto = frontmatter.renderizar(meta, cuerpo)
    patron = secreto_en(meta) or secreto_en(texto)
    if patron:  # solo podría venir de lo que ya había: no se escribe nada nuevo encima
        raise ValueError(f"PRODUCTO.md lleva algo con forma de secreto ({patron}); no se escribe el informe")
    escribir_atomico(ruta, texto)
    anadir_log(vault, _SKILL, que, [ruta.relative_to(vault).as_posix()], ahora=fecha)
    return despues or "sin estado"
