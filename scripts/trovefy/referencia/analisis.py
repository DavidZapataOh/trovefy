"""Análisis propio de Claude sobre los anuncios de referencia, con guarda anti-copia.

El texto ajeno (anuncio, título, transcripción) vive solo en la caché local y solo se usa para comprobar
que lo escrito en el vault es propio: nunca se copia al vault.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from trovefy.referencia import cache
from trovefy.referencia.salida import (
    Analisis,
    Referencia,
    cargar_referencia,
    escribir_referencia,
)
from trovefy.referencia.watch import texto_transcripcion
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import anadir_log

LIMITES = {
    "transcripcion_resumida": 400,
    "hook_sujeto": 80,
    "hook_dolor_o_resultado": 120,
    "angulo": 120,
    "cta": 60,
    "objecion": 120,
}
MAX_PALABRAS_SEGUIDAS = 7
MAX_BYTES_JSON = 1024 * 1024
_SIN_TEXTOS = (
    "no se puede comprobar que el texto sea propio: vuelve a ejecutar `trovefy ver-anuncios ver`"
)


class AnalisisInvalido(ValueError):
    def __init__(self, problemas: list[str] | str):
        self.problemas = [problemas] if isinstance(problemas, str) else list(problemas)
        super().__init__("; ".join(self.problemas))


def normalizar(t: str) -> list[str]:  # residuo aceptado: homoglifos (p. ej. cirílicos parecidos) no se detectan
    # Los caracteres de formato (Cf: U+00AD, U+200B…) no deben partir palabras y burlar la guarda.
    t = "".join(c for c in t if unicodedata.category(c) != "Cf")
    s = unicodedata.normalize("NFKD", t.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]|_", " ", s)
    return s.split()


def copia_literal(propio: str, ajenos: list[str], n: int = MAX_PALABRAS_SEGUIDAS + 1) -> bool:
    p = normalizar(propio)
    if len(p) < n:
        return False
    propios = {tuple(p[i : i + n]) for i in range(len(p) - n + 1)}
    for a in ajenos:
        w = normalizar(a or "")
        for i in range(len(w) - n + 1):
            if tuple(w[i : i + n]) in propios:
                return True
    return False


def validar(
    entradas: list[dict], ref: Referencia, ajenos: dict[str, list[str]]
) -> dict[str, Analisis]:
    conocidos = {f.library_id for f in ref.fichas}
    todos = [t for ts in ajenos.values() for t in ts]
    problemas: list[str] = []
    salida: dict[str, Analisis] = {}
    for i, e in enumerate(entradas):
        if not isinstance(e, dict):
            problemas.append(f"entrada {i}: no es un objeto")
            continue
        lib = e.get("library_id")
        if not isinstance(lib, str) or lib not in conocidos:
            problemas.append(f"{lib}: library_id desconocido")
            continue
        if lib not in ajenos:
            problemas.append(f"{lib}: {_SIN_TEXTOS}")
            continue
        malo = False
        valores: dict[str, str] = {}
        for campo, limite in LIMITES.items():
            v = e.get(campo)
            if not isinstance(v, str) or not v.strip():
                problemas.append(f"{lib}.{campo}: falta o no es texto")
            elif re.search(r"[\r\n]", v):
                problemas.append(f"{lib}.{campo}: tiene saltos de línea")
            elif any(unicodedata.category(c) == "Cc" for c in v):
                problemas.append(f"{lib}.{campo}: tiene caracteres de control")
            elif re.search(r"http|www\.", v, re.IGNORECASE):
                problemas.append(f"{lib}.{campo}: lleva una URL")
            elif len(v) > limite:
                problemas.append(f"{lib}.{campo}: supera {limite} caracteres")
            elif copia_literal(v, todos):
                problemas.append(f"{lib}.{campo}: copia literal del texto ajeno; reescríbelo con tus palabras")
            elif buscar_secreto(v):
                problemas.append(f"{lib}.{campo}: parece contener un secreto")
            else:
                valores[campo] = v.strip()
                continue
            malo = True
        if not malo:
            salida[lib] = Analisis(**valores)
    if problemas:
        raise AnalisisInvalido(problemas)
    return salida


def _cargar_ajenos(p_id: str) -> dict[str, list[str]]:
    ruta = cache.textos_path(p_id)
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AnalisisInvalido(_SIN_TEXTOS) from None
    if not isinstance(crudo, dict):
        raise AnalisisInvalido(_SIN_TEXTOS)
    ajenos: dict[str, list[str]] = {}
    for lib, d in crudo.items():
        d = d if isinstance(d, dict) else {"texto": d}
        textos = [d.get("texto"), d.get("titulo")]
        watch = cache.base_cache() / p_id / str(lib) / "watch.md"
        try:
            textos.append(texto_transcripcion(watch.read_text(encoding="utf-8")))
        except OSError:
            pass
        ajenos[str(lib)] = [t for t in textos if isinstance(t, str) and t.strip()]
    return ajenos


def _borrar_borrador(vault: Path, ruta_json: Path) -> None:
    """Tras anotar, borra el borrador de Claude, pero solo si vive en ``<vault>/data/referencia/``."""
    try:
        zona = (Path(vault) / "data" / "referencia").resolve()
        if ruta_json.is_symlink() or not ruta_json.is_file():
            return
        if ruta_json.resolve().parent.is_relative_to(zona):
            ruta_json.unlink()
    except OSError:
        pass


def anotar(vault: Path, p_id: str, ruta_json: Path, ahora: datetime) -> list[str]:
    ruta_json = Path(ruta_json)
    try:
        if ruta_json.stat().st_size > MAX_BYTES_JSON:
            raise AnalisisInvalido("el JSON de análisis supera 1 MB")
        entradas = json.loads(ruta_json.read_text(encoding="utf-8"))
    except OSError as e:
        raise AnalisisInvalido(f"no se puede leer el análisis: {e.strerror}") from None
    except ValueError:
        raise AnalisisInvalido("el análisis no es JSON válido") from None
    if not isinstance(entradas, list):
        raise AnalisisInvalido("el análisis debe ser una lista de objetos")
    ref = cargar_referencia(vault, p_id)
    ajenos = _cargar_ajenos(p_id)
    nuevos = validar(entradas, ref, ajenos)
    for f in ref.fichas:
        if f.library_id in nuevos:
            f.analisis = nuevos[f.library_id]
    escribir_referencia(vault, ref, ahora, log=False)
    ids = sorted(nuevos)
    _borrar_borrador(vault, ruta_json)
    anadir_log(
        vault, "ver-anuncios", f"anotar análisis de {len(ids)} anuncios", [f"productos/{p_id}/referencia/anuncios.md"], ahora=ahora
    )
    return ids
