"""Texto visible de la landing para el agente ``nativo`` y registro de su veredicto, atado a la versión.

La skill pasa al agente (``agents/nativo.md``) lo que imprime ``trovefy landing texto`` y guarda su
respuesta tal cual con ``trovefy landing nativo``. El veredicto es ``ok|corregir`` (resolución 17) y se lee
de la propia respuesta con :func:`trovefy.producto.qc_registro.parsear_veredicto`: líneas ``- `` bloquean y
``~ `` son sugerencias. Una respuesta sin veredicto claro, o que no dice lo mismo que ``--veredicto``, no se
registra (falla cerrado).

``nativo.md`` lleva la versión de la landing guardada (``landing.yaml``); al guardar otra versión el
veredicto deja de valer y la QA lo da por «no medido».
"""

from __future__ import annotations

import re
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


class _Texto(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pila: list[str] = []
        self.titulo: list[str] = []
        self.descripcion: str | None = None
        self.partes: list[str] = []  # texto con "\n" en los cortes de bloque

    def _oculto(self) -> bool:
        return any(t in _OCULTOS for t in self.pila)

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "meta" and a.get("name", "").strip().lower() == "description":
            self.descripcion = a.get("content", "")
        if not self._oculto():
            if tag == "section" and "data-tf-seccion" in a:
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
        elif not self._oculto():
            self.partes.append(data)


def _una_linea(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def texto_visible(html: str) -> str:
    """Título, descripción, ``alt`` de las imágenes y el texto visible por sección (cabeceras
    ``## Sección N (<tipo>)``), una línea por bloque; sin ``<script>`` ni ``<style>``."""
    p = _Texto()
    p.feed(html)
    p.close()
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
    return "\n".join(salida) + "\n"


def _version_actual(vault: Path, p_id: str, pais: str) -> str:
    from trovefy.landing.plantilla import leer_landing_yaml

    version = leer_landing_yaml(vault, p_id, pais).get("version")
    if not isinstance(version, str) or not version:
        raise EntradaInvalida(f"la landing de {pais} no está guardada: trovefy landing guardar")
    return version


def registrar_veredicto(vault: Path, p_id: str, pais: str, veredicto: Literal["ok", "corregir"], notas: str,
                        ahora: datetime) -> Path:
    """Escribe ``landing/<PAIS>/nativo.md`` con ``{tipo: qa_idioma, agente: nativo, veredicto, version,
    fecha}`` y la respuesta del agente tal cual. ``ValueError`` si el veredicto no es ``ok|corregir``;
    ``EntradaInvalida`` si la respuesta no termina en ese mismo ``VEREDICTO:`` (``parsear_veredicto``), si
    lleva algo con forma de secreto o si no hay landing guardada."""
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
    version = _version_actual(vault, p_id, pais)
    raiz = ruta_landing(vault, p_id, pais)
    try:
        carpeta_segura(vault, raiz, crear=False)
    except ValueError as exc:
        raise EntradaInvalida(str(exc)) from None
    ruta = raiz / NOMBRE
    if ruta.is_symlink():
        raise EntradaInvalida(f"{ruta} es un enlace simbólico: no se escribe a través de él")
    meta = {"tipo": "qa_idioma", "agente": "nativo", "veredicto": veredicto, "version": version,
            "fecha": ahora.isoformat(timespec="seconds")}
    escribir_atomico(ruta, renderizar(meta, notas))
    rel = ruta.relative_to(vault).as_posix()
    anadir_log(vault, "landing", f"{p_id} {pais}: veredicto del nativo {veredicto} (versión {version})", [rel])
    return ruta


def veredicto_vigente(vault: Path, p_id: str, pais: str) -> tuple[str, str] | None:
    """``(veredicto, version)`` de ``nativo.md``; ``None`` si no hay, está roto o enlazado, o si el
    frontmatter no dice lo mismo que la respuesta guardada (falla cerrado). La versión puede ser vieja:
    lo decide quien compara (``qa.evaluar``)."""
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
    return veredicto, version
