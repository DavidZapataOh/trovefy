"""Mapa versionado de pantallas de un servicio externo (Impultienda, Whop, Hotmart).

Un `mapa.yaml` describe, por pantalla, la URL, una *firma* (textos que deben aparecer para saber que
la pantalla es la esperada) y los campos que se leen con una expresión regular de un solo grupo.
Solo se lee: este módulo no hace clics ni escribe en el servicio.

`capturado` es la fecha en que el mapa se confirmó con la pantalla real del usuario; `None` significa
que se construyó a partir de documentación o páginas públicas y no se puede certificar nada con él.
"""

import re
from datetime import date
from pathlib import Path

import yaml


class MapaInvalido(ValueError):
    """El mapa.yaml no tiene la estructura esperada."""


class FirmaAusente(Exception):
    """Falta algún texto de la firma: la pantalla cambió o no es la esperada."""

    def __init__(self, pantalla):
        super().__init__(pantalla)
        self.pantalla = pantalla


_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


def _fecha(valor, ruta: Path) -> str | None:
    if valor is None:
        return None
    texto = valor.isoformat() if isinstance(valor, date) else str(valor)
    if not _FECHA.fullmatch(texto):
        raise MapaInvalido(f"{ruta}: «capturado» debe ser null o una fecha AAAA-MM-DD")
    return texto


def cargar(ruta: Path) -> dict:
    """Lee y valida un mapa.yaml; `capturado` sale como `str | None`."""
    ruta = Path(ruta)
    try:
        mapa = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        raise MapaInvalido(f"{ruta} no se puede leer: {type(exc).__name__}") from exc
    if not isinstance(mapa, dict):
        raise MapaInvalido(f"{ruta} no es un mapa")
    if "capturado" not in mapa:
        raise MapaInvalido(f"{ruta}: falta «capturado» (null o AAAA-MM-DD)")
    mapa["capturado"] = _fecha(mapa["capturado"], ruta)
    if not isinstance(mapa.get("fuente"), str) or not mapa["fuente"].strip():
        raise MapaInvalido(f"{ruta}: falta «fuente»")
    pantallas = mapa.get("pantallas")
    if not isinstance(pantallas, dict) or not pantallas:
        raise MapaInvalido(f"{ruta}: falta «pantallas»")
    for nombre, p in pantallas.items():
        if not isinstance(p, dict):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» no es un mapa")
        if not isinstance(p.get("url"), str) or not p["url"].startswith("https://"):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» necesita una «url» https")
        firma = p.get("firma")
        if not isinstance(firma, list) or not firma or not all(isinstance(t, str) and t for t in firma):
            raise MapaInvalido(f"{ruta}: la pantalla «{nombre}» necesita «firma» (lista de textos)")
        campos = p.get("campos", {})
        if not isinstance(campos, dict):
            raise MapaInvalido(f"{ruta}: «campos» de «{nombre}» no es un mapa")
        for campo, c in campos.items():
            patron = c.get("patron") if isinstance(c, dict) else None
            if not isinstance(patron, str):
                raise MapaInvalido(f"{ruta}: el campo «{campo}» de «{nombre}» necesita «patron»")
            try:
                compilado = re.compile(patron)
            except re.error as exc:
                raise MapaInvalido(f"{ruta}: patrón inválido en «{nombre}.{campo}»") from exc
            if compilado.groups != 1:
                raise MapaInvalido(f"{ruta}: el patrón de «{nombre}.{campo}» debe tener exactamente un grupo")
        p.setdefault("campos", {})
    return mapa


def leer_pantalla(pantalla: dict, texto: str) -> dict[str, str | None]:
    """Campos de la pantalla; lanza `FirmaAusente` si falta algún texto de la firma."""
    if any(t not in texto for t in pantalla["firma"]):
        raise FirmaAusente(pantalla)
    salida: dict[str, str | None] = {}
    for campo, c in pantalla.get("campos", {}).items():
        m = re.search(c["patron"], texto)
        salida[campo] = m.group(1).strip() if m else None
    return salida
