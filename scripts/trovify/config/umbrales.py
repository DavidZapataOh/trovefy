"""Umbrales de negocio con fuente, fecha y regla; nunca hay valores por defecto."""

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_CAMPOS = ("valor", "fuente", "fecha", "gana_sobre", "regla")
_REGLA = re.compile(r"R-\d{3}")


class UmbralInvalido(ValueError):
    def __init__(self, clave: str, motivo: str):
        self.clave = clave
        self.motivo = motivo
        super().__init__(f"Umbral «{clave}» inválido: {motivo}")


class UmbralFaltante(KeyError):
    def __init__(self, clave: str):
        self.clave = clave
        super().__init__(f"Umbral «{clave}» no existe en config/umbrales.yaml")

    def __str__(self) -> str:
        return self.args[0]


@dataclass(frozen=True)
class Umbral:
    clave: str
    valor: float
    fuente: str
    fecha: str
    gana_sobre: str
    regla: str


def cargar(ruta: Path) -> dict[str, Umbral]:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    umbrales: dict[str, Umbral] = {}
    for clave, entrada in datos.items():
        if not isinstance(entrada, dict):
            raise UmbralInvalido(clave, "la entrada no es un mapa")
        for campo in _CAMPOS:
            if campo not in entrada or entrada[campo] is None or entrada[campo] == "":
                raise UmbralInvalido(clave, f"falta el campo «{campo}»")
        v = entrada["valor"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise UmbralInvalido(clave, f"«valor» no es numérico: {v!r}")
        if not math.isfinite(v):
            raise UmbralInvalido(clave, f"«valor» no es finito: {v!r}")
        for campo in ("fuente", "fecha", "gana_sobre", "regla"):
            entrada[campo] = str(entrada[campo])
        if not _REGLA.fullmatch(entrada["regla"]):
            raise UmbralInvalido(clave, f"«regla» no tiene el formato R-NNN: {entrada['regla']!r}")
        umbrales[clave] = Umbral(clave=clave, **{c: entrada[c] for c in _CAMPOS})
    return umbrales


def valor(vault: Path, clave: str) -> float:
    umbrales = cargar(Path(vault) / "config" / "umbrales.yaml")
    if clave not in umbrales:
        raise UmbralFaltante(clave)
    return umbrales[clave].valor
