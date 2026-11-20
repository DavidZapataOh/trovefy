"""``config/montar.yaml``: DSA, hora de salida, plazo, ubicaciones, botón por defecto y sexo (plan 22, Tarea 3).

Cada hoja lleva ``{valor, fuente, fecha}``. Lo que el usuario aún no decidió queda con el valor por defecto del plan
(``salida.hora_local`` 00:00, ``plazo_dias`` 7, ``cta_por_defecto`` LEARN_MORE, ``segmentacion.sexo`` auto) o en
``null`` (DSA): un DSA en null para un país de la UE es «no medido» y no se monta.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trovefy.config.yaml_config import cargar_yaml
from trovefy.montar import NoMedido

RELATIVA = Path("config") / "montar.yaml"
PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "montar.yaml"
SEXOS = ("auto", "todos", "mujeres", "hombres")
GENEROS_META = {"hombres": 1, "mujeres": 2}  # targeting.genders de Meta


@dataclass(frozen=True)
class ConfigMontar:
    dsa_beneficiario: str | None
    dsa_pagador: str | None
    hora_local: str
    zona: str
    margen_min_h: int
    plazo_dias: int
    ubicaciones_excluidas: tuple[str, ...]
    cta_por_defecto: str
    sexo: str

    def dsa(self) -> dict:
        """``{beneficiario, pagador}`` o ``NoMedido`` si falta alguno."""
        for nombre, v in (("beneficiario", self.dsa_beneficiario), ("pagador", self.dsa_pagador)):
            if not v:
                raise NoMedido(f"falta dsa.{nombre} en config/montar.yaml: escribe el nombre del anunciante tal como "
                               "figura en Meta (Meta lo exige en la UE)")
        return {"beneficiario": self.dsa_beneficiario, "pagador": self.dsa_pagador}


def _hoja(datos: dict, ruta: str):
    nodo: object = datos
    for parte in ruta.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            raise ValueError(f"config/montar.yaml: falta {ruta}")
        nodo = nodo[parte]
    if not isinstance(nodo, dict) or "valor" not in nodo:
        raise ValueError(f"config/montar.yaml: {ruta} debe ser {{valor, fuente, fecha}}")
    return nodo["valor"]


def _texto_o_none(v: object, ruta: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise ValueError(f"config/montar.yaml: {ruta} debe ser texto (1–200) o null")
    return v.strip()


def cargar_texto(texto: str) -> ConfigMontar:
    datos = cargar_yaml(texto) or {}
    if not isinstance(datos, dict):
        raise ValueError("config/montar.yaml no es un mapa")  # noqa: TRY004
    hora = _hoja(datos, "salida.hora_local")
    if not isinstance(hora, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
        raise ValueError("config/montar.yaml: salida.hora_local debe ser HH:MM")
    zona = _hoja(datos, "salida.zona")
    try:
        ZoneInfo(str(zona))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"config/montar.yaml: salida.zona desconocida «{zona}»") from None
    margen = _hoja(datos, "salida.margen_min_h")
    plazo = _hoja(datos, "plazo_dias")
    for nombre, v in (("salida.margen_min_h", margen), ("plazo_dias", plazo)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"config/montar.yaml: {nombre} debe ser un entero ≥ 0")
    ubic = _hoja(datos, "ubicaciones_excluidas")
    if not isinstance(ubic, list) or not all(isinstance(x, str) and re.fullmatch(r"[a-z_]+", x) for x in ubic):
        raise ValueError("config/montar.yaml: ubicaciones_excluidas debe ser una lista de identificadores")
    cta = _hoja(datos, "cta_por_defecto")
    if not isinstance(cta, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,59}", cta):
        raise ValueError("config/montar.yaml: cta_por_defecto debe ser un código de Meta (LEARN_MORE…)")
    sexo = _hoja(datos, "segmentacion.sexo")
    if sexo not in SEXOS:
        raise ValueError(f"config/montar.yaml: segmentacion.sexo debe ser {', '.join(SEXOS)}")
    return ConfigMontar(_texto_o_none(_hoja(datos, "dsa.beneficiario"), "dsa.beneficiario"),
                        _texto_o_none(_hoja(datos, "dsa.pagador"), "dsa.pagador"), hora, str(zona), margen, plazo,
                        tuple(ubic), cta, sexo)


def cargar_config(vault: Path) -> ConfigMontar:
    """``config/montar.yaml`` del vault; si no existe, la plantilla (con el DSA en null)."""
    ruta = Path(vault) / RELATIVA
    return cargar_texto((ruta if ruta.is_file() else PLANTILLA).read_text(encoding="utf-8"))


# Palabras de «mujeres» y «hombres» en los idiomas de los mercados (y español e inglés). Solo decide si el avatar
# nombra un sexo y no el otro; si duda, todos.
_MUJERES = ("mujer", "mujeres", "women", "woman", "female", "жени", "жена", "femei", "femeie", "mulheres", "mulher",
            "femmes", "femme", "frauen", "frau", "donne", "donna", "kobiety", "kobieta", "женщины", "жінки",
            "zene", "ženy", "žene", "naiset", "nők")
_HOMBRES = ("hombre", "hombres", "men", "man", "male", "мъже", "мъж", "barbati", "bărbați", "barbat", "bărbat",
            "homens", "homem", "hommes", "homme", "männer", "mann", "uomini", "uomo", "mężczyźni", "mężczyzna",
            "мужчины", "чоловіки", "muzi", "muži", "muškarci", "miehet", "férfiak")


def _palabras(texto: str) -> set[str]:
    t = unicodedata.normalize("NFC", texto.casefold())
    return set(re.findall(r"\w+", t))


def sexo_del_avatar(avatar: str | None) -> str | None:
    """``mujeres``/``hombres`` si el avatar nombra solo uno; ``None`` (todos) si ninguno o los dos."""
    if not isinstance(avatar, str) or not avatar.strip():
        return None
    p = _palabras(avatar)
    m = any(unicodedata.normalize("NFC", w) in p for w in _MUJERES)
    h = any(unicodedata.normalize("NFC", w) in p for w in _HOMBRES)
    if m and not h:
        return "mujeres"
    if h and not m:
        return "hombres"
    return None


def generos(cfg: ConfigMontar, avatar: str | None) -> tuple[int, ...] | None:
    """``targeting.genders`` de Meta (``None`` = todos)."""
    sexo = sexo_del_avatar(avatar) if cfg.sexo == "auto" else (None if cfg.sexo == "todos" else cfg.sexo)
    return (GENEROS_META[sexo],) if sexo else None
