"""Registro de QC de una pieza en ``<raiz de la pieza>/QC.md`` y veredicto de los agentes.

Cada anotación es una sección ``## vN · <agente> · AAAA-MM-DD HH:MM`` que se añade al final y nunca
reescribe lo previo. Debajo van unas líneas ``- clave: valor`` (las escribe este módulo) y el texto libre
citado con ``> `` línea a línea: así un texto del agente no puede fingir otra sección ni otro veredicto.

El veredicto de ``revisor`` y ``nativo`` sale de la última línea no vacía de su respuesta
(``VEREDICTO: ok|corregir``, resolución 17). Cualquier otra cosa es ``None``: «no medido: el agente no
dio veredicto», que no deja cerrar la pieza (falla cerrado).
"""

import fcntl
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from trovefy.pdf.render import Producido
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, escribir_atomico
from trovefy.vault.producto import secreto_en

AGENTES = ("revisor", "nativo")
REGISTROS = ("gates", "maqueta", *AGENTES)
VEREDICTO = re.compile(r"^VEREDICTO: (ok|corregir)\s*$")
NO_MEDIDO = "no medido: el agente no dio veredicto"
NOMBRE = "QC.md"

Agente = Literal["gates", "maqueta", "revisor", "nativo"]
Veredicto = Literal["ok", "corregir"]

_CABECERA = re.compile(r"^## v([1-9]\d*) · (gates|maqueta|revisor|nativo) · (\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
_DATO = re.compile(r"^- ([a-z_0-9]+): (.*)$")
_CLAVE = re.compile(r"[a-z_0-9]+")


@dataclass(frozen=True)
class Seccion:
    version: int
    agente: str
    fecha: str
    veredicto: str | None
    datos: dict[str, str] = field(default_factory=dict)


def parsear_veredicto(texto: str | None) -> Veredicto | None:
    """``ok`` o ``corregir`` si la última línea no vacía es exactamente ``VEREDICTO: …``; si no, None."""
    if not isinstance(texto, str):
        return None
    lineas = [x for x in texto.splitlines() if x.strip()]
    if not lineas:
        return None
    m = VEREDICTO.match(lineas[-1])
    return m.group(1) if m else None  # type: ignore[return-value]


def ruta_qc(raiz: Path) -> Path:
    return Path(raiz) / NOMBRE


def _con_zona(ahora: datetime) -> datetime:
    if not isinstance(ahora, datetime) or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError(f"ahora sin zona horaria: {ahora!r} (usa un datetime con tzinfo)")
    return ahora


def _citar(texto: str) -> list[str]:
    return [f"> {x}" if x.strip() else ">" for x in texto.splitlines()]


def _una_linea(valor: object) -> str:
    return re.sub(r"\s+", " ", str(valor)).strip()


def _anotar(raiz: Path, version: int, agente: str, veredicto: str | None, texto: str, ahora: datetime,
            datos: dict[str, object] | None = None) -> Path:
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"versión mal escrita: «{version}»")
    if agente not in REGISTROS:
        raise ValueError(f"agente «{agente}» no admitido: {', '.join(REGISTROS)}")
    if veredicto not in ("ok", "corregir", None):
        raise ValueError(f"veredicto «{veredicto}» no admitido: ok, corregir o ninguno")
    if not isinstance(texto, str):
        raise ValueError("el texto del QC va en una cadena")  # noqa: TRY004 - error del llamador
    ahora = _con_zona(ahora)
    datos = {k: _una_linea(v) for k, v in (datos or {}).items()}
    if any(not _CLAVE.fullmatch(k) or k == "veredicto" for k in datos):
        raise ValueError("clave de dato mal escrita en el QC")
    # RevisionSecretosNoDisponible se propaga: sin revisión no se guarda nada
    if buscar_secreto(texto) or secreto_en(datos):
        raise ValueError("el texto trae algo con forma de secreto; no se guarda")

    lineas = [f"## v{version} · {agente} · {ahora.astimezone(ZONA_NEGOCIO):%Y-%m-%d %H:%M}", "",
              f"- veredicto: {veredicto or NO_MEDIDO}"]
    lineas += [f"- {k}: {v}" for k, v in datos.items()]
    citado = _citar(texto)
    if citado:
        lineas += ["", *citado]
    seccion = "\n".join(lineas) + "\n"

    raiz = Path(raiz)
    raiz.mkdir(parents=True, exist_ok=True)
    ruta = ruta_qc(raiz)
    with open(raiz / f".{NOMBRE}.lock", "a", encoding="utf-8") as cerrojo:
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        try:
            meta, cuerpo = frontmatter.leer(ruta) if ruta.is_file() else ({}, "")
            meta = dict(meta) if isinstance(meta, dict) else {}
            meta.setdefault("tipo", "qc")
            cuerpo = cuerpo.rstrip("\n")
            cuerpo = (cuerpo + "\n\n" if cuerpo else "") + seccion
            salida = frontmatter.renderizar(meta, cuerpo)
            if buscar_secreto(salida):
                raise ValueError("el texto trae algo con forma de secreto; no se guarda")
            escribir_atomico(ruta, salida)
        finally:
            fcntl.flock(cerrojo, fcntl.LOCK_UN)
    return ruta


def anotar_qc(raiz: Path, version: int, agente: Agente, veredicto: str | None, texto: str,
              ahora: datetime) -> Path:
    """Añade a ``QC.md`` la sección ``## vN · <agente> · fecha`` con el veredicto y el texto citado."""
    return _anotar(raiz, version, agente, veredicto, texto, ahora)


def anotar_producido(raiz: Path, r: Producido, ahora: datetime) -> Path:
    """Anota ``gates`` (puntuación y hallazgos) y ``maqueta`` (páginas, pdfinfo, desbordes, problemas)."""
    inf = r.informe
    hallazgos = [f"{h.gate} · {h.severidad} · {h.donde} · {h.texto}" for h in inf.hallazgos]
    _anotar(raiz, r.version, "gates", "ok" if inf.pasa else "corregir",
            "\n".join(hallazgos) or "sin hallazgos", ahora,
            {"puntuacion": inf.puntuacion, "palabras": inf.palabras, "paginas_estimadas": inf.paginas_estimadas})

    datos: dict[str, object] = {}
    if r.pdf is not None and Path(r.pdf).is_file():
        datos["pdf"] = Path(r.pdf).name
        datos["sha256"] = hashlib.sha256(Path(r.pdf).read_bytes()).hexdigest()
    else:
        datos["pdf"] = "sin PDF"
    datos["paginas"] = "no medido" if r.paginas is None else r.paginas
    datos["pdfinfo"] = "no medido" if r.paginas_pdfinfo is None else r.paginas_pdfinfo
    datos["desbordes"] = len(r.desbordes)
    notas = []
    if r.pdf is None:
        notas.append("sin PDF: " + ("no pasa los gates" if not inf.pasa else "problemas de fuentes"))
    notas += [f"desborda: {d}" for d in r.desbordes]
    notas += list(r.problemas)
    apto = bool(r.apto) and "sha256" in datos
    return _anotar(raiz, r.version, "maqueta", "ok" if apto else "corregir",
                   "\n".join(notas) or "sin problemas", ahora, datos)


def leer_qc(raiz: Path) -> list[Seccion]:
    """Secciones de ``QC.md`` en orden; [] si no existe."""
    ruta = ruta_qc(raiz)
    if not ruta.is_file():
        return []
    _, cuerpo = frontmatter.leer(ruta)
    secciones: list[Seccion] = []
    actual: dict | None = None
    en_datos = False
    for linea in cuerpo.splitlines():
        m = _CABECERA.match(linea)
        if m:
            if actual is not None:
                secciones.append(Seccion(**actual))
            actual = {"version": int(m.group(1)), "agente": m.group(2), "fecha": m.group(3),
                      "veredicto": None, "datos": {}}
            en_datos = True
            continue
        if actual is None or not en_datos:
            continue
        if not linea.strip() and not actual["datos"] and actual["veredicto"] is None:
            continue  # línea en blanco entre la cabecera y los datos
        d = _DATO.match(linea)
        if d is None:
            en_datos = False
            continue
        clave, valor = d.group(1), d.group(2).strip()
        if clave == "veredicto":
            actual["veredicto"] = valor if valor in ("ok", "corregir") else None
        else:
            actual["datos"][clave] = valor
    if actual is not None:
        secciones.append(Seccion(**actual))
    return secciones


def estado_qc(raiz: Path, version: int) -> dict[str, str | None]:
    """El último veredicto de cada registro (gates, maqueta, revisor, nativo) para esa versión."""
    estado: dict[str, str | None] = dict.fromkeys(REGISTROS)
    for s in leer_qc(raiz):
        if s.version == version:
            estado[s.agente] = s.veredicto
    return estado
