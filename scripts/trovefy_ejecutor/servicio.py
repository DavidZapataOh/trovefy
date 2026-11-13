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

import json
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

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
    redactar,
)
from .buzon import Buzon
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
from .config import RutasEjecutor
from .deposito import DepositoRechazado, comprobar_origen
from .dinero import Moneda, MonedaNoConfigurada, formatear
from .ejecutar import NO_SOPORTADO_P07, TIPOS_SOPORTADOS, Resultado, ejecutar
from .emparejar import Emparejamiento
from .esquema import RANGO_CLAUDE, PropuestaInvalida, cargar_propuesta
from .estado import Almacen, FilaPropuesta, IdDuplicado
from .graph import OFFSETS_META, DetenidoPorStop, ErrorGraph, clasificar
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
from .secretos import Secretos
from .stop import activar_stop, quitar_stop, stop_activo
from .telegram import Boton, ErrorRedTelegram, ErrorTelegram
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
        self._desfase_medido: datetime | None = None
        self._aviso_reloj: str | None = None
        self._cargar_desfase()
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
        actual = self._limite_actual(cambio["id"], cambio["clave"])
        if actual is None or actual != cambio["de"]:
            raise ValueError(f"{cambio['clave']} de {cambio['id']} vale {actual}, no {cambio['de']}")
        if "moneda" in cambio:
            lc = self.limites.cuentas[cambio["id"]]
            if cambio["moneda"] != lc.moneda_codigo:
                raise ValueError(f"moneda {cambio['moneda']} distinta de la de la cuenta ({lc.moneda_codigo})")

    def _aplicar_cambio_limite(self, cambio: dict, cuenta: str | None) -> None:
        """Escribe ``limites.yaml`` (Tarea 5). Hasta entonces falla cerrado: el resultado es ``fallida``."""
        raise NotImplementedError("escritura de limites.yaml pendiente (Tarea 5)")

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

    # -- ciclo ----------------------------------------------------------------------------------------
    def ciclo(self) -> None:
        """Provisional (Tarea 5 añade latido y copia de la auditoría)."""
        self._recargar_limites()
        self.ingerir()
        self.atender_updates()
        self.barrer()
