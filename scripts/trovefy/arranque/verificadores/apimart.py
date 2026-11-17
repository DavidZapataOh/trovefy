"""Paso 16: la cuenta de APIMart responde con saldo.

API confirmada en https://docs.apimart.ai/en/api-reference/account/token-balance (2026-11-10):
`GET {base}/v1/balance` con `Authorization: Bearer <clave>`; respuesta
`{"success": true, "remain_balance": 10.5, "remain_credits": 105, "used_balance": 2.3,
"used_credits": 23, "unlimited_quota": false}`. Base por defecto: https://api.apimart.ai.
La clave vive solo en ~/.config/trovefy/claude.env y nunca sale en ningún resultado.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from trovefy.apimart.http import (
    BASE_POR_DEFECTO,
    LOOPBACK,
    BaseInvalida,
    ClaveRara,
    ClaveRechazada,
    RespuestaInesperada,
    SinClave,
    SinRed,
    SinRedireccion,
    abrir_sin_redireccion,
    leer_credenciales,
    validar_base,
)
from trovefy.arranque.estado import ResultadoVerificacion
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import guardar_evidencia
from trovefy.secretos import RUTA_CLAUDE_ENV
from trovefy.vault.escritura import ZONA_NEGOCIO

__all__ = ["BASE_POR_DEFECTO", "LOOPBACK", "BaseInvalida", "ClaveRara", "ClaveRechazada", "RespuestaInesperada",
           "SinRed", "consultar_saldo", "verificar_apimart"]

# La documentación no nombra la moneda; USD se infiere de que 10,5 de saldo = 105 créditos (1 crédito ≈ 0,1 USD).
MONEDA = "USD (inferida)"
TIMEOUT = 15

# Nombres privados de antes del plan 17: ahora viven en trovefy.apimart.http.
_SinRedireccion = SinRedireccion
_abrir_sin_redireccion = abrir_sin_redireccion
_validar_base = validar_base


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def consultar_saldo(base: str, clave: str, abrir=None) -> dict:
    """Devuelve {"saldo", "moneda"}; lanza ClaveRechazada, SinRed o RespuestaInesperada."""
    _validar_base(base)
    if not (clave.isascii() and clave.isprintable()):
        raise ClaveRara
    abrir = abrir or _abrir_sin_redireccion
    req = urllib.request.Request(base.rstrip("/") + "/v1/balance", headers={"Authorization": f"Bearer {clave}"})
    try:
        with abrir(req, timeout=TIMEOUT) as resp:
            estado, cuerpo = resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaveRechazada from None
        raise RespuestaInesperada from None
    except UnicodeError:
        raise ClaveRara from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SinRed from None
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        raise RespuestaInesperada from None
    if estado != 200 or not isinstance(datos, dict) or datos.get("success") is not True:
        raise RespuestaInesperada
    if datos.get("unlimited_quota") is True:
        return {"saldo": "ilimitado", "creditos": _num(datos.get("remain_credits")), "moneda": None}
    saldo = datos.get("remain_balance")
    if isinstance(saldo, bool) or not isinstance(saldo, (int, float)):
        raise RespuestaInesperada
    return {"saldo": saldo, "creditos": _num(datos.get("remain_credits")), "moneda": MONEDA}


def _no(motivo: str, arreglos: list[str]) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, [], motivo, arreglos, {}, [f"✗ {motivo}"])


@verificador("16")
def verificar_apimart(vault: Path, ruta_env: Path = RUTA_CLAUDE_ENV, abrir=None) -> ResultadoVerificacion:
    try:
        cred = leer_credenciales(ruta_env)
    except SinClave as exc:
        return _no(exc.motivo, exc.arreglos)
    base, clave = cred.base, cred.clave
    try:
        saldo = consultar_saldo(base, clave, abrir)
    except BaseInvalida:
        return _no("APIMART_BASE_URL debe ser https", ["corrige APIMART_BASE_URL en claude.env (https://..., o bórrala para usar la oficial)"])
    except ClaveRara:
        return _no("la clave tiene caracteres raros; vuelve a pegarla", ["en una terminal de Ubuntu (WSL) aparte, abre ~/.config/trovefy/claude.env y pega la clave de nuevo, sin espacios ni caracteres especiales"])
    except ClaveRechazada:
        return _no("clave rechazada por APIMart", ["revisa o regenera la clave en el panel de APIMart y pégala de nuevo en claude.env"])
    except SinRed:
        motivo = "no medido: sin red"
        return ResultadoVerificacion(None, [], motivo, ["comprueba tu conexión y repite la verificación"], {}, [f"? {motivo}"])
    except RespuestaInesperada:
        motivo = "no medido: respuesta inesperada"
        return ResultadoVerificacion(None, [], motivo, ["repite más tarde; si persiste, revisa la documentación de APIMart"], {}, [f"? {motivo}"])
    fecha = datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d")
    rel = guardar_evidencia(vault, "16", "saldo", {**saldo, "fecha": fecha})
    unidad = f" {saldo['moneda']}" if saldo["moneda"] else ""
    cred = f", {saldo['creditos']} créditos" if saldo["creditos"] is not None else ""
    motivo = f"APIMart responde: saldo {saldo['saldo']}{unidad}{cred}"
    if isinstance(saldo["saldo"], (int, float)) and saldo["saldo"] <= 0:
        motivo += "; saldo agotado: recarga US$ 5–10"
    datos = {"saldo": str(saldo["saldo"])}
    if saldo["moneda"]:
        datos["moneda"] = saldo["moneda"]
    if saldo["creditos"] is not None:
        datos["creditos"] = str(saldo["creditos"])
    return ResultadoVerificacion(True, [rel], motivo, [], datos, [f"✓ {motivo}"])
