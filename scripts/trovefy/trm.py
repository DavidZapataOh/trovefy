"""TRM oficial (COP por USD, Banco de la República vía datos.gov.co). Sin TRM fiable, el importe es
«no medido»; nunca se inventa."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode, urlparse

from trovefy.caza.senales import Medida
from trovefy.vault.escritura import escribir_atomico

URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
FUENTE = "TRM · Banco de la República (datos.gov.co, 32sa-8pi3)"
_HOST = "www.datos.gov.co"
_TIMEOUT = 15
_MAX_BYTES = 1_000_000
_MIN, _MAX = Decimal(1000), Decimal(10000)


@dataclass(frozen=True)
class Trm:
    """TRM vigente de ``desde`` a ``hasta`` (fechas inclusivas, como las publica el Banco)."""

    cop_por_usd: Decimal
    desde: date
    hasta: date
    url: str = URL

    def vigente(self, dia: date) -> bool:
        return self.desde <= dia <= self.hasta

    def etiqueta(self, dia: date) -> str:
        valor = f"{self.cop_por_usd.quantize(Decimal('0.01')):,.2f}"
        valor = valor.replace(",", "\0").replace(".", ",").replace("\0", ".")
        base = f"TRM {valor} COP/USD · Banco de la República"
        if self.vigente(dia):
            return f"{base} · vigente {self.desde.isoformat()} a {self.hasta.isoformat()}"
        return f"{base} · última publicada, del {self.desde.isoformat()} (sin TRM para {dia.isoformat()})"


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_seguro(url: str, timeout: float = _TIMEOUT):
    if urlparse(url).scheme != "https":
        raise ValueError("solo https")
    return urllib.request.build_opener(_SinRedireccion).open(url, timeout=timeout)


def _fecha(texto: object) -> date:
    if not isinstance(texto, str):
        raise TypeError("fecha ilegible")
    return datetime.fromisoformat(texto).date()


def _fila(fila: object) -> Trm | None:
    """Una fila del Banco → Trm, o None si algo no cuadra (dato corrupto)."""
    if not isinstance(fila, dict) or fila.get("unidad") != "COP":
        return None
    try:
        crudo = fila.get("valor")
        if not isinstance(crudo, str):
            return None
        valor = Decimal(crudo.strip())
        if not valor.is_finite() or not (_MIN <= valor <= _MAX):
            return None
        desde, hasta = _fecha(fila.get("vigenciadesde")), _fecha(fila.get("vigenciahasta"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if hasta < desde:
        return None
    return Trm(valor, desde, hasta)


def _parsear(datos: bytes) -> Trm | None:
    try:
        lista = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(lista, list) or not lista:
        return None
    return _fila(lista[0])


def _leer_cache(ruta: Path, dia: date) -> Trm | None:
    try:
        trm = _parsear(ruta.read_bytes())
    except OSError:
        return None
    return trm if trm is not None and trm.vigente(dia) else None


def trm_del_dia(vault: Path, dia: date, abrir=_abrir_seguro) -> Trm | None:
    """La TRM vigente el ``dia`` (o, si aún no hay, la última publicada: ver ``Trm.etiqueta``).
    Caché ``data/cache/trm-AAAA-MM-DD.json`` solo si la fila es vigente para ``dia``."""
    ruta = Path(vault) / "data" / "cache" / f"trm-{dia.isoformat()}.json"
    en_cache = _leer_cache(ruta, dia)
    if en_cache is not None:
        return en_cache
    consulta = urlencode(
        {
            "$where": f"vigenciadesde <= '{dia.isoformat()}T00:00:00.000'",
            "$order": "vigenciadesde DESC",
            "$limit": "1",
        }
    )
    try:
        with abrir(f"{URL}?{consulta}", timeout=_TIMEOUT) as r:
            final = getattr(r, "geturl", None)
            if callable(final) and urlparse(final()).hostname != _HOST:
                return None
            datos = r.read(_MAX_BYTES + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if len(datos) > _MAX_BYTES:
        return None
    trm = _parsear(datos)
    if trm is None:
        return None
    if trm.vigente(dia):
        try:
            escribir_atomico(ruta, datos.decode("utf-8"))
        except OSError:
            pass  # sin caché sigue siendo una TRM válida
    return trm


def cop_a_usd_centavos(cop: Decimal, trm: Trm) -> int:
    """COP → centavos de USD, redondeando al alza (nunca se subestima un gasto)."""
    return int((cop / trm.cop_por_usd * 100).to_integral_value(rounding=ROUND_CEILING))


def usd_centavos_a_cop(centavos: int, trm: Trm) -> Decimal:
    """Centavos de USD → COP en peso entero, a la baja."""
    return (Decimal(centavos) / 100 * trm.cop_por_usd).to_integral_value(rounding=ROUND_FLOOR)


def a_usd(cop: Decimal, trm: Trm | None, dia: date) -> Medida:
    if trm is None:
        return Medida(None, f"no medido: sin TRM del {dia.isoformat()}")
    valor = float(cop / trm.cop_por_usd)
    if not math.isfinite(valor):
        return Medida(None, f"no medido: importe fuera de rango para la TRM del {dia.isoformat()}")
    return Medida(valor)
