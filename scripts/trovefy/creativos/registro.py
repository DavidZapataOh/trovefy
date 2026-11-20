"""``QA.md`` de la tanda (plan 21, Tareas 8–10): solo de añadir, lo escribe ``trovefy creativos``.

Cada anotación es una sección ``## <tipo> · AAAA-MM-DD HH:MM`` (``automatica``, ``revisor``, ``nativo`` o
``whisper``) con líneas ``- clave: valor`` que escribe este módulo y, debajo, el texto citado con ``> `` (así un
texto del agente no puede fingir otra sección). Cada veredicto queda atado a lo que se revisó: la **huella** de la
tanda (``brief.yaml`` y el ``sha256`` de cada pieza) para la automática, el revisor y el nativo, y el ``sha256`` del
vídeo para Whisper. Cambiar un byte de una pieza deja esos veredictos sin valor.
"""

from __future__ import annotations

import fcntl
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import ZONA_NEGOCIO

NOMBRE = "QA.md"
TIPOS = ("automatica", "revisor", "nativo", "whisper")
_CABECERA = re.compile(r"^## (automatica|revisor|nativo|whisper) · (\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
_DATO = re.compile(r"^- ([a-z_0-9]+): (.*)$")


@dataclass(frozen=True)
class Seccion:
    tipo: str
    fecha: str
    datos: dict[str, str] = field(default_factory=dict)


def sha_archivo(ruta: Path) -> str | None:
    try:
        with open(ruta, "rb") as f:
            h = hashlib.sha256()
            for bloque in iter(lambda: f.read(1 << 20), b""):
                h.update(bloque)
        return h.hexdigest()
    except OSError:
        return None


def archivo_pieza(carpeta: Path, ad: str, tipo: str) -> Path:
    return Path(carpeta) / f"{ad}.{'mp4' if tipo == 'video' else 'jpg'}"


def huella(carpeta: Path, piezas: list[tuple[str, str]]) -> str:
    """sha256 de ``brief.yaml`` y del ``sha256`` de cada pieza (``(ad, tipo)``), en orden."""
    h = hashlib.sha256()
    h.update((sha_archivo(Path(carpeta) / "brief.yaml") or "sin-brief").encode())
    for ad, tipo in sorted(piezas):
        h.update(f"|{ad}:{sha_archivo(archivo_pieza(carpeta, ad, tipo)) or 'falta'}".encode())
    return h.hexdigest()


def _una_linea(v: object) -> str:
    return re.sub(r"[\r\n]+", " ", str(v))


def anotar(carpeta: Path, tipo: str, datos: dict[str, object], texto: str, ahora: datetime) -> Path:
    if tipo not in TIPOS:
        raise ValueError(f"tipo de QA desconocido: {tipo}")
    if ahora.tzinfo is None:
        raise ValueError("fecha sin zona horaria")
    cuerpo = [f"## {tipo} · {ahora.astimezone(ZONA_NEGOCIO):%Y-%m-%d %H:%M}", ""]
    cuerpo += [f"- {k}: {_una_linea(v)}" for k, v in datos.items()]
    if texto.strip():
        cuerpo += [""] + [f"> {x}" if x else ">" for x in texto.rstrip("\n").split("\n")]
    bloque = "\n".join(cuerpo) + "\n\n"
    if buscar_secreto(bloque):
        raise ValueError("la anotación trae algo con forma de secreto; no se guarda")
    ruta = Path(carpeta) / NOMBRE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            if not f.read(1):
                f.write(f"# QA de la tanda {Path(carpeta).name}\n\n")
            f.write(bloque)
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return ruta


def leer(carpeta: Path) -> list[Seccion]:
    ruta = Path(carpeta) / NOMBRE
    if not ruta.is_file():
        return []
    salida: list[Seccion] = []
    actual: Seccion | None = None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        m = _CABECERA.match(linea)
        if m:
            actual = Seccion(m.group(1), m.group(2), {})
            salida.append(actual)
            continue
        d = _DATO.match(linea)
        if actual is not None and d and d.group(1) not in actual.datos:
            actual.datos[d.group(1)] = d.group(2)
    return salida


def ultima(secciones: list[Seccion], tipo: str, **filtro: str) -> Seccion | None:
    for s in reversed(secciones):
        if s.tipo == tipo and all(s.datos.get(k) == v for k, v in filtro.items()):
            return s
    return None


@dataclass(frozen=True)
class EstadoQA:
    huella: str
    automatica: str | None
    revisor: str | None
    nativo: str | None
    whisper: dict[str, str | None]
    hoja: str | None

    def faltan(self) -> list[str]:
        f = []
        if self.automatica != "ok":
            f.append(f"QA automática: {self.automatica or 'sin pasar sobre la tanda actual'}")
        if self.revisor != "ok":
            f.append(f"revisor: {self.revisor or 'sin veredicto sobre la tanda actual'}")
        if self.nativo != "ok":
            f.append(f"nativo: {self.nativo or 'sin veredicto sobre la tanda actual'}")
        for ad, e in self.whisper.items():
            if e != "ok":
                f.append(f"Whisper {ad}: {e or 'sin medir sobre el vídeo actual'}")
        return f

    @property
    def ok(self) -> bool:
        return not self.faltan()


def estado(carpeta: Path, piezas: list[tuple[str, str]]) -> EstadoQA:
    """Veredictos que valen hoy: los anotados sobre la huella actual (Whisper, sobre el vídeo actual)."""
    secciones = leer(carpeta)
    h = huella(carpeta, piezas)

    def veredicto(tipo: str) -> str | None:
        s = ultima(secciones, tipo, huella=h)
        return s.datos.get("estado") if s else None

    whisper = {}
    for ad, tipo in piezas:
        if tipo != "video":
            continue
        s = ultima(secciones, "whisper", ad=ad, sha256=sha_archivo(archivo_pieza(carpeta, ad, tipo)) or "falta")
        whisper[ad] = s.datos.get("estado") if s else None
    rev = ultima(secciones, "revisor", huella=h)
    return EstadoQA(h, veredicto("automatica"), veredicto("revisor"), veredicto("nativo"), whisper,
                    rev.datos.get("hoja") if rev else None)
