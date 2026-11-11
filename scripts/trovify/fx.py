"""Cambio de referencia del BCE. Sin cambio fiable, el precio es «no medido»; nunca se inventa."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Cambio:
    """Cambios de referencia del BCE: ``tasas`` (unidades por 1 EUR), su ``fecha`` (AAAA-MM-DD, la del
    XML; None si no se sabe) y la ``url`` de donde salen."""

    tasas: dict[str, float]
    fecha: str | None
    url: str = URL


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_seguro(url: str, timeout: float = _TIMEOUT):
    if urlparse(url).scheme != "https":
        raise ValueError("solo https")
    return urllib.request.build_opener(_SinRedireccion).open(url, timeout=timeout)


def _tasa_valida(x: float) -> bool:
    return math.isfinite(x) and x > 0


def _parsear(datos: bytes) -> Cambio | None:
    try:
        texto = datos.decode("utf-8")  # cualquier otra codificación (UTF-16…) se rechaza
    except UnicodeDecodeError:
        return None
    if "<!DOCTYPE" in texto.upper() or "<!ENTITY" in texto.upper():
        return None
    try:
        raiz = ElementTree.fromstring(datos)
        tasas: dict[str, float] = {}
        fecha: str | None = None
        for c in raiz.iter(f"{_NS}Cube"):
            moneda, tasa = c.get("currency"), c.get("rate")
            if moneda is None and tasa is None:
                t = c.get("time")
                if t is not None:
                    fecha = date.fromisoformat(t).isoformat()  # ValueError si no es una fecha
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
    return Cambio(tasas, fecha)


def _leer_cache(ruta: Path) -> Cambio | None:
    """``{"fecha": …, "tasas": {…}}``; la caché antigua (solo las tasas) vale, sin fecha."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        fecha = None
        if isinstance(datos.get("tasas"), dict):
            fecha = datos.get("fecha")
            fecha = date.fromisoformat(fecha).isoformat() if isinstance(fecha, str) else None
            datos = datos["tasas"]
        tasas = {str(k): float(v) for k, v in datos.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not tasas or not all(_tasa_valida(v) for v in tasas.values()):
        return None
    tasas["EUR"] = 1.0
    return Cambio(tasas, fecha)


def cambios(vault: Path, hoy: date, abrir=_abrir_seguro) -> dict[str, float] | None:
    """Unidades de cada moneda por 1 EUR (BCE); None sin cambio fiable. Ver :func:`cambio_del_dia`."""
    c = cambio_del_dia(vault, hoy, abrir)
    return None if c is None else c.tasas


def cambio_del_dia(vault: Path, hoy: date, abrir=_abrir_seguro) -> Cambio | None:
    """Cambios del BCE con su fecha y su fuente. Caché del día en ``data/cache/fx-AAAA-MM-DD.json``."""
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
    cambio = _parsear(datos)
    if cambio is None:
        return None
    try:
        escribir_atomico(ruta, json.dumps({"fecha": cambio.fecha, "tasas": cambio.tasas}, sort_keys=True))
    except OSError:
        pass  # sin caché sigue siendo un cambio válido de hoy
    return cambio


def a_eur(importe: float, moneda: str, tasas: dict[str, float] | None) -> Medida:
    moneda = (moneda or "").upper()
    if tasas is None or moneda not in tasas:
        return Medida(None, f"no medido: sin cambio de referencia para {moneda or 'moneda desconocida'}")
    return Medida(importe / tasas[moneda])
