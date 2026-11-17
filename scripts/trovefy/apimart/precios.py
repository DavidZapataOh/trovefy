"""Precio por imagen de cada modelo (P-11) y elección del más barato.

``GET {base}/api/pricing/model?model=<modelo>`` es público: va **sin** clave. La forma real
(``tests/fixtures/apimart/pricing-gpt-image-2.json``, 2026-11-16) trae
``data.resolution_paid_prices = {"1K": 0.0085, "2K": 0.015, "4K": 0.022}``: USD por imagen, ya con el
descuento de la cuenta (ficha pública de ``gpt-image-2``: «0.085 Credits ≈ $0.0085»).
Sin precio medido no se envía nada (falla cerrado): ante cualquier duda, ``None``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from trovefy.apimart.http import (
    ErrorApimart,
    abrir_sin_redireccion,
    pedir_json,
    validar_base,
)
from trovefy.vault.escritura import escribir_atomico

# Fuente: documentación de /v1/balance (10,5 de saldo = 105 créditos) y ficha pública de gpt-image-2
# («0.085 Credits ≈ $0.0085»); el ejemplo de /v1/tasks lo confirma (cost 0.15 = credits_cost 1.5).
CREDITO_USD = Decimal("0.1")
# Más de 1 USD por imagen es un dato corrupto (una imagen 4k cuesta unos 0,022 USD).
MAX_USD_IMAGEN = Decimal(1)
RESOLUCIONES = ("1k", "2k", "4k")
_MODELO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.ASCII)
RUTA_CACHE = Path("data") / "cache"


@dataclass(frozen=True)
class Precio:
    modelo: str
    resolucion: str
    usd_por_imagen: Decimal
    fuente: str
    fecha: date


def _ruta_cache(vault: Path, modelo: str, hoy: date) -> Path:
    return Path(vault) / RUTA_CACHE / f"apimart-precio-{modelo}-{hoy.isoformat()}.json"


def _usd(cuerpo: object, resolucion: str) -> Decimal | None:
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("data"), dict):
        return None
    if cuerpo.get("success") is False:
        return None
    tabla = cuerpo["data"].get("resolution_paid_prices")
    if not isinstance(tabla, dict):
        return None
    v = tabla.get(resolucion.upper(), tabla.get(resolucion))
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    usd = Decimal(str(v))
    if not usd.is_finite() or usd <= 0 or usd > MAX_USD_IMAGEN:
        return None
    return usd


def _leer_cache(ruta: Path) -> object:
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def precio_imagen(vault: Path, base: str, modelo: str, resolucion: str, hoy: date,
                  abrir=abrir_sin_redireccion) -> Precio | None:
    """Precio por imagen de ``modelo`` en ``resolucion``, o ``None`` si no se puede medir.

    Caché del día en ``data/cache/apimart-precio-<modelo>-<AAAA-MM-DD>.json`` (la respuesta tal cual);
    solo se guarda una respuesta que da un precio válido. ``None`` (sin caché) ante red caída, error
    HTTP, forma desconocida, falta de la resolución o precio ≤ 0 o > 1 USD.
    """
    if not isinstance(modelo, str) or not _MODELO.fullmatch(modelo):
        raise ValueError(f"modelo de APIMart mal escrito: «{modelo}»")
    if resolucion not in RESOLUCIONES:
        raise ValueError(f"resolución no admitida: «{resolucion}» (usa {', '.join(RESOLUCIONES)})")
    validar_base(base)
    base = base.rstrip("/")
    ruta_api = f"/api/pricing/model?model={quote(modelo, safe='')}"
    fuente = f"{base}{ruta_api} → data.resolution_paid_prices.{resolucion.upper()} (USD)"
    cache = _ruta_cache(vault, modelo, hoy)
    cuerpo = _leer_cache(cache)
    usd = _usd(cuerpo, resolucion)
    if usd is None:
        try:
            cuerpo = pedir_json(None, "GET", ruta_api, abrir=abrir, base=base)
        except ErrorApimart:
            return None
        usd = _usd(cuerpo, resolucion)
        if usd is None:
            return None
        escribir_atomico(cache, json.dumps(cuerpo, ensure_ascii=False, sort_keys=True) + "\n")
    return Precio(modelo, resolucion, usd, fuente, hoy)


def elegir_modelo(precios: list[Precio | None]) -> Precio | None:
    """El más barato de los medidos; a igual precio, el primero de la lista. Todo ``None`` → ``None``."""
    mejor = None
    for p in precios:
        if p is not None and (mejor is None or p.usd_por_imagen < mejor.usd_por_imagen):
            mejor = p
    return mejor
