"""Medios de la landing: imágenes propias del entregable a WebP y vistas previas reales del PDF vigente.

Todo va a ``landing/<PAIS>/assets/`` en modo 0640 (contrato 10) con ``escribir_medio`` del plan 17, y con
dos manifiestos: ``medios.json`` (el origen de cada archivo, contrato 4) y ``vistas.json`` (de qué PDF,
por su SHA-256, son las vistas previas: si el PDF cambia, ``validar`` lo detecta). Órdenes externas
(``pdfinfo``, ``pdftoppm``, ``ffmpeg``) en lista, sin ``shell``, con ``check`` y tope de tiempo.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from trovefy.landing.constantes import ANCHOS_IMAGEN, TIMEOUT_ORDEN_S
from trovefy.landing.entrada import DatosLanding, ruta_landing
from trovefy.pdf.render import PdfinfoNoMedido, paginas_pdfinfo
from trovefy.producto.medios import escribir_medio
from trovefy.vault.escritura import anadir_log
from trovefy.vault.producto import secreto_en

# «fuente»: un .woff2 OFL copiado a assets/ (resolución 19); este módulo aún no lo produce.
Origen = Literal["entregable", "vista_pdf", "propio", "fuente"]
ORIGENES = ("entregable", "vista_pdf", "propio", "fuente")
MANIFIESTO = "medios.json"
VISTAS = "vistas.json"
FIJOS = ("estilo.css", "utm.js", MANIFIESTO, VISTAS)  # archivos de assets/ que no son medios


@dataclass(frozen=True)
class Medio:
    archivo: str
    origen: Origen
    fuente: str
    ancho: int
    sha256: str


def _correr(ejecutar, orden: list[str]) -> None:
    ejecutar(orden, check=True, timeout=TIMEOUT_ORDEN_S, capture_output=True)


def _a_webp(ejecutar, origen: Path, destino: Path, ancho: int) -> None:
    _correr(ejecutar, ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(origen),
                       "-vf", f"scale={ancho}:-2", "-c:v", "libwebp", "-q:v", "75", str(destino)])


def _medio(ruta: Path, origen: Origen, fuente: str, ancho: int) -> Medio:
    return Medio(ruta.name, origen, fuente, ancho, hashlib.sha256(ruta.read_bytes()).hexdigest())


def _nombre_vista(n: int, ancho: int) -> str:
    return f"vista-p{n}-{ancho}.webp"


def _nombre_propia(ruta: Path, ancho: int) -> str:
    return f"{ruta.stem}-{ancho}.webp"


def _sin_repetidos(nombres: list[str]) -> None:
    """``ValueError`` si dos salidas se llamarían igual (una pisaría a la otra); se mira antes de convertir."""
    vistos, repetidos = set(), []
    for n in nombres:
        if n in vistos or n in FIJOS:
            repetidos.append(n)
        vistos.add(n)
    if repetidos:
        raise ValueError(f"nombre de medio repetido: {', '.join(dict.fromkeys(repetidos))} (dos imágenes o páginas "
                         "darían el mismo archivo; renombra una en el entregable o no repitas páginas)")


def vistas_previas(pdf: Path, paginas: tuple[int, ...], destino: Path, ejecutar=subprocess.run, *,
                   total: int | None = None) -> list[Medio]:
    """``vista-p<N>-<W>.webp`` por página y ancho; ``ValueError`` si una página no existe en el PDF o se repite."""
    pdf, destino = Path(pdf), Path(destino)
    _sin_repetidos([_nombre_vista(n, w) for n in paginas for w in ANCHOS_IMAGEN])
    if total is None:
        try:
            total = paginas_pdfinfo(pdf, correr=ejecutar)
        except PdfinfoNoMedido as exc:
            raise ValueError(f"páginas del PDF: {exc}") from None
    if not paginas:
        raise ValueError("hace falta al menos una página para la vista previa")
    fuera = [n for n in paginas if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= total]
    if fuera:
        raise ValueError(f"página {fuera[0]} fuera del PDF ({pdf.name} tiene {total} páginas)")
    destino.mkdir(parents=True, exist_ok=True)
    salida = []
    with tempfile.TemporaryDirectory(prefix="trovefy-vista-") as tmp:
        for n in paginas:
            prefijo = Path(tmp) / f"p{n}"
            _correr(ejecutar, ["pdftoppm", "-f", str(n), "-l", str(n), "-scale-to-x", str(max(ANCHOS_IMAGEN)),
                               "-scale-to-y", "-1", "-png", "-singlefile", str(pdf), str(prefijo)])
            for ancho in ANCHOS_IMAGEN:
                ruta = destino / _nombre_vista(n, ancho)
                _a_webp(ejecutar, prefijo.with_suffix(".png"), ruta, ancho)
                salida.append(_medio(ruta, "vista_pdf", f"{pdf.name}#p{n}", ancho))
    return salida


def _del_entregable(ruta: Path) -> str:
    """``entregable/…`` relativo al producto si ``ruta`` cae bajo ``productos/<p-id>/entregable/``."""
    ruta = Path(ruta)
    if ".." not in ruta.parts and not ruta.is_symlink():
        partes = ruta.parts
        for i in range(len(partes) - 2):
            if partes[i] == "productos" and partes[i + 2] == "entregable" and len(partes) > i + 3:
                return "/".join(partes[i + 2:])
    raise ValueError(f"solo imágenes propias del entregable: {ruta}")


def imagenes_propias(imagenes: tuple[Path, ...], destino: Path, ejecutar=subprocess.run) -> list[Medio]:
    """Cada imagen del entregable a ``<nombre>-<W>.webp`` por ancho; otra ruta → ``ValueError``."""
    fuentes = [(Path(p), _del_entregable(Path(p))) for p in imagenes]  # se comprueban todas antes de nada
    _sin_repetidos([_nombre_propia(r, w) for r, _ in fuentes for w in ANCHOS_IMAGEN])
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    salida = []
    for ruta, rel in fuentes:
        for ancho in ANCHOS_IMAGEN:
            dest = destino / _nombre_propia(ruta, ancho)
            _a_webp(ejecutar, ruta, dest, ancho)
            salida.append(_medio(dest, "entregable", rel, ancho))
    return salida


def _json(datos: dict) -> bytes:
    if secreto_en(datos):
        raise ValueError("el manifiesto trae algo con forma de secreto; no se guarda")
    return (json.dumps(datos, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _previos(assets: Path) -> set[str]:
    try:
        datos = json.loads((assets / MANIFIESTO).read_text(encoding="utf-8"))
        return {m["archivo"] for m in datos.get("medios", []) if isinstance(m, dict) and "archivo" in m}
    except (FileNotFoundError, ValueError, AttributeError, TypeError):
        return set()


def preparar_medios(vault: Path, datos: DatosLanding, paginas: tuple[int, ...] = (1, 2, 3),
                    ejecutar=subprocess.run) -> Path:
    """Vistas previas e imágenes propias en ``landing/<PAIS>/assets/`` con sus manifiestos; devuelve la carpeta."""
    vault = Path(vault)
    assets = ruta_landing(vault, datos.p_id, datos.pais) / "assets"
    _sin_repetidos([_nombre_vista(n, w) for n in paginas for w in ANCHOS_IMAGEN]
                   + [_nombre_propia(Path(r), w) for r in datos.imagenes for w in ANCHOS_IMAGEN])
    previos = _previos(assets) if assets.is_dir() else set()
    with tempfile.TemporaryDirectory(prefix="trovefy-medios-") as tmp:
        tmp = Path(tmp)
        medios = vistas_previas(datos.pdf, tuple(paginas), tmp, ejecutar, total=datos.pdf_paginas)
        medios += imagenes_propias(datos.imagenes, tmp, ejecutar)
        for m in medios:
            if escribir_medio(assets / m.archivo, (tmp / m.archivo).read_bytes(), base=vault) != m.sha256:
                raise ValueError(f"{m.archivo} cambió mientras se copiaba")
    escribir_medio(assets / MANIFIESTO, _json({"version": 1, "medios": [asdict(m) for m in medios]}), base=vault)
    escribir_medio(assets / VISTAS, _json({"pdf": datos.pdf.name, "sha256": datos.pdf_sha256,
                                          "paginas": list(paginas)}), base=vault)
    actuales = {m.archivo for m in medios}
    for viejo in sorted(previos - actuales):  # medios de una tanda anterior que ya no están en el manifiesto
        if "/" not in viejo and viejo not in FIJOS:
            (assets / viejo).unlink(missing_ok=True)
    rel = assets.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{datos.p_id} {datos.pais}: medios ({len(medios)} webp; vistas de "
               f"{datos.pdf.name} págs {','.join(map(str, paginas))})", [f"{rel}/{MANIFIESTO}", f"{rel}/{VISTAS}"])
    return assets
