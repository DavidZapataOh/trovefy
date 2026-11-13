"""Modo simulado: Telegram y Graph en proceso (sin sockets, sin hilos, sin token).

Los usa el comando ``simular`` y las pruebas. ``TelegramSimulado`` y ``GraphSimulado`` tienen la misma
interfaz pública que ``ClienteTelegram`` y ``ClienteGraph``. El mundo de Graph es mínimo y coherente con
``vivo.valores_vivos``: cuenta ficticia en COP + campaña ``c1`` + conjunto ``s1`` + anuncio ``a1``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from trovefy_ejecutor.callbacks import firmar
from trovefy_ejecutor.graph import (
    _CAMPOS_CUENTA,
    OFFSETS_META,
    ErrorGraph,
    InfoCuenta,
    _entero,
    _seg,
    _valor,
)
from trovefy_ejecutor.montaje import IDIOMAS_META
from trovefy_ejecutor.telegram import MAX_TEXTO, Boton, ErrorTelegram, largo_telegram

_IMPORTES = ("daily_budget", "lifetime_budget", "bid_amount", "spend_cap")
_MAX_VIDEO = 100 * 1024 * 1024


def _ahora() -> datetime:
    return datetime.now(UTC)


def _validar_largo(texto: str) -> None:
    n = largo_telegram(texto)
    if n > MAX_TEXTO:
        raise ValueError(f"texto de {n} > {MAX_TEXTO}")


def _lista_estados(v: object) -> list[str]:
    """Normaliza un filtro de estados: lista, cadena JSON o cadena suelta (nunca subcadenas)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return [v]
    if isinstance(v, (list, tuple, set, frozenset)):
        return [str(x) for x in v]
    return [str(v)]


class TelegramSimulado:
    """Cola de updates en memoria. ``obtener_updates`` no bloquea (ignora ``timeout_s``)."""

    def __init__(self, chat_id: int = 42, user_id: int = 42, *, ahora=_ahora):
        self.chat_id = chat_id
        self.user_id = user_id
        self._ahora = ahora
        self.mensajes: dict[int, dict] = {}
        self.respuestas_callback: list[tuple[str, str]] = []
        self._updates: list[dict] = []
        self._siguiente_update = 1
        self._siguiente_mensaje = 1
        self._siguiente_callback = 1

    def __repr__(self) -> str:
        return f"TelegramSimulado(chat_id={self.chat_id}, mensajes={len(self.mensajes)})"

    # -- API de ClienteTelegram ---------------------------------------------------------
    def obtener_updates(self, offset: int, timeout_s: int = 25) -> list[dict]:
        return [dict(u) for u in self._updates if u["update_id"] >= offset]

    def enviar(self, chat_id: int, texto: str, botones: list[list[Boton]] | None = None, *,
               sonido: bool = True) -> int:
        _validar_largo(texto)
        mid = self._siguiente_mensaje
        self._siguiente_mensaje += 1
        self.mensajes[mid] = {"chat_id": chat_id, "texto": texto, "botones": botones, "sonido": sonido}
        return mid

    def editar(self, chat_id: int, message_id: int, texto: str,
               botones: list[list[Boton]] | None = None) -> None:
        _validar_largo(texto)
        if message_id not in self.mensajes:
            raise ErrorTelegram(400, "Bad Request: message to edit not found")
        self.mensajes[message_id].update(texto=texto, botones=botones)

    def responder_callback(self, callback_id: str, texto: str = "") -> None:
        self.respuestas_callback.append((callback_id, texto))

    # -- guion --------------------------------------------------------------------------
    def _poner(self, upd: dict) -> None:
        upd["update_id"] = self._siguiente_update
        self._siguiente_update += 1
        self._updates.append(upd)

    def _mensaje_de(self, id: str, clave: bytes) -> int:
        buscadas = {firmar(id, "A", self.chat_id, clave), firmar(id, "R", self.chat_id, clave)}
        for mid in sorted(self.mensajes, reverse=True):
            for fila in self.mensajes[mid]["botones"] or []:
                if any(b.data in buscadas for b in fila):
                    return mid
        for mid in sorted(self.mensajes, reverse=True):
            if id in self.mensajes[mid]["texto"]:
                return mid
        raise KeyError(f"ningún mensaje enviado para {id}")

    def tocar(self, id: str, accion: Literal["A", "R"], clave: bytes, *, user_id: int | None = None,
              data: str | None = None, fecha: datetime | None = None) -> str:
        cb = str(self._siguiente_callback)
        self._siguiente_callback += 1
        self._poner({"callback_query": {
            "id": cb,
            "from": {"id": self.user_id if user_id is None else user_id, "is_bot": False},
            "message": {"message_id": self._mensaje_de(id, clave),
                        "date": int((fecha or self._ahora()).timestamp()),
                        "chat": {"id": self.chat_id, "type": "private"}},
            "data": firmar(id, accion, self.chat_id, clave) if data is None else data,
        }})
        return cb

    def escribir(self, texto: str, *, responde_a: int | None = None) -> None:
        mid = self._siguiente_mensaje
        self._siguiente_mensaje += 1
        msg: dict[str, Any] = {"message_id": mid, "from": {"id": self.user_id, "is_bot": False},
                               "chat": {"id": self.chat_id, "type": "private"},
                               "date": int(self._ahora().timestamp()), "text": texto}
        if responde_a is not None:
            msg["reply_to_message"] = {"message_id": responde_a, "from": {"id": 1, "is_bot": True}}
            previo = self.mensajes.get(responde_a)
            if previo is not None:
                msg["reply_to_message"]["text"] = previo["texto"]
        self._poner({"message": msg})


class GraphSimulado:
    """Graph en memoria con la interfaz pública de ``ClienteGraph``. Sin token ni red."""

    def __init__(self, cuenta: str = "act_0000000000000000", moneda: str = "COP"):
        _seg(cuenta)
        self._cuenta = cuenta
        num = cuenta.removeprefix("act_")
        self.escrituras: list[tuple] = []
        self.cuentas: dict[str, dict] = {cuenta: {
            "currency": moneda, "timezone_name": "America/Bogota", "spend_cap": "1000000",
            "amount_spent": "250000", "account_status": 1}}
        activo = {"status": "ACTIVE", "effective_status": "ACTIVE"}
        self.objetos: dict[str, dict] = {
            "c1": {"account_id": num, **activo, "name": "Campaña", "daily_budget": "0", "lifetime_budget": "0"},
            "s1": {"account_id": num, **activo, "daily_budget": "20000", "lifetime_budget": "0",
                   "bid_amount": "1500", "campaign_id": "c1", "name": "Conjunto 1"},
            "a1": {"account_id": num, **activo, "adset_id": "s1", "campaign_id": "c1", "name": "Anuncio"},
        }
        # id -> (arista, padres)
        self._hijos: dict[str, tuple[str, set[str]]] = {
            "c1": ("campaigns", {cuenta}), "s1": ("adsets", {cuenta, "c1"}), "a1": ("ads", {cuenta, "s1"})}
        self._videos: set[str] = set()
        self._siguiente_id = 9000001
        self._siguiente_video = 7000001

    def __repr__(self) -> str:
        return f"GraphSimulado(cuenta={self._cuenta!r}, escrituras={len(self.escrituras)})"

    @staticmethod
    def _normal(datos: Mapping[str, object]) -> dict[str, object]:
        salida: dict[str, object] = {}
        for k, v in datos.items():
            _valor(v)  # mismo ValueError que el cliente real ante None
            if k in _IMPORTES:
                try:
                    v = str(int(str(v)))
                except ValueError:
                    raise ErrorGraph(100, None, f"Invalid parameter: {k}") from None
            salida[k] = v
        for k, v in salida.items():
            if k in _IMPORTES and int(str(v)) < 0:
                raise ErrorGraph(100, None, f"Invalid parameter: {k} must not be negative")
        return salida

    def _existe(self, id: str) -> None:
        if id not in self.objetos and id not in self.cuentas:
            raise ErrorGraph(100, 33, "Unsupported post request. Object does not exist")

    # -- lectura ------------------------------------------------------------------------
    def leer(self, id: str, campos: Sequence[str]) -> dict:
        _seg(id)
        if id in self._videos:
            return self._leer_video(id, campos)
        origen = self.objetos.get(id, self.cuentas.get(id))
        if origen is None:
            raise ErrorGraph(100, 33, "Unsupported get request. Object does not exist")
        return {"id": id, **{c: origen[c] for c in campos if c in origen and c != "id"}}

    def _leer_video(self, id: str, campos: Sequence[str]) -> dict:
        salida: dict = {"id": id}
        for c in campos:
            base = c.split("{")[0]
            if base == "status":
                salida["status"] = {"video_status": "ready"}
            elif base == "thumbnails":
                salida["thumbnails"] = {"data": [{"uri": "https://scontent.example/miniatura.jpg",
                                                  "is_preferred": True}]}
        return salida

    def listar(self, padre: str, arista: str, campos: Sequence[str],
               filtros: Mapping[str, object] | None = None, max_paginas: int = 20,
               limite: int | None = None) -> list[dict]:
        _seg(padre, arista)
        for v in (filtros or {}).values():
            _valor(v)
        permitidos = (filtros or {}).get("effective_status")
        if permitidos is not None:
            permitidos = _lista_estados(permitidos)
        salida = []
        for oid, (ar, padres) in self._hijos.items():
            if ar != arista or padre not in padres or oid not in self.objetos:
                continue
            obj = self.objetos[oid]
            if permitidos is not None and obj.get("effective_status") not in permitidos:
                continue
            salida.append({"id": oid, **{c: obj[c] for c in campos if c in obj and c != "id"}})
        return salida

    def buscar(self, tipo: str, q: str, campos: Sequence[str]) -> list[dict]:
        if not isinstance(tipo, str) or not tipo or not all(ch.islower() or ch == "_" for ch in tipo):
            raise ValueError("tipo de búsqueda inválido")
        if not isinstance(q, str) or not 1 <= len(q) <= 100:
            raise ValueError("texto de búsqueda inválido")
        if tipo != "adlocale":
            return []
        filas = [{"key": 1000 + i, "name": n} for i, n in enumerate(sorted(IDIOMAS_META.values()))]
        return [{k: v for k, v in f.items() if k in campos} for f in filas if f["name"] == q]

    # -- escritura ----------------------------------------------------------------------
    def escribir(self, id: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        _seg(id)
        normal = self._normal(datos)
        self._existe(id)
        if validate_only:
            return {"success": True}
        destino = self.objetos.get(id, self.cuentas.get(id, {}))
        destino.update(normal)
        if "status" in normal and id in self.objetos:
            destino["effective_status"] = normal["status"]
        self.escrituras.append(("escribir", id, dict(datos)))
        return {"success": True}

    def crear(self, padre: str, arista: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        _seg(padre, arista)
        normal = self._normal(datos)
        self._existe(padre)
        if arista == "campaigns" and not any(
                k in normal for k in ("daily_budget", "lifetime_budget", "is_adset_budget_sharing_enabled")):
            raise ErrorGraph(100, None, "Invalid parameter: is_adset_budget_sharing_enabled is required")
        for k in ("campaign_id", "adset_id"):
            if k in normal:
                self._existe(str(normal[k]))
        if validate_only:
            return {"success": True}
        nuevo = str(self._siguiente_id)
        self._siguiente_id += 1
        obj = dict(normal)
        if padre in self.cuentas:
            obj["account_id"] = padre.removeprefix("act_")
        else:
            obj["account_id"] = self.objetos[padre].get("account_id", self._cuenta.removeprefix("act_"))
            if arista == "adsets":
                obj.setdefault("campaign_id", padre)
            elif arista == "ads":
                obj.setdefault("adset_id", padre)
                if "campaign_id" in self.objetos[padre]:
                    obj.setdefault("campaign_id", self.objetos[padre]["campaign_id"])
        if "status" in obj:
            obj["effective_status"] = obj["status"]
        self.objetos[nuevo] = obj
        self._hijos[nuevo] = (arista, {padre})
        self.escrituras.append(("crear", f"{padre}/{arista}", dict(datos)))
        return {"id": nuevo}

    def subir_imagen(self, act_id: str, contenido: bytes, nombre: str) -> str:
        _seg(act_id)
        self.escrituras.append(("subir_imagen", act_id, nombre))
        return hashlib.sha256(contenido).hexdigest()[:32]

    def subir_video(self, act_id: str, ruta: Path) -> str:
        _seg(act_id)
        if ruta.stat().st_size > _MAX_VIDEO:
            raise ValueError("vídeo > 100 MB: subida por partes no soportada")
        vid = str(self._siguiente_video)
        self._siguiente_video += 1
        self._videos.add(vid)
        self.escrituras.append(("subir_video", act_id, ruta.name))
        return vid

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
