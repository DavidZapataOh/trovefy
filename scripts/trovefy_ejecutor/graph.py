"""Cliente de la Graph API de Meta (v25.0) sobre urllib.

Reglas: el token solo viaja en la cabecera ``Authorization: Bearer``; ninguna excepción lleva la URL,
la petición ni el token (se levantan fuera de ``except`` para no encadenar causas); sin redirecciones;
las escrituras nunca se reintentan aquí.
"""

from __future__ import annotations

import base64
import http.client
import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from trovefy_ejecutor.auditoria import redactar

BASE = "https://graph.facebook.com"
VERSION = "v25.0"

_MAX_RESPUESTA = 5 * 1024 * 1024
_MAX_VIDEO = 100 * 1024 * 1024
_MAX_MENSAJE = 300
_MAX_TRAZA = 64
_SEGMENTO = re.compile(r"[A-Za-z0-9_]+")
_TIPO_BUSQUEDA = re.compile(r"[a-z_]+")

# Offset oficial de Meta por moneda. Graph no lo expone: la confirmación es «moneda leída + esta tabla» (P-21).
# Fuente: https://developers.facebook.com/documentation/ads-commerce/marketing-api/currencies (leído 2026-11-12).
# Debe coincidir con dinero.OFFSETS_OFICIALES (lo comprueba un test).
OFFSETS_META: dict[str, int] = {
    "DZD": 100, "ARS": 100, "AUD": 100, "BHD": 100, "BDT": 100, "BOB": 100, "BGN": 100, "BRL": 100,
    "GBP": 100, "CAD": 100, "CLP": 1, "CNY": 100, "COP": 1, "CRC": 1, "HRK": 100, "CZK": 100,
    "DKK": 100, "EGP": 100, "EUR": 100, "GTQ": 100, "HNL": 100, "HKD": 100, "HUF": 1, "ISK": 1,
    "INR": 100, "IDR": 1, "ILS": 100, "JPY": 1, "JOD": 100, "KES": 100, "KRW": 1, "LVL": 100,
    "LTL": 100, "MOP": 100, "MYR": 100, "MXN": 100, "NZD": 100, "NIO": 100, "NGN": 100, "NOK": 100,
    "PKR": 100, "PYG": 1, "PEN": 100, "PHP": 100, "PLN": 100, "QAR": 100, "RON": 100, "RUB": 100,
    "SAR": 100, "RSD": 100, "SGD": 100, "SKK": 100, "ZAR": 100, "SEK": 100, "CHF": 100, "TWD": 1,
    "THB": 100, "TRY": 100, "AED": 100, "UAH": 100, "USD": 100, "UYU": 100, "VEF": 100, "VND": 1,
    "FBZ": 100, "VES": 100,
}

_CAMPOS_CUENTA = ["currency", "timezone_name", "spend_cap", "account_status", "amount_spent"]


class DetenidoPorStop(Exception):
    """La lanza ``GraphConStop`` (plan 12) antes de una escritura cuando hay STOP."""


class ErrorGraph(Exception):
    def __init__(self, codigo: int, subcodigo: int | None, mensaje: str, fbtrace_id: str | None = None):
        self.codigo = codigo
        self.subcodigo = subcodigo
        self.mensaje = redactar(str(mensaje))[:_MAX_MENSAJE]
        self.fbtrace_id = None if fbtrace_id is None else redactar(str(fbtrace_id))[:_MAX_TRAZA]
        super().__init__(f"Meta {codigo}/{subcodigo or '-'}: {self.mensaje}")


class ErrorRed(Exception):
    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def clasificar(e: ErrorGraph) -> Literal["token", "limite_meta", "permiso", "otro"]:
    if e.codigo in (190, 102):
        return "token"
    if e.codigo in (4, 17, 32, 613, 80004):
        return "limite_meta"
    if e.codigo == 10 or 200 <= e.codigo <= 299:
        return "permiso"
    return "otro"


# Códigos de Meta que son un rechazo definitivo: la escritura o creación no se aplicó. Cualquier otro
# (1, 2, ≥ 500, el «HTTP 5xx» sin cuerpo, desconocidos) es ambiguo: puede haberse aplicado.
_RECHAZO_DEFINITIVO = frozenset({100, 190, 102, 10, 4, 17, 32, 613, 80004, *range(200, 300)})


def es_rechazo_definitivo(e: ErrorGraph) -> bool:
    return e.codigo in _RECHAZO_DEFINITIVO


@dataclass(frozen=True)
class InfoCuenta:
    currency: str
    offset: int | None
    timezone_name: str
    spend_cap: int | None
    account_status: int
    amount_spent: int | None


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_defecto(req, timeout=None):
    return urllib.request.build_opener(_SinRedireccion).open(req, timeout=timeout)


def _seg(*partes: str) -> str:
    for x in partes:
        if not isinstance(x, str) or not _SEGMENTO.fullmatch(x):
            raise ValueError("identificador de Graph inválido")
    return "/".join(partes)


def _entero(v: object) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _valor(v: object) -> str:
    if v is None:
        raise ValueError("valor None no se envía a Graph")
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _codificar(datos: Mapping[str, object], validate_only: bool) -> bytes:
    pares = [(k, _valor(v)) for k, v in datos.items()]
    if validate_only:
        pares.append(("execution_options", json.dumps(["validate_only"])))
    return urlencode(pares).encode("utf-8")


class ClienteGraph:
    def __init__(
        self,
        token: str,
        *,
        base: str = BASE,
        version: str = VERSION,
        abrir: Callable = _abrir_defecto,
        timeout_lectura: float = 20,
        timeout_escritura: float = 30,
        timeout_subida: float = 120,
    ) -> None:
        if not base.startswith("https://"):
            raise ValueError("Graph solo se llama por https")
        self._token = token
        self._base = base.rstrip("/")
        self._version = version
        self._abrir = abrir
        self._t_lectura = timeout_lectura
        self._t_escritura = timeout_escritura
        self._t_subida = timeout_subida

    def __repr__(self) -> str:
        return f"ClienteGraph(base={self._base!r}, version={self._version!r})"

    # -- transporte -------------------------------------------------------------------------
    def _limpio(self, texto: str) -> str:
        return texto.replace(self._token, "***") if self._token else texto

    def _enviar(self, metodo: str, ruta: str, *, consulta: str = "", cuerpo: bytes | None = None,
                tipo: str | None = None, timeout: float) -> dict:
        url = f"{self._base}/{self._version}/{ruta}" + (f"?{consulta}" if consulta else "")
        req = urllib.request.Request(url, data=cuerpo, method=metodo)
        req.add_header("Authorization", f"Bearer {self._token}")
        if tipo:
            req.add_header("Content-Type", tipo)
        datos: bytes | None = None
        fallo: tuple[int, bytes] | None = None
        motivo: str | None = None
        try:
            with self._abrir(req, timeout=timeout) as r:
                datos = r.read(_MAX_RESPUESTA + 1)
        except urllib.error.HTTPError as e:
            try:
                fallo = (e.code, e.read(_MAX_RESPUESTA + 1))
            except (OSError, ValueError):
                fallo = (e.code, b"")
            finally:
                e.close()
        except TimeoutError:
            motivo = "timeout"
        except (urllib.error.URLError, OSError):
            motivo = "conexión"
        except http.client.HTTPException:
            motivo = "conexión"
        if motivo is not None:
            raise ErrorRed(motivo) from None
        if fallo is not None:
            raise (self._error(fallo[1], fallo[0]) or ErrorGraph(fallo[0], None, f"HTTP {fallo[0]}")) from None
        assert datos is not None
        if len(datos) > _MAX_RESPUESTA:
            raise ErrorRed("respuesta ilegible") from None
        try:
            obj: Any = json.loads(datos.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            obj = None
        if not isinstance(obj, dict):
            raise ErrorRed("respuesta ilegible") from None
        if "error" in obj:
            err = self._error(datos, 200)
            if err is None:
                raise ErrorRed("respuesta ilegible") from None
            raise err from None
        return obj

    def _error(self, cuerpo: bytes, http: int) -> ErrorGraph | None:
        try:
            obj = json.loads(cuerpo.decode("utf-8"))
            err = obj["error"]
            codigo = _entero(err.get("code"))
            if codigo is None:
                raise ValueError
            return ErrorGraph(
                codigo,
                _entero(err.get("error_subcode")),
                self._limpio(str(err.get("message", ""))),
                None if err.get("fbtrace_id") is None else self._limpio(str(err["fbtrace_id"])),
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return None if http < 400 else ErrorGraph(http, None, f"HTTP {http}")

    # -- API --------------------------------------------------------------------------------
    def leer(self, id: str, campos: Sequence[str]) -> dict:
        return self._enviar("GET", _seg(id), consulta=urlencode({"fields": ",".join(campos)}, safe=","),
                            timeout=self._t_lectura)

    def listar(self, padre: str, arista: str, campos: Sequence[str],
               filtros: Mapping[str, object] | None = None, max_paginas: int = 20,
               limite: int | None = None) -> list[dict]:
        """Lista una arista. Falla cerrado: si quedan páginas tras ``max_paginas`` o hay ``next`` sin
        cursor, lanza ``ErrorRed("listado incompleto")`` (nunca devuelve un listado truncado)."""
        salida: list[dict] = []
        despues: str | None = None
        for _ in range(max_paginas):
            pares = [("fields", ",".join(campos))] + [(k, _valor(v)) for k, v in (filtros or {}).items()]
            if limite is not None:
                pares.append(("limit", str(int(limite))))
            if despues is not None:
                pares.append(("after", despues))
            r = self._enviar("GET", _seg(padre, arista), consulta=urlencode(pares, safe=","),
                             timeout=self._t_lectura)
            datos = r.get("data")
            if isinstance(datos, list):
                salida.extend(d for d in datos if isinstance(d, dict))
            paging = r.get("paging")
            if not isinstance(paging, dict) or not paging.get("next"):
                return salida
            cursores = paging.get("cursors")
            despues = cursores.get("after") if isinstance(cursores, dict) else None
            if not despues:
                break
        raise ErrorRed("listado incompleto")

    def buscar(self, tipo: str, q: str, campos: Sequence[str]) -> list[dict]:
        """``GET /search?type=…&q=…`` (solo lectura; p. ej. ``adlocale``). Una sola página: si Meta
        indica que hay más (``paging.next``), falla cerrado con ``ErrorRed("listado incompleto")``."""
        if not isinstance(tipo, str) or not _TIPO_BUSQUEDA.fullmatch(tipo):
            raise ValueError("tipo de búsqueda inválido")
        if not isinstance(q, str) or not 1 <= len(q) <= 100:
            raise ValueError("texto de búsqueda inválido")
        consulta = urlencode([("type", tipo), ("q", q), ("fields", ",".join(campos))], safe=",")
        r = self._enviar("GET", _seg("search"), consulta=consulta, timeout=self._t_lectura)
        datos = r.get("data")
        if not isinstance(datos, list):
            raise ErrorRed("respuesta ilegible") from None
        paging = r.get("paging")
        if isinstance(paging, dict) and paging.get("next"):
            raise ErrorRed("listado incompleto") from None
        return [d for d in datos if isinstance(d, dict)]

    def _post(self, ruta: str, datos: Mapping[str, object], validate_only: bool) -> dict:
        return self._enviar("POST", ruta, cuerpo=_codificar(datos, validate_only),
                            tipo="application/x-www-form-urlencoded", timeout=self._t_escritura)

    def escribir(self, id: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        return self._post(_seg(id), datos, validate_only)

    def crear(self, padre: str, arista: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        return self._post(_seg(padre, arista), datos, validate_only)

    def subir_imagen(self, act_id: str, contenido: bytes, nombre: str) -> str:
        cuerpo = urlencode({"bytes": base64.b64encode(contenido).decode("ascii"), "name": nombre}).encode()
        r = self._enviar("POST", _seg(act_id, "adimages"), cuerpo=cuerpo,
                         tipo="application/x-www-form-urlencoded", timeout=self._t_subida)
        imagenes = r.get("images")
        if isinstance(imagenes, dict):
            for v in imagenes.values():
                if isinstance(v, dict) and isinstance(v.get("hash"), str):
                    return v["hash"]
        raise ErrorRed("respuesta ilegible") from None

    def subir_video(self, act_id: str, ruta: Path) -> str:
        if ruta.stat().st_size > _MAX_VIDEO:
            raise ValueError("vídeo > 100 MB: subida por partes no soportada")
        borde = uuid.uuid4().hex
        nombre = ruta.name.replace('"', "").replace("\r", "").replace("\n", "")
        cuerpo = (
            f'--{borde}\r\nContent-Disposition: form-data; name="source"; filename="{nombre}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + ruta.read_bytes() + f"\r\n--{borde}--\r\n".encode()
        r = self._enviar("POST", _seg(act_id, "advideos"), cuerpo=cuerpo,
                         tipo=f"multipart/form-data; boundary={borde}", timeout=self._t_subida)
        vid = r.get("id")
        if not vid:
            raise ErrorRed("respuesta ilegible") from None
        return str(vid)

    def cuenta(self, act_id: str) -> InfoCuenta:
        r = self.leer(act_id, _CAMPOS_CUENTA)
        moneda = str(r.get("currency", ""))
        tope = _entero(r.get("spend_cap"))
        return InfoCuenta(
            currency=moneda,
            offset=OFFSETS_META.get(moneda),
            timezone_name=str(r.get("timezone_name", "")),
            spend_cap=tope if tope else None,
            account_status=_entero(r.get("account_status")) or 0,
            amount_spent=_entero(r.get("amount_spent")),
        )
