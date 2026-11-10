"""Ingesta de fuentes a raw/ (capa inmutable): copia sin duplicados y HTML a texto."""

import fcntl
import hashlib
import importlib.util
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from trovify.vault import frontmatter
from trovify.vault.escritura import ZONA_NEGOCIO

_IGNORAR = {"script", "style", "nav", "aside", "button", "svg", "noscript", "title"}
# Un inicio de estas etiquetas cierra una región ignorada sin cierre: no pueden estar dentro.
_CORTAN_IGNORADO = {"body", "main", "article", "section"}
_VACIOS = {"br", "hr", "img", "input", "meta", "link"}
_BLOQUES = {"p", "div", "section", "article", "main", "header", "footer", "ul", "ol",
            "blockquote", "pre", "details", "summary", "figure", "figcaption"}
_MAX_LINEAS_FRONTMATTER = 60
_MAX_LINEA = 4096


class _Tabla:
    def __init__(self) -> None:
        self.celdas: list[str] = []
        self.celda: list[str] | None = None
        self.en_fila = False


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ign: str | None = None
        self._ign_prof = 0
        self._tablas: list[_Tabla] = []

    def _destino(self, nivel: int) -> list[str]:
        """Lista donde escribir lo que pertenece al nivel `nivel` de tablas (0 = texto libre)."""
        if nivel > 0 and self._tablas[nivel - 1].celda is not None:
            return self._tablas[nivel - 1].celda
        return self.partes

    def _emitir(self, texto: str) -> None:
        self._destino(len(self._tablas)).append(texto)

    def _cerrar_celda(self) -> None:
        t = self._tablas[-1]
        if t.celda is not None:
            t.celdas.append(re.sub(r"\s+", " ", "".join(t.celda)).strip())
            t.celda = None

    def _cerrar_fila(self) -> None:
        self._cerrar_celda()
        t = self._tablas[-1]
        if any(t.celdas):
            nivel = len(self._tablas) - 1
            fila = " | ".join(t.celdas)
            self._destino(nivel).append(("\n" if nivel == 0 else " ") + fila + "\n" * (nivel == 0))
        t.celdas = []
        t.en_fila = False

    def _cerrar_tabla(self) -> None:
        self._cerrar_fila()
        self._tablas.pop()

    def handle_starttag(self, tag, attrs):
        if self._ign is not None:
            if tag in _CORTAN_IGNORADO:
                self._ign = None
            else:
                if tag == self._ign:
                    self._ign_prof += 1
                return
        if tag in _VACIOS:
            if tag in ("br", "hr"):
                self._emitir("\n")
            return
        if tag in _IGNORAR:
            self._ign, self._ign_prof = tag, 1
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._emitir("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self._emitir("\n- ")
        elif tag == "table":
            self._tablas.append(_Tabla())
            self._emitir("\n\n") if len(self._tablas) == 1 else None
        elif tag == "tr" and self._tablas:
            self._cerrar_fila()
            self._tablas[-1].en_fila = True
        elif tag in ("td", "th") and self._tablas:
            self._cerrar_celda()
            self._tablas[-1].celda = []
        elif tag in _BLOQUES or tag in ("thead", "tbody"):
            self._emitir("\n\n")

    def handle_endtag(self, tag):
        if self._ign is not None:
            if tag == self._ign:
                self._ign_prof -= 1
                if self._ign_prof <= 0:
                    self._ign = None
            return
        if tag in _VACIOS:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._emitir("\n\n")
        elif tag in ("td", "th") and self._tablas:
            self._cerrar_celda()
        elif tag == "tr" and self._tablas:
            self._cerrar_fila()
        elif tag == "table" and self._tablas:
            self._cerrar_tabla()
            self._emitir("\n\n")
        elif tag in _BLOQUES:
            self._emitir("\n\n")

    def handle_data(self, data):
        if self._ign is not None:
            return
        en_celda = bool(self._tablas) and self._tablas[-1].celda is not None
        self._emitir(data if en_celda else re.sub(r"[ \t\r\n]+", " ", data))

    def close(self):
        super().close()
        while self._tablas:
            self._cerrar_tabla()


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
            if f.readline(_MAX_LINEA).strip() != "---":
                return None
            for _ in range(_MAX_LINEAS_FRONTMATTER):
                linea = f.readline(_MAX_LINEA)
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


def _crear_exclusivo(carpeta: Path, base: str, contenido: str) -> Path:
    """Crea carpeta/base[-n].md sin sobrescribir nada (ni enlaces rotos)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=f".{base}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        n = 1
        while True:
            destino = carpeta / (f"{base}.md" if n == 1 else f"{base}-{n}.md")
            try:
                os.link(tmp, destino)
                return destino
            except FileExistsError:
                n += 1
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def _buscar_secreto(texto: str) -> str | None:
    """Usa los patrones de hooks/secretos.py (una sola fuente), sin la mención `access_token=`."""
    for padre in Path(__file__).resolve().parents:
        hooks = padre / "hooks"
        if (hooks / "secretos.py").is_file() and (hooks / "_comun.py").is_file():
            break
    else:
        raise FileNotFoundError("No encuentro hooks/secretos.py; no se puede revisar si hay secretos.")
    sys.path.insert(0, str(hooks))
    try:
        spec = importlib.util.spec_from_file_location("_trovify_hook_secretos", hooks / "secretos.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(hooks))
    return mod.buscar_secreto(texto, mod.PATRONES[:3])


def ingerir(vault: Path, origen: Path, fecha: date | None = None) -> tuple[Path, bool]:
    """Copia `origen` a raw/AAAA-MM-DD/<slug>.md. Devuelve (ruta, creado); nunca sobrescribe."""
    vault = Path(vault)
    origen = Path(origen).expanduser().resolve()
    datos = origen.read_bytes()
    sha = hashlib.sha256(datos).hexdigest()
    fecha = fecha or datetime.now(ZONA_NEGOCIO).date()
    texto = datos.decode("utf-8", errors="replace")
    if origen.suffix.lower() in (".html", ".htm"):
        texto = html_a_texto(texto)
    patron = _buscar_secreto(texto)
    if patron:
        raise ValueError(f"contiene un posible {patron}; no se ingiere")
    meta = {"tipo": "fuente", "origen": str(origen), "sha256": sha,
            "fecha_ingesta": fecha.isoformat()}
    raw = vault / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with open(raw / ".ingesta.lock", "a") as cerrojo:
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        existente = _buscar_por_sha(raw, sha)
        if existente is not None:
            return existente, False
        destino = _crear_exclusivo(raw / fecha.isoformat(), _slug(origen.stem),
                                   frontmatter.renderizar(meta, texto))
        return destino, True
