"""Modo simulado: Telegram y Graph en proceso (sin sockets, sin hilos, sin token).

Los usa el comando ``simular`` y las pruebas. ``TelegramSimulado`` y ``GraphSimulado`` tienen la misma
interfaz pública que ``ClienteTelegram`` y ``ClienteGraph``. El mundo de Graph es mínimo y coherente con
``vivo.valores_vivos``: cuenta ficticia en COP + campaña ``c1`` + conjunto ``s1`` + anuncio ``a1``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets as _secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
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
from trovefy_ejecutor.secretos import Secretos
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
        self._ultima_fecha: int | None = None

    def __repr__(self) -> str:
        return f"TelegramSimulado(chat_id={self.chat_id}, mensajes={len(self.mensajes)})"

    # -- API de ClienteTelegram ---------------------------------------------------------
    def obtener_updates(self, offset: int, timeout_s: int = 25) -> list[dict]:
        return [dict(u) for u in self._updates if u["update_id"] >= offset]

    def enviar(self, chat_id: int, texto: str, botones: list[list[Boton]] | None = None, *,
               sonido: bool = True, responde_a: int | None = None) -> int:
        _validar_largo(texto)
        mid = self._siguiente_mensaje
        self._siguiente_mensaje += 1
        self.mensajes[mid] = {"chat_id": chat_id, "texto": texto, "botones": botones, "sonido": sonido}
        if responde_a is not None:
            self.mensajes[mid]["responde_a"] = responde_a
        self._ultima_fecha = int(self._ahora().timestamp())
        return mid

    def editar(self, chat_id: int, message_id: int, texto: str,
               botones: list[list[Boton]] | None = None) -> None:
        _validar_largo(texto)
        if message_id not in self.mensajes:
            raise ErrorTelegram(400, "Bad Request: message to edit not found")
        self.mensajes[message_id].update(texto=texto, botones=botones)
        self._ultima_fecha = int(self._ahora().timestamp())

    def tomar_fecha(self) -> int | None:
        f, self._ultima_fecha = self._ultima_fecha, None
        return f

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


# == Simulacro de extremo a extremo ===============================================================
_CUENTA = "act_0000000000000000"
_PAGINA, _DATASET = "1357661930771909", "8877665544"
_C1, _S1, _A1 = "100000001", "100000011", "100000021"
_RUTA_IMG, _BYTES_IMG = "productos/p-0001/creativos/BG/t1/img01.jpg", b"\xff\xd8\xff imagen de prueba"
_ESPERA_MOTIVO = "¿Motivo?"


class _Reloj:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def avanzar(self, **kw: float) -> None:
        self.t += timedelta(**kw)


def _limites_simulacro() -> dict:
    return {
        "version": 1, "cuentas_permitidas": [_CUENTA], "paso_max_pct": 50,
        "cadencia_min_presupuesto_min": 120, "enfriamiento_puja_estructura_h": 48, "max_cambios_hora_conjunto": 4,
        "acciones_permitidas": ["noop", "alerta", "crear_estructura_pausada", "activar", "pausar", "presupuesto",
                                "lote", "spend_cap", "limite_cuenta", "limite_ejecutor", "puja"],
        "montaje_status_forzado": "PAUSED",
        "cuentas": {_CUENTA: {
            "moneda": "COP", "offset": 1, "zona_horaria": "America/Bogota",
            "tope_gasto_diario_total": 165000, "max_presupuesto_conjunto": 99000,
            "max_presupuesto_campana_cbo": 132000, "spend_cap_test": 99000, "spend_cap_test_prorroga": 181500,
            "paginas_permitidas": [_PAGINA], "datasets_permitidos": [_DATASET]}},
    }


def _graph_numerico() -> GraphSimulado:
    """``GraphSimulado`` con los ids numéricos que exige el esquema (§5.2)."""
    g = GraphSimulado(_CUENTA, "COP")
    ren = {"c1": _C1, "s1": _S1, "a1": _A1}
    objetos = {}
    for k, v in g.objetos.items():
        v = dict(v)
        for campo in ("campaign_id", "adset_id"):
            if campo in v:
                v[campo] = ren[v[campo]]
        objetos[ren[k]] = v
    g.objetos = objetos
    g._hijos = {ren[k]: (ar, {ren.get(x, x) for x in padres}) for k, (ar, padres) in g._hijos.items()}
    return g


class _Mundo:
    """Un ejecutor real con Telegram y Graph en proceso, todo dentro de ``carpeta`` (un mundo por paso)."""

    def __init__(self, carpeta: Path, secretos: Secretos, ahora: datetime) -> None:
        from trovefy_ejecutor import ejecutar as _ejecutar
        from trovefy_ejecutor.config import RutasEjecutor
        from trovefy_ejecutor.servicio import Ejecutor

        _ejecutar._EMITIDOS.clear()  # memoria de ids emitidos por proceso: cada paso parte limpio
        carpeta.mkdir(parents=True)
        datos = carpeta / "datos"
        vault = carpeta / "vault"
        img = vault / _RUTA_IMG
        img.parent.mkdir(parents=True)
        img.write_bytes(_BYTES_IMG)
        self.rutas = RutasEjecutor(
            secretos=carpeta.parent / "secretos.env", limites=carpeta / "limites.yaml",
            base=datos / "estado.sqlite", auditoria=datos / "auditoria.jsonl", stop=datos / "STOP",
            spool=carpeta / "spool", vault=vault)
        import yaml
        self.rutas.limites.write_text(yaml.safe_dump(_limites_simulacro()), encoding="utf-8")
        os.chmod(self.rutas.limites, 0o600)
        self.secretos = secretos
        self.clave = secretos.hmac_clave or b""
        self.reloj = _Reloj(ahora)
        self.tg = TelegramSimulado(42, 42, ahora=self.reloj)
        self.graph = _graph_numerico()
        self.ej = Ejecutor(self.rutas, self.tg, self.graph, secretos, reloj=self.reloj, modo="simulado")
        self._ejecutar = _ejecutar
        self._Ejecutor = Ejecutor

    def reiniciar(self) -> None:
        self.ej.almacen.cerrar()
        self.ej = self._Ejecutor(self.rutas, self.tg, self.graph, self.secretos, reloj=self.reloj, modo="simulado")

    def cerrar(self) -> None:
        self.ej.almacen.cerrar()
        self._ejecutar._EMITIDOS.clear()

    def id(self, n: int) -> str:
        return f"P-{self.reloj():%Y%m%d}-{n:03d}"

    def creada(self) -> str:
        return (self.reloj() - timedelta(minutes=1)).isoformat()

    def depositar(self, d: dict) -> None:
        ruta = self.rutas.spool / "entrada" / f"{d['id']}.json"
        ruta.write_text(json.dumps(d), encoding="utf-8")
        viejo = self.reloj().timestamp() - 60
        os.utime(ruta, (viejo, viejo))

    def enviar(self, d: dict) -> str:
        self.depositar(d)
        self.ej.ciclo()
        _exigir(self.estado(d["id"]) == "enviada", f"{d['id']} no llegó a enviada ({self.estado(d['id'])})")
        return d["id"]

    def estado(self, id: str) -> str:
        fila = self.ej.almacen.obtener(id)
        return "inexistente" if fila is None else fila.estado

    def eventos(self, nombre: str) -> list[dict]:
        return [x["datos"] for x in map(json.loads, self.rutas.auditoria.read_text(encoding="utf-8").splitlines())
                if x["evento"] == nombre]

    def mensaje_de(self, id: str) -> dict:
        fila = self.ej.almacen.obtener(id)
        assert fila is not None and fila.message_id is not None
        return self.tg.mensajes[fila.message_id]

    def escrituras(self) -> list[tuple]:
        return list(self.graph.escrituras)

    # propuestas (§5.2)
    def noop(self, n: int = 1) -> dict:
        return {"version": 1, "id": self.id(n), "tipo": "noop", "creada": self.creada(), "origen": "/probar",
                "motivo": "Prueba de extremo a extremo", "prioridad": "normal", "expira_en_min": 30}

    def presupuesto(self, n: int = 3) -> dict:
        return {"version": 1, "id": self.id(n), "tipo": "presupuesto", "creada": self.creada(),
                "origen": "/leer --intradia", "producto": "p-0001-herramientas", "pais": "BG", "cuenta": _CUENTA,
                "operaciones": [{"entidad": "adset", "id": _S1, "campo": "daily_budget", "de_esperado": 20000,
                                 "a": 26000, "unidad": "minima", "moneda": "COP"}],
                "motivo": "ROAS neto acum. 2,6", "reinicia_aprendizaje": False, "prioridad": "normal",
                "expira_en_min": 45}

    def estructura(self, n: int = 2) -> dict:
        return {"version": 1, "id": self.id(n), "tipo": "crear_estructura_pausada", "creada": self.creada(),
                "origen": "/montar", "producto": "p-0001", "pais": "BG", "cuenta": _CUENTA, "pagina_id": _PAGINA,
                "dataset_id": _DATASET,
                "medios": [{"ref": "img01", "ruta": _RUTA_IMG, "sha256": hashlib.sha256(_BYTES_IMG).hexdigest()}],
                "campana": {"nombre": "PRUEBA BG | ABO", "objetivo": "OUTCOME_SALES", "tipo_presupuesto": "ABO",
                            "spend_cap": 90000, "bid_strategy": "LOWEST_COST_WITHOUT_CAP"},
                "conjuntos": [{"nombre": "01 IMG", "daily_budget": 20000, "paises": ["BG"], "idiomas": ["bg"],
                               "evento": "PURCHASE", "ubicaciones_excluidas": ["audience_network"],
                               "anuncios": [{"nombre": "AD01", "medio": "img01", "texto": "Texto",
                                             "titulo": "Titulo", "descripcion": "Descripcion",
                                             "cta": "LEARN_MORE", "url": "https://example.com/bg"}]}],
                "unidad": "minima", "moneda": "COP"}


def _exigir(cond: object, motivo: str) -> None:
    if not cond:
        raise AssertionError(motivo)


def _paso_noop(m: _Mundo) -> None:
    id = m.enviar(m.noop())
    cb = m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    _exigir(m.estado(id) == "ejecutada", f"estado {m.estado(id)}")
    _exigir(any(c == cb for c, _ in m.tg.respuestas_callback), "el toque no se respondió")
    _exigir("EJECUTADA" in m.mensaje_de(id)["texto"] and not m.mensaje_de(id)["botones"], "mensaje sin cerrar")
    _exigir((m.rutas.vault / f"propuestas/{id}.md").exists(), "sin registro en el vault")  # type: ignore[operator]
    _exigir(m.ej.auditoria.verificar(), "cadena de auditoría rota")


def _paso_rechazo(m: _Mundo) -> None:
    id = m.enviar(m.presupuesto())
    m.tg.tocar(id, "R", m.clave)
    m.ej.ciclo()
    _exigir(m.estado(id) == "rechazada" and not m.escrituras(), "no quedó rechazada sin escribir")
    pregunta = next((k for k, v in m.tg.mensajes.items() if _ESPERA_MOTIVO in v["texto"]), None)
    _exigir(pregunta is not None, "no preguntó el motivo")
    m.tg.escribir("pico puntual", responde_a=pregunta)
    m.ej.ciclo()
    nota = m.rutas.vault / f"raw/telegram/motivos/{m.reloj():%Y-%m-%d}-{id}.md"  # type: ignore[operator]
    _exigir(nota.exists() and "> pico puntual" in nota.read_text(encoding="utf-8"), "motivo no guardado")
    _exigir(bool(m.eventos("motivo_rechazo")), "motivo sin auditar")


def _paso_doble_toque(m: _Mundo) -> None:
    id = m.enviar(m.presupuesto())
    m.tg.tocar(id, "A", m.clave)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    _exigir(m.estado(id) == "ejecutada", f"estado {m.estado(id)}")
    _exigir(len(m.escrituras()) == 1, f"{len(m.escrituras())} escrituras en vez de 1")
    _exigir(m.graph.objetos[_S1]["daily_budget"] == "26000", "presupuesto sin cambiar")


def _paso_tardio(m: _Mundo) -> None:
    id = m.enviar(m.presupuesto())  # caduca a los 45 min
    m.reloj.avanzar(hours=1)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    _exigir(m.estado(id) == "caducada" and not m.escrituras(), f"estado {m.estado(id)}")


def _paso_stop(m: _Mundo) -> None:
    from trovefy_ejecutor.render import STOP_ACTIVO
    from trovefy_ejecutor.stop import activar_stop, stop_activo

    id = m.enviar(m.presupuesto())
    activar_stop(m.rutas, "simulacro", m.reloj())
    _exigir(stop_activo(m.rutas), "el STOP no quedó activo")
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    _exigir(m.estado(id) == "enviada" and not m.escrituras(), f"estado {m.estado(id)}")
    _exigir(m.mensaje_de(id)["texto"].endswith(STOP_ACTIVO), "el mensaje no avisa del STOP")


def _paso_falsificado(m: _Mundo) -> None:
    id = m.enviar(m.presupuesto())
    data = firmar(id, "A", m.tg.chat_id, m.clave)
    m.tg.tocar(id, "A", m.clave, data=data[:-1] + ("x" if data[-1] != "x" else "y"))
    m.tg.tocar(id, "A", m.clave, user_id=99)
    m.tg.tocar(id, "A", _secrets.token_bytes(32))
    m.ej.ciclo()
    _exigir(m.estado(id) == "enviada" and not m.escrituras(), f"estado {m.estado(id)}")
    motivos = [e["motivo"] for e in m.eventos("callback_invalido")]
    _exigir(motivos == ["callback_firma", "callback_usuario_ajeno", "callback_firma"], f"motivos {motivos}")


def _paso_montaje(m: _Mundo) -> None:
    d = m.estructura(2)
    m.depositar(d)
    m.ej.ciclo()
    id = d["id"]
    _exigir(m.estado(id) == "ejecutada", f"estado {m.estado(id)}: {m.ej.almacen.obtener(id).datos}")  # type: ignore[union-attr]
    fila = m.ej.almacen.obtener(id)
    nueva = fila.datos.get("nueva_propuesta")  # type: ignore[union-attr]
    _exigir(nueva == m.id(800), f"propuesta de activación {nueva}")
    _exigir(m.estado(m.id(800)) == "enviada", "la propuesta de activar no se envió")
    _exigir(m.mensaje_de(m.id(800))["texto"].startswith(f"{m.id(800)} · ACTIVAR"), "texto de activar")
    creados = [o for k, o in m.graph.objetos.items() if k.startswith("900") and "status" in o]
    _exigir(len(creados) >= 3, f"{len(creados)} objetos creados")
    _exigir(all(o.get("status") == "PAUSED" for o in creados), "algún objeto creado no está en PAUSED")


def _paso_pausar_todo(m: _Mundo) -> None:
    m.tg.escribir("/stop")
    m.tg.escribir("/pausar_todo")
    m.ej.ciclo()
    _exigir(m.estado(m.id(900)) == "rechazada" and not m.escrituras(), f"estado {m.estado(m.id(900))}")
    ultimo = m.tg.mensajes[max(m.tg.mensajes)]["texto"]
    _exigir(ultimo.endswith("STOP activo: primero /reanudar y luego /pausar_todo"), "respuesta distinta")


def _paso_reinicio(m: _Mundo) -> None:
    id = m.enviar(m.presupuesto())
    _exigir(m.ej.almacen.transicion(id, "enviada", "aceptada", callback_id="1"), "no pasó a aceptada")
    _exigir(m.ej.almacen.transicion(id, "aceptada", "ejecutando"), "no pasó a ejecutando")
    m.graph.objetos[_S1]["daily_budget"] = "26000"  # la escritura llegó a Meta antes de la caída
    m.reiniciar()
    m.ej.recuperar()
    fila = m.ej.almacen.obtener(id)
    _exigir(fila is not None and fila.estado == "ejecutada", f"estado {m.estado(id)}")
    _exigir(not m.escrituras(), "el reinicio volvió a escribir en Meta")
    _exigir("relectura tras reinicio" in str(fila.datos.get("detalle")), "sin la relectura")  # type: ignore[union-attr]


_PASOS: tuple[tuple[str, Callable[[_Mundo], None]], ...] = (
    ("noop → Aceptar → registro", _paso_noop),
    ("presupuesto → Rechazar con motivo", _paso_rechazo),
    ("doble toque", _paso_doble_toque),
    ("toque tardío", _paso_tardio),
    ("STOP activo", _paso_stop),
    ("callback falsificado", _paso_falsificado),
    ("crear_estructura_pausada", _paso_montaje),
    ("STOP y luego /pausar_todo responde", _paso_pausar_todo),
    ("reinicio en ejecutando no reescribe", _paso_reinicio),
)


def simulacro(raiz: Path, salida: Callable[[str], None] = print) -> list[tuple[str, bool]]:
    """Recorre el ``Ejecutor`` real con Telegram y Graph en proceso. Sin red ni token reales.

    Todo vive dentro de ``raiz`` (rutas, vault, spool, ``limites.yaml``, ``secretos.env`` 0600 con una clave
    HMAC aleatoria y tokens ficticios): nunca lee el ``secretos.env`` real. Cada paso usa su propio mundo.
    Imprime ``OK``/``FALLO`` por paso (sin secretos) y devuelve ``[(nombre, ok)]``.
    """
    from trovefy_ejecutor.auditoria import redactar
    from trovefy_ejecutor.secretos import cargar_secretos, guardar_secretos

    raiz = Path(raiz)
    raiz.mkdir(parents=True, exist_ok=True)
    env = raiz / "secretos.env"
    guardar_secretos(env, {
        "META_TOKEN": "EAA" + _secrets.token_hex(16),
        "TELEGRAM_BOT_TOKEN": f"{_secrets.randbelow(900000) + 100000}:{_secrets.token_urlsafe(26)[:35]}",
        "HMAC_CLAVE": _secrets.token_bytes(32).hex(),
        "TELEGRAM_USER_ID": "42", "TELEGRAM_CHAT_ID": "42", "CLAUDE_UID": str(os.geteuid()),
    }, sobrescribir=True)
    os.chmod(env, 0o600)
    secretos = cargar_secretos(env)
    ahora = datetime(2026, 11, 12, 15, 0, tzinfo=timezone(timedelta(hours=-5)))
    pasos: list[tuple[str, bool]] = []
    for n, (nombre, fn) in enumerate(_PASOS, 1):
        mundo = None
        try:
            mundo = _Mundo(raiz / f"paso{n}", secretos, ahora)
            fn(mundo)
        except Exception as e:  # noqa: BLE001  (un fallo del paso es un resultado, no una caída)
            salida(redactar(f"FALLO {nombre}: {type(e).__name__}: {e}"))
            pasos.append((nombre, False))
        else:
            salida(f"OK    {nombre}")
            pasos.append((nombre, True))
        finally:
            if mundo is not None:
                mundo.cerrar()
    return pasos
