"""PDF de una pieza con WeasyPrint (D-15): versiones, ``pdfinfo`` y desbordes de páginas fijas.

Orden de ``producir_pdf`` (sin gates no hay PDF): ensamblar → escribir ``fuente/<nombre>.html`` →
``evaluar`` → ``comprobar_fuentes`` → WeasyPrint → ``pdfinfo``. WeasyPrint se importa tarde: si falta
o no encuentra Pango, ``PdfNoDisponible`` con la orden ``apt`` guiada. El ``url_fetcher`` solo sirve
archivos ``file://`` resueltos dentro de la raíz de la pieza: nada sale a la red (Global Constraints).

Desbordes (Review Focus 4): cada página fija lleva ``<span id="ini-X">`` al principio y
``<span id="fin-X">`` al final. La página desborda (y el PDF no es apto) si el PDF los pone en páginas
distintas, si ``fin-X`` queda por debajo del margen inferior de ``.page`` (el contenido que sobra se
pinta fuera del papel) o si falta cualquiera de los dos: las páginas fijas esperadas salen del HTML
(``portada`` y cada ficha), así que un ancla perdida es desborde, nunca un aprobado. Nunca se recorta.

Escrituras (contrato 10): HTML, PDF y hoja de contactos se crean con ``escribir_exclusivo``: carpetas
revisadas desde el vault (ningún enlace simbólico), temporal ``O_EXCL|O_NOFOLLOW`` y ``link`` al nombre
final, que falla si ya existe. Así la versión se reserva de forma atómica (ruling M4) y nada se pisa.
"""

from __future__ import annotations

import errno
import mimetypes
import os
import re
import secrets
import stat
import subprocess
from collections.abc import Iterable
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
from trovefy.producto.medios import MODO_MEDIO, _carpeta_segura, leer_manifiesto
from trovefy.producto.rutas import PIEZA, pieza
from trovefy.vault.escritura import anadir_log
from trovefy.vault.producto import ruta_producto, secreto_en

ORDEN_PANGO = "sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0"
NO_PDFINFO = "no medido: falta pdfinfo (sudo apt install -y poppler-utils)"
MARGEN_INFERIOR_MM = 20  # padding inferior de .page en templates/pdf/base.css (un test lo comprueba)
_PX_POR_MM = 96 / 25.4  # WeasyPrint da las anclas en px CSS
_TOLERANCIA_PX = 0.5
_ANCLA_FIJA = re.compile(r"""\bid\s*=\s*["'](?:ini|fin)-([A-Za-z0-9_-]+)["']""")
_VERSIONES_MAX = 1000
_SKILL = "producto"
_PAGES = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
_IDIOMA = re.compile(r"[a-z]{2}", re.ASCII)


class PdfNoDisponible(RuntimeError):
    """WeasyPrint no importa o no encuentra Pango."""


class PdfinfoNoMedido(RuntimeError):
    """``pdfinfo`` falta, falla o da una salida que no se entiende; el mensaje es el «no medido: …»."""


@dataclass(frozen=True)
class Ancla:
    pagina: int  # índice de la página (desde 0)
    y: float  # px CSS desde el borde superior de la página
    limite: float  # alto de la página menos el padding inferior de .page: un fin-X más abajo desborda


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


def escribir_exclusivo(ruta: Path, datos: bytes, *, base: Path) -> None:
    """Crea ``ruta`` (0640) con ``datos`` sin pisar nada ni seguir enlaces.

    Las carpetas entre ``base`` (el vault) y ``ruta.parent`` se revisan y crean una a una: un enlace
    simbólico es ``ValueError`` y no se escribe nada. El contenido va a un temporal ``O_EXCL|O_NOFOLLOW``
    y se publica con ``os.link``, que es atómico y falla con ``FileExistsError`` si ``ruta`` ya existe
    (también si es un enlace colgante). El temporal se borra siempre.
    """
    ruta = Path(os.path.abspath(ruta))
    _carpeta_segura(Path(base), ruta.parent, crear=True)
    tmp = ruta.parent / f".{ruta.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fchmod(f.fileno(), MODO_MEDIO)
            os.fsync(f.fileno())
        os.link(tmp, ruta, follow_symlinks=False)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _reservar_html(fuente: Path, base: Path, ficha: Ficha, pieza_id: str, html: str) -> tuple[int, Path]:
    """Escribe ``fuente/<nombre>-vN.html`` con la primera N libre desde ``siguiente_version`` y la devuelve.
    Dos ejecuciones a la vez nunca se quedan la misma N: la segunda recibe ``FileExistsError`` y sube."""
    raiz = fuente.parent
    version = siguiente_version(raiz, _slug_pieza(ficha, pieza_id), ficha.idioma)
    datos = html.encode("utf-8")
    for _ in range(_VERSIONES_MAX):
        ruta = fuente / f"{nombre_pdf(ficha, pieza_id, version).removesuffix('.pdf')}.html"
        try:
            escribir_exclusivo(ruta, datos, base=base)
        except FileExistsError:
            version = max(version + 1, siguiente_version(raiz, _slug_pieza(ficha, pieza_id), ficha.idioma))
            continue
        return version, ruta
    raise RuntimeError(f"no hay versión libre para {nombre_pdf(ficha, pieza_id, version)} "
                       f"tras {_VERSIONES_MAX} intentos")


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
        if not ruta.is_relative_to(self.raiz):
            raise ValueError(f"recurso fuera de la pieza bloqueado: {url}")
        return ruta

    def _leer(self, ruta: Path, url: str) -> bytes:
        """Lee sin seguir un enlace en el último componente y solo si el descriptor es un archivo regular
        (si algo cambia entre ``realpath`` y la apertura, no se sigue)."""
        try:
            fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ValueError(f"recurso que es un enlace simbólico bloqueado: {url}") from None
            raise ValueError(f"recurso de la pieza ilegible: {url} ({exc.strerror})") from None
        try:
            regular = stat.S_ISREG(os.fstat(fd).st_mode)
        except BaseException:
            os.close(fd)
            raise
        if not regular:
            os.close(fd)
            raise ValueError(f"recurso que no es un archivo regular bloqueado: {url}")
        with os.fdopen(fd, "rb") as f:
            return f.read()

    def fetch(self, url: str, headers=None):
        ruta = self._ruta(url)
        datos = self._leer(ruta, url)
        from weasyprint.urls import URLFetcherResponse

        tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        return URLFetcherResponse(ruta.as_uri(), datos, {"Content-Type": tipo})

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


def _render(html: str, raiz: Path, destino: Path, base: Path) -> tuple[dict[str, Ancla], int]:
    weasyprint = _weasyprint()
    raiz = Path(raiz)
    documento = weasyprint.HTML(string=html, base_url=str(raiz) + os.sep,
                                url_fetcher=fetcher_local(raiz)).render()
    anclas: dict[str, Ancla] = {}
    margen = MARGEN_INFERIOR_MM * _PX_POR_MM
    for i, pagina in enumerate(documento.pages):
        for nombre, posicion in pagina.anchors.items():
            anclas.setdefault(nombre, Ancla(i, float(posicion[1]), float(pagina.height) - margen))
    escribir_exclusivo(destino, documento.write_pdf(), base=base)
    return anclas, len(documento.pages)


def renderizar(html: str, raiz: Path, destino: Path, *, base: Path) -> dict[str, Ancla]:
    """Escribe el PDF en ``destino`` (0640, sin pisar uno que exista; las carpetas desde ``base`` no pueden
    ser enlaces) y devuelve las anclas ``{nombre: Ancla(página, y, límite)}``."""
    return _render(html, raiz, destino, base)[0]


def fijas_esperadas(html: str) -> tuple[str, ...]:
    """Páginas fijas que el HTML debe tener en el PDF: ``portada`` y cada ``X`` de un ``ini-X``/``fin-X``
    (las fichas). Sirve para que un ancla que no llega al PDF cuente como desborde."""
    return tuple(sorted({"portada", *_ANCLA_FIJA.findall(html)}))


def desbordes(anclas: dict[str, Ancla], esperadas: Iterable[str] = ()) -> tuple[str, ...]:
    """Cada página fija ``X`` (de ``esperadas`` o con alguna ancla) que desborda: falta ``ini-X`` o
    ``fin-X``, están en páginas distintas o ``fin-X`` queda por debajo de su límite."""
    nombres = set(esperadas)
    nombres |= {n[4:] for n in anclas if n.startswith(("ini-", "fin-"))}
    salida = []
    for x in nombres:
        ini, fin = anclas.get(f"ini-{x}"), anclas.get(f"fin-{x}")
        if ini is None or fin is None or ini.pagina != fin.pagina or fin.y > fin.limite + _TOLERANCIA_PX:
            salida.append(x)
    return tuple(sorted(salida))


def paginas_pdfinfo(pdf: Path, correr=subprocess.run) -> int:
    """Páginas según ``pdfinfo``. ``PdfinfoNoMedido`` si falta (``NO_PDFINFO``), si falla o si su salida no
    trae ``Pages:`` («no medido: pdfinfo falló (…)»)."""
    try:
        r = correr(["pdfinfo", str(pdf)], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise PdfinfoNoMedido(NO_PDFINFO) from None
    if r.returncode != 0:
        error = " ".join((r.stderr or "").split())[:200] or "sin mensaje"
        raise PdfinfoNoMedido(f"no medido: pdfinfo falló (código {r.returncode}: {error})")
    m = _PAGES.search(r.stdout or "")
    if not m:
        raise PdfinfoNoMedido("no medido: pdfinfo falló (salida sin «Pages:»)")
    return int(m.group(1))


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

    version, ruta_html = _reservar_html(fuente, vault, ficha, pieza_id, html)
    nombre = nombre_pdf(ficha, pieza_id, version)
    informe = evaluar(html, raiz=p.raiz, idioma=ficha.idioma, exigencia=ficha.exigencia,
                      tipo_pieza=pieza_ficha.tipo, paginas_objetivo=pieza_ficha.paginas_objetivo, cfg=cfg,
                      vault=vault)

    pdf, paginas, en_pdfinfo, desb, problemas = None, None, None, (), []
    if informe.pasa:
        problemas = comprobar_fuentes(html, familias, correr=correr)
        if not problemas:
            try:
                anclas, paginas = _render(html, p.raiz, p.raiz / nombre, vault)
            except PdfNoDisponible:
                anadir_log(vault, _SKILL, f"{p_id} {pieza_id} v{version}: sin PDF (WeasyPrint no disponible)",
                           [ruta_html.relative_to(vault).as_posix()], ahora=ahora)
                raise
            pdf = p.raiz / nombre
            desb = desbordes(anclas, fijas_esperadas(html))
            try:
                en_pdfinfo = paginas_pdfinfo(pdf, correr=correr)
            except PdfinfoNoMedido as exc:
                problemas.append(str(exc))
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
