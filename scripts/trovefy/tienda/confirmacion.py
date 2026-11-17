"""Confirmación, por el usuario y con su pantalla real delante, de una pantalla con controles del mapa.

Una pantalla con `controles` solo es escribible con su propio `capturado` (ruling R-1 del plan 19). Hasta que
un commit ponga esa fecha en el mapa del repo, el usuario la confirma en su vault: abre la pantalla en la
ventana visible, Trovefy comprueba firma y controles sin pulsar nada, y él responde «sí». Queda en
`config/pantallas-confirmadas.yaml`:

    impultienda:
      diseno_contenido: {fecha, url, huella, respuesta, evidencia}

`url` es la de la pantalla real (la del mapa puede ser una suposición) y `huella` la de la pantalla del mapa
que se confirmó (`url`, `firma`, `controles`): si el mapa cambia, la confirmación deja de valer. Una URL fuera
de los orígenes del mapa, de login o de cobros no se confirma ni se acepta al leer (aunque se edite a mano).
El `capturado` del código, si lo hay, manda sobre esto.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urldefrag

import yaml

from trovefy.mapa import capturado_de, origen, origenes_de, palabra_prohibida, prohibida
from trovefy.navegador import sesion_caducada
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

RUTA = "config/pantallas-confirmadas.yaml"
_SI = frozenset({"si", "sí"})


def huella_pantalla(pantalla: dict) -> str:
    """sha256 de lo que se confirma de una pantalla: `url`, `firma` y `controles`."""
    proyeccion = {"url": pantalla.get("url"), "firma": pantalla.get("firma"),
                  "controles": pantalla.get("controles") or {}}
    return hashlib.sha256(json.dumps(proyeccion, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _motivo_url(mapa: dict, url: str) -> str | None:
    """Por qué `url` no puede ser la de una pantalla confirmada (None si puede)."""
    if not isinstance(url, str) or origen(url) not in origenes_de(mapa):
        return "la URL no es de un origen del mapa (https y su host)"
    if sesion_caducada(url):
        return "la URL es de una pantalla de inicio de sesión"
    if palabra := palabra_prohibida(url):
        return f"la URL parece de cobros o datos sensibles («{palabra}»)"
    return None


def _leer(vault: Path) -> dict:
    ruta = Path(vault) / RUTA
    if not ruta.exists():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"{RUTA} no se puede leer ({type(exc).__name__}); no se sobrescribe") from exc
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise ValueError(f"{RUTA} no se puede leer (no es un mapa); no se sobrescribe")  # noqa: TRY004
    return datos


def confirmar_pantalla(vault: Path, servicio: str, mapa: dict, nombre: str, url: str, respuesta: str,
                       ahora: datetime, evidencia: str | None = None) -> dict:
    """Registra la confirmación del usuario de la pantalla `nombre` vista en `url`.

    `respuesta` son las palabras literales del usuario: solo «si»/«sí» confirma (si no, `ValueError` y no se
    escribe nada). Devuelve la entrada escrita.
    """
    vault = Path(vault)
    p = mapa["pantallas"].get(nombre)
    if p is None:
        raise ValueError(f"no hay pantalla «{nombre}» en el mapa")
    if prohibida(mapa, nombre):
        raise ValueError(f"«{nombre}» es una pantalla prohibida (cobros, pasarelas…): nunca se confirma para escribir")
    if not p.get("controles"):
        raise ValueError(f"«{nombre}» no tiene controles: es de solo lectura y no hace falta confirmarla")
    if not isinstance(respuesta, str) or respuesta.strip().casefold() not in _SI:
        raise ValueError(f"respuesta «{respuesta}»: no se confirma nada (hace falta un «sí»)")
    url = urldefrag(url).url if isinstance(url, str) else url
    if motivo := _motivo_url(mapa, url):
        raise ValueError(f"{motivo}: no se confirma nada")
    datos = _leer(vault)
    entrada = {"fecha": ahora.astimezone(ZONA_NEGOCIO).date().isoformat(), "url": url,
               "huella": huella_pantalla(p), "respuesta": respuesta.strip(), "evidencia": evidencia}
    servicio_datos = datos.get(servicio) if isinstance(datos.get(servicio), dict) else {}
    datos[servicio] = {**servicio_datos, nombre: entrada}
    escribir_atomico(vault / RUTA, yaml.safe_dump(datos, allow_unicode=True, sort_keys=True))
    anadir_log(vault, "landing", f"{servicio}: pantalla {nombre} confirmada por el usuario",
               [RUTA, *([evidencia] if evidencia else [])], ahora=ahora)
    return entrada


def mapa_con_confirmaciones(vault: Path, servicio: str, mapa: dict) -> dict:
    """Copia de `mapa` con `capturado` y la `url` real de las pantallas que el usuario confirmó.

    Solo cuentan las confirmaciones con la huella de la pantalla actual y una URL válida, y solo en pantallas
    sin `capturado` propio en el mapa. Un archivo ilegible cuenta como «sin confirmar».
    """
    salida = copy.deepcopy(mapa)
    try:
        confirmadas = _leer(vault).get(servicio)
    except (ValueError, OSError):
        return salida
    if not isinstance(confirmadas, dict):
        return salida
    for nombre, entrada in confirmadas.items():
        p = salida["pantallas"].get(nombre)
        if p is None or not isinstance(entrada, dict) or capturado_de(mapa, nombre) is not None:
            continue
        fecha = entrada.get("fecha")
        fecha = fecha.isoformat() if isinstance(fecha, date) else fecha
        if (entrada.get("huella") != huella_pantalla(mapa["pantallas"][nombre]) or not isinstance(fecha, str)
                or _motivo_url(mapa, entrada.get("url")) or prohibida(mapa, nombre)):
            continue
        try:
            date.fromisoformat(fecha)
        except ValueError:
            continue
        p["capturado"] = fecha
        p["url"] = entrada["url"]
    return salida
