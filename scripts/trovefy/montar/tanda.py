"""Leer la tanda aprobada del plan 21 y elegir los anuncios del test (plan 22, Tarea 1).

**Qué hacen los vídeos:** 10 anuncios por país, con un ``.txt`` por anuncio con «el guion, el copy largo, el título, la
descripción y los UTM» (L1 0:56:40; aquí, el ``manifest.csv`` del 21). El test usa **5 conjuntos con 1 anuncio cada uno
a US$ 5** (C1 0:18:10); los otros 5 quedan de reserva para las renovaciones cada 48 h (T3 18:55). Sin desvío.

Manda el 21 (resolución 1 de la fase 3): imagen o vídeo sale de ``tipo``; el patrón es ``hook``; ``archivo`` y
``miniatura`` son relativas al **vault**; el nombre del anuncio y del conjunto es la columna ``nombre`` tal cual; el
``texto`` admite hasta ``texto.principal_max`` de ``config/creativos.yaml``. Tanda aprobada (resolución 2) = la tanda
vigente, cerrada, con el ``manifest_sha256`` igual al del archivo y el gate ``creativos`` de `/listo` en ``ok``. Qué
se monta (resolución 3): las filas ``uso: test`` en su ``orden``. URL (resolución 4): ``url_base`` = ``url`` sin el
sufijo literal ``?``/``&`` + ``PLANTILLA_UTM`` y ``url_tags`` = ``PLANTILLA_UTM``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from trovefy.montar import TandaInvalida
from trovefy.tracking.modelo import PLANTILLA_UTM
from trovefy.vault import frontmatter
from trovefy.vault.producto import ruta_producto

EXT_IMAGEN = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})  # las mismas que trovefy_ejecutor.montaje
EXT_VIDEO = frozenset({".mp4", ".mov", ".m4v"})
COLUMNAS = ("id", "nombre", "uso", "orden", "angulo", "tipo", "archivo", "sha256", "miniatura", "texto", "titulo",
            "descripcion", "cta", "url")
_AD = re.compile(r"AD\d{2}")
_TANDA = re.compile(r"t(\d{1,3})")
_CTA = re.compile(r"[A-Z][A-Z0-9_]{0,59}")


@dataclass(frozen=True)
class PiezaTanda:
    id: str
    nombre: str
    uso: str
    orden: int
    angulo: str
    tipo: str  # imagen | video
    ruta: str  # relativa al vault
    miniatura: str | None  # relativa al vault (en las imágenes, la propia imagen)
    sha256: str
    texto: str
    titulo: str
    descripcion: str
    cta: str
    url_base: str
    url_tags: str


@dataclass(frozen=True)
class Tanda:
    nombre: str  # t1, t2…
    grupo: int  # el N de G<N> es el número de la tanda (resolución 6)
    carpeta: Path
    piezas: tuple[PiezaTanda, ...]
    aprobada: bool
    motivo: str | None
    manifest_sha256: str


def _limites(vault: Path) -> tuple[int, int, int]:
    from trovefy.creativos.config import cargar_config, cargar_plantilla

    ruta = Path(vault) / "config" / "creativos.yaml"
    cfg = cargar_config(vault) if ruta.is_file() else cargar_plantilla()
    return cfg.principal_max, cfg.titulo_max, cfg.descripcion_max


def bloque_pais(vault: Path, p_id: str, pais: str) -> dict:
    """``paises.<PAIS>`` de ``PRODUCTO.md`` ({} si no hay)."""
    ruta = ruta_producto(vault, p_id)
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md")
    meta, _ = frontmatter.leer(ruta)
    paises = meta.get("paises") if isinstance(meta, dict) else None
    b = paises.get(pais) if isinstance(paises, dict) else None
    return b if isinstance(b, dict) else {}


def _archivo_seguro(vault: Path, carpeta: Path, rel: str, quien: str, *, lectura_grupo: bool = True) -> Path:
    """La ruta (relativa al vault) existe, es un archivo regular, no es enlace en ningún tramo y cae dentro de la
    tanda; con ``lectura_grupo``, el ejecutor (grupo trovefy) puede leerla."""
    if not rel or rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
        raise TandaInvalida(f"{quien}: ruta no válida «{rel}» (relativa al vault, sin «..»)")
    ruta = Path(vault) / rel
    try:
        dentro = ruta.parent.resolve(strict=True) == carpeta.resolve(strict=True) or (
            carpeta.resolve(strict=True) in ruta.parent.resolve(strict=True).parents)
    except OSError:
        raise TandaInvalida(f"{quien}: no existe {rel}") from None
    if not dentro:
        raise TandaInvalida(f"{quien}: {rel} no está dentro de la tanda {carpeta.name}")
    actual = Path(vault)
    for parte in Path(rel).parts:
        actual = actual / parte
        try:
            st = os.lstat(actual)
        except OSError:
            raise TandaInvalida(f"{quien}: no existe {rel}") from None
        if stat.S_ISLNK(st.st_mode):
            raise TandaInvalida(f"{quien}: {rel} es (o pasa por) un enlace simbólico")
    if not stat.S_ISREG(st.st_mode):
        raise TandaInvalida(f"{quien}: {rel} no es un archivo")
    if lectura_grupo and not st.st_mode & 0o040:
        raise TandaInvalida(f"{quien}: el ejecutor no puede leer {rel} (falta la lectura de grupo: chmod 0640)")
    return ruta


def _sha(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _url(url: str, host_landing: str | None, quien: str) -> tuple[str, str]:
    for sep in ("?", "&"):
        sufijo = sep + PLANTILLA_UTM
        if url.endswith(sufijo):
            base = url[: -len(sufijo)]
            break
    else:
        raise TandaInvalida(f"{quien}: la url no termina en la plantilla UTM literal de §4.9 (utm_source=fb…)")
    if not base.startswith("https://") or any(c.isspace() for c in base):
        raise TandaInvalida(f"{quien}: la url debe ser https:// y sin espacios")
    if host_landing is None:
        raise TandaInvalida(f"{quien}: no medido: sin paises.<PAIS>.landing.url en PRODUCTO.md no se comprueba el host")
    if (urlsplit(base).hostname or "").lower() != host_landing:
        raise TandaInvalida(f"{quien}: la url va a {urlsplit(base).hostname}, no a la landing ({host_landing})")
    return base, PLANTILLA_UTM


def _pieza(vault: Path, carpeta: Path, fila: dict, n: int, limites: tuple[int, int, int],
           host: str | None) -> PiezaTanda:
    quien = f"manifest.csv fila {n} ({fila.get('id') or '?'})"
    ad = fila.get("id") or ""
    if not _AD.fullmatch(ad):
        raise TandaInvalida(f"{quien}: id «{ad}» no es ADnn")
    try:
        orden = int(fila.get("orden") or "")
    except ValueError:
        raise TandaInvalida(f"{quien}: orden «{fila.get('orden')}» no es un entero") from None
    tipo = fila.get("tipo") or ""
    if tipo not in ("imagen", "video"):
        raise TandaInvalida(f"{quien}: tipo «{tipo}» (imagen o video)")
    principal_max, titulo_max, descripcion_max = limites
    for campo, maximo in (("texto", principal_max), ("titulo", titulo_max), ("descripcion", descripcion_max)):
        v = fila.get(campo) or ""
        if not v.strip():
            raise TandaInvalida(f"{quien}: falta {campo}")
        if len(v) > maximo:
            raise TandaInvalida(f"{ad}: {campo} {len(v)} > {maximo}")
    nombre = (fila.get("nombre") or "").strip()
    if not nombre or len(nombre) > 200:
        raise TandaInvalida(f"{quien}: falta el nombre del anuncio (ADnn G<N> <ángulo>)")
    archivo = fila.get("archivo") or ""
    ruta = _archivo_seguro(vault, carpeta, archivo, quien)
    ext = ruta.suffix.lower()
    if (tipo == "imagen" and ext not in EXT_IMAGEN) or (tipo == "video" and ext not in EXT_VIDEO):
        raise TandaInvalida(f"{quien}: tipo {tipo} con un archivo {ext or 'sin extensión'}")
    sha = _sha(ruta)
    if sha != (fila.get("sha256") or ""):
        raise TandaInvalida(f"{quien}: {archivo} cambió después de cerrar la tanda (sha256 distinto)")
    miniatura: str | None = fila.get("miniatura") or None
    if tipo == "video":
        if not miniatura:
            raise TandaInvalida(f"{quien}: vídeo sin miniatura")
        _archivo_seguro(vault, carpeta, miniatura, quien, lectura_grupo=False)
    elif miniatura:
        _archivo_seguro(vault, carpeta, miniatura, quien, lectura_grupo=False)
    else:
        miniatura = archivo
    cta = (fila.get("cta") or "").strip()
    if cta and not _CTA.fullmatch(cta):
        raise TandaInvalida(f"{quien}: cta «{cta}» no es un código de Meta (LEARN_MORE, SHOP_NOW…)")
    base, tags = _url(fila.get("url") or "", host, quien)
    return PiezaTanda(ad, nombre, (fila.get("uso") or "").strip(), orden, (fila.get("angulo") or "").strip(), tipo,
                      archivo, miniatura, sha, fila["texto"], fila["titulo"], fila["descripcion"], cta, base, tags)


def _aprobada(vault: Path, p_id: str, pais: str, tanda: str, bloque: dict, sha: str) -> tuple[bool, str | None]:
    c = bloque.get("creativos") if isinstance(bloque.get("creativos"), dict) else {}
    vigente = c.get("vigente")
    t = (c.get("tandas") or {}).get(tanda) if isinstance(c.get("tandas"), dict) else None
    if not isinstance(t, dict):
        return False, f"la tanda {tanda} no está registrada en PRODUCTO.md (/trovefy:creativos)"
    if not t.get("cerrada"):
        return False, f"la tanda {tanda} no está cerrada (/trovefy:creativos)"
    if t.get("manifest_sha256") != sha:
        return False, f"el manifest.csv de {tanda} cambió después de cerrarla"
    if vigente != tanda:
        return False, f"la tanda vigente es {vigente or 'ninguna'}, no {tanda}"
    from trovefy.listo import gates
    from trovefy.listo.ficha import leer_ficha

    g = gates.gate_creativos(leer_ficha(vault, p_id, pais))
    if g.estado != "ok":
        return False, f"el gate creativos de /listo no está en ok: {g.texto}"
    return True, None


def leer_tanda(vault: Path, p_id: str, pais: str, tanda: str) -> Tanda:
    """La tanda con todas sus piezas validadas. ``TandaInvalida`` si algo no se puede montar; ``aprobada`` dice si
    pasó la revisión del 21 (con ``motivo`` si no)."""
    vault = Path(vault)
    m = _TANDA.fullmatch(tanda or "")
    if m is None:
        raise TandaInvalida(f"tanda «{tanda}»: se escribe t1, t2…")
    carpeta = ruta_producto(vault, p_id).parent / "creativos" / pais / tanda
    manifiesto = carpeta / "manifest.csv"
    try:
        crudo = manifiesto.read_bytes()
    except OSError:
        raise TandaInvalida(f"no existe {manifiesto.relative_to(vault).as_posix()}: /trovefy:creativos") from None
    lector = csv.DictReader(io.StringIO(crudo.decode("utf-8")))
    faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
    if faltan:
        raise TandaInvalida(f"manifest.csv: faltan las columnas {', '.join(faltan)}")
    bloque = bloque_pais(vault, p_id, pais)
    landing = (bloque.get("landing") or {}).get("url") if isinstance(bloque.get("landing"), dict) else None
    host = (urlsplit(landing).hostname or "").lower() if isinstance(landing, str) and landing else None
    limites = _limites(vault)
    piezas = tuple(_pieza(vault, carpeta, fila, n, limites, host) for n, fila in enumerate(lector, start=2))
    ids = [p.id for p in piezas]
    if len(set(ids)) != len(ids):
        raise TandaInvalida("manifest.csv: hay ids repetidos")
    nombres = [p.nombre for p in piezas]
    if len(set(nombres)) != len(nombres):
        raise TandaInvalida("manifest.csv: hay nombres de anuncio repetidos")
    sha = hashlib.sha256(crudo).hexdigest()
    aprobada, motivo = _aprobada(vault, p_id, pais, tanda, bloque, sha)
    return Tanda(tanda, int(m.group(1)), carpeta, piezas, aprobada, motivo, sha)


def elegir(piezas: Sequence[PiezaTanda], *, uso: str = "test", ids: Sequence[str] | None = None,
           n: int | None = None) -> tuple[PiezaTanda, ...]:
    """Las filas ``uso`` en su ``orden`` (resolución 3). Con ``ids``, esas y en ese orden (solo entre las de la
    tanda). Con ``n``, exige exactamente ``n``."""
    if ids:
        por_id = {p.id: p for p in piezas}
        if len(set(ids)) != len(ids):
            raise TandaInvalida("--anuncios con ids repetidos")
        ajenos = [i for i in ids if i not in por_id]
        if ajenos:
            raise TandaInvalida(f"--anuncios: {', '.join(ajenos)} no está en la tanda")
        elegidas = tuple(por_id[i] for i in ids)
    else:
        elegidas = tuple(sorted((p for p in piezas if p.uso == uso), key=lambda p: (p.orden, p.id)))
    if n is not None and len(elegidas) != n:
        raise TandaInvalida(f"la tanda trae {len(elegidas)} piezas de {uso}; el test lleva {n}")
    if not elegidas:
        raise TandaInvalida(f"la tanda no trae piezas de {uso}")
    return elegidas
