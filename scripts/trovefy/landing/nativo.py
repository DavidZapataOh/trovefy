"""Texto visible de la landing para el agente ``nativo`` y registro de su veredicto, atado a la versión.

La skill pasa al agente (``agents/nativo.md``) lo que imprime ``trovefy landing texto`` y guarda su
respuesta tal cual con ``trovefy landing nativo``. El veredicto es ``ok|corregir`` (resolución 17) y se lee
de la propia respuesta con :func:`trovefy.producto.qc_registro.parsear_veredicto`: líneas ``- `` bloquean y
``~ `` son sugerencias. Una respuesta sin veredicto claro, o que no dice lo mismo que ``--veredicto``, no se
registra (falla cerrado).

``nativo.md`` lleva la versión de la landing guardada (``landing.yaml``) y el SHA-256 del texto que se le
pasó al agente (``texto_sha256``: HTML visible más los ``content:`` del CSS, que no entran en la versión).
``trovefy landing texto`` imprime los dos; ``trovefy landing nativo --version`` exige que sean los actuales.
:func:`veredicto_vigente` vuelve a calcular el texto y, si ya no es el leído, el veredicto no vale; con otra
versión pero el mismo texto, la QA lo da por «no medido» (la versión manda).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from trovefy.landing.entrada import EntradaInvalida, ruta_landing
from trovefy.producto.qc_registro import parsear_veredicto
from trovefy.secretos import buscar_secreto

VEREDICTOS = ("ok", "corregir")
NOMBRE = "nativo.md"

_BLOQUES = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dl", "dt", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "summary", "table", "td", "th", "tr", "ul",
})
_OCULTOS = frozenset({"script", "style", "template", "noscript", "head", "title", "svg"})
_VACIOS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                     "wbr"})


@dataclass(frozen=True)
class TextoLanding:
    """Lo que lee el nativo: la versión guardada, el texto y su SHA-256."""

    version: str
    texto: str
    sha256: str


class _Texto(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pila: list[str] = []
        self.titulo: list[str] = []
        self.descripcion: str | None = None
        self.partes: list[str] = []  # texto con "\n" en los cortes de bloque
        self.secciones = 0
        self.estilos: list[str] = []  # contenido de los <style> (sus content: también se leen)

    def _oculto(self) -> bool:
        return any(t in _OCULTOS for t in self.pila)

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "meta" and a.get("name", "").strip().lower() == "description":
            self.descripcion = a.get("content", "")
        if not self._oculto():
            if tag == "section" and "data-tf-seccion" in a:
                self.secciones += 1
                tipo = a.get("data-tf-tipo") or "sin tipo"
                self.partes.append(f"\n\n## Sección {a['data-tf-seccion']} ({tipo})\n\n")
            elif tag in _BLOQUES:
                self.partes.append("\n")
            if tag == "img" and a.get("alt", "").strip():
                self.partes.append(f"\n[imagen: {a['alt'].strip()}]\n")
        if tag not in _VACIOS:
            self.pila.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VACIOS and self.pila and self.pila[-1] == tag:
            self.pila.pop()

    def handle_endtag(self, tag):
        if tag not in self.pila:
            return
        while self.pila and self.pila.pop() != tag:
            pass
        if tag in _BLOQUES and not self._oculto():
            self.partes.append("\n")

    def handle_data(self, data):
        if "title" in self.pila and "svg" not in self.pila:
            self.titulo.append(data)
        elif self.pila and self.pila[-1] == "style" and "svg" not in self.pila:
            self.estilos.append(data)
        elif not self._oculto():
            self.partes.append(data)


def _una_linea(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def texto_visible(html: str, css: str = "", esperadas: int | None = None) -> str:
    """Título, descripción, ``alt`` de las imágenes y el texto visible por sección (cabeceras
    ``## Sección N (<tipo>)``), una línea por bloque; sin ``<script>`` ni ``<style>``. Al final, bajo
    ``## CSS (content)``, las cadenas de ``content:`` de los ``<style>`` y de ``css`` (también se leen).

    ``EntradaInvalida`` si no hay ninguna sección o, con ``esperadas``, si no son las del wireframe: un texto
    a medias no se le pasa al nativo."""
    from trovefy.landing.validar import textos_content_css

    p = _Texto()
    p.feed(html)
    p.close()
    if p.secciones == 0:
        raise EntradaInvalida("el HTML no tiene ninguna sección data-tf-seccion: no hay texto que pasar al nativo")
    if esperadas is not None and p.secciones != esperadas:
        raise EntradaInvalida(f"el HTML tiene {p.secciones} secciones y el wireframe {esperadas}: el nativo leería "
                              "un texto a medias (trovefy landing validar)")
    salida = [f"# {_una_linea(''.join(p.titulo)) or '(sin título)'}", ""]
    if p.descripcion is not None:
        salida += [f"Descripción: {_una_linea(p.descripcion)}", ""]
    for linea in "".join(p.partes).split("\n"):
        limpia = _una_linea(linea)
        if limpia.startswith("## Sección "):
            if salida[-1] != "":
                salida.append("")
            salida += [limpia, ""]
        elif limpia:
            salida.append(limpia)
    while salida and salida[-1] == "":
        salida.pop()
    contenidos = [t for t in (_una_linea(x) for x in textos_content_css("\n".join([*p.estilos, css]))) if t]
    if contenidos:
        salida += ["", "## CSS (content)", "", *contenidos]
    return "\n".join(salida) + "\n"


def _version_actual(vault: Path, p_id: str, pais: str) -> str:
    from trovefy.landing.plantilla import leer_landing_yaml

    version = leer_landing_yaml(vault, p_id, pais).get("version")
    if not isinstance(version, str) or not version:
        raise EntradaInvalida(f"la landing de {pais} no está guardada: trovefy landing guardar")
    return version


def _leer(ruta: Path) -> str | None:
    return None if ruta.is_symlink() or not ruta.is_file() else ruta.read_text(encoding="utf-8")


def _secciones_wireframe(raiz: Path) -> int | None:
    import yaml

    try:
        texto = _leer(raiz / "wireframe.yaml")
        secciones = (yaml.safe_load(texto) or {}).get("secciones") if texto else None
    except (yaml.YAMLError, AttributeError):
        return None
    return len(secciones) if isinstance(secciones, list) else None


def texto_landing(vault: Path, p_id: str, pais: str) -> TextoLanding:
    """El texto de la landing guardada para el nativo (``index.html`` + ``assets/estilo.css``), con su versión y
    su SHA-256. ``EntradaInvalida`` si no está guardada, si ``index.html`` no es la versión de ``landing.yaml``
    (editado a mano) o si no tiene las secciones del wireframe."""
    from trovefy.landing.plantilla import version_de

    vault = Path(vault)
    version = _version_actual(vault, p_id, pais)
    raiz = ruta_landing(vault, p_id, pais)
    html = _leer(raiz / "index.html")
    if html is None:
        raise EntradaInvalida(f"falta landing/{pais}/index.html: trovefy landing guardar")
    if version_de(html) != version:
        raise EntradaInvalida(f"landing/{pais}/index.html no es la versión guardada ({version}): ¿editado a mano? "
                              "vuelve a trovefy landing guardar")
    texto = texto_visible(html, _leer(raiz / "assets" / "estilo.css") or "", _secciones_wireframe(raiz))
    return TextoLanding(version, texto, hashlib.sha256(texto.encode("utf-8")).hexdigest())


def registrar_veredicto(vault: Path, p_id: str, pais: str, veredicto: Literal["ok", "corregir"], notas: str,
                        ahora: datetime, *, version: str | None = None, texto_sha256: str | None = None) -> Path:
    """Escribe ``landing/<PAIS>/nativo.md`` con ``{tipo: qa_idioma, agente: nativo, veredicto, version,
    texto_sha256, fecha}`` y la respuesta del agente tal cual. ``ValueError`` si el veredicto no es
    ``ok|corregir``; ``EntradaInvalida`` si la respuesta no termina en ese mismo ``VEREDICTO:``
    (``parsear_veredicto``), si lleva algo con forma de secreto, si no hay landing guardada o si ``version``
    o ``texto_sha256`` (lo que leyó el agente, de ``trovefy landing texto``) no son los actuales."""
    from trovefy.producto.medios import carpeta_segura
    from trovefy.vault.escritura import anadir_log, escribir_atomico
    from trovefy.vault.frontmatter import renderizar

    if veredicto not in VEREDICTOS:
        raise ValueError(f"veredicto «{veredicto}»: solo ok o corregir")
    if not isinstance(notas, str):
        raise EntradaInvalida("las notas del nativo tienen que ser texto")
    leido = parsear_veredicto(notas)
    if leido != veredicto:
        motivo = "no da un veredicto claro" if leido is None else f"dice VEREDICTO: {leido}"
        raise EntradaInvalida(f"la respuesta del nativo {motivo}; tiene que terminar en «VEREDICTO: {veredicto}» "
                              "(y un ok no puede traer líneas «- »)")
    patron = buscar_secreto(notas)
    if patron:
        raise EntradaInvalida(f"las notas del nativo llevan algo con forma de secreto ({patron}): no se guardan")
    vault = Path(vault)
    actual = texto_landing(vault, p_id, pais)
    if version is not None and version != actual.version:
        raise EntradaInvalida(f"el nativo leyó la versión {version} y la guardada es {actual.version}: vuelve a "
                              "trovefy landing texto y pásale el texto nuevo")
    if texto_sha256 is not None and texto_sha256.strip().lower() != actual.sha256:
        raise EntradaInvalida(f"el texto que leyó el nativo (Texto-sha256 {texto_sha256}) no es el de la landing "
                              f"actual ({actual.sha256}): vuelve a trovefy landing texto")
    raiz = ruta_landing(vault, p_id, pais)
    try:
        carpeta_segura(vault, raiz, crear=False)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    ruta = raiz / NOMBRE
    if ruta.is_symlink():
        raise EntradaInvalida(f"{ruta} es un enlace simbólico: no se escribe a través de él")
    meta = {"tipo": "qa_idioma", "agente": "nativo", "veredicto": veredicto, "version": actual.version,
            "texto_sha256": actual.sha256, "fecha": ahora.isoformat(timespec="seconds")}
    escribir_atomico(ruta, renderizar(meta, notas))
    rel = ruta.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{p_id} {pais}: veredicto del nativo {veredicto} (versión {actual.version})",
               [rel])
    return ruta


def veredicto_vigente(vault: Path, p_id: str, pais: str) -> tuple[str, str] | None:
    """``(veredicto, version)`` de ``nativo.md``; ``None`` si no hay, está roto o enlazado, si el
    frontmatter no dice lo mismo que la respuesta guardada, o si el texto de la landing ya no es el que leyó
    el agente (``texto_sha256``; falla cerrado). La versión puede ser vieja con el mismo texto: lo decide quien
    compara (``qa.evaluar``)."""
    from trovefy.vault import frontmatter

    ruta = ruta_landing(Path(vault), p_id, pais) / NOMBRE
    if ruta.is_symlink() or not ruta.is_file():
        return None
    try:
        meta, cuerpo = frontmatter.leer(ruta)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(meta, dict) or meta.get("tipo") != "qa_idioma" or meta.get("agente") != "nativo":
        return None
    veredicto, version = meta.get("veredicto"), meta.get("version")
    if veredicto not in VEREDICTOS or not isinstance(version, str) or not version:
        return None
    if parsear_veredicto(cuerpo) != veredicto:
        return None
    leido = meta.get("texto_sha256")
    if not isinstance(leido, str) or not leido:
        return None
    try:
        actual = texto_landing(Path(vault), p_id, pais)
    except (EntradaInvalida, OSError, UnicodeDecodeError):
        return None
    if actual.sha256 != leido:
        return None
    return veredicto, version
