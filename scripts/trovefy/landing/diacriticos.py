"""Escritura y diacríticos por idioma: el texto «casi búlgaro» o el rumano con cedilla, antes del ``nativo``.

Reglas (todas bloquean salvo ``sin_reglas``):

- ``bg``: ≥ 95 % de letras cirílicas (sin las palabras ``permitidas``: marca, «PDF», «A4») → si no,
  ``escritura``; ``ы э ё`` → ``letra_rusa``; letras de otros alfabetos cirílicos (``і ї є ґ ў ј љ њ ћ ђ џ``)
  → ``letra_ajena``; una palabra con cirílico y cualquier otra escritura (latín, griego…) → ``homoglifo``.
  Los emails y las URLs (o dominios sueltos) se quitan antes de medir.
- ``ro``: ``ş ţ`` con cedilla → ``cedilla`` (deben ser ``ș ț`` con coma); ≥ 50 palabras sin ninguna de
  ``ă â î ș ț`` → ``sin_diacriticos``.
- Cualquier idioma: ``trovefy.idioma.detectar`` entre el idioma y sus vecinos; otro idioma →
  ``idioma_distinto``; ``None`` (corto o ambiguo) → nada: lo cubre el ``nativo``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from trovefy.idioma import detectar

IDIOMAS_REVISADOS = ("bg", "ro")
VECINOS = ("ru", "mk", "sr", "uk", "es", "en")
CIRILICO_MIN = 0.95  # dato técnico: margen para siglas sueltas («PDF» va en permitidas)
PALABRAS_SIN_DIACRITICOS = 50  # un texto rumano de este largo sin ninguna letra con diacrítico no es natural
_RUSAS = frozenset("ыэёЫЭЁ")
_AJENAS = frozenset("іїєґўјљњћђџІЇЄҐЎЈЉЊЋЂЏ")
_CEDILLA = {"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"}
_DIACRITICOS_RO = frozenset("ăâîșțĂÂÎȘȚ")
_MAX_EJEMPLOS = 5


@dataclass(frozen=True)
class Hallazgo:
    regla: str
    detalle: str
    bloquea: bool


def _alfabeto(c: str) -> str:
    """``cirilico``, ``latino`` o la escritura del nombre Unicode en minúsculas (``greek``, ``armenian``…)."""
    nombre = unicodedata.name(c, "")
    if nombre.startswith("CYRILLIC"):
        return "cirilico"
    if nombre.startswith("LATIN"):
        return "latino"
    return nombre.split(" ", 1)[0].lower() or "desconocido"


# Emails y URLs (con o sin esquema, y dominios sueltos como «ejemplo-demo.test»): no son texto en el idioma,
# así que no cuentan para la cuota de escritura ni para la detección de idioma.
_EMAIL_URL = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|(?:https?://|www\.)\S+"
    r"|\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}\b(?:/\S*)?",
    re.IGNORECASE | re.ASCII,
)


def _lista(palabras: list[str]) -> str:
    unicas = list(dict.fromkeys(palabras))
    extra = f" y {len(unicas) - _MAX_EJEMPLOS} más" if len(unicas) > _MAX_EJEMPLOS else ""
    return ", ".join(f"«{p}»" for p in unicas[:_MAX_EJEMPLOS]) + extra


def _bg(palabras: list[str], permitidas: frozenset[str]) -> list[Hallazgo]:
    hallazgos = []
    libres = [p for p in palabras if p.casefold() not in permitidas]
    letras = [_alfabeto(c) for p in libres for c in p if c.isalpha()]
    if letras:
        cuota = letras.count("cirilico") / len(letras)
        if cuota < CIRILICO_MIN:
            hallazgos.append(Hallazgo("escritura", f"{cuota:.0%} de letras cirílicas; el búlgaro pide ≥ 95 % "
                                      "(añade la marca o las siglas a las permitidas si son legítimas)", True))
    rusas = [p for p in palabras if _RUSAS & set(p)]
    if rusas:
        hallazgos.append(Hallazgo("letra_rusa", f"ы, э o ё no existen en búlgaro: {_lista(rusas)}", True))
    ajenas = [p for p in palabras if _AJENAS & set(p)]
    if ajenas:
        hallazgos.append(Hallazgo("letra_ajena", f"letras de otro alfabeto cirílico: {_lista(ajenas)}", True))
    for p in dict.fromkeys(palabras):
        alfabetos = {_alfabeto(c) for c in p if c.isalpha()}
        if "cirilico" in alfabetos and len(alfabetos) > 1:
            ajenas = "".join(c for c in p if c.isalpha() and _alfabeto(c) != "cirilico")
            otras = ", ".join(sorted(alfabetos - {"cirilico"}))
            hallazgos.append(Hallazgo("homoglifo", f"«{p}» mezcla cirílico con letras de otra escritura "
                                      f"({ajenas}: {otras})", True))
    return hallazgos


def _ro(texto: str, palabras: list[str]) -> list[Hallazgo]:
    hallazgos = []
    con_cedilla = [p for p in palabras if set(_CEDILLA) & set(p)]
    if con_cedilla:
        hallazgos.append(Hallazgo("cedilla", f"ş/ţ con cedilla en {_lista(con_cedilla)}: el rumano usa ș y ț "
                                  "(con coma debajo)", True))
    if len(palabras) >= PALABRAS_SIN_DIACRITICOS and not _DIACRITICOS_RO & set(texto):
        hallazgos.append(Hallazgo("sin_diacriticos", f"{len(palabras)} palabras y ninguna con ă, â, î, ș o ț: "
                                  "texto rumano sin diacríticos", True))
    return hallazgos


def revisar_texto(texto: str, idioma: str, permitidas: frozenset[str] = frozenset()) -> list[Hallazgo]:
    """Hallazgos de escritura del texto en ``idioma``; ``[]`` si está limpio."""
    texto = _EMAIL_URL.sub(" ", unicodedata.normalize("NFC", texto or ""))
    palabras = re.findall(r"\w+", texto)
    permitidas = frozenset(p.casefold() for p in permitidas)
    if idioma == "bg":
        hallazgos = _bg(palabras, permitidas)
    elif idioma == "ro":
        hallazgos = _ro(texto, palabras)
    else:
        hallazgos = []
    detectado = detectar(texto, [idioma, *VECINOS])
    if detectado is not None and detectado != idioma:
        hallazgos.append(Hallazgo("idioma_distinto", f"el texto parece {detectado}, no {idioma}", True))
    if idioma not in IDIOMAS_REVISADOS:
        hallazgos.append(Hallazgo("sin_reglas", f"no medido: sin reglas de diacríticos para {idioma}", False))
    return hallazgos
