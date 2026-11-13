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

import os
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .auditoria import (
    EV_CALLBACK_INVALIDO,
    EV_MENSAJE_IGNORADO,
    EV_RECIBIDA,
    EV_TRANSICION,
    EV_VALIDACION_RECHAZADA,
    Auditoria,
    redactar,
)
from .buzon import Buzon
from .comandos import Ignorar, Responder, interpretar_update
from .config import RutasEjecutor
from .deposito import DepositoRechazado, comprobar_origen
from .dinero import Moneda, MonedaNoConfigurada
from .ejecutar import NO_SOPORTADO_P07, TIPOS_SOPORTADOS
from .emparejar import Emparejamiento
from .esquema import RANGO_CLAUDE, PropuestaInvalida, cargar_propuesta
from .estado import Almacen, FilaPropuesta, IdDuplicado
from .graph import OFFSETS_META, DetenidoPorStop
from .limites import (
    CLAVES_CUENTA,
    CLAVES_GLOBALES,
    ContextoVivo,
    Limites,
    cargar_limites,
    comprobar,
    contexto_para,
)
from .modelo import Propuesta
from .reloj import base_caducidad, caducidad
from .render import DatosRender, botones_propuesta, render_alerta, render_propuesta
from .ritmo import Ritmo
from .secretos import Secretos
from .stop import stop_activo
from .telegram import Boton, ErrorRedTelegram, ErrorTelegram
from .vault_copia import CopiaVault
from .vivo import ValoresVivos, valores_vivos

TIPOS_INGERIBLES: frozenset[str] = TIPOS_SOPORTADOS | {"crear_estructura_pausada"}
ZONA_POR_DEFECTO = "America/Bogota"
_SIN_LECTURA_VIVA = frozenset({"noop", "limite_ejecutor"})
_ERRORES_TELEGRAM = (ErrorTelegram, ErrorRedTelegram, ValueError)


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
        self.desfase_s: float | None = None
        self._DESPACHO: dict[type, Callable[[Any], None]] = {
            Ignorar: self._ignorar,
            Responder: self._responder,
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

    def _decir(self, texto: str, botones: list[list[Boton]] | None = None, *, sonido: bool = True) -> int | None:
        """Envía un mensaje al chat emparejado; un fallo de Telegram se audita y devuelve None."""
        if self._chat is None:
            return None
        try:
            return self.telegram.enviar(self._chat, self._limpio(texto), botones, sonido=sonido)
        except _ERRORES_TELEGRAM as e:
            self._anotar_error("telegram", e)
            return None

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
                self.copia.resultado(fila, r, t if isinstance(t, str) else f"{fila.id} · {fila.tipo}")
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
        self.auditoria.anotar(EV_RECIBIDA, id=p.id, tipo=p.tipo)
        self.buzon.procesar(ruta, {"estado": "recibida", "motivo": None})
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
            for op in p.operaciones:
                if op.campo == "daily_budget" and op.id in sim and isinstance(op.a, int):
                    sim[op.id] = op.a
                elif op.campo == "status" and op.a == "PAUSED":
                    sim.pop(op.id, None)
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
            return self._rechazar_recibida(id, f"no se pudo leer Meta: {self._texto_error(e)}")
        if obsoleta:
            if self._transicion(id, "recibida", "obsoleta", motivo=obsoleta):
                self._copiar(id)
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
            mid = self.telegram.enviar(chat, self._limpio(texto), botones_propuesta(id, chat, clave),
                                       sonido=decision.sonido)
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
        texto = render_alerta(p)
        try:
            mid = self.telegram.enviar(self._chat, self._limpio(texto), None, sonido=decision.sonido)
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
        self._rechazar_recibida(fila.id, "montaje aún no disponible")

    # -- Telegram -----------------------------------------------------------------------------------
    def atender_updates(self) -> int:
        updates = self.telegram.obtener_updates(self.almacen.ultimo_update() + 1, 25)
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
            self.desfase_s = self.reloj().timestamp() - fecha

    def _ignorar(self, a: Ignorar) -> None:
        if a.motivo.startswith("callback_"):
            self.auditoria.anotar(EV_CALLBACK_INVALIDO, motivo=a.motivo)
        else:
            self.auditoria.anotar(EV_MENSAJE_IGNORADO, motivo=a.motivo)

    def _responder(self, a: Responder) -> None:
        self._decir(a.texto)

    # -- ciclo ----------------------------------------------------------------------------------------
    def ciclo(self) -> None:
        """Provisional (Tarea 5 añade latido, barrido y copia de la auditoría)."""
        self._recargar_limites()
        self.ingerir()
        self.atender_updates()
