"""Mercados europeos semilla."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Mercado:
    pais: str
    idioma: str
    moneda: str
    zona: str
    banda_eur: tuple[float, float]
    precio_referencia: str | None
    estado: str


def cargar(ruta: Path) -> dict[str, Mercado]:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    mercados: dict[str, Mercado] = {}
    for pais, e in datos.items():
        banda = e["banda_eur"]
        mercados[pais] = Mercado(
            pais=pais,
            idioma=e["idioma"],
            moneda=e["moneda"],
            zona=e["zona"],
            banda_eur=(float(banda[0]), float(banda[1])),
            precio_referencia=e.get("precio_referencia"),
            estado=e["estado"],
        )
    return mercados
