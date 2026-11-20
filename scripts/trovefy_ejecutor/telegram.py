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
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trovefy_ejecutor.auditoria import redactar

BASE_OFICIAL = "https://api.telegram.org"
_TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")
_LOCAL_RE = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})")
MAX_TEXTO = 4096
_MAX_BYTES = 2_000_000
_TIMEOUT_NORMAL = 30.0
_TIMEOUT_CALLBACK = 3.0
_INTENTOS_429 = 3
_RETRY_AFTER_MAX = 60
_PAUSA_CHAT = 1.0
MAX_ALBUM = 10  # sendMediaGroup admite de 2 a 10 elementos
_MAX_PIE = 64


def largo_telegram(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


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
        self.ultimo_envio: dict[int, float] = {}
        self._ultima_fecha: int | None = None

    def __repr__(self) -> str:
        return f"ClienteTelegram(base={self._base!r})"

    def tomar_fecha(self) -> int | None:
        """(extra, plan 12) Hora del servidor (epoch) de la última respuesta de ``sendMessage``
        (``date``) o ``editMessageText`` (``edit_date``). Se consume al leerla: nunca se reutiliza."""
        f, self._ultima_fecha = self._ultima_fecha, None
        return f

    def _guardar_fecha(self, res: Any, campo: str) -> None:
        f = res.get(campo) if isinstance(res, dict) else None
        self._ultima_fecha = f if type(f) is int and f > 0 else None

    def _limpiar(self, texto: str) -> str:
        return redactar(str(texto).replace(self._token, "***"))

    def _llamar(self, metodo: str, params: dict[str, Any], timeout: float,
                archivos: dict[str, tuple[str, bytes]] | None = None) -> Any:
        """POST a la Bot API: JSON o, con ``archivos``, multipart/form-data (los ``params`` van como campos de
        texto; los que no son texto, en JSON)."""
        url = f"{self._base}/bot{self._token}/{metodo}"
        if archivos:
            cuerpo, tipo = _multipart(params, archivos)
        else:
            cuerpo, tipo = json.dumps(params).encode("utf-8"), "application/json"
        req = urllib.request.Request(url, data=cuerpo, method="POST", headers={"Content-Type": tipo})
        del url
        http_error: int | None = None
        crudo: bytes | None = None
        fallo_red: str | None = None
        # Ningún raise dentro de un except: así ninguna excepción lleva la URL en su cadena.
        try:
            with self._abrir(req, timeout) as r:
                crudo = r.read(_MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            http_error = e.code
            try:
                crudo = e.read(_MAX_BYTES + 1)
            except (OSError, http.client.HTTPException) as e2:
                fallo_red = f"{type(e2).__name__} leyendo el error HTTP {http_error}"
        except (OSError, http.client.HTTPException) as e:
            fallo_red = f"{type(e).__name__}: {e}"
        del req
        if fallo_red is not None:
            raise ErrorRedTelegram(self._limpiar(fallo_red)) from None
        assert crudo is not None
        if http_error is not None:
            self._lanzar_si_error(http_error, crudo)
            raise ErrorRedTelegram(f"respuesta HTTP {http_error} ilegible")
        if len(crudo) > _MAX_BYTES:
            raise ErrorRedTelegram("respuesta demasiado grande")
        return self._resultado(crudo)

    def _con_429(self, metodo: str, params: dict[str, Any], timeout: float, chat_id: int | None = None,
                 archivos: dict[str, tuple[str, bytes]] | None = None) -> Any:
        for intento in range(1, _INTENTOS_429 + 1):
            if chat_id is not None:
                previo = self.ultimo_envio.get(chat_id)
                if previo is not None:
                    falta = _PAUSA_CHAT - (self._reloj() - previo)
                    if falta > 0:
                        self._dormir(falta)
                self.ultimo_envio[chat_id] = self._reloj()
            try:
                return self._llamar(metodo, params, timeout, archivos)
            except ErrorTelegram as e:
                ra = e.retry_after
                if e.codigo != 429 or ra is None or ra > _RETRY_AFTER_MAX or intento == _INTENTOS_429:
                    raise
            self._dormir(ra)
        raise AssertionError("inalcanzable")

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

    @staticmethod
    def _validar_largo(texto: str) -> None:
        n = largo_telegram(texto)
        if n > MAX_TEXTO:
            raise ValueError(f"texto de {n} > {MAX_TEXTO}")

    def obtener_updates(self, offset: int, timeout_s: int = 25) -> list[dict]:
        res = self._con_429(
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
        responde_a: int | None = None,
    ) -> int:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": texto,
            "link_preview_options": {"is_disabled": True},
            "disable_notification": not sonido,
        }
        if botones:
            params["reply_markup"] = _teclado(botones)
        if responde_a is not None:
            params["reply_parameters"] = {"message_id": responde_a, "allow_sending_without_reply": True}
        self._validar_largo(texto)
        self._ultima_fecha = None
        res = self._con_429("sendMessage", params, _TIMEOUT_NORMAL, chat_id)
        if not isinstance(res, dict) or not isinstance(res.get("message_id"), int):
            raise ErrorRedTelegram("sendMessage con forma inesperada")
        self._guardar_fecha(res, "date")
        return res["message_id"]

    def editar(
        self,
        chat_id: int,
        message_id: int,
        texto: str,
        botones: list[list[Boton]] | None = None,
    ) -> None:
        self._validar_largo(texto)
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": texto,
            "link_preview_options": {"is_disabled": True},
            "reply_markup": _teclado(botones),
        }
        self._ultima_fecha = None
        try:
            self._guardar_fecha(self._con_429("editMessageText", params, _TIMEOUT_NORMAL, chat_id), "edit_date")
        except ErrorTelegram as e:
            if e.codigo == 400 and "message is not modified" in e.descripcion.lower():
                return
            raise

    def enviar_album(self, chat_id: int, fotos: list[tuple[str, bytes | str]]) -> list[int]:
        """(plan 22, [D-33]) Miniaturas de «Activar»: 1 foto → ``sendPhoto``; 2–10 → ``sendMediaGroup``. Cada foto
        es ``(nombre, contenido)``: bytes (se suben por multipart) o una URL ``https://``. El pie es como mucho el
        nombre del anuncio, limpio y corto: nunca texto libre. Devuelve los ``message_id``."""
        if not fotos:
            return []
        if len(fotos) > MAX_ALBUM:
            raise ValueError(f"álbum de {len(fotos)} fotos (máximo {MAX_ALBUM})")
        medios: list[dict[str, Any]] = []
        archivos: dict[str, tuple[str, bytes]] = {}
        for i, (nombre, foto) in enumerate(fotos):
            if isinstance(foto, (bytes, bytearray)):
                if not foto:
                    raise ValueError("foto vacía")
                clave = f"foto{i}"
                archivos[clave] = (f"{clave}.jpg", bytes(foto))
                media = f"attach://{clave}"
            elif isinstance(foto, str) and foto.startswith("https://") and not any(c.isspace() for c in foto):
                media = foto
            else:
                raise ValueError("cada foto va en bytes o como URL https://")
            item: dict[str, Any] = {"type": "photo", "media": media}
            pie = _pie(nombre)
            if pie:
                item["caption"] = pie
            medios.append(item)
        if len(medios) == 1:
            m = medios[0]
            params: dict[str, Any] = {"chat_id": chat_id, "disable_notification": True}
            una = {"photo": next(iter(archivos.values()))} if archivos else None
            if una is None:
                params["photo"] = m["media"]
            if "caption" in m:
                params["caption"] = m["caption"]
            res = self._con_429("sendPhoto", params, _TIMEOUT_NORMAL, chat_id, una)
            if not isinstance(res, dict) or not isinstance(res.get("message_id"), int):
                raise ErrorRedTelegram("sendPhoto con forma inesperada")
            return [res["message_id"]]
        params = {"chat_id": chat_id, "media": medios, "disable_notification": True}
        res = self._con_429("sendMediaGroup", params, _TIMEOUT_NORMAL, chat_id, archivos or None)
        if not isinstance(res, list) or not all(isinstance(x, dict) and isinstance(x.get("message_id"), int)
                                                for x in res):
            raise ErrorRedTelegram("sendMediaGroup con forma inesperada")
        return [x["message_id"] for x in res]

    def responder_callback(self, callback_id: str, texto: str = "") -> None:
        params: dict[str, Any] = {"callback_query_id": callback_id}
        if texto:
            params["text"] = texto
        self._llamar("answerCallbackQuery", params, _TIMEOUT_CALLBACK)


def _pie(nombre: str) -> str:
    """Pie de foto: solo el nombre del anuncio, sin controles ni saltos, como mucho ``_MAX_PIE`` caracteres."""
    limpio = " ".join("".join(c for c in str(nombre) if c.isprintable()).split())
    return limpio[:_MAX_PIE]


def _multipart(params: dict[str, Any], archivos: dict[str, Any]) -> tuple[bytes, str]:
    """multipart/form-data: ``params`` como campos (texto tal cual; lo demás en JSON) y ``archivos`` como
    ``{campo: bytes}`` o ``{campo: (nombre, bytes)}``."""
    limite = f"trovefy-{uuid.uuid4().hex}"
    partes: list[bytes] = []
    for k, v in params.items():
        if v is None:
            continue
        valor = v if isinstance(v, str) else json.dumps(v)
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
                      + valor.encode("utf-8") + b"\r\n")
    for campo, dato in archivos.items():
        nombre, contenido = dato if isinstance(dato, tuple) else (f"{campo}.jpg", dato)
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{campo}"; filename="{nombre}"\r\n'
                      "Content-Type: image/jpeg\r\n\r\n".encode() + contenido + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"
