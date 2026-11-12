"""Cliente mínimo de la Bot API de Telegram (long polling, solo biblioteca estándar).

El token va en la ruta de la URL (lo exige Telegram): la URL solo existe dentro de ``_llamar``;
nunca se guarda en un atributo, ni se registra, ni aparece en una excepción (todo error se
redacta y se lanza ``from None``).
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trovefy_ejecutor.auditoria import redactar

BASE_OFICIAL = "https://api.telegram.org"
_TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")
_LOCAL_RE = re.compile(r"http://127\.0\.0\.1:(\d{1,5})")
_MAX_BYTES = 2_000_000
_TIMEOUT_NORMAL = 30.0
_TIMEOUT_CALLBACK = 3.0


@dataclass(frozen=True)
class Boton:
    texto: str
    data: str


class ErrorTelegram(Exception):
    """Telegram contestó con ``ok: false`` (o con un HTTP de error)."""

    def __init__(self, codigo: int, descripcion: str, retry_after: int | None = None):
        self.codigo = codigo
        self.descripcion = descripcion
        self.retry_after = retry_after
        super().__init__(f"Telegram {codigo}: {descripcion}")
        self.__suppress_context__ = True


class ErrorRedTelegram(Exception):
    """No hubo respuesta utilizable (red, corte, tiempo agotado, respuesta ilegible)."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)
        self.__suppress_context__ = True


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abrir_por_defecto(req: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_SinRedireccion).open(req, timeout=timeout)


def _teclado(botones: list[list[Boton]] | None) -> dict[str, Any]:
    filas = [[{"text": b.texto, "callback_data": b.data} for b in fila] for fila in (botones or [])]
    return {"inline_keyboard": filas}


class ClienteTelegram:
    def __init__(
        self,
        token: str,
        base: str = BASE_OFICIAL,
        *,
        abrir: Callable[..., Any] | None = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ):
        if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            raise ValueError("token del bot con formato inválido")
        if base != BASE_OFICIAL:
            m = _LOCAL_RE.fullmatch(base)
            if m is None or not 0 < int(m.group(1)) <= 65535:
                raise ValueError("base de Telegram no permitida")
        self._token = token
        self._base = base
        self._abrir = abrir or _abrir_por_defecto
        self._dormir = dormir
        self._reloj = reloj

    def __repr__(self) -> str:
        return f"ClienteTelegram(base={self._base!r})"

    def _limpiar(self, texto: str) -> str:
        return redactar(str(texto).replace(self._token, "***"))

    def _llamar(self, metodo: str, params: dict[str, Any], timeout: float) -> Any:
        url = f"{self._base}/bot{self._token}/{metodo}"
        cuerpo = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(
            url, data=cuerpo, method="POST", headers={"Content-Type": "application/json"}
        )
        del url
        http_error: int | None = None
        try:
            with self._abrir(req, timeout) as r:
                crudo = r.read(_MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            http_error = e.code
            crudo = e.read(_MAX_BYTES + 1)
        except (OSError, http.client.HTTPException) as e:
            raise ErrorRedTelegram(self._limpiar(f"{type(e).__name__}: {e}")) from None
        if http_error is not None:  # fuera del except: sin contexto que lleve la URL
            self._lanzar_si_error(http_error, crudo)
            raise ErrorRedTelegram(f"respuesta HTTP {http_error} ilegible")
        if len(crudo) > _MAX_BYTES:
            raise ErrorRedTelegram("respuesta demasiado grande")
        return self._resultado(crudo)

    def _lanzar_si_error(self, http_code: int, crudo: bytes) -> None:
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(datos, dict) and datos.get("ok") is False:
            params = datos.get("parameters")
            ra = params.get("retry_after") if isinstance(params, dict) else None
            raise ErrorTelegram(
                int(datos.get("error_code", http_code)),
                self._limpiar(str(datos.get("description", ""))),
                ra if isinstance(ra, int) else None,
            )

    def _resultado(self, crudo: bytes) -> Any:
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ErrorRedTelegram("respuesta no es JSON") from None
        if not isinstance(datos, dict):
            raise ErrorRedTelegram("respuesta con forma inesperada")
        if datos.get("ok") is not True:
            self._lanzar_si_error(0, crudo)
            raise ErrorRedTelegram("respuesta con forma inesperada")
        return datos.get("result")

    def obtener_updates(self, offset: int, timeout_s: int = 25) -> list[dict]:
        res = self._llamar(
            "getUpdates",
            {"offset": offset, "timeout": timeout_s, "allowed_updates": ["message", "callback_query"]},
            timeout_s + 10,
        )
        if not isinstance(res, list):
            raise ErrorRedTelegram("getUpdates con forma inesperada")
        return [u for u in res if isinstance(u, dict)]

    def enviar(
        self,
        chat_id: int,
        texto: str,
        botones: list[list[Boton]] | None = None,
        *,
        sonido: bool = True,
    ) -> int:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": texto,
            "link_preview_options": {"is_disabled": True},
            "disable_notification": not sonido,
        }
        if botones:
            params["reply_markup"] = _teclado(botones)
        res = self._llamar("sendMessage", params, _TIMEOUT_NORMAL)
        if not isinstance(res, dict) or not isinstance(res.get("message_id"), int):
            raise ErrorRedTelegram("sendMessage con forma inesperada")
        return res["message_id"]

    def editar(
        self,
        chat_id: int,
        message_id: int,
        texto: str,
        botones: list[list[Boton]] | None = None,
    ) -> None:
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": texto,
            "link_preview_options": {"is_disabled": True},
            "reply_markup": _teclado(botones),
        }
        try:
            self._llamar("editMessageText", params, _TIMEOUT_NORMAL)
        except ErrorTelegram as e:
            if e.codigo == 400 and "message is not modified" in e.descripcion.lower():
                return
            raise

    def responder_callback(self, callback_id: str, texto: str = "") -> None:
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if texto:
            params["text"] = texto
        self._llamar("answerCallbackQuery", params, _TIMEOUT_CALLBACK)
