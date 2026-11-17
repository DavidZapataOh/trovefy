"""Carga y validación de ``config/producto.yaml``. Cada hoja es ``{valor, fuente, fecha}``.

Mismo formato que ``config/economia.yaml`` (contrato, resolución 12): la validación de las hojas es la
de :mod:`trovefy.economia.config`. Los importes salen en ``Decimal`` (``Decimal(str(v))``), con dos
decimales como mucho y mayores que 0; nunca ``float``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.economia.config import EconomiaInvalida, _es_hoja, _revisar_hojas
from trovefy.producto.rutas import validar_p_id
from trovefy.vault import frontmatter
from trovefy.vault.escritura import escribir_atomico

PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "producto.yaml"
RELATIVA = Path("config") / "producto.yaml"
RESOLUCIONES = ("1k", "2k", "4k")
# Claves de plan.paginas_min: tipo de la pieza principal (ebook|kit) y tipo de las demás piezas.
TIPOS_PAGINAS = ("ebook", "kit", "bono", "bump", "upsell")


class ConfigInvalida(ValueError):
    """``config/producto.yaml`` (o ``apimart_tope_usd`` de ``PRODUCTO.md``) no cumple el formato."""


@dataclass(frozen=True)
class ConfigProducto:
    tope_usd: Decimal
    modelos_imagen: tuple[str, ...]
    resolucion: str
    palabras_por_pagina: int
    paginas_min: dict[str, int]
    seccion_palabras_min: int
    puntuacion_min: int


def importe_usd(v: Any, clave: str) -> Decimal:
    """Importe en USD: número o texto, > 0 y con dos decimales como mucho. ``ConfigInvalida`` si no."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ConfigInvalida(f"{clave}: importe ilegible ({v!r})")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise ConfigInvalida(f"{clave}: importe ilegible ({v!r})") from None
    if not d.is_finite() or d <= 0:
        raise ConfigInvalida(f"{clave}: debe ser un importe mayor que 0 ({v!r})")
    if d.as_tuple().exponent < -2:
        raise ConfigInvalida(f"{clave}: como mucho dos decimales ({v!r})")
    return d


def _valor(datos: dict, clave: str) -> Any:
    actual: Any = datos
    for parte in clave.split("."):
        if not isinstance(actual, dict) or _es_hoja(actual) or parte not in actual:
            raise ConfigInvalida(f"falta {clave} en config/producto.yaml")
        actual = actual[parte]
    if not _es_hoja(actual):
        raise ConfigInvalida(f"{clave}: no es una hoja {{valor, fuente, fecha}}")
    return actual["valor"]


def _entero(datos: dict, clave: str, maximo: int | None = None) -> int:
    v = _valor(datos, clave)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0 or (maximo is not None and v > maximo):
        rango = f"entre 1 y {maximo}" if maximo is not None else "mayor que 0"
        raise ConfigInvalida(f"{clave}: debe ser un entero {rango} ({v!r})")
    return v


def _construir(datos: Any) -> ConfigProducto:
    if not isinstance(datos, dict):
        raise ConfigInvalida("config/producto.yaml no es un mapa")
    try:
        _revisar_hojas(datos, "")
    except EconomiaInvalida as exc:
        raise ConfigInvalida(f"config/producto.yaml: {exc}") from None

    modelos = _valor(datos, "apimart.modelos_imagen")
    if not isinstance(modelos, list) or not modelos or not all(isinstance(m, str) and m.strip() for m in modelos):
        raise ConfigInvalida("apimart.modelos_imagen: debe ser una lista de modelos no vacía")
    resolucion = _valor(datos, "apimart.resolucion")
    if resolucion not in RESOLUCIONES:
        raise ConfigInvalida(f"apimart.resolucion: {resolucion!r} no es {', '.join(RESOLUCIONES)}")
    paginas = {t: _entero(datos, f"plan.paginas_min.{t}") for t in TIPOS_PAGINAS}

    return ConfigProducto(
        tope_usd=importe_usd(_valor(datos, "apimart.tope_producto_usd"), "apimart.tope_producto_usd"),
        modelos_imagen=tuple(m.strip() for m in modelos),
        resolucion=resolucion,
        palabras_por_pagina=_entero(datos, "plan.palabras_por_pagina"),
        paginas_min=paginas,
        seccion_palabras_min=_entero(datos, "plan.seccion_palabras_min"),
        puntuacion_min=_entero(datos, "gates.puntuacion_min", maximo=100),
    )


def cargar_config(vault: Path) -> ConfigProducto:
    ruta = Path(vault) / RELATIVA
    if not ruta.is_file():
        raise FileNotFoundError("falta config/producto.yaml: ejecuta `trovefy producto iniciar`")
    try:
        datos = cargar_yaml(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigInvalida(f"config/producto.yaml no se puede leer: {exc}") from None
    return _construir(datos)


def iniciar_config(vault: Path) -> Path:
    """Copia la plantilla a ``config/producto.yaml``; nunca sobrescribe."""
    ruta = Path(vault) / RELATIVA
    if ruta.exists():
        raise FileExistsError(f"ya existe {RELATIVA}: no se sobrescribe")
    escribir_atomico(ruta, PLANTILLA.read_text(encoding="utf-8"))
    return ruta


def tope_de(vault: Path, p_id: str, cfg: ConfigProducto) -> Decimal:
    """Tope de APIMart del producto: ``PRODUCTO.md`` → ``apimart_tope_usd`` si está; si no, ``cfg.tope_usd``."""
    ruta = Path(vault) / "productos" / validar_p_id(p_id) / "PRODUCTO.md"
    if not ruta.is_file():
        return cfg.tope_usd
    meta, _ = frontmatter.leer(ruta)
    valor = (meta or {}).get("apimart_tope_usd")
    if valor is None:
        return cfg.tope_usd
    return importe_usd(valor, f"productos/{p_id}/PRODUCTO.md: apimart_tope_usd")
