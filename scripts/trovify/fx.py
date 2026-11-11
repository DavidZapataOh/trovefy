"""Cambio de referencia del BCE. Sin cambio fiable, el precio es «no medido»; nunca se inventa."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from trovify.caza.senales import Medida
from trovify.vault.escritura import escribir_atomico

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_HOST = "www.ecb.europa.eu"
_TIMEOUT = 15
_MAX_BYTES = 1_000_000
_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_seguro(url: str, timeout: float = _TIMEOUT):
    if urlparse(url).scheme != "https":
        raise ValueError("solo https")
    return urllib.request.build_opener(_SinRedireccion).open(url, timeout=timeout)


def _tasa_valida(x: float) -> bool:
    return math.isfinite(x) and x > 0


def _parsear(datos: bytes) -> dict[str, float] | None:
    cabecera = datos.upper()
    if b"<!DOCTYPE" in cabecera or b"<!ENTITY" in cabecera:
        return None
    try:
        raiz = ElementTree.fromstring(datos)
        tasas: dict[str, float] = {}
        for c in raiz.iter(f"{_NS}Cube"):
            moneda, tasa = c.get("currency"), c.get("rate")
            if moneda is None and tasa is None:
                continue
            if not moneda or not moneda.isalpha() or len(moneda) != 3 or tasa is None:
                return None
            valor = float(tasa)
            if not _tasa_valida(valor):
                return None
            tasas[moneda.upper()] = valor
    except (ElementTree.ParseError, ValueError):
        return None
    if not tasas:
        return None
    tasas["EUR"] = 1.0
    return tasas


def _leer_cache(ruta: Path) -> dict[str, float] | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        tasas = {str(k): float(v) for k, v in datos.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not tasas or not all(_tasa_valida(v) for v in tasas.values()):
        return None
    tasas["EUR"] = 1.0
    return tasas


def cambios(vault: Path, hoy: date, abrir=_abrir_seguro) -> dict[str, float] | None:
    """Unidades de cada moneda por 1 EUR (BCE). Caché del día en ``data/cache/fx-AAAA-MM-DD.json``."""
    ruta = Path(vault) / "data" / "cache" / f"fx-{hoy.isoformat()}.json"
    en_cache = _leer_cache(ruta)
    if en_cache is not None:
        return en_cache
    try:
        with abrir(URL, timeout=_TIMEOUT) as r:
            final = getattr(r, "geturl", None)
            if callable(final) and urlparse(final()).hostname != _HOST:
                return None
            datos = r.read(_MAX_BYTES + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if len(datos) > _MAX_BYTES:
        return None
    tasas = _parsear(datos)
    if tasas is None:
        return None
    try:
        escribir_atomico(ruta, json.dumps(tasas, sort_keys=True))
    except OSError:
        pass  # sin caché sigue siendo un cambio válido de hoy
    return tasas


def a_eur(importe: float, moneda: str, tasas: dict[str, float] | None) -> Medida:
    moneda = (moneda or "").upper()
    if tasas is None or moneda not in tasas:
        return Medida(None, f"no medido: sin cambio de referencia para {moneda or 'moneda desconocida'}")
    return Medida(importe / tasas[moneda])
