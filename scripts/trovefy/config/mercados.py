"""Mercados europeos semilla."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from trovefy.config.yaml_config import cargar_yaml


@dataclass(frozen=True)
class Mercado:
    pais: str
    idioma: str
    moneda: str
    zona: str
    banda_eur: tuple[float, float]
    precio_referencia: str | None
    estado: str
    fuente_banda: str | None = None


def cargar(ruta: Path) -> dict[str, Mercado]:
    try:
        datos = cargar_yaml(Path(ruta).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"config/mercados.yaml no se puede leer: {exc}") from None
    if not isinstance(datos, dict):
        raise ValueError("config/mercados.yaml no es un mapa de países")  # noqa: TRY004 - error de configuración
    mercados: dict[str, Mercado] = {}
    for pais, e in datos.items():
        if not isinstance(pais, str) or not pais.strip():
            raise ValueError(f"la clave {pais!r} de config/mercados.yaml no es un código de país: escríbela "
                             'entre comillas, por ejemplo "NO":')
        if not isinstance(e, dict):
            raise ValueError(f"el país {pais} de config/mercados.yaml no es un mapa")  # noqa: TRY004
        faltan = [c for c in ("idioma", "moneda", "zona", "banda_eur", "estado") if c not in e]
        if faltan:
            raise ValueError(f"al país {pais} de config/mercados.yaml le falta: {', '.join(faltan)}")
        banda = e["banda_eur"]
        mercados[pais] = Mercado(
            pais=pais,
            idioma=e["idioma"],
            moneda=e["moneda"],
            zona=e["zona"],
            banda_eur=(float(banda[0]), float(banda[1])),
            precio_referencia=e.get("precio_referencia"),
            estado=e["estado"],
            fuente_banda=e.get("fuente_banda"),
        )
    return mercados
