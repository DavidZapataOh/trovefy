"""Cobertura de fuentes antes del PDF (Review Focus 3; resoluciones 18 y 19).

``fc-match`` nunca falla: si la familia pedida no está instalada, devuelve otra en silencio (en esta
máquina, DejaVu). Si esa otra no tiene cirílico, el búlgaro sale con «tofu». Por eso se comprueba que
la familia devuelta sea la pedida y que su archivo tenga, en su ``cmap`` (fontTools), cada letra del
texto. Si algo falla no se hace el PDF y se da la orden ``apt`` para que el usuario la ejecute él, en
una terminal aparte: Claude nunca usa sudo.
"""

from __future__ import annotations

import subprocess
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

FORMATO_FC = "%{family}\n%{file}\n%{index}"  # index: la fuente dentro de una colección .ttc/.otc
# Paquete de Debian/Ubuntu por prefijo de familia (resolución 19). Sin coincidencia: fonts-noto-core.
_PAQUETES = (
    ("dejavu", "fonts-dejavu-core"),
    ("noto sans mono", "fonts-noto-mono"),
    ("noto mono", "fonts-noto-mono"),
    ("noto", "fonts-noto-core"),
    ("ubuntu", "fonts-ubuntu"),
    ("liberation", "fonts-liberation"),
    ("nimbus", "fonts-urw-base35"),
    ("urw", "fonts-urw-base35"),
    ("c059", "fonts-urw-base35"),
    ("p052", "fonts-urw-base35"),
    ("z003", "fonts-urw-base35"),
)
_PAQUETE_POR_DEFECTO = "fonts-noto-core"
_IGNORADAS = ("Cc", "Cf", "Zs", "Zl", "Zp")  # control, formato (ZWSP, guion blando…) y espacios
_MAX_LETRAS = 20
_NO_VISIBLE = ("head", "title", "style", "script", "template", "noscript")


def _normalizar(familia: str) -> str:
    return " ".join(familia.lower().split())


def paquete_apt(familia: str) -> str:
    nombre = _normalizar(familia)
    for prefijo, paquete in _PAQUETES:
        if nombre.startswith(prefijo):
            return paquete
    return _PAQUETE_POR_DEFECTO


def _orden_apt(paquete: str) -> str:
    return f"en una terminal de Ubuntu (WSL) aparte: `sudo apt install -y {paquete}`"


class _IndiceIlegible(ValueError):
    """``fc-match`` dio un ``%{index}`` que no es un número."""


def _fc_match(familia: str, correr) -> tuple[str, Path | None, int]:
    """(primera familia que da ``fc-match``, archivo, índice en la colección). ``FileNotFoundError`` si falta
    ``fc-match``; ``_IndiceIlegible`` si el índice no es un número (sin índice: 0)."""
    r = correr(["fc-match", "-f", FORMATO_FC, familia], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return "", None, 0
    lineas = (r.stdout or "").split("\n")
    dada = lineas[0].split(",")[0].strip()
    archivo = lineas[1].strip() if len(lineas) > 1 else ""
    texto_indice = lineas[2].strip() if len(lineas) > 2 else ""
    if texto_indice and not (texto_indice.isascii() and texto_indice.isdigit()):
        raise _IndiceIlegible(f"fc-match dio un índice ilegible para «{familia}»: «{texto_indice[:20]}»")
    return dada, Path(archivo) if archivo else None, int(texto_indice or 0)


def ruta_fuente(familia: str, correr=subprocess.run) -> Path | None:
    """Archivo de ``familia`` según ``fc-match``; ``None`` si ``fc-match`` da otra familia (la sustituye
    en silencio) o el archivo no existe. ``FileNotFoundError`` si falta ``fc-match``."""
    dada, ruta, _ = _fc_match(familia, correr)
    if _normalizar(dada) != _normalizar(familia) or ruta is None or not ruta.is_file():
        return None
    return ruta


def glifos_faltantes(texto: str, ruta: Path, indice: int = 0) -> set[str]:
    """Letras de ``texto`` que no están en el ``cmap`` de la fuente (sin espacios ni caracteres de control).
    En una colección ``.ttc``/``.otc`` se lee la fuente número ``indice`` (el ``%{index}`` de ``fc-match``)."""
    from fontTools.ttLib import TTFont

    ruta = Path(ruta)
    coleccion = ruta.suffix.lower() in (".ttc", ".otc")
    with TTFont(str(ruta), lazy=True, fontNumber=indice if coleccion else -1) as fuente:
        cmap = fuente.getBestCmap() or {}
    return {c for c in set(texto)
            if not c.isspace() and unicodedata.category(c) not in _IGNORADAS and ord(c) not in cmap}


class _Texto(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.trozos: list[str] = []
        self._oculto = 0

    def handle_starttag(self, tag, attrs):
        if tag in _NO_VISIBLE:
            self._oculto += 1

    def handle_endtag(self, tag):
        if tag in _NO_VISIBLE and self._oculto:
            self._oculto -= 1

    def handle_data(self, data):
        if not self._oculto:
            self.trozos.append(data)


def texto_visible(html: str) -> str:
    p = _Texto()
    p.feed(html)
    p.close()
    return " ".join(p.trozos)


def comprobar_fuentes(html: str, familias: tuple[str, str], correr=subprocess.run) -> list[str]:
    """Problemas de fuentes del HTML (vacío si todo está bien). Cada familia (títulos y texto) debe estar
    instalada de verdad y cubrir todas las letras visibles del documento (se pide lo mismo a las dos)."""
    texto = texto_visible(html)
    problemas: list[str] = []
    for familia in dict.fromkeys(familias):
        try:
            dada, ruta, indice = _fc_match(familia, correr)
        except FileNotFoundError:
            return [f"no medido: falta fc-match; {_orden_apt('fontconfig')}"]
        except _IndiceIlegible as exc:
            problemas.append(f"no medido: {exc}")
            continue
        if _normalizar(dada) != _normalizar(familia) or ruta is None or not ruta.is_file():
            problemas.append(f"la fuente «{familia}» no está instalada (fc-match da «{dada or 'nada'}»); "
                             f"{_orden_apt(paquete_apt(familia))} o elige otra en BRANDBOOK.md")
            continue
        try:
            faltan = sorted(glifos_faltantes(texto, ruta, indice))
        except Exception as exc:  # noqa: BLE001 - un archivo de fuente roto es un problema que se informa
            problemas.append(f"no medido: no se puede leer la fuente «{familia}» ({ruta.name}: {exc})")
            continue
        if faltan:
            muestra = ", ".join(faltan[:_MAX_LETRAS]) + (" …" if len(faltan) > _MAX_LETRAS else "")
            problemas.append(f"«{familia}» no tiene {len(faltan)} letras del texto: {muestra}")
    return problemas
