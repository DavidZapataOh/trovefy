"""Ingesta de fuentes a raw/ (capa inmutable): copia sin duplicados y HTML a texto."""

import hashlib
import re
import unicodedata
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from trovify.vault import frontmatter
from trovify.vault.escritura import ZONA_NEGOCIO

_IGNORAR = {"script", "style", "nav", "aside", "button", "svg", "noscript", "title", "head"}
_VACIOS = {"br", "hr", "img", "input", "meta", "link"}
_BLOQUES = {"p", "div", "section", "article", "main", "header", "footer", "ul", "ol",
            "blockquote", "pre", "details", "summary", "figure", "figcaption"}
_MAX_LINEAS_FRONTMATTER = 60


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorando = 0
        self._celdas: list[str] | None = None
        self._celda: list[str] | None = None

    def _emitir(self, texto: str) -> None:
        (self._celda if self._celda is not None else self.partes).append(texto)

    def handle_starttag(self, tag, attrs):
        if tag in _VACIOS:
            if not self._ignorando and tag in ("br", "hr"):
                self._emitir("\n")
            return
        if tag in _IGNORAR:
            self._ignorando += 1
            return
        if self._ignorando:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self.partes.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.partes.append("\n- ")
        elif tag == "tr":
            self._celdas = []
            self.partes.append("\n")
        elif tag in ("td", "th") and self._celdas is not None:
            self._celda = []
        elif tag in _BLOQUES or tag in ("table", "thead", "tbody"):
            self.partes.append("\n\n")

    def handle_endtag(self, tag):
        if tag in _VACIOS:
            return
        if tag in _IGNORAR:
            self._ignorando = max(0, self._ignorando - 1)
            return
        if self._ignorando:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self.partes.append("\n\n")
        elif tag in ("td", "th") and self._celda is not None and self._celdas is not None:
            self._celdas.append(re.sub(r"\s+", " ", "".join(self._celda)).strip())
            self._celda = None
        elif tag == "tr" and self._celdas is not None:
            if any(self._celdas):
                self.partes.append(" | ".join(self._celdas))
            self.partes.append("\n")
            self._celdas = None
        elif tag in _BLOQUES or tag == "table":
            self.partes.append("\n\n")

    def handle_data(self, data):
        if not self._ignorando:
            self._emitir(data if self._celda is not None else re.sub(r"[ \t\r\n]+", " ", data))


def html_a_texto(html: str) -> str:
    """HTML a texto plano con estructura Markdown mínima; sin CSS, JS ni navegación."""
    ex = _Extractor()
    ex.feed(html)
    ex.close()
    texto = "".join(ex.partes)
    lineas = [ln.strip() for ln in texto.split("\n")]
    texto = "\n".join(lineas)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto + "\n"


def _slug(nombre: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
    return slug or "fuente"


def _sha_de_frontmatter(ruta: Path) -> str | None:
    """Lee solo las primeras líneas del frontmatter, no el archivo entero."""
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            if f.readline().strip() != "---":
                return None
            for _ in range(_MAX_LINEAS_FRONTMATTER):
                linea = f.readline()
                if not linea or linea.strip() == "---":
                    return None
                m = re.match(r"sha256:\s*['\"]?([0-9a-fA-F]{64})", linea)
                if m:
                    return m.group(1).lower()
    except OSError:
        return None
    return None


def _buscar_por_sha(raw: Path, sha: str) -> Path | None:
    if not raw.is_dir():
        return None
    for ruta in sorted(raw.rglob("*.md")):
        if _sha_de_frontmatter(ruta) == sha:
            return ruta
    return None


def ingerir(vault: Path, origen: Path, fecha: date | None = None) -> tuple[Path, bool]:
    """Copia `origen` a raw/AAAA-MM-DD/<slug>.md. Devuelve (ruta, creado); nunca sobrescribe."""
    vault = Path(vault)
    origen = Path(origen).expanduser().resolve()
    datos = origen.read_bytes()
    sha = hashlib.sha256(datos).hexdigest()
    existente = _buscar_por_sha(vault / "raw", sha)
    if existente is not None:
        return existente, False
    fecha = fecha or datetime.now(ZONA_NEGOCIO).date()
    texto = datos.decode("utf-8", errors="replace")
    if origen.suffix.lower() in (".html", ".htm"):
        texto = html_a_texto(texto)
    carpeta = vault / "raw" / fecha.isoformat()
    base = _slug(origen.stem)
    destino, n = carpeta / f"{base}.md", 1
    while destino.exists():
        n += 1
        destino = carpeta / f"{base}-{n}.md"
    meta = {"tipo": "fuente", "origen": str(origen), "sha256": sha,
            "fecha_ingesta": fecha.isoformat()}
    frontmatter.escribir(destino, meta, texto)
    return destino, True
