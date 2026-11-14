"""Estado del producto-país en ``productos/<p-id>/PRODUCTO.md``, común a los planes 16–20.

Un solo ayudante de estado (contrato, resoluciones 1–3): cada plan avanza solo su paso con
``avanzar_estado`` y todo lo demás que escribe en ``PRODUCTO.md`` va por ``actualizar_producto``,
que fusiona y nunca borra claves, ni cuerpo, ni toca ``paises.<P>.estado`` o su ``historial``.
"""

import copy
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from trovefy.config import mercados
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

ESTADOS_FASE2 = ("aprobado", "modelado", "producido", "con_landing", "con_checkout", "listo")
# Claves de cada país que solo escribe avanzar_estado.
_PROTEGIDAS = ("estado", "historial")
_P_ID = re.compile(r"p-\d{4}-[a-z0-9-]+")
_PAIS = re.compile(r"[A-Z]{2}")


class EstadoInesperado(ValueError):
    """El país no está en el estado desde el que la skill puede avanzar."""


def ruta_producto(vault: Path, p_id: str) -> Path:
    if not isinstance(p_id, str) or not _P_ID.fullmatch(p_id):
        raise ValueError(f"producto mal escrito: «{p_id}»; usa su p-id (por ejemplo p-0001-fise-terapie)")
    return Path(vault) / "productos" / p_id / "PRODUCTO.md"


def _pais(pais: str) -> str:
    codigo = pais.strip().upper() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(codigo):
        raise ValueError(f"país mal escrito: «{pais}»; usa su código de dos letras (por ejemplo RO)")
    return codigo


def _con_zona(ahora: datetime) -> datetime:
    if not isinstance(ahora, datetime) or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError(f"ahora sin zona horaria: {ahora!r} (usa un datetime con tzinfo)")
    return ahora


def _leer(vault: Path, p_id: str) -> tuple[Path, dict, str]:
    ruta = ruta_producto(vault, p_id)
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md: el producto sale de /trovefy:auditar")
    meta, cuerpo = frontmatter.leer(ruta)
    return ruta, dict(meta or {}), cuerpo


def _guardar(vault: Path, ruta: Path, meta: dict, cuerpo: str, skill: str, que: str, ahora: datetime) -> Path:
    texto = frontmatter.renderizar(meta, cuerpo)
    nombre = buscar_secreto(texto)  # RevisionSecretosNoDisponible: no se escribe nada
    if nombre:
        raise ValueError(f"{ruta.name}: aparece un secreto ({nombre}); no se escribe nada")
    escribir_atomico(ruta, texto)
    anadir_log(vault, skill, que, [ruta.relative_to(vault).as_posix()], ahora=ahora)
    return ruta


def estado_pais(vault: Path, p_id: str, pais: str) -> str | None:
    """``paises.<PAIS>.estado`` de ``PRODUCTO.md``; None si el país no tiene estado."""
    _, meta, _ = _leer(vault, p_id)
    paises = meta.get("paises")
    bloque = paises.get(_pais(pais)) if isinstance(paises, dict) else None
    return bloque.get("estado") if isinstance(bloque, dict) else None


def pais_elegido(vault: Path, p_id: str) -> tuple[str, str | None, Path]:
    """(país, reserva, ruta) de la ``decisiones/*-eleccion.md`` válida más reciente del producto.

    Mismo orden que ``arranque.verificadores.cuenta.mercado_elegido``: se saltan las marcadas
    ``fuera_de_mercados`` y, si existe ``config/mercados.yaml``, las de un país que no está en él."""
    vault = Path(vault)
    dir_decisiones = ruta_producto(vault, p_id).parent / "decisiones"
    archivos = sorted(dir_decisiones.glob("*-eleccion.md"), key=lambda p: (p.name, p.stat().st_mtime))
    ruta_mercados = vault / "config" / "mercados.yaml"
    validos = mercados.cargar(ruta_mercados) if ruta_mercados.is_file() else None
    for archivo in reversed(archivos):
        meta, _ = frontmatter.leer(archivo)
        if not isinstance(meta, dict) or meta.get("fuera_de_mercados") is True:
            continue
        pais = meta.get("pais")
        if not isinstance(pais, str) or not _PAIS.fullmatch(pais):
            continue
        if validos is not None and pais not in validos:
            continue
        reserva = meta.get("reserva")
        return pais, reserva if isinstance(reserva, str) and reserva else None, archivo
    raise FileNotFoundError("falta la elección de país en decisiones/: /auditar")


def _evidencias(evidencia: str | Sequence[str]) -> list[str]:
    if isinstance(evidencia, str):
        lista = [evidencia]
    elif isinstance(evidencia, Sequence) and not isinstance(evidencia, (bytes, bytearray)):
        lista = list(evidencia)
    else:
        msg = f"evidencia de tipo {type(evidencia).__name__}: va un texto o una lista de textos"
        raise ValueError(msg)  # noqa: TRY004 - el contrato (resolución 1) promete ValueError
    if not lista or any(not isinstance(e, str) or not e.strip() for e in lista):
        raise ValueError("falta la evidencia del paso (un texto o una lista de textos no vacíos)")
    return [e.strip() for e in lista]


def avanzar_estado(vault: Path, p_id: str, pais: str, desde: str, hacia: str, evidencia: str | Sequence[str],
                   skill: str, ahora: datetime) -> Path:
    """Pasa ``paises.<PAIS>.estado`` de ``desde`` al siguiente estado (``hacia``) y lo anota en ``historial``."""
    vault = Path(vault)
    ahora = _con_zona(ahora)
    pais = _pais(pais)
    if desde not in ESTADOS_FASE2[:-1] or hacia != ESTADOS_FASE2[ESTADOS_FASE2.index(desde) + 1]:
        raise ValueError(f"paso no permitido: {desde} → {hacia} (los estados van en orden: "
                         f"{' → '.join(ESTADOS_FASE2)})")
    evidencias = _evidencias(evidencia)
    ruta, meta, cuerpo = _leer(vault, p_id)
    paises = meta.get("paises") if isinstance(meta.get("paises"), dict) else {}
    bloque = dict(paises.get(pais)) if isinstance(paises.get(pais), dict) else {}
    actual = bloque.get("estado")
    if actual != desde:
        raise EstadoInesperado(f"{pais} está en {actual or 'sin estado'}: {skill} solo avanza desde {desde}")
    historial = bloque.get("historial")
    historial = list(historial) if isinstance(historial, list) else ([] if historial is None else [historial])
    historial.append({"de": desde, "a": hacia,
                      "fecha": ahora.astimezone(ZONA_NEGOCIO).isoformat(timespec="seconds"),
                      "evidencia": evidencias})
    bloque["estado"] = hacia
    bloque["historial"] = historial
    meta["paises"] = {**paises, pais: bloque}
    return _guardar(vault, ruta, meta, cuerpo, skill, f"{p_id} {pais}: {desde} → {hacia}", ahora)


def _fusionar(base: dict, cambios: dict, camino: str) -> dict:
    out = dict(base)
    for clave, nuevo in cambios.items():
        donde = f"{camino}.{clave}" if camino else str(clave)
        viejo = out.get(clave)
        if isinstance(viejo, dict):
            if not isinstance(nuevo, dict):
                msg = f"{donde} es un mapa en PRODUCTO.md: no se sustituye por otro valor (se perderían sus claves)"
                raise ValueError(msg)  # noqa: TRY004 - dato del vault, no un error de tipos
            out[clave] = _fusionar(viejo, nuevo, donde)
        else:
            out[clave] = copy.deepcopy(nuevo)
    return out


def _sin_protegidas(cambios: dict) -> dict:
    """Normaliza los códigos de país y quita ``paises.<P>.estado`` e ``historial`` (solo de ``avanzar_estado``)."""
    paises = cambios.get("paises")
    if not isinstance(paises, dict):
        return cambios
    limpios = {}
    vistos: set[str] = set()
    for crudo, b in paises.items():
        p = _pais(crudo)
        if p in vistos:
            raise ValueError(f"el país {p} aparece dos veces en los cambios (con mayúsculas y minúsculas)")
        vistos.add(p)
        if not isinstance(b, dict):
            limpios[p] = b
            continue
        resto = {k: v for k, v in b.items() if k not in _PROTEGIDAS}
        if resto or not b:
            limpios[p] = resto  # un bloque que solo traía estado/historial no crea nada
    return {**cambios, "paises": limpios}


def actualizar_producto(vault: Path, p_id: str, cambios: dict, enlaces: list[str], skill: str,
                        ahora: datetime) -> Path:
    """Fusiona ``cambios`` en el frontmatter (mapas en profundidad) y añade al cuerpo los enlaces que falten.

    Los códigos de ``cambios["paises"]`` se normalizan a mayúsculas. Si no cambia nada (mismo
    frontmatter y ningún enlace nuevo) devuelve la ruta sin escribir ni anotar en ``log.md``.
    Al reescribir, el frontmatter conserva su significado pero no sus comentarios ni el formato
    hecho a mano; el cuerpo se conserva byte a byte.
    """
    vault = Path(vault)
    ahora = _con_zona(ahora)
    if not isinstance(cambios, dict):
        raise ValueError("los cambios de PRODUCTO.md van en un mapa")  # noqa: TRY004 - error del llamador
    for e in enlaces:
        if not isinstance(e, str) or not e.strip() or "\n" in e or "\r" in e:
            raise ValueError(f"enlace mal escrito: {e!r} (una sola línea, no vacía)")
    limpios = _sin_protegidas(cambios)
    ruta, original, cuerpo = _leer(vault, p_id)
    meta = _fusionar(original, limpios, "")
    presentes = {linea.strip() for linea in cuerpo.splitlines()}
    nuevos = []
    for e in (x.strip() for x in enlaces):
        if e not in presentes:
            nuevos.append(e)
            presentes.add(e)
    if not nuevos and meta == original:
        return ruta
    if nuevos:
        cuerpo = cuerpo.rstrip("\n") + "\n\n" + "\n".join(nuevos) + "\n"
    que = f"{p_id}: actualiza {', '.join(map(str, cambios)) or 'enlaces'}"
    if nuevos:
        que += f" (+{len(nuevos)} enlaces)"
    return _guardar(vault, ruta, meta, cuerpo, skill, que, ahora)
