"""HTTP de APIMart: credenciales, base https, petición JSON sin redirecciones y errores con nombre.

Sale del verificador del paso 16 (``trovefy.arranque.verificadores.apimart``), que ahora importa de aquí.
Patrón portado de LordVayron/video-factory ``engine/lib/apimart.mjs`` (MIT, commit 8afd1b2e).

Reglas (contrato 5): la clave sale solo de ``claude.env``; ``Credenciales`` no la muestra en ``repr``;
ningún mensaje de error lleva cabeceras ni la clave; no se siguen redirecciones (urllib copiaría
``Authorization`` al destino). Formas de respuesta y de error: ``tests/fixtures/apimart/README.md``.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from trovefy.secretos import RUTA_CLAUDE_ENV, EnvNoSeguro, PermisosInseguros, leer_env

BASE_POR_DEFECTO = "https://api.apimart.ai"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
TIMEOUT = 30
MAX_RESPUESTA = 1 << 20  # 1 MB: las respuestas JSON de APIMart ocupan unos cientos de bytes
_TIPOS_SIN_SALDO = ("payment_required", "insufficient_user_quota")


class ErrorApimart(Exception):
    """Base de los errores de APIMart. El mensaje nunca lleva la clave ni cabeceras."""


class ClaveRechazada(ErrorApimart):
    pass


class SinSaldo(ErrorApimart):
    pass


class Limitado(ErrorApimart):
    pass


class ErrorServidor(ErrorApimart):
    pass


class SinRed(ErrorApimart):
    pass


class RespuestaInesperada(ErrorApimart):
    pass


class BaseInvalida(ErrorApimart):
    pass


class ClaveRara(ErrorApimart):
    pass


class SinClave(ErrorApimart):
    """No hay credenciales usables; ``motivo`` y ``arreglos`` son los del paso 16."""

    def __init__(self, motivo: str, arreglos: list[str]) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.arreglos = list(arreglos)


@dataclass(frozen=True, repr=False)
class Credenciales:
    base: str
    clave: str

    def __repr__(self) -> str:
        return f"Credenciales(base={self.base!r}, clave=***)"

    __str__ = __repr__


class SinRedireccion(urllib.request.HTTPRedirectHandler):
    """No sigue redirecciones: urllib copiaría Authorization al destino."""

    def redirect_request(self, *args, **kwargs):
        return None


def abrir_sin_redireccion(req, timeout=None):
    return urllib.request.build_opener(SinRedireccion).open(req, timeout=timeout)


def validar_base(base: str) -> None:
    """https, o http solo hacia loopback (pruebas locales). ``BaseInvalida`` si no."""
    try:
        u = urlparse(base)
        host = u.hostname
    except ValueError:
        raise BaseInvalida from None
    if not host or not (u.scheme == "https" or (u.scheme == "http" and host in LOOPBACK)):
        raise BaseInvalida


def clave_valida(clave: str) -> bool:
    return bool(clave) and clave.isascii() and clave.isprintable() and " " not in clave


def leer_credenciales(ruta_env: Path = RUTA_CLAUDE_ENV) -> Credenciales:
    """Lee ``APIMART_API_KEY`` y ``APIMART_BASE_URL`` (opcional, https) de ``ruta_env`` (modo 0600).

    Lanza ``SinClave`` con los mismos motivos y arreglos que el verificador del paso 16.
    """
    try:
        env = leer_env(ruta_env)
    except FileNotFoundError:
        raise SinClave(f"no existe {ruta_env}", [
            "en una terminal de Ubuntu (WSL) aparte: `mkdir -p ~/.config/trovefy && touch ~/.config/trovefy/claude.env && chmod 600 ~/.config/trovefy/claude.env`",
            "en esa terminal, abre ~/.config/trovefy/claude.env con un editor (por ejemplo `nano ~/.config/trovefy/claude.env`) y pega tu clave como APIMART_API_KEY=... (Claude no la ve)",
        ]) from None
    except EnvNoSeguro as exc:
        raise SinClave(f"{ruta_env} no es seguro: {exc}",
                       ["usa un archivo regular tuyo, sin enlaces simbólicos, con permisos 600"]) from None
    except (OSError, UnicodeDecodeError):  # PermissionError, IsADirectoryError…; sin contenido ni clave
        raise SinClave(f"no se pudo leer {ruta_env}",
                       ["comprueba que es un archivo de texto UTF-8 legible por ti"]) from None
    except PermisosInseguros as exc:
        raise SinClave(f"{ruta_env} tiene permisos {exc.modo:o}; deben ser 600",
                       [f"en una terminal de Ubuntu (WSL) aparte: `chmod 600 {ruta_env}`"]) from None
    clave = env.get("APIMART_API_KEY", "")
    if not clave:
        raise SinClave("falta APIMART_API_KEY en claude.env", [
            "en una terminal de Ubuntu (WSL) aparte, abre ~/.config/trovefy/claude.env con tu editor y añade APIMART_API_KEY=... (Claude no la ve)",
        ])
    if not clave_valida(clave):
        raise SinClave("la clave tiene caracteres raros; vuelve a pegarla", [
            "en una terminal de Ubuntu (WSL) aparte, abre ~/.config/trovefy/claude.env y pega la clave de nuevo, sin espacios ni caracteres especiales",
        ])
    base = (env.get("APIMART_BASE_URL") or BASE_POR_DEFECTO).rstrip("/")
    try:
        validar_base(base)
    except BaseInvalida:
        raise SinClave("APIMART_BASE_URL debe ser https", [
            "corrige APIMART_BASE_URL en claude.env (https://..., o bórrala para usar la oficial)",
        ]) from None
    return Credenciales(base, clave)


def credenciales_publicas(ruta_env: Path = RUTA_CLAUDE_ENV) -> Credenciales:
    """Credenciales **sin clave** para lo público (el precio de ``--simular``; ruling de la revisión final).

    La base sale de ``APIMART_BASE_URL`` si ``ruta_env`` se puede leer y es https; si no, la oficial. La
    clave nunca se toma, aunque esté en el archivo.
    """
    try:
        base = (leer_env(ruta_env).get("APIMART_BASE_URL") or BASE_POR_DEFECTO).rstrip("/")
        validar_base(base)
    except (OSError, UnicodeDecodeError, EnvNoSeguro, PermisosInseguros, BaseInvalida):
        base = BASE_POR_DEFECTO
    return Credenciales(base, "")


def _limpio(texto: object, clave: str | None) -> str:
    """Texto del servidor apto para un mensaje: una línea, corto y sin la clave."""
    t = re.sub(r"\s+", " ", str(texto))[:200]
    if clave:
        t = t.replace(clave, "***")
    return re.sub(r"(?i)bearer\s+\S+", "Bearer ***", t)


def _error_de(datos: object) -> dict:
    if isinstance(datos, dict) and isinstance(datos.get("error"), dict):
        return datos["error"]
    return {}


def _lanzar(codigo: int, datos: object, clave: str | None) -> None:
    err = _error_de(datos)
    tipo = err.get("type") if isinstance(err.get("type"), str) else ""
    if codigo in (401, 403):
        raise ClaveRechazada(f"APIMart rechazó la clave (HTTP {codigo})")
    if codigo == 402 or tipo in _TIPOS_SIN_SALDO:
        raise SinSaldo("APIMart: saldo insuficiente; recarga en el panel de APIMart")
    if codigo == 429:
        raise Limitado("APIMart: demasiadas peticiones; prueba más tarde")
    if codigo >= 500:
        raise ErrorServidor(f"APIMart falló en su lado (HTTP {codigo})")
    detalle = f" ({_limpio(tipo, clave)}: {_limpio(err.get('message', ''), clave)})" if err else ""
    raise RespuestaInesperada(f"APIMart respondió HTTP {codigo}{detalle}")


def _leer_json(cuerpo: bytes) -> object:
    try:
        return json.loads(cuerpo)
    except (ValueError, UnicodeDecodeError):
        return None


def pedir(cred: Credenciales | None, metodo: Literal["GET", "POST"], ruta: str, datos: bytes | None = None,
          tipo: str | None = None, abrir=abrir_sin_redireccion, timeout: float = TIMEOUT, *,
          base: str | None = None) -> dict:
    """Petición cruda (``datos`` ya codificados, ``tipo`` = Content-Type) que devuelve un mapa JSON.

    Con ``cred`` va ``Authorization: Bearer``; sin ``cred`` (precios públicos) no, y la base es ``base``.
    """
    raiz = (cred.base if cred is not None else (base or BASE_POR_DEFECTO)).rstrip("/")
    validar_base(raiz)
    if not ruta.startswith("/"):
        raise ValueError(f"ruta de APIMart mal escrita: {ruta!r}")
    cabeceras = {"Accept": "application/json", "User-Agent": "trovefy"}
    if tipo:
        cabeceras["Content-Type"] = tipo
    clave = None
    if cred is not None:
        if not clave_valida(cred.clave):
            raise ClaveRara("la clave tiene caracteres raros")
        clave = cred.clave
        cabeceras["Authorization"] = f"Bearer {clave}"
    req = urllib.request.Request(raiz + ruta, data=datos, headers=cabeceras, method=metodo)
    try:
        with abrir(req, timeout=timeout) as resp:
            codigo, cuerpo = resp.status, resp.read(MAX_RESPUESTA + 1)
    except urllib.error.HTTPError as exc:
        try:
            cuerpo = exc.read(MAX_RESPUESTA) if exc.fp is not None else b""
        except Exception:  # noqa: BLE001 - el cuerpo del error es opcional
            cuerpo = b""
        _lanzar(exc.code, _leer_json(cuerpo), clave)
        raise  # inalcanzable: _lanzar siempre lanza
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        # HTTPException (BadStatusLine, IncompleteRead…) puede llevar bytes de la conexión: mensaje fijo.
        raise SinRed("sin red: APIMart no responde") from None
    if len(cuerpo) > MAX_RESPUESTA:
        raise RespuestaInesperada("respuesta de APIMart de más de 1 MB")
    datos_json = _leer_json(cuerpo)
    if datos_json is None:
        if codigo >= 400:
            _lanzar(codigo, None, clave)
        raise RespuestaInesperada("APIMart no devolvió JSON")
    err = _error_de(datos_json)
    if codigo >= 400 or err:
        # Un error dentro de un 200 se trata por su propio código (o como 400 si no lo trae).
        propio = err.get("code")
        if codigo < 400:
            codigo = propio if isinstance(propio, int) and not isinstance(propio, bool) and propio >= 400 else 400
        _lanzar(codigo, datos_json, clave)
    if not isinstance(datos_json, dict):
        raise RespuestaInesperada("la respuesta de APIMart no es un objeto JSON")
    return datos_json


def pedir_json(cred: Credenciales | None, metodo: Literal["GET", "POST"], ruta: str, cuerpo: dict | None = None,
               abrir=abrir_sin_redireccion, timeout: float = TIMEOUT, *, base: str | None = None) -> dict:
    """``pedir`` con cuerpo JSON. Errores: 401/403 ``ClaveRechazada``; 402 o ``payment_required``
    ``SinSaldo``; 429 ``Limitado``; ≥ 500 ``ErrorServidor``; red ``SinRed``; JSON roto o > 1 MB
    ``RespuestaInesperada``."""
    datos = None if cuerpo is None else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    tipo = None if cuerpo is None else "application/json"
    return pedir(cred, metodo, ruta, datos, tipo, abrir, timeout, base=base)
