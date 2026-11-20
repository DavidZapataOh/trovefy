"""Telegram falso local para los tests: misma forma de respuestas y validaciones que la Bot API."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

TOKEN_PRUEBA = "123456:" + "A" * 35


@dataclass
class Llamada:
    metodo: str
    params: dict
    t: float


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True


class TelegramFalso:
    def __init__(self, token: str = TOKEN_PRUEBA):
        self.token = token
        self.llamadas: list[Llamada] = []
        self.mensajes: dict[int, dict] = {}
        self._updates: list[dict] = []
        self._cond = threading.Condition()
        self._next_mid = 1
        self._next_uid = 1
        self._next_cq = 1
        self._fallos: dict[str, list[tuple[int, int]]] = {}
        self._cortes: dict[str, int] = {}
        self._entregas: dict[str, float] = {}
        self._srv = _Servidor(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._hilo = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self._hilo.start()
        return self

    def __exit__(self, *exc) -> None:
        with self._cond:
            self._cond.notify_all()
        self._srv.shutdown()
        self._srv.server_close()

    # --- API de test ---
    def meter_mensaje(self, texto, user_id, chat_id, chat_type="private", reply_to=None) -> int:
        with self._cond:
            mid = self._next_mid
            self._next_mid += 1
            msg: dict[str, Any] = {
                "message_id": mid,
                "from": {"id": user_id, "is_bot": False},
                "chat": {"id": chat_id, "type": chat_type},
                "date": int(time.time()),
                "text": texto,
            }
            if reply_to is not None:
                previo = self.mensajes.get(reply_to)
                msg["reply_to_message"] = {"message_id": reply_to}
                if previo is not None:  # como Telegram: el mensaje citado con su autor (el bot) y su texto
                    msg["reply_to_message"].update({"from": {"id": 1, "is_bot": True}, "text": previo["texto"]})
            self._poner({"message": msg})
            return mid

    def meter_toque(self, data, user_id, chat_id, message_id) -> str:
        with self._cond:
            cq = str(self._next_cq)
            self._next_cq += 1
            self._entregas[cq] = time.monotonic()
            self._poner(
                {
                    "callback_query": {
                        "id": cq,
                        "from": {"id": user_id, "is_bot": False},
                        "message": {"message_id": message_id, "date": int(time.time()),
                                    "chat": {"id": chat_id, "type": "private"}},
                        "data": data,
                    }
                }
            )
            return cq

    def entregado_en(self, callback_id: str) -> float:
        return self._entregas[callback_id]

    def fallar(self, metodo, veces=1, codigo=429, retry_after=1) -> None:
        with self._cond:
            self._fallos.setdefault(metodo, []).extend([(codigo, retry_after)] * veces)

    def cortar(self, metodo, veces=1) -> None:
        with self._cond:
            self._cortes[metodo] = self._cortes.get(metodo, 0) + veces

    # --- internos ---
    def _poner(self, upd: dict) -> None:
        upd["update_id"] = self._next_uid
        self._next_uid += 1
        self._updates.append(upd)
        self._cond.notify_all()

    def _error(self, codigo: int, desc: str, retry_after: int | None = None) -> tuple[int, dict]:
        cuerpo: dict[str, Any] = {"ok": False, "error_code": codigo, "description": desc}
        if retry_after is not None:
            cuerpo["parameters"] = {"retry_after": retry_after}
        return codigo, cuerpo

    @staticmethod
    def _datos_boton(rm: Any) -> list:
        return rm.get("inline_keyboard", []) if isinstance(rm, dict) else []

    def _botones_validos(self, rm: Any) -> bool:
        for fila in self._datos_boton(rm):
            for b in fila:
                if len(str(b.get("callback_data", "")).encode("utf-8")) > 64:
                    return False
        return True

    def _despachar(self, metodo: str, p: dict) -> tuple[int, dict] | None:
        """Devuelve (http, cuerpo) o None para cortar la conexión."""
        with self._cond:
            self.llamadas.append(Llamada(metodo, p, time.monotonic()))
            if self._cortes.get(metodo, 0) > 0:
                self._cortes[metodo] -= 1
                if metodo == "sendMessage":
                    self._crear(p)
                return None
            if self._fallos.get(metodo):
                codigo, ra = self._fallos[metodo].pop(0)
                return self._error(codigo, "Too Many Requests: retry later", ra if codigo == 429 else None)
        if metodo == "getUpdates":
            return self._get_updates(p)
        with self._cond:
            if metodo == "sendMessage":
                if len(p.get("text", "")) > 4096:
                    return self._error(400, "Bad Request: message is too long")
                if not self._botones_validos(p.get("reply_markup")):
                    return self._error(400, "Bad Request: BUTTON_DATA_INVALID")
                return 200, {"ok": True, "result": self._crear(p)}
            if metodo == "editMessageText":
                m = self.mensajes.get(p.get("message_id"))
                if m is None or m["chat_id"] != p.get("chat_id"):
                    return self._error(400, "Bad Request: message to edit not found")
                if len(p.get("text", "")) > 4096:
                    return self._error(400, "Bad Request: message is too long")
                if not self._botones_validos(p.get("reply_markup")):
                    return self._error(400, "Bad Request: BUTTON_DATA_INVALID")
                botones = self._datos_boton(p.get("reply_markup"))
                if m["texto"] == p.get("text") and m["botones"] == botones:
                    return self._error(
                        400,
                        "Bad Request: message is not modified: specified new message content and "
                        "reply markup are exactly the same as a current content and reply markup",
                    )
                m["texto"], m["botones"] = p.get("text"), botones
                return 200, {"ok": True, "result": {"message_id": p["message_id"], "date": m["date"],
                                                    "edit_date": int(time.time())}}
            if metodo == "answerCallbackQuery":
                return 200, {"ok": True, "result": True}
            if metodo == "sendPhoto":
                if "photo" not in p:
                    return self._error(400, "Bad Request: there is no photo in the request")
                return 200, {"ok": True, "result": self._crear({"chat_id": p.get("chat_id"), "text": None})}
            if metodo == "sendMediaGroup":
                media = p.get("media")
                if not isinstance(media, list) or not 2 <= len(media) <= 10:
                    return self._error(400, "Bad Request: wrong number of media")
                for m in media:
                    ref = str(m.get("media", ""))
                    if ref.startswith("attach://") and ref[len("attach://"):] not in p.get("_archivos", {}):
                        return self._error(400, "Bad Request: wrong file attached")
                return 200, {"ok": True, "result": [self._crear({"chat_id": p.get("chat_id"), "text": None})
                                                    for _ in media]}
        return self._error(404, "Not Found")

    def _crear(self, p: dict) -> dict:
        mid = self._next_mid
        self._next_mid += 1
        self.mensajes[mid] = {
            "chat_id": p.get("chat_id"),
            "texto": p.get("text"),
            "botones": self._datos_boton(p.get("reply_markup")),
            "sonido": not p.get("disable_notification", False),
            "responde_a": (p.get("reply_parameters") or {}).get("message_id"),
            "date": int(time.time()),
        }
        return {"message_id": mid, "chat": {"id": p.get("chat_id")}, "text": p.get("text"),
                "date": self.mensajes[mid]["date"]}

    def _get_updates(self, p: dict) -> tuple[int, dict]:
        offset = int(p.get("offset", 0))
        limite = time.monotonic() + float(p.get("timeout", 0))
        with self._cond:
            while True:
                res = [u for u in self._updates if u["update_id"] >= offset]
                restante = limite - time.monotonic()
                if res or restante <= 0:
                    return 200, {"ok": True, "result": res}
                self._cond.wait(restante)

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                crudo = self.rfile.read(n)
                tipo = self.headers.get("Content-Type") or ""
                if tipo.startswith("multipart/form-data"):
                    p = _multipart(tipo, crudo)
                else:
                    try:
                        p = json.loads(crudo or b"{}")
                    except ValueError:
                        p = {}
                partes = self.path.split("/")
                if len(partes) != 3 or partes[1] != f"bot{fake.token}":
                    res: tuple[int, dict] | None = fake._error(401, "Unauthorized")
                else:
                    res = fake._despachar(partes[2], p)
                if res is None:
                    self.close_connection = True
                    self.connection.close()
                    return
                codigo, cuerpo = res
                datos = json.dumps(cuerpo).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        return H


def _multipart(tipo: str, crudo: bytes) -> dict:
    """Lo justo de multipart/form-data: campos de texto (los JSON, decodificados) y, en ``_archivos``, el tamaño
    de cada archivo; un campo de archivo queda además como ``"<archivo>"``."""
    msg = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {tipo}\r\n\r\n".encode() + crudo)
    p: dict = {"_archivos": {}}
    for parte in msg.iter_parts():
        nombre = parte.get_param("name", header="content-disposition")
        datos = parte.get_payload(decode=True) or b""
        if parte.get_filename():
            p["_archivos"][nombre] = len(datos)
            p[nombre] = "<archivo>"
            continue
        texto = datos.decode("utf-8")
        try:
            p[nombre] = json.loads(texto)
        except ValueError:
            p[nombre] = texto
    return p
