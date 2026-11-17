"""Confirmación, por el usuario y con su pantalla real delante, de una pantalla con controles del mapa.

Una pantalla con `controles` solo es escribible con su propio `capturado` (ruling R-1 del plan 19). Hasta que
un commit ponga esa fecha en el mapa del repo, el usuario la confirma: abre la pantalla en la ventana visible,
Trovefy comprueba firma y controles sin pulsar nada, y él responde «sí». Queda **fuera del vault**, en el
directorio de configuración de trovefy (`~/.config/trovefy/pantallas-confirmadas.yaml`, el mismo que guarda
las claves; el hook `apimart_gasto` impide a Claude leerlo o escribirlo):

    impultienda:
      diseno_contenido: {fecha, url, huella, respuesta, evidencia, evidencia_sha256}

`url` es la de la pantalla real (la del mapa puede ser una suposición) y `huella` la de la pantalla del mapa
que se confirmó (`url`, `firma`, `controles`): si el mapa cambia, la confirmación deja de valer. Una URL fuera
de los orígenes del mapa, de login o de cobros no se confirma ni se acepta al leer. El `capturado` del código,
si lo hay, manda sobre esto. La copia antigua del vault (`config/pantallas-confirmadas.yaml`) ya no se lee.

La evidencia es la captura enmascarada que deja `trovefy landing capturar` en el vault, exactamente
`config/evidencia/p05-<pantalla>-<fecha>.png` (con guiones; para `diseno_contenido`,
`p05-diseno-contenido-<fecha>.png`) de la misma `fecha` de la entrada: un PNG (por sus bytes mágicos), archivo
normal sin enlaces, cuyo SHA-256 se guarda al confirmar (`evidencia_sha256`) y se vuelve a calcular al leer.
Una confirmación de hace más de 90 días, o con fecha futura, no vale.

La confirmación exige una persona (ruling I-1): `confirmar_pantalla` comprueba ella misma que stdin y stdout son
una terminal; sin eso no escribe nada.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import sys
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urldefrag

import yaml

from trovefy.mapa import capturado_de, origen, origenes_de, palabra_prohibida, prohibida
from trovefy.navegador import _base, _base_privada, sesion_caducada
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

NOMBRE = "pantallas-confirmadas.yaml"
CADUCIDAD_DIAS = 90
PNG_MAGICO = b"\x89PNG\r\n\x1a\n"
SIN_TERMINAL = "`trovefy landing capturar`: ejecútalo tú en tu terminal."
_SI = frozenset({"si", "sí"})
_EVIDENCIA = ("config", "evidencia")


def ruta_confirmaciones() -> Path:
    """`~/.config/trovefy/pantallas-confirmadas.yaml` (el directorio de configuración de trovefy)."""
    return _base() / NOMBRE


def ruta_evidencia(nombre: str, fecha: str) -> str:
    """La captura de la pantalla `nombre` del día `fecha`, relativa al vault."""
    return f"config/evidencia/p05-{nombre.replace('_', '-')}-{fecha}.png"


def hay_terminal() -> bool:
    """¿Hay una persona delante? stdin y stdout son una terminal (no una tubería ni un agente)."""
    try:
        return os.isatty(sys.stdin.fileno()) and os.isatty(sys.stdout.fileno())
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return False


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


def _leer() -> dict:
    ruta = ruta_confirmaciones()
    if ruta.is_symlink():
        raise ValueError(f"{NOMBRE} es un enlace: no se lee ni se sobrescribe")
    if not ruta.exists():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"{NOMBRE} no se puede leer ({type(exc).__name__}); no se sobrescribe") from exc
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise ValueError(f"{NOMBRE} no se puede leer (no es un mapa); no se sobrescribe")  # noqa: TRY004
    return datos


def _evidencia_sha(vault: Path, evidencia: object) -> str | None:
    """SHA-256 de `evidencia` si es un PNG, archivo normal bajo `config/evidencia/` del vault y sin enlaces por
    medio (carpetas incluidas); None si no."""
    if not isinstance(evidencia, str) or not evidencia or "\\" in evidencia:
        return None
    partes = PurePosixPath(evidencia).parts
    if len(partes) != 3 or partes[:2] != _EVIDENCIA or any(p in ("..", ".", "") for p in partes):
        return None
    ruta = Path(vault)
    for parte in partes:
        ruta = ruta / parte
        if ruta.is_symlink():
            return None
    try:
        if not stat.S_ISREG(ruta.lstat().st_mode):
            return None
        contenido = ruta.read_bytes()
    except OSError:
        return None
    if not contenido.startswith(PNG_MAGICO):
        return None
    return hashlib.sha256(contenido).hexdigest()


def confirmar_pantalla(vault: Path, servicio: str, mapa: dict, nombre: str, url: str, respuesta: str,
                       ahora: datetime) -> dict:
    """Registra la confirmación del usuario de la pantalla `nombre` vista en `url`.

    Solo con stdin y stdout en una terminal. `respuesta` son las palabras literales del usuario: solo «si»/«sí»
    confirma. La captura `ruta_evidencia(nombre, fecha)` tiene que existir en el vault y ser un PNG. Si algo
    falla, `ValueError` y no se escribe nada. Devuelve la entrada escrita."""
    if not hay_terminal():
        raise ValueError(SIN_TERMINAL)
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
    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    evidencia = ruta_evidencia(nombre, fecha)
    if not (vault / evidencia).is_file():
        raise ValueError(f"falta la captura {evidencia}: no se confirma nada")
    sha = _evidencia_sha(vault, evidencia)
    if sha is None:
        raise ValueError(f"la captura {evidencia} no es un PNG normal (sin enlaces): no se confirma nada")
    datos = _leer()
    entrada = {"fecha": fecha, "url": url, "huella": huella_pantalla(p), "respuesta": respuesta.strip(),
               "evidencia": evidencia, "evidencia_sha256": sha}
    servicio_datos = datos.get(servicio) if isinstance(datos.get(servicio), dict) else {}
    datos[servicio] = {**servicio_datos, nombre: entrada}
    _base_privada()
    escribir_atomico(ruta_confirmaciones(), yaml.safe_dump(datos, allow_unicode=True, sort_keys=True))
    anadir_log(vault, "landing", f"{servicio}: pantalla {nombre} confirmada por el usuario (en la configuración "
               "de trovefy)", [evidencia], ahora=ahora)
    return entrada


def _vale(vault: Path, mapa: dict, nombre: str, entrada: object, hoy: date) -> str | None:
    """La fecha (ISO) de una confirmación que se puede creer, o None: «sí», huella, URL, fecha de los últimos
    90 días y la captura de esa fecha con su SHA-256."""
    if not isinstance(entrada, dict) or prohibida(mapa, nombre):
        return None
    respuesta = entrada.get("respuesta")
    if not isinstance(respuesta, str) or respuesta.strip().casefold() not in _SI:
        return None
    if entrada.get("huella") != huella_pantalla(mapa["pantallas"][nombre]) or _motivo_url(mapa, entrada.get("url")):
        return None
    fecha = entrada.get("fecha")
    fecha = fecha.isoformat() if isinstance(fecha, date) else fecha
    try:
        dia = date.fromisoformat(fecha) if isinstance(fecha, str) else None
    except ValueError:
        return None
    if dia is None or dia > hoy or (hoy - dia).days > CADUCIDAD_DIAS:
        return None
    evidencia = entrada.get("evidencia")
    if evidencia != ruta_evidencia(nombre, fecha):
        return None
    sha = entrada.get("evidencia_sha256")
    if not isinstance(sha, str) or not sha or _evidencia_sha(vault, evidencia) != sha:
        return None
    return fecha


def mapa_con_confirmaciones(vault: Path, servicio: str, mapa: dict, *, hoy: date | None = None) -> dict:
    """Copia de `mapa` con `capturado` y la `url` real de las pantallas que el usuario confirmó.

    Solo cuentan las confirmaciones de la configuración de trovefy que pasan `_vale` y solo en pantallas sin
    `capturado` propio en el mapa. Un archivo ilegible cuenta como «sin confirmar»."""
    hoy = hoy or datetime.now(ZONA_NEGOCIO).date()
    salida = copy.deepcopy(mapa)
    try:
        confirmadas = _leer().get(servicio)
    except (ValueError, OSError):
        return salida
    if not isinstance(confirmadas, dict):
        return salida
    for nombre, entrada in confirmadas.items():
        p = salida["pantallas"].get(nombre)
        if p is None or capturado_de(mapa, nombre) is not None:
            continue
        fecha = _vale(vault, mapa, nombre, entrada, hoy)
        if fecha is None:
            continue
        p["capturado"] = fecha
        p["url"] = entrada["url"]
    return salida


def url_confirmada(vault: Path, servicio: str, mapa: dict, nombre: str) -> str | None:
    """La URL confirmada por el usuario (en la configuración de trovefy, fuera del vault) si es esa confirmación
    (y no un `capturado` del mapa) la que hace escribible la pantalla `nombre`; None si no."""
    if capturado_de(mapa, nombre) is not None:
        return None
    c = mapa_con_confirmaciones(vault, servicio, mapa)
    return c["pantallas"][nombre]["url"] if capturado_de(c, nombre) is not None else None
