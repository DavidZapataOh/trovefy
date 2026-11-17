"""PDF de una pieza con WeasyPrint (D-15): versiones, ``pdfinfo`` y desbordes de páginas fijas.

Orden de ``producir_pdf`` (sin gates no hay PDF): ensamblar → escribir ``fuente/<nombre>.html`` →
``evaluar`` → ``comprobar_fuentes`` → WeasyPrint → ``pdfinfo``. WeasyPrint se importa tarde: si falta
o no encuentra Pango, ``PdfNoDisponible`` con la orden ``apt`` guiada. El ``url_fetcher`` solo sirve
archivos ``file://`` resueltos dentro de la raíz de la pieza: nada sale a la red (Global Constraints).

Desbordes (Review Focus 4): cada página fija lleva ``<span id="ini-X">`` al principio y
``<span id="fin-X">`` al final. Si el PDF los pone en páginas distintas (o ``fin-X`` desaparece porque
WeasyPrint no partió la caja), la página desborda y el PDF no es apto. Nunca se recorta.
"""

from __future__ import annotations

import mimetypes
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from trovefy.modelar.salida import cargar_brandbook
from trovefy.pdf.fuentes import comprobar_fuentes
from trovefy.pdf.gates import Informe, evaluar
from trovefy.pdf.maqueta import ensamblar, familias_brandbook, tokens_brandbook
from trovefy.producto.config import ConfigProducto
from trovefy.producto.ficha import Ficha, leer_ficha
from trovefy.producto.medios import escribir_medio, leer_manifiesto
from trovefy.producto.rutas import PIEZA, pieza
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import ruta_producto, secreto_en

ORDEN_PANGO = "sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0"
NO_PDFINFO = "no medido: falta pdfinfo (sudo apt install -y poppler-utils)"
_SKILL = "producto"
_PAGES = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
_IDIOMA = re.compile(r"[a-z]{2}", re.ASCII)


class PdfNoDisponible(RuntimeError):
    """WeasyPrint no importa o no encuentra Pango."""


@dataclass(frozen=True)
class Producido:
    version: int
    html: Path
    pdf: Path | None
    informe: Informe
    paginas: int | None
    paginas_pdfinfo: int | None
    desbordes: tuple[str, ...]
    problemas: tuple[str, ...]
    apto: bool


# --- nombres y versiones ----------------------------------------------------------------------------


def _base(slug: str, idioma: str) -> str:
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError(f"slug mal escrito: «{slug}»")
    if not isinstance(idioma, str) or not _IDIOMA.fullmatch(idioma):
        raise ValueError(f"idioma mal escrito: «{idioma}»")
    return f"{slug}-{idioma}"


def siguiente_version(raiz: Path, slug: str, idioma: str) -> int:
    """Máximo ``vN`` de ``<slug>-<idioma>-vN.pdf`` (y de ``fuente/<slug>-<idioma>-vN.html``) + 1; empieza
    en 1. Cuenta también el HTML para que un intento sin PDF (gates o fuentes) no se sobrescriba."""
    raiz = Path(raiz)
    patron = re.compile(rf"{re.escape(_base(slug, idioma))}-v([1-9]\d*)\.(?:pdf|html)")
    versiones = [int(m.group(1)) for carpeta in (raiz, raiz / "fuente") if carpeta.is_dir()
                 for f in carpeta.iterdir() if (m := patron.fullmatch(f.name))]
    return max(versiones, default=0) + 1


def _slug_pieza(ficha: Ficha, pieza_id: str) -> str:
    if not isinstance(pieza_id, str) or not PIEZA.fullmatch(pieza_id):
        raise ValueError(f"pieza mal escrita: «{pieza_id}»")
    return ficha.slug if pieza_id == "principal" else f"{ficha.slug}-{pieza_id}"


def nombre_pdf(ficha: Ficha, pieza_id: str, version: int) -> str:
    """``respira-es-v1.pdf`` (principal), ``respira-bono-1-es-v1.pdf``, ``respira-u1-es-v1.pdf``…"""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"versión mal escrita: «{version}»")
    return f"{_base(_slug_pieza(ficha, pieza_id), ficha.idioma)}-v{version}.pdf"


# --- WeasyPrint -------------------------------------------------------------------------------------


class _FetcherLocal:
    """``url_fetcher`` de WeasyPrint: solo ``file://`` dentro de ``raiz`` (enlaces resueltos)."""

    _fail_on_errors = False  # lo lee weasyprint.urls.fetch: un recurso rechazado no para el render

    def __init__(self, raiz: Path) -> None:
        self.raiz = Path(os.path.realpath(raiz))

    def _ruta(self, url: str) -> Path:
        partes = urlsplit(url)
        if partes.scheme.lower() != "file" or partes.netloc not in ("", "localhost"):
            raise ValueError(f"recurso no local bloqueado: {url}")
        ruta = Path(os.path.realpath(url2pathname(unquote(partes.path))))
        if not ruta.is_relative_to(self.raiz) or not ruta.is_file():
            raise ValueError(f"recurso fuera de la pieza bloqueado: {url}")
        return ruta

    def fetch(self, url: str, headers=None):
        ruta = self._ruta(url)
        from weasyprint.urls import URLFetcherResponse

        tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        return URLFetcherResponse(ruta.as_uri(), ruta.read_bytes(), {"Content-Type": tipo})

    def __call__(self, url: str):
        return self.fetch(url)


def fetcher_local(raiz: Path) -> _FetcherLocal:
    return _FetcherLocal(raiz)


def _weasyprint():
    try:
        import weasyprint
    except (ImportError, OSError) as exc:
        raise PdfNoDisponible(
            f"no se puede hacer el PDF: WeasyPrint no carga ({exc}). En una terminal de Ubuntu (WSL) aparte: "
            f"`{ORDEN_PANGO}` y repite el paso 00 de /arranque") from None
    return weasyprint


def _render(html: str, raiz: Path, destino: Path) -> tuple[dict[str, int], int]:
    weasyprint = _weasyprint()
    raiz = Path(raiz)
    documento = weasyprint.HTML(string=html, base_url=str(raiz) + os.sep,
                                url_fetcher=fetcher_local(raiz)).render()
    anclas: dict[str, int] = {}
    for i, pagina in enumerate(documento.pages):
        for nombre in pagina.anchors:
            anclas.setdefault(nombre, i)
    escribir_medio(destino, documento.write_pdf(), base=raiz)
    return anclas, len(documento.pages)


def renderizar(html: str, raiz: Path, destino: Path) -> dict[str, int]:
    """Escribe el PDF en ``destino`` (0640) y devuelve las anclas ``{nombre: índice de página}``."""
    return _render(html, raiz, destino)[0]


def desbordes(anclas: dict[str, int]) -> tuple[str, ...]:
    """Cada ``X`` con ``ini-X`` y ``fin-X`` en páginas distintas, o sin ``fin-X``."""
    salida = []
    for nombre, pagina in anclas.items():
        if nombre.startswith("ini-"):
            x = nombre[4:]
            if anclas.get(f"fin-{x}") != pagina:
                salida.append(x)
    return tuple(sorted(salida))


def paginas_pdfinfo(pdf: Path, correr=subprocess.run) -> int | None:
    try:
        r = correr(["pdfinfo", str(pdf)], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    m = _PAGES.search(r.stdout or "") if r.returncode == 0 else None
    return int(m.group(1)) if m else None


# --- producir ---------------------------------------------------------------------------------------


def producir_pdf(vault: Path, p_id: str, pieza_id: str, cfg: ConfigProducto, correr=subprocess.run, *,
                 ahora: datetime) -> Producido:
    vault = Path(vault)
    ficha = leer_ficha(vault, p_id)
    pieza_ficha = next((x for x in ficha.piezas if x.id == pieza_id), None)
    if pieza_ficha is None:
        raise ValueError(f"la pieza {pieza_id} no está en FICHA.md: rehaz el paso 1")
    p = pieza(vault, p_id, pieza_id)
    ruta_bb = ruta_producto(vault, p_id).parent / "BRANDBOOK.md"
    tokens = tokens_brandbook(ruta_bb.read_text(encoding="utf-8"))
    familias = familias_brandbook(cargar_brandbook(vault, p_id))
    fuente = p.raiz / "fuente"
    html = ensamblar(p, ficha, pieza_ficha, tokens, familias, sorted((fuente / "secciones").glob("*.html")),
                     sorted((fuente / "fichas").glob("*.yaml")), leer_manifiesto(p.raiz))
    if secreto_en(html):
        raise ValueError("el HTML de la pieza trae algo con forma de secreto: no se escribe nada")

    version = siguiente_version(p.raiz, _slug_pieza(ficha, pieza_id), ficha.idioma)
    nombre = nombre_pdf(ficha, pieza_id, version)
    ruta_html = fuente / f"{nombre.removesuffix('.pdf')}.html"
    escribir_atomico(ruta_html, html)
    informe = evaluar(html, raiz=p.raiz, idioma=ficha.idioma, exigencia=ficha.exigencia,
                      tipo_pieza=pieza_ficha.tipo, paginas_objetivo=pieza_ficha.paginas_objetivo, cfg=cfg,
                      vault=vault)

    pdf, paginas, en_pdfinfo, desb, problemas = None, None, None, (), []
    if informe.pasa:
        problemas = comprobar_fuentes(html, familias, correr=correr)
        if not problemas:
            pdf = p.raiz / nombre
            anclas, paginas = _render(html, p.raiz, pdf)
            desb = desbordes(anclas)
            en_pdfinfo = paginas_pdfinfo(pdf, correr=correr)
            if en_pdfinfo is None:
                problemas.append(NO_PDFINFO)
    apto = (informe.pasa and not problemas and not desb and en_pdfinfo is not None and en_pdfinfo == paginas)

    if pdf is None:
        motivo = "no pasa los gates" if not informe.pasa else "problemas de fuentes"
        que = f"{p_id} {pieza_id} v{version}: sin PDF ({motivo}; puntuación {informe.puntuacion})"
    else:
        que = (f"{p_id} {pieza_id} v{version}: PDF de {paginas} páginas, "
               f"{'apto' if apto else 'no apto'}" + (f", desbordes: {', '.join(desb)}" if desb else ""))
    archivos = [x.relative_to(vault).as_posix() for x in (ruta_html, pdf) if x is not None]
    anadir_log(vault, _SKILL, que, archivos, ahora=ahora)
    return Producido(version, ruta_html, pdf, informe, paginas, en_pdfinfo, desb, tuple(problemas), apto)
