"""Servicio del ejecutor (§5.5, plan 12): buzón → validación → Telegram → Aceptar → Meta.

Invariantes (no negociables):

- Nada que gaste se ejecuta sin un Aceptar válido (firma HMAC, chat y usuario emparejados). Solo
  ``alerta`` (avisa) y ``crear_estructura_pausada`` (crea todo en PAUSED; su ``activar`` sí pide Aceptar)
  van sin botones, y aun así pasan por STOP, moneda y ``comprobar``.
- Nunca hay segunda ejecución: ``aceptada→ejecutando`` es atómica y solo quien la gana llama a Meta.
- Cualquier excepción al leer o validar es un rechazo: nunca «pasa» ni tumba el ciclo.
- Solo ``_transicion`` cambia el estado de una propuesta.
- Ningún token aparece en la auditoría, el vault, ``estado/``, stderr ni ``repr``: todo texto saliente
  pasa por ``_limpio`` (quita los tokens conocidos y aplica ``auditoria.redactar``).
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import sys
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml

from .auditoria import (
    EV_CALLBACK_INVALIDO,
    EV_EJECUCION,
    EV_LIMITE_CAMBIADO,
    EV_MENSAJE_IGNORADO,
    EV_RECIBIDA,
    EV_STOP,
    EV_TRANSICION,
    EV_VALIDACION_RECHAZADA,
    Auditoria,
    AuditoriaCorrupta,
    redactar,
)
from .buzon import Buzon
from .candado import MENSAJE_OTRO, OtroEjecutorActivo, candado
from .comandos import (
    CONFIRMAR_REANUDAR,
    ActivarStop,
    Confirmar,
    ErrorComando,
    GuardarMotivo,
    Ignorar,
    PedirCambioLimite,
    PedirEstado,
    PedirLimites,
    PedirPausarTodo,
    Responder,
    ResponderToque,
    Toque,
    ToqueInterruptor,
    construir_cambio_limite,
    interpretar_update,
    nota_motivo,
    nuevo_id_usuario,
)
from .comprobar_meta import comprobar_meta, informe_a_dict
from .config import RutasEjecutor, rutas_por_defecto
from .deposito import DepositoRechazado, comprobar_origen
from .dinero import Moneda, MonedaNoConfigurada, formatear
from .ejecutar import NO_SOPORTADO_P07, TIPOS_SOPORTADOS, Resultado, ejecutar
from .emparejar import Emparejamiento
from .esquema import RANGO_CLAUDE, PropuestaInvalida, cargar_propuesta
from .estado import Almacen, FilaPropuesta, IdDuplicado
from .graph import OFFSETS_META, ClienteGraph, DetenidoPorStop, ErrorGraph, clasificar
from .limites import (
    CLAVES_CUENTA,
    CLAVES_GLOBALES,
    ContextoVivo,
    Limites,
    LimitesInvalidos,
    cargar_limites,
    comprobar,
    contexto_para,
    limites_a_dict,
)
from .modelo import Propuesta
from .montaje import montar
from .reloj import ZONA_COT, base_caducidad, caducidad, en_silencio, recordatorios
from .render import (
    MAX_RESUMEN,
    PREGUNTA_MOTIVO,
    RECIBIDO,
    STOP_ACTIVO,
    DatosRender,
    Desenlace,
    ItemResumen,
    ResumenEstado,
    botones_propuesta,
    render_alerta,
    render_estado,
    render_propuesta,
    render_resultado,
    render_resumen,
    texto_ya_procesada,
)
from .ritmo import Ritmo
from .secretos import Secretos, SecretosInseguros, cargar_secretos
from .simulado import GraphSimulado
from .stop import activar_stop, quitar_stop, stop_activo
from .telegram import Boton, ClienteTelegram, ErrorRedTelegram, ErrorTelegram
from .vault_copia import CopiaVault
from .vivo import ValoresVivos, presupuestos_activos_cuenta, valores_vivos

TIPOS_INGERIBLES: frozenset[str] = TIPOS_SOPORTADOS | {"crear_estructura_pausada"}
ZONA_POR_DEFECTO = "America/Bogota"
_SIN_LECTURA_VIVA = frozenset({"noop", "limite_ejecutor"})
_ERRORES_TELEGRAM = (ErrorTelegram, ErrorRedTelegram, ValueError)
_TOCA_META = frozenset(TIPOS_INGERIBLES - {"noop", "limite_ejecutor", "alerta"})
DESFASE_MAX_S = 300
VIGENCIA_DESFASE = timedelta(minutes=10)  # una medida más vieja no vale para ejecutar
CLAVE_DESFASE = "desfase_reloj"
AVISO_DESFASE = ("{id}: reloj desfasado ({s} s): ejecuta `sudo hwclock -s`. No se ejecutó nada; la propuesta "
                 "queda aceptada y se reintenta al reiniciar el servicio.")
AVISO_SIN_MEDIDA = ("{id}: no se pudo comprobar la hora con Telegram. No se ejecutó nada; la propuesta queda "
                    "aceptada y se reintenta al reiniciar el servicio. Si el reloj de WSL va mal, ejecuta "
                    "`sudo hwclock -s`.")
AVISO_RELOJ = "reloj sin comprobar o desfasado: ejecuta `sudo hwclock -s` y reinicia el servicio"
AVISO_TOKEN = ("Token de Meta caducado: renuévalo en /arranque paso 13. No se ejecuta nada en Meta hasta que "
               "comprobar-meta vuelva a dar ok.")
MOTIVO_TOKEN = "token de Meta caducado: renuévalo en /arranque paso 13"
CLAVE_TOKEN = "token_caducado"
AVISO_STOP_TELEGRAM = "STOP activo: primero /reanudar y luego /pausar_todo"
CONFIRMACION_USADA = "Esta confirmación ya se usó: no se hizo nada"
TITULO_RESUMEN = "En espera"
RECORDATORIO = "Recordatorio: {id} sigue pendiente; el dinero sigue corriendo"
_LINEAS_FUERA_DEL_RESUMEN = ("Por qué:", "Reinicia aprendizaje:", "Caduca", "Gasto diario")
AVISO_TOKEN_RENOVADO = "token de Meta renovado: el ejecutor vuelve a operar"
INTERVALO_LATIDO = timedelta(seconds=30)
INTERVALO_META = timedelta(minutes=10)
INTERVALO_COPIA_AUDITORIA = timedelta(minutes=1)
# Long polling corto: el ciclo vuelve pronto para ver ``parar``/SIGTERM y el buzón (ver ``servir``).
TIMEOUT_UPDATES_S = 10


def _version() -> str:
    try:
        return metadata.version("trovefy")
    except metadata.PackageNotFoundError:
        return "desconocida"


VERSION = _version()


class GraphConStop:
    """Envoltorio de Graph que corta toda escritura (también ``validate_only``) si hay STOP (resolución 11).

    Deja pasar sin tocar las lecturas (``leer``, ``listar``, ``buscar``, ``cuenta``). No expone ningún
    otro método del cliente: lo que no está aquí no existe para ``ejecutar``/``montar``."""

    def __init__(self, graph, rutas: RutasEjecutor) -> None:
        self._graph = graph
        self._rutas = rutas

    def __repr__(self) -> str:
        return "GraphConStop()"

    def _parar(self) -> None:
        if stop_activo(self._rutas):
            raise DetenidoPorStop()

    def escribir(self, id: str, datos, *, validate_only: bool = False) -> dict:
        self._parar()
        return self._graph.escribir(id, datos, validate_only=validate_only)

    def crear(self, padre: str, arista: str, datos, *, validate_only: bool = False) -> dict:
        self._parar()
        return self._graph.crear(padre, arista, datos, validate_only=validate_only)

    def subir_imagen(self, act_id: str, contenido: bytes, nombre: str) -> str:
        self._parar()
        return self._graph.subir_imagen(act_id, contenido, nombre)

    def subir_video(self, act_id: str, ruta: Path) -> str:
        self._parar()
        return self._graph.subir_video(act_id, ruta)

    def leer(self, id: str, campos) -> dict:
        return self._graph.leer(id, campos)

    def listar(self, *args, **kwargs) -> list[dict]:
        return self._graph.listar(*args, **kwargs)

    def buscar(self, tipo: str, q: str, campos) -> list[dict]:
        return self._graph.buscar(tipo, q, campos)

    def cuenta(self, act_id: str):
        return self._graph.cuenta(act_id)


class Ejecutor:
    def __init__(self, rutas: RutasEjecutor, telegram, graph, secretos: Secretos, *,
                 reloj: Callable[[], datetime], modo: Literal["real", "simulado"] = "real") -> None:
        self.rutas = rutas
        self.telegram = telegram
        self.graph = graph
        self.secretos = secretos
        self.reloj = reloj
        self.modo = modo
        rutas.base.parent.mkdir(parents=True, exist_ok=True)
        self.almacen = Almacen(rutas.base, reloj=reloj)
        self.auditoria = Auditoria(rutas.auditoria, reloj=reloj)
        self.buzon = Buzon(rutas.spool, reloj=lambda: reloj().timestamp())
        self.copia = CopiaVault(rutas.vault, rutas.base.with_suffix(".pendientes"))
        self.ritmo = Ritmo()
        self.ritmo.sembrar(self.almacen.envios_desde(reloj() - timedelta(hours=1)))
        self.limites: Limites = cargar_limites(rutas.limites)  # inválido al arrancar: lo trata servir()
        self._limites_mtime: int | None = rutas.limites.stat().st_mtime_ns
        self._limites_error: str | None = None
        self._limites_json_mtime: int | None = None
        self.desfase_s: float | None = None
        self._desfase_medido: datetime | None = None
        self._aviso_reloj: str | None = None
        self._cargar_desfase()
        self.parar = threading.Event()  # servir() pone el suyo: corta las esperas del ciclo
        self.espera_red_s: float = 5
        self.timeout_updates_s = TIMEOUT_UPDATES_S
        self._telegram_estado: Literal["ok", "sin red"] = "sin red"  # hasta el primer getUpdates bueno
        self._ultimo_latido: datetime | None = None
        self._ultima_comprobacion_meta: datetime | None = None
        self._token_al_arrancar = bool(self.almacen.leer_kv(CLAVE_TOKEN))
        self._auditoria_copiada: datetime | None = None
        self._dia_auditoria: date | None = None
        self._DESPACHO: dict[type, Callable[[Any], None]] = {
            Ignorar: self._ignorar,
            Responder: self._responder,
            ResponderToque: self._responder_toque_invalido,
            Toque: self._toque,
            GuardarMotivo: self._guardar_motivo,
            ActivarStop: self._activar_stop,
            Confirmar: self._confirmar,
            ToqueInterruptor: self._toque_interruptor,
            PedirEstado: self._pedir_estado,
            PedirLimites: self._pedir_limites,
            PedirCambioLimite: self._pedir_cambio_limite,
            PedirPausarTodo: self._pedir_pausar_todo,
        }

    def __repr__(self) -> str:
        return f"Ejecutor(modo={self.modo!r})"

    # -- utilidades -----------------------------------------------------------------------------------
    @property
    def _chat(self) -> int | None:
        return self.secretos.telegram_chat_id

    def _emparejado(self) -> Emparejamiento | None:
        s = self.secretos
        if s.telegram_user_id is None or s.telegram_chat_id is None:
            return None
        return Emparejamiento(s.telegram_user_id, s.telegram_chat_id)

    def _limpio(self, texto: object) -> str:
        t = str(texto)
        for secreto in (self.secretos.meta_token, self.secretos.telegram_bot_token):
            if secreto:
                t = t.replace(secreto, "***")
        return redactar(t)

    def _texto_error(self, e: BaseException) -> str:
        return self._limpio(f"{type(e).__name__}: {e}")[:300]

    def _anotar_error(self, donde: str, e: BaseException) -> None:
        try:
            self.auditoria.anotar("error", donde=donde, detalle=self._texto_error(e))
        except Exception:  # noqa: BLE001, S110 — la auditoría rota no puede tumbar el ciclo
            pass

    def _vigilar_token(self, e: BaseException) -> None:
        """Un 190/102 de Meta al leer: se marca el token como caducado (no más gasto) y se avisa una vez."""
        if isinstance(e, ErrorGraph) and clasificar(e) == "token" and not self.almacen.leer_kv(CLAVE_TOKEN):
            self.almacen.poner_kv(CLAVE_TOKEN, self.reloj().isoformat())
            self._decir(AVISO_TOKEN)

    def _decir(self, texto: str, botones: list[list[Boton]] | None = None, *, sonido: bool = True) -> int | None:
        """Envía un mensaje al chat emparejado; un fallo de Telegram se audita y devuelve None."""
        if self._chat is None:
            return None
        try:
            return self._tg_enviar(self._chat, self._limpio(texto), botones, sonido=sonido)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            return None

    def _tg_enviar(self, chat: int, texto: str, botones: list[list[Boton]] | None, *, sonido: bool,
                   responde_a: int | None = None) -> int:
        """``telegram.enviar`` + medida del desfase con la hora que devuelve el servidor. Lanza si falla."""
        extra = {"responde_a": responde_a} if responde_a is not None else {}
        mid = self.telegram.enviar(chat, texto, botones, sonido=sonido, **extra)
        self._tomar_fecha()
        return mid

    # -- desfase de reloj -------------------------------------------------------------------------------
    def _cargar_desfase(self) -> None:
        """La última medida sobrevive al reinicio (kv), con su hora: ``_desfase_fresco`` decide si vale."""
        try:
            d = json.loads(self.almacen.leer_kv(CLAVE_DESFASE) or "null")
            s, medido = float(d["s"]), datetime.fromisoformat(d["medido"])
            if medido.utcoffset() is None:
                return
            self.desfase_s, self._desfase_medido = s, medido
        except (TypeError, ValueError, KeyError):
            return

    def _anotar_desfase(self, s: float) -> None:
        ahora = self.reloj()
        self.desfase_s, self._desfase_medido = s, ahora
        self.almacen.poner_kv(CLAVE_DESFASE, json.dumps({"s": s, "medido": ahora.isoformat()}))

    def _tomar_fecha(self) -> None:
        """Mide con la hora del servidor de la última respuesta de ``sendMessage``/``editMessageText``."""
        tomar = getattr(self.telegram, "tomar_fecha", None)
        if not callable(tomar):
            return
        try:
            f = tomar()
        except Exception:  # noqa: BLE001 — sin medida: _ejecutar falla cerrado
            return
        if type(f) is int and f > 0:
            self._anotar_desfase(self.reloj().timestamp() - f)

    def _desfase_fresco(self) -> float | None:
        """La última medida si tiene ≤ 10 min (en cualquier sentido: un salto del reloj la invalida)."""
        if self.desfase_s is None or self._desfase_medido is None:
            return None
        if abs(self.reloj() - self._desfase_medido) > VIGENCIA_DESFASE:
            return None
        return self.desfase_s

    def _medir_ahora(self, fila: FilaPropuesta, mid: int | None) -> None:
        """Pide a Telegram una hora fresca editando el mensaje de la propuesta (o con un mensaje nuevo si
        es un resumen o no hay mensaje): la respuesta trae ``edit_date``/``date`` del servidor."""
        propio = fila.message_id
        destino = mid if mid is not None else propio
        aviso = f"ACEPTADA {self._hora()}: comprobando la hora antes de ejecutar…"
        if (destino is None or fila.datos.get("resumen")
                or (mid is not None and propio is not None and mid != propio)):
            self._decir(f"{fila.id}: {aviso}", sonido=False)
            return
        original = fila.datos.get("texto")
        original = original if isinstance(original, str) else f"{fila.id} · {fila.tipo}"
        self._editar(destino, f"{original[:3800]}\n\n{aviso}")

    def _transicion(self, id: str, de, a, **datos) -> bool:
        """Única vía de transición del servicio: ``Almacen.transicion`` + ``EV_TRANSICION`` si cambió."""
        if not self.almacen.transicion(id, de, a, **datos):
            return False
        fila = self.almacen.obtener(id)
        extra = {"motivo": self._limpio(datos["motivo"])[:500]} if "motivo" in datos else {}
        self.auditoria.anotar(EV_TRANSICION, id=id, tipo=fila.tipo if fila else "?", de=de, a=a, **extra)
        return True

    def _copiar(self, id: str, r=None, texto: str | None = None) -> None:
        try:
            fila = self.almacen.obtener(id)
            if fila is not None:
                t = texto if texto is not None else fila.datos.get("texto")
                t = self._limpio(t) if isinstance(t, str) else f"{fila.id} · {fila.tipo}"
                self.copia.resultado(fila, r, t)
        except Exception as e:  # noqa: BLE001 — copiar no es escribir en Meta: nunca tumba nada
            self._anotar_error("vault", e)

    # -- límites ----------------------------------------------------------------------------------------
    def _recargar_limites(self) -> None:
        try:
            mtime = self.rutas.limites.stat().st_mtime_ns
        except OSError:
            self._limites_error = "limites.yaml ilegible: no se valida nada"
            self._limites_mtime = None
            return
        if mtime == self._limites_mtime:
            return
        self._limites_mtime = mtime
        try:
            self.limites = cargar_limites(self.rutas.limites)
            self._limites_error = None
        except Exception as e:  # noqa: BLE001 — falla cerrada: todo se rechaza hasta que vuelva a cargar
            self._limites_error = f"limites.yaml no válido: {self._texto_error(e)}"

    def _limite_actual(self, id: str, campo: str) -> int | None:
        lim = self.limites
        if id == "global":
            return getattr(lim, campo, None) if campo in CLAVES_GLOBALES else None
        lc = lim.cuentas.get(id)
        return getattr(lc, campo, None) if lc is not None and campo in CLAVES_CUENTA else None

    def _moneda_respaldo(self) -> Moneda:
        for _, lc in sorted(self.limites.cuentas.items()):
            try:
                return lc.moneda()
            except MonedaNoConfigurada:
                continue
        return Moneda("USD", 100)

    # -- buzón --------------------------------------------------------------------------------------
    def ingerir(self) -> int:
        n = 0
        for ruta in self.buzon.nuevas():
            try:
                self._ingerir_una(ruta)
                n += 1
            except sqlite3.OperationalError:
                raise
            except Exception as e:  # noqa: BLE001 — una propuesta nunca tumba el ciclo
                self._anotar_error("ingerir", e)
                if ruta.exists():
                    try:
                        self.buzon.procesar(ruta, {"estado": "rechazada", "motivo": "error interno"})
                    except Exception as e2:  # noqa: BLE001
                        self._anotar_error("ingerir", e2)
        return n

    def _rechazo_buzon(self, ruta: Path, id: str, motivo: str, **extra) -> None:
        motivo = self._limpio(motivo)[:500]
        self.auditoria.anotar(EV_VALIDACION_RECHAZADA, id=self._limpio(id)[:40], motivo=motivo, **extra)
        self.buzon.procesar(ruta, {"estado": "rechazada", "motivo": motivo})

    def _ingerir_una(self, ruta: Path) -> None:
        id_archivo = ruta.stem
        uids = {u for u in (self.secretos.claude_uid, os.geteuid()) if u is not None}
        try:
            comprobar_origen(ruta, uids)
            datos = self.buzon.leer(ruta)
            p = cargar_propuesta(datos)
        except DepositoRechazado as e:
            return self._rechazo_buzon(ruta, id_archivo, f"origen: {e.motivo}", uid=e.uid)
        except PropuestaInvalida as e:
            return self._rechazo_buzon(ruta, id_archivo, e.motivo)
        except Exception as e:  # noqa: BLE001 — cualquier fallo de lectura es un rechazo
            return self._rechazo_buzon(ruta, id_archivo, f"ilegible: {self._texto_error(e)}")
        if p.id != id_archivo:
            return self._rechazo_buzon(ruta, id_archivo, f"el nombre del archivo no es el id ({p.id})")
        if int(p.id[-3:]) not in RANGO_CLAUDE:
            return self._rechazo_buzon(ruta, p.id, "id reservado (800–899 ejecutor, 900–999 Telegram)")
        if p.tipo not in TIPOS_INGERIBLES:
            return self._rechazo_buzon(ruta, p.id, NO_SOPORTADO_P07)
        try:
            self.almacen.registrar(p)
        except IdDuplicado:
            return self._rechazo_buzon(ruta, p.id, "id duplicado")
        try:
            self.auditoria.anotar(EV_RECIBIDA, id=p.id, tipo=p.tipo)
            self.buzon.procesar(ruta, {"estado": "recibida", "motivo": None})
        except sqlite3.OperationalError:
            raise
        except Exception as e:  # registrada pero sin procesar: nunca queda viva a medias
            self._rechazar_recibida(p.id, f"error interno al recibir: {self._texto_error(e)}")
            raise
        self._despachar(p.id)

    # -- despacho de propuestas -------------------------------------------------------------------------
    def _despachar(self, id: str) -> None:
        fila = self.almacen.obtener(id)
        if fila is None or fila.estado != "recibida":
            return
        if fila.tipo == "alerta":
            self._despachar_alerta(fila)
        elif fila.tipo == "crear_estructura_pausada":
            self._despachar_montaje(fila)
        else:
            self._despachar_propuesta(fila)

    def _rechazar_recibida(self, id: str, motivo: str) -> None:
        motivo = self._limpio(motivo)[:500]
        if self._transicion(id, "recibida", "rechazada", motivo=motivo):
            self.auditoria.anotar(EV_VALIDACION_RECHAZADA, id=id, motivo=motivo)
            self._copiar(id)
            self._avisar_si_telegram(id, motivo)

    def _avisar_si_telegram(self, id: str, motivo: str) -> None:
        """Lo pedido desde Telegram y rechazado al recibir se responde con el motivo (lo de Claude, no)."""
        fila = self.almacen.obtener(id)
        if fila is None or not fila.propuesta.origen.startswith("telegram:"):
            return
        texto = AVISO_STOP_TELEGRAM if motivo == "STOP activo" else motivo
        self._decir(f"{id}: rechazada, no se hizo nada. {texto}")

    def _leer_vivo(self, p: Propuesta) -> ValoresVivos | None:
        if p.tipo in _SIN_LECTURA_VIVA:
            return None
        return valores_vivos(p, self.graph, ahora=self.reloj)

    def _obsoleta(self, p: Propuesta, vv: ValoresVivos | None) -> str | None:
        if p.tipo == "limite_ejecutor":
            for op in p.operaciones:
                actual = self._limite_actual(op.id, op.campo)
                if actual is not None and actual != op.de_esperado:
                    return f"{op.id} {op.campo}: esperado {op.de_esperado}, actual {actual}"
            return None
        return vv.obsoleta(p) if vv is not None else None

    def _contexto(self, p: Propuesta, vv: ValoresVivos | None) -> ContextoVivo:
        return contexto_para(
            p, self.almacen, ahora=self.reloj(), stop=stop_activo(self.rutas),
            valores=vv.valores_para_limites() if vv is not None else {},
            presupuestos_activos=vv.presupuestos_activos if vv is not None else {},
            presupuesto_al_activar=vv.presupuesto_al_activar_por_id(p) if vv is not None else {})

    def _validar(self, p: Propuesta, vv: ValoresVivos | None) -> str | None:
        """Moneda viva frente a ``limites.yaml`` y ``comprobar``. Devuelve el motivo del rechazo o None.

        Cualquier excepción (lectura de la cuenta, ``comprobar``…) es un rechazo, nunca un «pasa»."""
        try:
            if self._limites_error:
                return self._limites_error
            lim = self.limites
            cuentas = {p.cuenta} if p.cuenta is not None else set()
            cuentas |= {op.id for op in p.operaciones if op.entidad == "ejecutor" and op.unidad is not None}
            for c in sorted(cuentas):
                lc = lim.cuentas.get(c)
                if lc is None:
                    return f"cuenta_no_permitida: {c} sin sección en limites.yaml"
                info = vv.cuenta if vv is not None and c == p.cuenta else self.graph.cuenta(c)
                viva = info.currency
                if viva != lc.moneda_codigo or lc.offset is None or OFFSETS_META.get(viva) != lc.offset:
                    return (f"moneda viva ≠ limites.yaml (P-21): Meta {viva or '?'}, limites "
                            f"{lc.moneda_codigo} con offset {lc.offset}")
            violaciones = comprobar(p, lim, self._contexto(p, vv))
            return "; ".join(violaciones) if violaciones else None
        except MonedaNoConfigurada:
            return "moneda sin offset confirmado (P-21)"
        except Exception as e:  # noqa: BLE001 — falla cerrada
            return f"validación fallida: {self._texto_error(e)}"

    def _zona(self, p: Propuesta) -> str:
        lc = self.limites.cuentas.get(p.cuenta) if p.cuenta else None
        return lc.zona_horaria if lc is not None else ZONA_POR_DEFECTO

    def _caduca(self, fila: FilaPropuesta) -> datetime:
        p = fila.propuesta
        return caducidad(p, base_caducidad(p, fila.recibida), self._zona(p))

    def _datos_render(self, fila: FilaPropuesta, vv: ValoresVivos | None) -> DatosRender:
        p = fila.propuesta
        lc = self.limites.cuentas.get(p.cuenta) if p.cuenta else None
        moneda = lc.moneda() if lc is not None else self._moneda_respaldo()
        valores: dict[tuple[str, str, str], int | str] = {}
        for op in p.operaciones:
            v = self._limite_actual(op.id, op.campo) if op.entidad == "ejecutor" else (
                vv.valor(op) if vv is not None else None)
            if v is not None:
                valores[(op.entidad, op.id, op.campo)] = v
        gasto, desconocido = self._gasto_tras(p, vv)
        mostrar = (gasto is not None or desconocido) and lc is not None
        return DatosRender(moneda=moneda, leido=vv.leido_en if vv is not None else self.reloj(),
                           caduca=self._caduca(fila), valores=valores,
                           gasto_cuenta_tras=gasto if mostrar else None,
                           tope_cuenta=lc.tope_gasto_diario_total if mostrar and lc is not None else None,
                           gasto_desconocido=desconocido and mostrar)

    @staticmethod
    def _gasto_tras(p: Propuesta, vv: ValoresVivos | None) -> tuple[int | None, bool]:
        """Gasto diario activo de la cuenta tras aplicar ``p``; ``(None, True)`` si no se sabe (nunca 0)."""
        if vv is None or vv.suma_diaria_activa is None:
            return None, False
        if p.tipo == "activar":
            extra = vv.presupuesto_al_activar(p)
            return (None, True) if extra is None else (vv.suma_diaria_activa + extra, False)
        if p.tipo in ("presupuesto", "lote"):
            sim = dict(vv.presupuestos_activos)
            pendientes: dict[str, int] = {}  # presupuesto nuevo de algo que hoy no gasta
            for op in p.operaciones:
                if op.campo == "daily_budget" and isinstance(op.a, int):
                    if op.id in sim:
                        sim[op.id] = op.a
                    else:
                        pendientes[op.id] = op.a
                elif op.campo == "status" and op.a == "PAUSED":
                    sim.pop(op.id, None)
            activadas = [op for op in p.operaciones if op.campo == "status" and op.a == "ACTIVE"]
            if activadas:
                if vv.presupuesto_al_activar(p) is None:
                    return None, True
                por_id = vv.presupuesto_al_activar_por_id(p)
                # Una sola vez por entidad: si además cambia su presupuesto, cuenta lo mayor (como comprobar).
                for op in activadas:
                    sim[op.id] = max(sim.get(op.id, 0), por_id.get(op.id, 0), pendientes.get(op.id, 0))
            return sum(sim.values()), False
        return None, False

    def _despachar_propuesta(self, fila: FilaPropuesta) -> None:
        id, p = fila.id, fila.propuesta
        if stop_activo(self.rutas):
            return self._rechazar_recibida(id, "STOP activo")
        try:
            vv = self._leer_vivo(p)
            obsoleta = self._obsoleta(p, vv)
        except Exception as e:  # noqa: BLE001 — EntidadAjena, LecturaIncompleta, ErrorRed… = rechazo
            self._vigilar_token(e)
            return self._rechazar_recibida(id, f"no se pudo leer Meta: {self._texto_error(e)}")
        if obsoleta:
            if self._transicion(id, "recibida", "obsoleta", motivo=obsoleta):
                self._copiar(id)
                self._avisar_si_telegram(id, f"obsoleta: {self._limpio(obsoleta)}")
            return
        motivo = self._validar(p, vv)
        if motivo:
            return self._rechazar_recibida(id, motivo)
        try:
            texto = render_propuesta(p, self._datos_render(fila, vv))
        except Exception as e:  # noqa: BLE001 — SinValorVivo, MensajeDemasiadoLargo, moneda…
            return self._rechazar_recibida(id, f"no se pudo preparar el mensaje: {self._texto_error(e)}")
        self._enviar(id, texto)

    def _enviar(self, id: str, texto: str) -> None:
        """Envía la propuesta con sus dos botones si el ritmo lo permite; si no, queda en cola."""
        texto = self._limpio(texto)
        fila = self.almacen.obtener(id)
        if fila is None:
            return
        ahora = self.reloj()
        decision = self.ritmo.decidir(fila.propuesta, ahora)
        chat, clave = self._chat, self.secretos.hmac_clave
        if not decision.enviar or chat is None or not clave:
            self.almacen.actualizar_datos(id, "recibida", en_cola=True, texto=texto)
            return
        try:
            mid = self._tg_enviar(chat, texto, botones_propuesta(id, chat, clave), sonido=decision.sonido)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            self.almacen.actualizar_datos(id, "recibida", en_cola=True, texto=texto)
            return
        self.ritmo.anotar_envio(ahora)
        self.almacen.guardar_mensaje(id, chat, mid)
        self._transicion(id, "recibida", "enviada", texto=texto, enviada_en=ahora.isoformat(), en_cola=False)

    def _despachar_alerta(self, fila: FilaPropuesta) -> None:
        p, ahora = fila.propuesta, self.reloj()
        decision = self.ritmo.decidir(p, ahora)
        if not decision.enviar or self._chat is None:
            self.almacen.actualizar_datos(fila.id, "recibida", en_cola=True)
            return
        texto = self._limpio(render_alerta(p))
        try:
            mid = self._tg_enviar(self._chat, texto, None, sonido=decision.sonido)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            self.almacen.actualizar_datos(fila.id, "recibida", en_cola=True)
            return
        self.ritmo.anotar_envio(ahora)
        self.almacen.guardar_mensaje(fila.id, self._chat, mid)
        if self._transicion(fila.id, "recibida", "ejecutando", texto=texto):
            self._transicion(fila.id, "ejecutando", "ejecutada")
            self._copiar(fila.id, None, texto)

    def _despachar_montaje(self, fila: FilaPropuesta) -> None:
        """``crear_estructura_pausada`` no gasta (todo en PAUSED; su ``activar`` pide Aceptar): se monta sin
        botones, pero antes pasa STOP, token, moneda viva y ``comprobar`` (páginas, datasets, topes)."""
        id, p = fila.id, fila.propuesta
        if stop_activo(self.rutas):
            return self._rechazar_recibida(id, "STOP activo")
        if self.almacen.leer_kv(CLAVE_TOKEN):
            return self._rechazar_recibida(id, MOTIVO_TOKEN)
        motivo = self._validar(p, None)
        if motivo:
            return self._rechazar_recibida(id, motivo)
        if not self._transicion(id, "recibida", "ejecutando"):
            return
        if self.rutas.vault is None:
            if self._transicion(id, "ejecutando", "fallida", motivo="sin vault configurado"):
                self._editar_desenlace(id, None, Desenlace("fallida", self.reloj(), codigo="sin vault configurado"))
            return
        try:
            r = montar(p, GraphConStop(self.graph, self.rutas), self.almacen, self.auditoria, self.rutas.vault,
                       ahora=self.reloj)
        except Exception as e:  # noqa: BLE001 — montar no debería lanzar; si lo hace, no se sabe qué creó
            r = Resultado("discrepancia", f"error inesperado en el montaje ({self._texto_error(e)}): puede "
                                          "haberse creado algo; revisa Ads Manager", error="otro")
        self._cerrar(id, r, None)

    # -- toques y ejecución ---------------------------------------------------------------------------
    def _responder_toque(self, callback_id: str, texto: str) -> None:
        try:
            self.telegram.responder_callback(callback_id, texto)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)

    def _editar(self, mid: int, texto: str, botones: list[list[Boton]] | None = None) -> bool:
        if self._chat is None:
            return False
        try:
            self.telegram.editar(self._chat, mid, self._limpio(texto), botones)
            self._tomar_fecha()
            return True
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            return False

    def _editar_desenlace(self, id: str, mid: int | None, d: Desenlace,
                          botones: list[list[Boton]] | None = None) -> str:
        """Reescribe el mensaje de la propuesta con su desenlace (sin botones salvo que se pidan).
        Si no hay mensaje (montaje) o no se puede editar, envía uno nuevo. Devuelve el texto final."""
        fila = self.almacen.obtener(id)
        original = fila.datos.get("texto") if fila is not None else None
        if not isinstance(original, str):
            original = f"{id} · {fila.tipo if fila is not None else '?'}"
        final = render_resultado(original, d)
        propio = fila.message_id if fila is not None else None
        if fila is not None and (fila.datos.get("resumen") or (mid is not None and propio is not None
                                                               and mid != propio)):
            self._editar_en_resumen(fila, mid, d, final)
            return final
        destino = mid if mid is not None else propio
        if destino is None or not self._editar(destino, final, botones):
            self._decir(final, botones)
        return final

    def _editar_en_resumen(self, fila: FilaPropuesta, mid: int | None, d: Desenlace, final: str) -> None:
        """Toque desde un resumen: se reescribe solo el bloque de esta propuesta (su estado, sin sus botones;
        los de las demás siguen) y el desenlace completo va en un mensaje aparte (salvo «ejecutando», que es
        de paso). Si el toque llegó desde otro mensaje que no es un resumen, solo el mensaje aparte."""
        if fila.datos.get("resumen") and fila.message_id is not None:
            self._reescribir_resumen(fila)
        if d.estado != "ejecutando":
            self._decir(final, sonido=False)

    def _item_resumen(self, f: FilaPropuesta, estado=None) -> ItemResumen:
        texto = f.datos.get("texto")
        lineas = [ln for ln in (texto.splitlines() if isinstance(texto, str) else [])
                  if ln and not ln.startswith(_LINEAS_FUERA_DEL_RESUMEN)]
        primera = lineas[0].removeprefix(f"{f.id} · ") if lineas else f.tipo
        try:
            cad = self._caduca(f)
        except Exception:  # noqa: BLE001 — solo es lo que se muestra; el toque vuelve a comprobarla
            cad = self.reloj()
        return ItemResumen(id=f.id, linea=" · ".join([primera, *lineas[1:2]]), motivo=f.propuesta.motivo or "",
                           caduca=cad, estado=estado or f.estado)

    def _reescribir_resumen(self, fila: FilaPropuesta) -> None:
        chat, clave = self._chat, self.secretos.hmac_clave
        if chat is None or not clave or fila.message_id is None:
            return
        ids = fila.datos.get("resumen_ids")
        ids = ids if isinstance(ids, list) and fila.id in ids else [fila.id]
        filas = [self.almacen.obtener(i) for i in ids[:MAX_RESUMEN]]
        try:
            texto, botones = render_resumen([self._item_resumen(f) for f in filas if f is not None], TITULO_RESUMEN,
                                            chat, clave)
        except Exception as e:  # noqa: BLE001 — el resumen queda como estaba; el desenlace va aparte
            self._anotar_error("resumen", e)
            return
        self._editar(fila.message_id, texto, botones)

    def _caducada(self, fila: FilaPropuesta) -> bool:
        try:
            return self.reloj() >= self._caduca(fila)
        except Exception:  # noqa: BLE001 — sin poder calcularla, se da por caducada (falla cerrada)
            return True

    def _toque(self, a: Toque) -> None:
        self._responder_toque(a.callback_id, RECIBIDO)  # antes de nada más
        fila = self.almacen.obtener(a.id)
        if fila is None:
            self._decir(f"{a.id}: propuesta desconocida; no se hizo nada")
            return
        ahora = self.reloj()
        if a.accion == "R":
            if not self._transicion(a.id, "enviada", "rechazada", callback_id=a.callback_id,
                                    motivo="rechazada en Telegram"):
                return self._ya_procesada(a.id)
            self._editar_desenlace(a.id, a.message_id, Desenlace("rechazada", ahora))
            pregunta = self._decir(PREGUNTA_MOTIVO.format(id=a.id), sonido=False)
            if pregunta is not None:
                self.almacen.actualizar_datos(a.id, "rechazada", pregunta_motivo=pregunta)
            self._copiar(a.id)
            return
        if stop_activo(self.rutas):
            if fila.estado == "enviada" and self._chat is not None and self.secretos.hmac_clave:
                # La fila sigue enviada: se conservan los botones para cuando se quite el STOP.
                self._editar_desenlace(a.id, a.message_id, Desenlace("stop", ahora),
                                       botones_propuesta(a.id, self._chat, self.secretos.hmac_clave))
            else:
                self._decir(STOP_ACTIVO)
            return
        if fila.estado == "enviada" and self._caducada(fila):
            if self._transicion(a.id, "enviada", "caducada", motivo="caducada al tocar Aceptar"):
                self._editar_desenlace(a.id, a.message_id, Desenlace("caducada", ahora))
                self._copiar(a.id)
            return
        if not self._transicion(a.id, "enviada", "aceptada", callback_id=a.callback_id,
                                aceptada_en=ahora.isoformat()):
            return self._ya_procesada(a.id)
        self._ejecutar(a.id, a.message_id)

    def _ya_procesada(self, id: str) -> None:
        fila = self.almacen.obtener(id)
        self._decir(texto_ya_procesada(fila.estado) if fila is not None else f"{id}: propuesta desconocida")

    def _fallar_aceptada(self, id: str, mid: int | None, motivo: str, desenlace: str = "fallida") -> None:
        motivo = self._limpio(motivo)[:500]
        if self._transicion(id, "aceptada", "fallida", motivo=motivo):
            d = (Desenlace("stop", self.reloj()) if desenlace == "stop"
                 else Desenlace("fallida", self.reloj(), codigo=motivo))
            self._copiar(id, None, self._editar_desenlace(id, mid, d))

    def _ejecutar(self, id: str, mid: int | None) -> None:
        """Orden (resolución 9 y notas del plan 11): desfase → STOP → token → valores_vivos → obsoleta →
        moneda → comprobar → ``aceptada→ejecutando`` → ``ejecutar``. Sin ``ejecutando`` no hay Meta."""
        fila = self.almacen.obtener(id)
        if fila is None or fila.estado != "aceptada":
            return
        p, ahora = fila.propuesta, self.reloj()
        desfase = self._desfase_fresco()
        if desfase is None:
            self._medir_ahora(fila, mid)
            desfase = self._desfase_fresco()
        if desfase is None:  # sin medida fresca no se sabe si el reloj miente: no se ejecuta
            self._aviso_reloj = AVISO_RELOJ
            self._decir(AVISO_SIN_MEDIDA.format(id=id))
            self.auditoria.anotar("reloj_sin_medida", id=id)
            return
        if abs(desfase) > DESFASE_MAX_S:
            self._aviso_reloj = AVISO_RELOJ
            self._decir(AVISO_DESFASE.format(id=id, s=int(desfase)))
            self.auditoria.anotar("reloj_desfasado", id=id, desfase_s=int(desfase))
            return
        self._aviso_reloj = None
        if stop_activo(self.rutas):
            return self._fallar_aceptada(id, mid, "STOP activo", desenlace="stop")
        if p.tipo in _TOCA_META and self.almacen.leer_kv(CLAVE_TOKEN):
            return self._fallar_aceptada(id, mid, MOTIVO_TOKEN)
        try:
            vv = self._leer_vivo(p)
            obsoleta = self._obsoleta(p, vv)
        except Exception as e:  # noqa: BLE001 — cualquier fallo de lectura = no se ejecuta
            self._vigilar_token(e)
            return self._fallar_aceptada(id, mid, f"no se pudo leer Meta: {self._texto_error(e)}")
        if obsoleta:
            if self._transicion(id, "aceptada", "obsoleta", motivo=obsoleta):
                self._copiar(id, None, self._editar_desenlace(id, mid, Desenlace("obsoleta", ahora,
                                                                                  relectura=obsoleta)))
            return
        motivo = self._validar(p, vv)
        if motivo:
            return self._fallar_aceptada(id, mid, motivo)
        if not self._transicion(id, "aceptada", "ejecutando"):
            return  # otro ya la ejecuta o ejecutó: nunca hay segunda ejecución
        self._editar_desenlace(id, mid, Desenlace("ejecutando", ahora))
        try:
            r = ejecutar(p, GraphConStop(self.graph, self.rutas), self.almacen, self.auditoria, ahora=self.reloj)
        except Exception as e:  # noqa: BLE001 — ejecutar no debería lanzar; si lo hace, estado desconocido
            r = Resultado("discrepancia", f"error inesperado al ejecutar ({self._texto_error(e)}): puede "
                                          "haberse aplicado algo; revísalo en Ads Manager", error="otro")
        self._cerrar(id, r, mid)

    def _comprobar_cambio_limite(self, cambio: dict, p: Propuesta) -> None:
        self._recargar_limites()  # lo que hay en disco ahora, no lo de hace un ciclo
        if self._limites_error:
            raise ValueError(self._limites_error)
        actual = self._limite_actual(cambio["id"], cambio["clave"])
        if actual is None or actual != cambio["de"]:
            raise ValueError(f"el límite cambió desde la propuesta: {cambio['clave']} de {cambio['id']} vale "
                             f"{actual}, no {cambio['de']}")
        if "moneda" in cambio:
            lc = self.limites.cuentas[cambio["id"]]
            if cambio["moneda"] != lc.moneda_codigo:
                raise ValueError(f"moneda {cambio['moneda']} distinta de la de la cuenta ({lc.moneda_codigo})")

    @staticmethod
    def _valor_limite(lim: Limites, id: str, clave: str) -> object:
        if id == "global":
            return getattr(lim, clave, None)
        lc = lim.cuentas.get(id)
        return getattr(lc, clave, None) if lc is not None else None

    def _aplicar_cambio_limite(self, cambio: dict, cuenta: str | None) -> None:
        """Escribe ``cambio`` (``{clave, id: "global"|"act_…", de, a[, moneda, unidad]}``) en ``limites.yaml``.

        Antes de escribir: ``de`` debe ser el valor que hay ahora en el archivo, la ``moneda`` la de la
        cuenta, y nunca se cambia el ``offset``. Escribe un temporal 0600 en la misma carpeta, lo valida
        con ``cargar_limites`` (y que tenga el valor nuevo), hace ``fsync`` y ``os.replace``. Ante cualquier
        error lanza sin tocar el archivo (el resultado es ``fallida``).

        AVISO: el archivo se reescribe desde su contenido YAML, así que **los comentarios se pierden** (la
        plantilla del repo y ``/limites`` muestran qué significa cada clave)."""
        clave, id_, de, a = cambio["clave"], cambio["id"], cambio["de"], cambio["a"]
        if clave == "offset":
            raise ValueError("el offset no se cambia por /limites: lo fija el ejecutor con estado/meta.json")
        if type(a) is not int or a <= 0 or type(de) is not int:
            raise ValueError(f"{clave}: de y a deben ser enteros > 0")
        ruta = self.rutas.limites
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        if not isinstance(crudo, dict):
            raise TypeError("limites.yaml no es un mapa")
        if id_ == "global":
            if clave not in CLAVES_GLOBALES:
                raise ValueError(f"{clave} no es una clave global")
            seccion = crudo
        else:
            if clave not in CLAVES_CUENTA:
                raise ValueError(f"{clave} no es una clave de cuenta")
            seccion = crudo["cuentas"][id_]
            if not isinstance(seccion, dict) or seccion.get("moneda") != cambio.get("moneda"):
                raise ValueError(f"moneda {cambio.get('moneda')} distinta de la de la cuenta en limites.yaml")
        if type(seccion.get(clave)) is not int or seccion[clave] != de:
            raise ValueError(f"el límite cambió desde la propuesta: {clave} vale {seccion.get(clave)}, no {de}")
        seccion[clave] = a
        texto = yaml.safe_dump(crudo, sort_keys=False, allow_unicode=True)
        tmp = ruta.with_name(f".{ruta.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(texto)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            if self._valor_limite(cargar_limites(tmp), id_, clave) != a:
                raise ValueError("limites.yaml nuevo sin el valor pedido")
            os.replace(tmp, ruta)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        try:  # el cambio ya está hecho: un fallo aquí no lo deshace ni lo convierte en fallida
            dfd = os.open(ruta.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    def _escribir_limites_json(self) -> None:
        """``estado/limites.json`` (resolución 12): misma forma que ``limites.yaml``, sin páginas ni datasets."""
        if self._limites_error:
            return
        self.buzon.escribir_estado("limites", limites_a_dict(self.limites))
        self._limites_json_mtime = self._limites_mtime

    @staticmethod
    def _hay_creados(r: Resultado) -> bool:
        return bool(r.ids_creados) and any(bool(v) for v in r.ids_creados.values())

    def _cerrar(self, id: str, r: Resultado, mid: int | None) -> None:
        fila = self.almacen.obtener(id)
        if fila is None:
            return
        p, ahora = fila.propuesta, self.reloj()
        # ejecutando → {ejecutada, fallida, discrepancia}: una obsoleta de ejecutar() es una fallida.
        estado = r.estado if r.estado in ("ejecutada", "fallida", "discrepancia") else "fallida"
        detalle = r.detalle
        if r.cambio_limite is not None and estado == "ejecutada":
            try:
                self._comprobar_cambio_limite(r.cambio_limite, p)
                self._aplicar_cambio_limite(r.cambio_limite, p.cuenta)
                self._limites_mtime = None
                self._recargar_limites()
                c = r.cambio_limite
                self.auditoria.anotar(EV_LIMITE_CAMBIADO, clave=c["clave"], de=c["de"], a=c["a"], id=c["id"],
                                      propuesta=id)
                try:
                    self._escribir_limites_json()
                except Exception as e2:  # noqa: BLE001 — el cambio ya está en limites.yaml; el latido lo reintenta
                    self._limites_json_mtime = None
                    self._anotar_error("estado", e2)
            except Exception as e:  # noqa: BLE001 — sin escribir limites.yaml no hay cambio
                estado = "fallida"
                detalle = f"{detalle} | no se pudo escribir limites.yaml: {self._texto_error(e)}"
                self.auditoria.anotar(EV_EJECUCION, id=id, tipo=p.tipo, validate_only=False, ok=False,
                                      detalle=self._limpio(detalle)[:500])
        nueva_id: str | None = None
        aviso: str | None = None
        if r.nueva_propuesta is not None:
            try:
                nueva = cargar_propuesta(r.nueva_propuesta)
                self.almacen.registrar(nueva)
                self.auditoria.anotar(EV_RECIBIDA, id=nueva.id, tipo=nueva.tipo, origen=id)
                nueva_id = nueva.id
            except sqlite3.OperationalError:
                raise
            except Exception as e:  # noqa: BLE001
                aviso = f"no se pudo registrar la propuesta nueva: {self._texto_error(e)}; créala a mano"
        datos: dict[str, Any] = {"detalle": self._limpio(detalle)[:2000], "parcial": r.parcial}
        if r.error:
            datos["error"] = r.error
        if r.ids_creados:
            datos["ids_creados"] = r.ids_creados
        if r.reintentable_desde is not None:
            datos["reintentable_desde"] = r.reintentable_desde.isoformat()  # solo se guarda; nunca se reintenta
        if nueva_id:
            datos["nueva_propuesta"] = nueva_id
        if aviso:
            datos["aviso"] = aviso
        if estado != r.estado:
            datos["motivo"] = self._limpio(detalle)[:500]
        self._transicion(id, "ejecutando", estado, **datos)
        if r.error == "token":
            self.almacen.poner_kv(CLAVE_TOKEN, ahora.isoformat())
            self._decir(AVISO_TOKEN)
        final = self._editar_desenlace(id, mid, self._desenlace(estado, r, detalle, nueva_id, aviso, ahora))
        self._copiar(id, r, final)
        if nueva_id:
            try:
                self._despachar(nueva_id)
            except sqlite3.OperationalError:
                raise
            except Exception as e:  # noqa: BLE001
                self._anotar_error("despachar", e)

    def _desenlace(self, estado: str, r: Resultado, detalle: str, nueva_id: str | None, aviso: str | None,
                   ahora: datetime) -> Desenlace:
        lineas: tuple[str, ...] = ()
        if len(r.operaciones) > 1:
            lineas = tuple(f"{o.entidad_id} {o.campo}: {o.estado} ({o.antes} → {o.despues})" for o in r.operaciones)
        if aviso:
            lineas += (aviso,)
        if r.estado == "obsoleta":
            return Desenlace("obsoleta", ahora, relectura=detalle, lineas_lote=lineas)
        if estado == "ejecutada":
            leido = "; ".join(f"{o.entidad_id[-4:]} {o.campo} {o.despues}" for o in r.operaciones
                              if o.estado == "ejecutada")
            return Desenlace("ejecutada", ahora, relectura=leido or detalle, lineas_lote=lineas)
        if estado == "discrepancia":
            return Desenlace("discrepancia", ahora, relectura=detalle, nueva_propuesta=nueva_id, lineas_lote=lineas)
        aplicado = (r.parcial or self._hay_creados(r)
                    or any(o.estado in ("ejecutada", "discrepancia") for o in r.operaciones))
        return Desenlace("fallida", ahora, codigo=f"{r.error or 'otro'}: {detalle}", aplicado=aplicado,
                         lineas_lote=lineas)

    def _guardar_motivo(self, a: GuardarMotivo) -> None:
        m = a.motivo
        fila = self.almacen.obtener(m.id)
        if fila is None or fila.estado != "rechazada":
            self.auditoria.anotar(EV_MENSAJE_IGNORADO, motivo="motivo_sin_rechazo", id=m.id)
            return
        n = 1
        nota = nota_motivo(m, fila.propuesta, n)
        while self.rutas.vault is not None and self.copia.ocupada(nota.ruta_relativa):
            n += 1
            nota = nota_motivo(m, fila.propuesta, n)
        guardado = self.copia.motivo(nota)
        self.auditoria.anotar("motivo_rechazo", id=m.id, n=n, guardado=guardado)

    # -- Telegram -----------------------------------------------------------------------------------
    def atender_updates(self) -> int:
        updates = self.telegram.obtener_updates(self.almacen.ultimo_update() + 1, self.timeout_updates_s)
        emparejado, clave = self._emparejado(), self.secretos.hmac_clave or b""
        n = 0
        for u in updates:
            uid = u.get("update_id") if isinstance(u, dict) else None
            if type(uid) is not int:
                continue
            try:
                self._medir_desfase(u)
                accion = interpretar_update(u, emparejado, clave, self.reloj())
                manejador = self._DESPACHO.get(type(accion))
                if manejador is None:
                    raise TypeError(f"acción sin despacho: {type(accion).__name__}")
                manejador(accion)
            except sqlite3.OperationalError:
                raise
            except Exception as e:  # noqa: BLE001 — un update nunca tumba el ciclo
                self._anotar_error("update", e)
            self.almacen.marcar_update(uid)
            n += 1
        return n

    def _medir_desfase(self, u: dict) -> None:
        """Desfase del reloj con la hora de Telegram. Solo con ``message`` (su ``date`` es el instante del
        envío); la fecha de un ``callback_query`` es la del mensaje del bot, que puede tener horas."""
        m = u.get("message")
        fecha = m.get("date") if isinstance(m, dict) else None
        if type(fecha) is int and fecha > 0:
            self._anotar_desfase(self.reloj().timestamp() - fecha)

    def _ignorar(self, a: Ignorar) -> None:
        if a.motivo.startswith("callback_"):
            self.auditoria.anotar(EV_CALLBACK_INVALIDO, motivo=a.motivo)
        else:
            self.auditoria.anotar(EV_MENSAJE_IGNORADO, motivo=a.motivo)

    def _responder(self, a: Responder) -> None:
        self._decir(a.texto)

    def _responder_toque_invalido(self, a: ResponderToque) -> None:
        self._responder_toque(a.callback_id, a.texto)
        self.auditoria.anotar(EV_CALLBACK_INVALIDO, motivo=a.motivo)

    # -- comandos ------------------------------------------------------------------------------------
    def _hora(self) -> str:
        return self.reloj().astimezone(ZONA_COT).strftime("%H:%M")

    def _activar_stop(self, a: ActivarStop) -> None:
        """``/stop``: inmediato y sin botones (D-38). No pausa campañas."""
        if stop_activo(self.rutas):
            self._decir("STOP ya estaba activo")
            return
        activar_stop(self.rutas, "Telegram /stop", self.reloj())
        self.auditoria.anotar(EV_STOP, activo=True, motivo="Telegram /stop")
        self._decir(f"STOP activo desde {self._hora()}. No pausa campañas: para pausarlas, /reanudar y luego "
                    "/pausar_todo.")

    def _confirmar(self, a: Confirmar) -> None:
        if self._chat is None or not self.secretos.hmac_clave:
            return
        self._decir(a.texto, botones_propuesta(a.id, self._chat, self.secretos.hmac_clave))

    def _toque_interruptor(self, a: ToqueInterruptor) -> None:
        self._responder_toque(a.callback_id, RECIBIDO)
        if not self.almacen.consumir(a.id):  # un Q-/S- vale una sola vez, aunque siga en sus 10 min
            self.auditoria.anotar(EV_CALLBACK_INVALIDO, motivo="callback_confirmacion_usada", id=a.id)
            self._decir(CONFIRMACION_USADA)
            return
        original = CONFIRMAR_REANUDAR if not a.activar else "¿Activar el STOP?"
        if a.accion == "R":
            self._editar(a.message_id, f"{original}\n\nRECHAZADA {self._hora()}")
            return
        if a.activar:  # no debería llegar (/stop es inmediato): idempotente
            if not stop_activo(self.rutas):
                activar_stop(self.rutas, "Telegram (confirmación)", self.reloj())
                self.auditoria.anotar(EV_STOP, activo=True, motivo="Telegram (confirmación)")
            self._editar(a.message_id, f"{original}\n\nSTOP activo desde {self._hora()}")
            return
        quitado = quitar_stop(self.rutas)
        if quitado:
            self.auditoria.anotar(EV_STOP, activo=False, motivo="Telegram /reanudar")
        final = f"STOP quitado {self._hora()}" if quitado else "No había STOP activo"
        self._editar(a.message_id, f"{original}\n\n{final}")

    def _cuenta_corta(self, c: str) -> str:
        return f"…{c[-4:]}"

    def _pedir_estado(self, a: PedirEstado) -> None:
        gasto: dict[str, str] = {}
        for c in sorted(self.limites.cuentas_permitidas):
            lc = self.limites.cuentas.get(c)
            try:
                moneda = lc.moneda() if lc is not None else None
            except MonedaNoConfigurada:
                moneda = None
            if moneda is None:
                gasto[self._cuenta_corta(c)] = "sin configurar (P-21)"
                continue
            try:
                suma, _ = presupuestos_activos_cuenta(self.graph, c)
                gasto[self._cuenta_corta(c)] = formatear(suma, moneda)
            except Exception as e:  # noqa: BLE001
                self._vigilar_token(e)
                gasto[self._cuenta_corta(c)] = "no medido"
        pendientes = []
        for f in self.almacen.en_estado("recibida", "enviada", "aceptada"):
            try:
                cad = self._caduca(f)
            except Exception:  # noqa: BLE001
                cad = self.reloj()
            pendientes.append((f.id, f.tipo, cad))
        self._decir(render_estado(ResumenEstado(gasto_hoy=gasto, pendientes=pendientes,
                                                stop=stop_activo(self.rutas))))

    def _pedir_limites(self, a: PedirLimites) -> None:
        lim = self.limites
        lineas = [f"AVISO: {self._limites_error}"] if self._limites_error else []
        lineas.append("Límites del ejecutor:")
        lineas += [f"{k}: {getattr(lim, k)}" for k in sorted(CLAVES_GLOBALES)]
        for c, lc in sorted(lim.cuentas.items()):
            try:
                moneda = lc.moneda()
            except MonedaNoConfigurada:
                lineas.append(f"Cuenta {self._cuenta_corta(c)} ({lc.moneda_codigo}): sin configurar (P-21)")
                continue
            lineas.append(f"Cuenta {self._cuenta_corta(c)} ({lc.moneda_codigo}):")
            lineas += [f"{k}: {formatear(getattr(lc, k), moneda)}" for k in sorted(CLAVES_CUENTA)]
        self._decir("\n".join(lineas))

    def _monedas_vivas(self) -> dict[str, Moneda]:
        """Moneda leída en Meta por cuenta permitida (nunca la de limites.yaml): sin lectura, sin moneda."""
        monedas: dict[str, Moneda] = {}
        for c in sorted(self.limites.cuentas_permitidas):
            try:
                info = self.graph.cuenta(c)
                if info.offset is not None:
                    monedas[c] = Moneda(info.currency, info.offset)
            except Exception as e:  # noqa: BLE001
                self._vigilar_token(e)
        return monedas

    def _registrar_y_despachar(self, datos: dict) -> None:
        """Las propuestas nacidas en Telegram: un fallo al armarlas se responde (``ErrorComando``)."""
        try:
            p = cargar_propuesta(datos)
            self.almacen.registrar(p)
        except PropuestaInvalida as e:
            raise ErrorComando(f"no se pudo armar la propuesta: {self._limpio(e.motivo)[:300]}") from None
        except IdDuplicado:
            raise ErrorComando("id de propuesta ya usado: vuelve a intentarlo") from None
        self.auditoria.anotar(EV_RECIBIDA, id=p.id, tipo=p.tipo, origen=p.origen)
        self._despachar(p.id)

    def _nuevo_id(self) -> str:
        return nuevo_id_usuario(self.reloj(), existe=lambda i: self.almacen.obtener(i) is not None)

    def _pedir_cambio_limite(self, a: PedirCambioLimite) -> None:
        try:
            if self._limites_error:
                raise ErrorComando(self._limites_error)
            monedas = self._monedas_vivas() if a.clave in CLAVES_CUENTA else {}
            datos = construir_cambio_limite(a, self.limites, monedas, self._nuevo_id(), self.reloj())
            self._registrar_y_despachar(datos)
        except ErrorComando as e:
            self._decir(str(e))

    def _pedir_pausar_todo(self, a: PedirPausarTodo) -> None:
        """Un ``lote`` de ``pausar`` (prioridad alta) por cuenta con las campañas con ``status`` ACTIVE.

        Se lista sin filtro de estado en el servidor y se elige en local (no una lista blanca de Meta)."""
        creadas = 0
        for c in sorted(self.limites.cuentas_permitidas):
            try:
                filas = self.graph.listar(c, "campaigns", ["id", "status", "effective_status"])
            except Exception as e:  # noqa: BLE001
                self._vigilar_token(e)
                self._decir(f"No se pudo leer Meta para {self._cuenta_corta(c)}: {self._texto_error(e)}")
                continue
            ids = sorted({f["id"] for f in filas if isinstance(f, dict) and f.get("status") == "ACTIVE"
                          and isinstance(f.get("id"), str) and f["id"].isdigit()})
            for i in range(0, len(ids), 40):
                try:
                    datos = {"version": 1, "id": self._nuevo_id(), "tipo": "lote",
                             "creada": self.reloj().astimezone(ZONA_COT).isoformat(timespec="seconds"),
                             "origen": "telegram:/pausar_todo", "cuenta": c, "prioridad": "alta",
                             "motivo": "Pedido por el usuario en Telegram: pausar todas las campañas activas",
                             "operaciones": [{"entidad": "campaign", "id": x, "campo": "status",
                                              "de_esperado": "ACTIVE", "a": "PAUSED"} for x in ids[i:i + 40]]}
                    self._registrar_y_despachar(datos)
                    creadas += 1
                except ErrorComando as e:
                    self._decir(str(e))
                    return
        if creadas == 0:
            self._decir("No hay campañas activas")

    # -- recuperación tras reinicio ------------------------------------------------------------------
    def recuperar(self) -> None:
        """Solo al arrancar. Un reinicio nunca reenvía una escritura a Meta:

        - ``ejecutando`` (pudo llegar a Meta o no): solo se relee; nunca se reintenta (``_recuperar_ejecutando``).
        - ``aceptada`` caducada → ``fallida`` («caducó antes de ejecutarse»).
        - ``aceptada`` sin caducar → ``_ejecutar`` entero (desfase fresco, STOP, token, vivo, obsoleta, moneda,
          ``comprobar``): nunca llegó a Meta, porque ``ejecutando`` se marca antes de escribir.
        - ``recibida`` sin cola (caída a mitad del despacho) → se despacha otra vez desde el principio."""
        for fila in self.almacen.en_estado("ejecutando"):
            self._aislado("recuperar", self._recuperar_ejecutando, fila)
        for fila in self.almacen.en_estado("aceptada"):
            if self._caducada(fila):
                self._fallar_aceptada(fila.id, None, "caducó antes de ejecutarse")
            else:
                self._aislado("recuperar", self._ejecutar, fila.id, None)
        for fila in self.almacen.en_estado("recibida"):
            if not fila.datos.get("en_cola"):
                self._aislado("recuperar", self._despachar, fila.id)

    def _aislado(self, donde: str, fn: Callable[..., Any], *args: Any) -> None:
        """Un fallo en una fila (o en el latido, o en la copia al vault) no impide lo demás; SQLite roto o la
        auditoría corrupta sí paran el servicio (``servir`` sale con 1)."""
        try:
            fn(*args)
        except (sqlite3.OperationalError, AuditoriaCorrupta):
            raise
        except Exception as e:  # noqa: BLE001
            self._anotar_error(donde, e)

    def _recuperar_ejecutando(self, fila: FilaPropuesta) -> None:
        p, ahora = fila.propuesta, self.reloj()
        estado, detalle = self._veredicto_reinicio(fila)
        if not self._transicion(fila.id, "ejecutando", estado, detalle=self._limpio(detalle)[:2000],
                                motivo=self._limpio(detalle)[:500], tras_reinicio=True):
            return
        if estado == "ejecutada":
            d = Desenlace("ejecutada", ahora, relectura=detalle)
        elif estado == "discrepancia":
            d = Desenlace("discrepancia", ahora, relectura=detalle)
        else:
            d = Desenlace("fallida", ahora, codigo=detalle)
        self._copiar(fila.id, None, self._editar_desenlace(fila.id, None, d))
        if p.tipo == "limite_ejecutor" and estado == "ejecutada":
            try:
                self._escribir_limites_json()
            except Exception as e:  # noqa: BLE001
                self._anotar_error("estado", e)

    def _veredicto_reinicio(self, fila: FilaPropuesta) -> tuple[str, str]:
        """(estado, detalle) de una fila que quedó en ``ejecutando``. Ante la duda, ``discrepancia``."""
        p = fila.propuesta
        if p.tipo == "crear_estructura_pausada":
            return "discrepancia", "reinicio a mitad del montaje: puede haberse creado algo; revisa Ads Manager"
        if p.tipo in ("noop", "alerta"):
            return "fallida", "interrumpida por un reinicio; no se reintenta"
        if p.tipo == "limite_ejecutor":
            self._recargar_limites()
            hecho = not self._limites_error and all(
                self._limite_actual(op.id, op.campo) == op.a for op in p.operaciones)
            if hecho:
                return "ejecutada", "relectura tras reinicio: limites.yaml ya tiene el valor nuevo"
            return "fallida", "interrumpida por un reinicio; no se reintenta"
        try:
            vv = valores_vivos(p, self.graph, ahora=self.reloj)
            vivos = [(op, vv.valor(op)) for op in p.operaciones]
        except Exception as e:  # noqa: BLE001 — lectura imposible: nunca «no se cambió nada»
            self._vigilar_token(e)
            return "discrepancia", f"estado desconocido tras reinicio ({self._texto_error(e)}): revisa Ads Manager"
        resumen = "; ".join(f"{op.id} {op.campo}={v}" for op, v in vivos)
        if vivos and all(v == op.a for op, v in vivos):
            return "ejecutada", f"relectura tras reinicio: {resumen}"
        if vivos and all(v == op.de_esperado for op, v in vivos):
            return "fallida", f"interrumpida por un reinicio antes de llegar a Meta ({resumen}); no se reintenta"
        return "discrepancia", f"estado mezclado tras reinicio ({resumen}): revisa Ads Manager"

    # -- barrido -------------------------------------------------------------------------------------
    def barrer(self) -> None:
        """Caducidad (también de una ``aceptada`` que nunca llegó a ejecutarse), recordatorios de ``pausar``
        y cola (alertas cuando el ritmo lo permite; propuestas en resúmenes de ≤ 5)."""
        ahora = self.reloj()
        for fila in self.almacen.en_estado("recibida", "enviada", "aceptada"):
            try:
                self._barrer_una(fila, ahora)
            except sqlite3.OperationalError:
                raise
            except Exception as e:  # noqa: BLE001 — una fila nunca tumba el barrido
                self._anotar_error("barrer", e)
        try:
            self._enviar_cola(ahora)
        except sqlite3.OperationalError:
            raise
        except Exception as e:  # noqa: BLE001
            self._anotar_error("cola", e)

    def _barrer_una(self, fila: FilaPropuesta, ahora: datetime) -> None:
        try:
            vencida = self._caduca(fila) <= ahora
        except Exception:  # noqa: BLE001 — sin poder calcularla, caducada (falla cerrada)
            vencida = True
        if vencida:
            if fila.estado == "aceptada":
                return self._fallar_aceptada(fila.id, None, "caducó antes de ejecutarse")
            if self._transicion(fila.id, fila.estado, "caducada", motivo="caducó sin respuesta"):
                if fila.datos.get("resumen"):  # solo su bloque: sin un mensaje aparte por cada una
                    nueva = self.almacen.obtener(fila.id)
                    if nueva is not None:
                        self._reescribir_resumen(nueva)
                elif fila.message_id is not None:
                    self._editar_desenlace(fila.id, None, Desenlace("caducada", ahora))
                self._copiar(fila.id)
            return
        if fila.estado == "enviada" and fila.tipo == "pausar":
            self._recordar(fila, ahora)

    def _recordar(self, fila: FilaPropuesta, ahora: datetime) -> None:
        """Un ``pausar`` sin respuesta: a +1 h y +3 h se responde a su mensaje. Si el servicio estuvo parado
        y ya pasaron varios instantes, un solo mensaje los cubre. Se anota solo si se envió."""
        p = fila.propuesta
        hechos = {x for x in fila.datos.get("recordatorios") or [] if isinstance(x, str)}
        nuevos = {r.isoformat() for r in recordatorios(p, base_caducidad(p, fila.recibida), self._zona(p))
                  if r <= ahora} - hechos
        if not nuevos or self._chat is None or fila.message_id is None:
            return
        try:
            self._tg_enviar(self._chat, self._limpio(RECORDATORIO.format(id=fila.id)), None,
                            sonido=not en_silencio(ahora), responde_a=fila.message_id)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            return
        self._transicion(fila.id, "enviada", "enviada", recordatorios=sorted(hechos | nuevos))

    def _enviar_cola(self, ahora: datetime) -> None:
        cola = [f for f in self.almacen.en_estado("recibida") if f.datos.get("en_cola")]
        for f in cola:
            if f.tipo == "alerta":
                self._despachar_alerta(f)  # decide el ritmo, como al recibirla
        props = [f for f in cola if f.tipo != "alerta" and isinstance(f.datos.get("texto"), str)]
        chat, clave = self._chat, self.secretos.hmac_clave
        if not props or chat is None or not clave or stop_activo(self.rutas):
            return
        if not self.ritmo.toca_resumen(ahora, len(props)):
            return
        lote = props[:MAX_RESUMEN]
        texto, botones = render_resumen([self._item_resumen(f, "enviada") for f in lote], TITULO_RESUMEN, chat, clave)
        try:
            mid = self._tg_enviar(chat, self._limpio(texto), botones, sonido=True)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            return
        self.ritmo.anotar_envio(ahora)  # un resumen cuenta como un envío
        ids = [f.id for f in lote]
        for f in lote:
            self.almacen.guardar_mensaje(f.id, chat, mid)
            self._transicion(f.id, "recibida", "enviada", en_cola=False, resumen=True, resumen_ids=ids,
                             enviada_en=ahora.isoformat())

    # -- latido y archivos de estado (resolución 12) -------------------------------------------------
    def latir(self) -> None:
        """Como mucho cada 30 s escribe ``estado/{latido,stop,emparejamiento}.json`` y, si cambió el ``mtime``
        de ``limites.yaml``, ``estado/limites.json``. Con el token marcado como caducado, ``comprobar_meta``
        (al arrancar y luego como mucho cada 10 min). Un fallo al escribir nunca tumba el ciclo."""
        ahora = self.reloj()
        self._aislado("token", self._vigilar_renovacion, ahora)
        if self._ultimo_latido is not None and abs(ahora - self._ultimo_latido) < INTERVALO_LATIDO:
            return
        self._ultimo_latido = ahora
        self._aislado("estado", self._escribir_estados, ahora)

    def _escribir_estados(self, ahora: datetime) -> None:
        stop = self._estado_stop()
        desfase = self._desfase_fresco()
        avisos: list[str] = []
        if self._limites_error:
            avisos.append(self._limites_error)
        if self._aviso_reloj or (desfase is not None and abs(desfase) > DESFASE_MAX_S):
            avisos.append(AVISO_RELOJ)
        if self.almacen.leer_kv(CLAVE_TOKEN):
            avisos.append(MOTIVO_TOKEN)
        if self.rutas.vault is None:
            avisos.append("sin vault configurado: no se copian resultados")
        vault = self.copia.estado() if self.rutas.vault is not None else "no escribible"
        self.buzon.escribir_estado("latido", {
            "fecha": ahora.isoformat(), "version": VERSION, "modo": self.modo, "stop": stop["activo"],
            "telegram": self._telegram_estado,
            "pendientes": len(self.almacen.en_estado("recibida", "enviada", "aceptada")),
            "reloj_desfase_s": None if desfase is None else round(desfase, 1), "vault": vault,
            "avisos": [self._limpio(a)[:300] for a in avisos]})
        self.buzon.escribir_estado("stop", stop)
        self.buzon.escribir_estado("emparejamiento", {"emparejado": self._emparejado() is not None,
                                                      "fecha": ahora.isoformat()})
        if self._limites_json_mtime is None or self._limites_json_mtime != self._limites_mtime:
            self._escribir_limites_json()

    def _estado_stop(self) -> dict:
        if not stop_activo(self.rutas):
            return {"activo": False, "motivo": None, "fecha": None}
        motivo = fecha = None
        try:
            d = json.loads(self.rutas.stop.read_text(encoding="utf-8"))
            motivo = self._limpio(d["motivo"])[:200] if isinstance(d.get("motivo"), str) else None
            fecha = d["desde"] if isinstance(d.get("desde"), str) else None
        except (OSError, ValueError, AttributeError, KeyError):
            pass  # un STOP vacío o ilegible sigue siendo STOP
        return {"activo": True, "motivo": motivo, "fecha": fecha}

    def _vigilar_renovacion(self, ahora: datetime) -> None:
        """Con el token marcado: una comprobación al arrancar (si ya lo estaba) y luego como mucho cada
        10 min. Si se marca con el servicio en marcha, la primera llega a los 10 min (no al ciclo siguiente)."""
        if not self.almacen.leer_kv(CLAVE_TOKEN):
            self._ultima_comprobacion_meta = None
            self._token_al_arrancar = False
            return
        if self._ultima_comprobacion_meta is None and not self._token_al_arrancar:
            self._ultima_comprobacion_meta = ahora
            return
        if self._ultima_comprobacion_meta is not None and abs(ahora - self._ultima_comprobacion_meta) < INTERVALO_META:
            return
        self._token_al_arrancar = False
        self._ultima_comprobacion_meta = ahora
        self.comprobar_meta()

    def comprobar_meta(self) -> bool:
        """``comprobar_meta`` de cada cuenta permitida (lecturas y un ``validate_only``, por ``GraphConStop``)
        y ``estado/meta.json`` con la primera. Si todas dan ok y el token estaba marcado, se desmarca."""
        informes = [comprobar_meta(GraphConStop(self.graph, self.rutas), c, ahora=self.reloj)
                    for c in sorted(self.limites.cuentas_permitidas)]
        if informes:
            try:
                self.buzon.escribir_estado("meta", informe_a_dict(informes[0]))
            except Exception as e:  # noqa: BLE001
                self._anotar_error("estado", e)
        ok = bool(informes) and all(i.ok for i in informes)
        if ok and self.almacen.leer_kv(CLAVE_TOKEN):
            self.almacen.borrar_kv(CLAVE_TOKEN)
            self.auditoria.anotar("token_renovado")
            self._decir(AVISO_TOKEN_RENOVADO)
        return ok

    def _copiar_auditoria(self) -> None:
        """Copia la auditoría del día al vault como mucho cada minuto (lee el archivo entero) y, al cambiar
        de día, cierra la copia del día anterior."""
        ahora = self.reloj()
        hoy = ahora.astimezone(ZONA_COT).date()
        if (self._auditoria_copiada is not None and self._dia_auditoria == hoy
                and abs(ahora - self._auditoria_copiada) < INTERVALO_COPIA_AUDITORIA):
            return
        if self._dia_auditoria is not None and self._dia_auditoria != hoy:
            self.copia.auditoria(self.rutas.auditoria, self._dia_auditoria)
        self.copia.auditoria(self.rutas.auditoria, hoy)
        self._auditoria_copiada, self._dia_auditoria = ahora, hoy

    # -- ciclo ----------------------------------------------------------------------------------------
    def ciclo(self) -> None:
        """``latir`` → ``ingerir`` → ``atender_updates`` → ``barrer`` → copia al vault (pendientes y auditoría).

        Sin red con Telegram (o un error de la API al leer updates): ``telegram: "sin red"`` en el latido y
        espera ``espera_red_s`` (interrumpible con ``parar``); el barrido sigue (caducar es local)."""
        self._recargar_limites()
        self.latir()
        self.ingerir()
        try:
            self.atender_updates()
            self._telegram_estado = "ok"
        except (ErrorRedTelegram, ErrorTelegram):
            self._telegram_estado = "sin red"
            self.parar.wait(self.espera_red_s)
        self.barrer()
        self._aislado("vault", self.copia.reintentar)
        self._aislado("vault", self._copiar_auditoria)


# -- servir ---------------------------------------------------------------------------------------------
def _decir_err(texto: str) -> None:
    print(redactar(texto), file=sys.stderr)


def _preparar_spool(spool: Path) -> None:
    """``estado/`` y ``procesadas/`` se crean (si faltan) con 2750 y setgid (nota 09·T9): los archivos de
    estado son 0640 y Claude los lee por el grupo. Los dueños los pone el instalador, nunca este proceso."""
    for nombre in ("estado", "procesadas"):
        d = spool / nombre
        if not d.exists():
            d.mkdir(parents=True)
            os.chmod(d, 0o2750)


def _instalar_senales(parar: threading.Event) -> dict:
    if threading.current_thread() is not threading.main_thread():
        return {}
    previos = {}
    for s in (signal.SIGTERM, signal.SIGINT):
        previos[s] = signal.signal(s, lambda *_: parar.set())
    return previos


def servir(rutas: RutasEjecutor | None = None, *, graph_simulado: bool = False,
           parar: threading.Event | None = None, fabrica: Callable[[Secretos], tuple[Any, Any]] | None = None,
           reloj: Callable[[], datetime] | None = None) -> int:
    """Proceso del servicio. Devuelve el código de salida:

    0 parado con ``parar``/SIGTERM/SIGINT · 1 SQLite roto (``OperationalError``) o auditoría corrupta: se
    detiene sin ejecutar nada · 2 tzdata, secretos, ``limites.yaml`` o clientes no válidos · 3 otro ejecutor
    con el candado · 4 Telegram sin emparejar.

    Orden: tzdata → candado → secretos → límites → emparejamiento → ``recuperar()`` → bucle de ``ciclo()``.
    ``fabrica(secretos) -> (telegram, graph)`` y ``reloj`` permiten inyectar clientes y hora en las pruebas.

    SIGTERM/SIGINT solo marcan ``parar``: el ciclo en curso termina entero (nunca se corta una ejecución a
    medias) y luego se sale. Peor caso hasta atender un ``/stop`` o salir tras SIGTERM: un ``getUpdates``
    de ``TIMEOUT_UPDATES_S`` (10 s) + 10 s de margen de red; con 429 de Telegram el cliente duerme hasta
    3×60 s antes de devolver el control (≈ 200 s). El STOP por archivo (``trovefy-ejecutor stop``) no
    depende de Telegram: se mira justo antes de cada escritura en Meta (``GraphConStop``)."""
    rutas = rutas or rutas_por_defecto()
    parar = parar or threading.Event()
    try:
        ZoneInfo(ZONA_POR_DEFECTO)
    except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError, OSError…
        _decir_err("Falta tzdata (zona America/Bogota): instala el paquete tzdata y vuelve a arrancar")
        return 2
    try:
        rutas.base.parent.mkdir(parents=True, exist_ok=True)
        _preparar_spool(rutas.spool)
    except OSError as e:
        _decir_err(f"No se pueden preparar las carpetas del ejecutor: {e}")
        return 2
    try:
        with candado(rutas.base.with_suffix(".lock")):
            return _servir_con_candado(rutas, graph_simulado, parar, fabrica, reloj)
    except OtroEjecutorActivo:
        _decir_err(MENSAJE_OTRO)
        return 3


def _servir_con_candado(rutas: RutasEjecutor, graph_simulado: bool, parar: threading.Event,
                        fabrica: Callable[[Secretos], tuple[Any, Any]] | None,
                        reloj: Callable[[], datetime] | None) -> int:
    try:
        secretos = cargar_secretos(rutas.secretos)
    except SecretosInseguros as e:
        _decir_err(f"Secretos inseguros: {e}")
        return 2
    except (OSError, ValueError) as e:
        _decir_err(f"No se pueden leer los secretos ({type(e).__name__}): {e}")
        return 2
    try:
        cargar_limites(rutas.limites)
    except Exception as e:  # noqa: BLE001 — LimitesInvalidos u otro: no se arranca
        _decir_err(f"limites.yaml no válido: {e}")
        return 2
    if secretos.telegram_chat_id is None or secretos.telegram_user_id is None:
        _decir_err("Telegram sin emparejar: ejecuta `trovefy-ejecutor emparejar`")
        return 4
    if not secretos.hmac_clave or not secretos.telegram_bot_token:
        _decir_err("Faltan HMAC_CLAVE o TELEGRAM_BOT_TOKEN en secretos.env")
        return 2
    try:
        if fabrica is not None:
            telegram, graph = fabrica(secretos)
        else:
            if not graph_simulado and not secretos.meta_token:
                _decir_err("Falta META_TOKEN en secretos.env (paso 13 de /arranque)")
                return 2
            telegram = ClienteTelegram(secretos.telegram_bot_token)
            graph = GraphSimulado() if graph_simulado else ClienteGraph(secretos.meta_token)
    except Exception as e:  # noqa: BLE001 — el texto podría llevar un token: solo el tipo
        _decir_err(f"No se pudieron crear los clientes de Telegram/Meta ({type(e).__name__})")
        return 2
    previos = _instalar_senales(parar)
    ej: Ejecutor | None = None
    try:
        ej = Ejecutor(rutas, telegram, graph, secretos, reloj=reloj or (lambda: datetime.now(UTC)),
                      modo="simulado" if graph_simulado else "real")
        ej.parar = parar
        ej.recuperar()
        while not parar.is_set():
            try:
                ej.ciclo()
            except (sqlite3.OperationalError, AuditoriaCorrupta):
                raise
            except Exception as e:  # noqa: BLE001 — un fallo inesperado no para el /stop ni el barrido
                _decir_err(f"Error en el ciclo ({type(e).__name__}): {ej._texto_error(e)}")
                ej._anotar_error("ciclo", e)
                parar.wait(ej.espera_red_s)
        return 0
    except sqlite3.OperationalError as e:
        _decir_err(f"SQLite no disponible ({e}): el ejecutor se detiene sin ejecutar nada")
        return 1
    except AuditoriaCorrupta as e:
        _decir_err(f"Auditoría corrupta ({e}): para el servicio y repárala con `trovefy-ejecutor auditoria "
                   "reparar`; no se ejecuta nada")
        return 1
    except LimitesInvalidos as e:
        _decir_err(f"limites.yaml no válido: {e}")
        return 2
    finally:
        for s, h in previos.items():
            signal.signal(s, h)
        if ej is not None:
            with contextlib.suppress(Exception):
                ej.almacen.cerrar()
