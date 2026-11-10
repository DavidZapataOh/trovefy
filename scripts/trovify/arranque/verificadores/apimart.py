"""Paso 16: la cuenta de APIMart responde con saldo.

API confirmada en https://docs.apimart.ai/en/api-reference/account/token-balance (2026-11-10):
`GET {base}/v1/balance` con `Authorization: Bearer <clave>`; respuesta
`{"success": true, "remain_balance": 10.5, "remain_credits": 105, "used_balance": 2.3,
"used_credits": 23, "unlimited_quota": false}`. Base por defecto: https://api.apimart.ai.
La clave vive solo en ~/.config/trovify/claude.env y nunca sale en ningún resultado.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import guardar_evidencia
from trovify.secretos import RUTA_CLAUDE_ENV, PermisosInseguros, leer_env
from trovify.vault.escritura import ZONA_NEGOCIO

BASE_POR_DEFECTO = "https://api.apimart.ai"
MONEDA = "USD"  # los créditos de APIMart se cotizan en dólares (1 crédito ≈ 0,1 USD)
TIMEOUT = 15


class ClaveRechazada(Exception):
    pass


class SinRed(Exception):
    pass


class RespuestaInesperada(Exception):
    pass


def consultar_saldo(base: str, clave: str, abrir=urllib.request.urlopen) -> dict:
    """Devuelve {"saldo", "moneda"}; lanza ClaveRechazada, SinRed o RespuestaInesperada."""
    req = urllib.request.Request(base.rstrip("/") + "/v1/balance", headers={"Authorization": f"Bearer {clave}"})
    try:
        with abrir(req, timeout=TIMEOUT) as resp:
            estado, cuerpo = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaveRechazada from None
        raise RespuestaInesperada from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SinRed from None
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        raise RespuestaInesperada from None
    if estado != 200 or not isinstance(datos, dict) or datos.get("success") is not True:
        raise RespuestaInesperada
    if datos.get("unlimited_quota") is True:
        return {"saldo": "ilimitado", "moneda": MONEDA}
    saldo = datos.get("remain_balance")
    if isinstance(saldo, bool) or not isinstance(saldo, (int, float)):
        raise RespuestaInesperada
    return {"saldo": saldo, "moneda": MONEDA}


def _no(motivo: str, arreglos: list[str]) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, [], motivo, arreglos, {}, [f"✗ {motivo}"])


@verificador("16")
def verificar_apimart(vault: Path, ruta_env: Path = RUTA_CLAUDE_ENV, abrir=urllib.request.urlopen) -> ResultadoVerificacion:
    try:
        env = leer_env(ruta_env)
    except FileNotFoundError:
        return _no(f"no existe {ruta_env}", [
            "crea el archivo vacío: `! mkdir -p ~/.config/trovify && ! touch ~/.config/trovify/claude.env && ! chmod 600 ~/.config/trovify/claude.env`",
            "abre ~/.config/trovify/claude.env con tu editor y pega tu clave como APIMART_API_KEY=... (Claude no la ve)",
        ])
    except PermisosInseguros as exc:
        return _no(f"{ruta_env} tiene permisos {exc.modo:o}; deben ser 600", [f"`! chmod 600 {ruta_env}`"])
    clave = env.get("APIMART_API_KEY", "")
    if not clave:
        return _no("falta APIMART_API_KEY en claude.env", ["abre ~/.config/trovify/claude.env con tu editor y añade APIMART_API_KEY=... (Claude no la ve)"])
    base = env.get("APIMART_BASE_URL") or BASE_POR_DEFECTO
    try:
        saldo = consultar_saldo(base, clave, abrir)
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
    motivo = f"APIMart responde: saldo {saldo['saldo']} {saldo['moneda']}"
    return ResultadoVerificacion(True, [rel], motivo, [], {"saldo": str(saldo["saldo"]), "moneda": saldo["moneda"]}, [f"✓ {motivo}"])
