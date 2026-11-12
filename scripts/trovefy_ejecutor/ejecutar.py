"""Ejecución de propuestas de una o varias operaciones sobre Meta (§5.5, §5.10; resoluciones 9, 11 y 13).

Por cada operación: forma → lectura viva → moneda → precondición → ``validate_only`` → **una** escritura
real → relectura nueva a Graph. Las escrituras nunca se reintentan: tras un fallo de red después de
enviar se relee y se decide con lo leído; si tampoco se puede releer, ``discrepancia`` (estado
desconocido). Ante cualquier duda, falla cerrado y no escribe.

No mira STOP ni límites ni hace transiciones (resolución 9): eso lo hace el servicio (plan 12) antes
y después. Solo reacciona a ``DetenidoPorStop`` del cliente (resolución 11).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from trovefy_ejecutor.auditoria import EV_EJECUCION, Auditoria, redactar
from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.graph import DetenidoPorStop, ErrorGraph, ErrorRed, clasificar
from trovefy_ejecutor.modelo import Operacion, Propuesta
from trovefy_ejecutor.vivo import (
    CAMPOS_IMPORTE,
    EntidadAjena,
    LecturaIncompleta,
    ValoresVivos,
    valores_vivos,
)

EstadoOp = Literal["ejecutada", "fallida", "discrepancia", "no_intentada"]
EstadoRes = Literal["ejecutada", "fallida", "discrepancia", "obsoleta"]

_ESTADOS = frozenset({"campaign", "adset", "ad"})
CAMPOS_POR_TIPO: dict[str, set[tuple[str, str]]] = {
    "presupuesto": {(e, c) for e in ("adset", "campaign") for c in ("daily_budget", "lifetime_budget")},
    "puja": {("adset", "bid_amount")},
    "spend_cap": {("campaign", "spend_cap")},
    "limite_cuenta": {("account", "spend_cap")},
    "pausar": {(e, "status") for e in _ESTADOS},
    "activar": {(e, "status") for e in _ESTADOS},
}
_STATUS_POR_TIPO = {"pausar": "PAUSED", "activar": "ACTIVE"}
# Campo de la regla de cadencia (limites) que cuenta cada cambio. status y spend_cap no tienen regla.
CAMPO_CADENCIA = {"daily_budget": "daily_budget", "lifetime_budget": "daily_budget", "bid_amount": "bid_amount"}

ZONA_IDS = "America/Bogota"
_EMITIDOS: set[str] = set()
ORIGEN = "trovefy-ejecutor"
_ESPERA_LIMITE_META = timedelta(hours=1)
_SIN_NUMERO = "sin número libre 800–899 hoy: crea la propuesta a mano"


@dataclass(frozen=True)
class ResultadoOp:
    entidad_id: str
    campo: str
    estado: EstadoOp
    antes: object
    pedido: object
    despues: object | None
    detalle: str
    # (extra) clasificación del error de esta operación y si Meta la dejó en PAUSED sin pedirlo.
    error: str | None = None
    pausada_sin_pedir: bool = False


@dataclass(frozen=True)
class Resultado:
    estado: EstadoRes
    detalle: str
    operaciones: tuple[ResultadoOp, ...] = ()
    parcial: bool = False
    nueva_propuesta: dict | None = None
    cambio_limite: dict | None = None
    error: str | None = None
    reintentable_desde: datetime | None = None
    ids_creados: dict | None = None


def _ahora() -> datetime:
    return datetime.now(UTC)


# -- ids 800–899 ---------------------------------------------------------------------------
def siguiente_id(almacen: Almacen, ahora: datetime) -> str | None:
    """Primer ``P-AAAAMMDD-8NN`` libre del día de la cuenta (``ZONA_IDS``), o ``None`` si no queda."""
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=UTC)
    dia = ahora.astimezone(ZoneInfo(ZONA_IDS)).strftime("%Y%m%d")
    for n in range(800, 900):
        candidato = f"P-{dia}-{n}"
        if candidato in _EMITIDOS or almacen.obtener(candidato) is not None:
            continue
        _EMITIDOS.add(candidato)
        return candidato
    return None


# -- utilidades ----------------------------------------------------------------------------
def _texto_error(e: BaseException) -> str:
    """Nunca ``repr``: ``ErrorGraph``/``ErrorRed`` ya llevan texto redactado; el resto, solo su clase."""
    if isinstance(e, ErrorGraph):
        return str(e)
    if isinstance(e, ErrorRed):
        return f"red: {e.motivo}"
    if isinstance(e, LecturaIncompleta):
        return redactar(str(e))[:300]
    return type(e).__name__


def _anotar(auditoria: Auditoria, p: Propuesta, validate_only: bool, ok: bool, detalle: str) -> bool:
    try:
        auditoria.anotar(EV_EJECUCION, id=p.id, tipo=p.tipo, validate_only=validate_only, ok=ok,
                         detalle=redactar(detalle))
        return True
    except Exception:  # noqa: BLE001 — la auditoría rota no debe tumbar una ejecución ya hecha
        return False


def _es_importe_valido(v: object) -> bool:
    return type(v) is int and v > 0


def _desc(op: Operacion) -> str:
    return f"{op.entidad} {op.id} {op.campo}"


def _forma(p: Propuesta, op: Operacion) -> str | None:
    if (op.entidad, op.campo) not in CAMPOS_POR_TIPO[p.tipo]:
        return f"{_desc(op)}: campo no permitido en {p.tipo}"
    if op.a == "ACTIVE" and p.tipo != "activar":
        return f"{_desc(op)}: ACTIVE solo en propuestas activar"
    if op.campo == "status":
        if op.a != _STATUS_POR_TIPO[p.tipo]:
            return f"{_desc(op)}: {p.tipo} solo pide status {_STATUS_POR_TIPO[p.tipo]}"
    elif op.campo in CAMPOS_IMPORTE:
        if not _es_importe_valido(op.a):
            return f"{_desc(op)}: el importe debe ser un entero > 0"
        if op.unidad != "minima":
            return f"{_desc(op)}: unidad debe ser \"minima\""
    else:
        return f"{_desc(op)}: campo no soportado"
    return None


def _normal(campo: str, v: object) -> object:
    """Normaliza como ``vivo``: importes a ``int`` (o ``None`` si no es entero decimal)."""
    if v is None:
        return None
    if campo in CAMPOS_IMPORTE:
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        s = str(v)
        return int(s) if s.lstrip("-").isdigit() else None
    return v if isinstance(v, str) else str(v)


def _no_intentadas(ops, vv: ValoresVivos | None, detalle: str) -> tuple[ResultadoOp, ...]:
    return tuple(ResultadoOp(op.id, op.campo, "no_intentada", None if vv is None else vv.valor(op), op.a, None,
                             detalle) for op in ops)


# -- una operación -------------------------------------------------------------------------
def _releer(graph, op: Operacion) -> dict:
    campos = [op.campo] if op.entidad == "account" else list(dict.fromkeys(["status", "effective_status", op.campo]))
    crudo = graph.leer(op.id, campos)
    if not isinstance(crudo, dict):
        raise ErrorRed("respuesta ilegible")
    return crudo


def _ejecutar_op(op: Operacion, p: Propuesta, vv: ValoresVivos, graph, almacen: Almacen, auditoria: Auditoria,
                 ahora: Callable[[], datetime]) -> ResultadoOp:
    """Valida, escribe una sola vez y relee. Nunca reenvía una escritura real ni deja escapar errores
    de Graph: el resultado lo dice ``ResultadoOp.estado``. ``no_intentada`` = STOP (quien llama para)."""
    antes = vv.valor(op)
    desc = f"{_desc(op)}: antes {antes}, pedido {op.a}"

    def r(estado: EstadoOp, detalle: str, despues: object = None, error: str | None = None,
          pausada: bool = False) -> ResultadoOp:
        return ResultadoOp(op.id, op.campo, estado, antes, op.a, despues, f"{desc}; {detalle}", error, pausada)

    # 1) validate_only
    try:
        graph.escribir(op.id, {op.campo: op.a}, validate_only=True)
    except DetenidoPorStop:
        return r("no_intentada", "STOP: no se intentó", error="stop")
    except ErrorGraph as e:
        _anotar(auditoria, p, True, False, f"{desc}; {_texto_error(e)}")
        return r("fallida", f"validate_only rechazado: {_texto_error(e)}", error=clasificar(e))
    except ErrorRed as e:
        _anotar(auditoria, p, True, False, f"{desc}; {_texto_error(e)}")
        return r("fallida", f"validate_only sin respuesta ({e.motivo}): no se escribió", error="red")
    except Exception as e:  # noqa: BLE001 — falla cerrado sin escribir
        _anotar(auditoria, p, True, False, f"{desc}; {_texto_error(e)}")
        return r("fallida", f"validate_only falló ({_texto_error(e)}): no se escribió", error="otro")
    if not _anotar(auditoria, p, True, True, f"{desc}; validate_only ok"):
        return r("fallida", "auditoría no disponible: no se escribe", error="otro")

    # 2) escritura real: exactamente una, pase lo que pase
    perdida: str | None = None
    try:
        graph.escribir(op.id, {op.campo: op.a})
    except DetenidoPorStop:
        return r("no_intentada", "STOP: no se intentó", error="stop")
    except ErrorGraph as e:
        _anotar(auditoria, p, False, False, f"{desc}; {_texto_error(e)}")
        return r("fallida", f"Meta rechazó la escritura: {_texto_error(e)}", error=clasificar(e))
    except ErrorRed as e:
        perdida = e.motivo
        _anotar(auditoria, p, False, False, f"{desc}; red tras enviar ({e.motivo}): se relee")
    except Exception as e:  # noqa: BLE001 — no se sabe si salió: se relee, nunca se reenvía
        perdida = _texto_error(e)
        _anotar(auditoria, p, False, False, f"{desc}; fallo tras enviar ({perdida}): se relee")
    else:
        _anotar(auditoria, p, False, True, f"{desc}; enviada")

    # 3) relectura nueva (no reutiliza vv)
    try:
        crudo = _releer(graph, op)
    except Exception as e:  # noqa: BLE001
        _cadencia(almacen, op, ahora)  # pudo cambiar: cuenta para la cadencia (lado seguro)
        return r("discrepancia", f"estado desconocido: no se pudo releer ({_texto_error(e)})")
    despues = _normal(op.campo, crudo.get(op.campo))
    status_antes = vv.status(op.id)
    status_despues = crudo.get("status")
    pausada = (op.entidad in _ESTADOS and op.campo != "status" and status_antes == "ACTIVE"
               and status_despues == "PAUSED")
    if despues != antes:
        _cadencia(almacen, op, ahora)
    esperado = _normal(op.campo, op.de_esperado)
    if despues == op.a and not pausada:
        nota = f"respuesta perdida ({perdida}); la relectura confirma" if perdida else "la relectura confirma"
        return r("ejecutada", f"después {despues}; {nota}", despues)
    if perdida and despues == esperado and not pausada:
        return r("fallida", f"red tras enviar ({perdida}); la relectura dice {despues}: no se aplicó", despues,
                 error="red")
    if pausada:
        return r("discrepancia", f"después {despues}; Meta dejó la entidad en PAUSED sin pedirlo", despues,
                 pausada=True)
    return r("discrepancia", f"después {despues}: no es lo pedido", despues)


def _cadencia(almacen: Almacen, op: Operacion, ahora: Callable[[], datetime]) -> None:
    campo = CAMPO_CADENCIA.get(op.campo)
    if campo is None:
        return
    try:
        almacen.registrar_cambio(op.id, campo, ahora())
    except Exception:  # noqa: BLE001, S110 — la escritura ya está hecha; no se pierde el resultado
        pass


# -- Reactivar -----------------------------------------------------------------------------
def _reactivar(p: Propuesta, ops: list[ResultadoOp], tipos: dict[str, str], almacen: Almacen,
               ahora: Callable[[], datetime]) -> tuple[dict | None, str | None]:
    momento = ahora()
    nuevo_id = siguiente_id(almacen, momento)
    if nuevo_id is None:
        return None, _SIN_NUMERO
    datos: dict = {
        "version": 1, "id": nuevo_id, "tipo": "activar", "creada": momento.isoformat(), "origen": ORIGEN,
        "cuenta": p.cuenta,
        "operaciones": [{"entidad": tipos[o.entidad_id], "id": o.entidad_id, "campo": "status",
                         "de_esperado": "PAUSED", "a": "ACTIVE"} for o in ops],
        "motivo": f"Meta la dejó en PAUSED tras {p.tipo} de {p.id} (status_forced_to_paused)",
    }
    if p.producto is not None:
        datos["producto"] = p.producto
    if p.pais is not None:
        datos["pais"] = p.pais
    try:
        cargar_propuesta(datos)
    except PropuestaInvalida as e:
        return None, f"no se pudo preparar la propuesta de reactivar ({e.motivo}): crea la propuesta a mano"
    return datos, None


# -- propuesta -----------------------------------------------------------------------------
def _rechazo(p: Propuesta, auditoria: Auditoria, detalle: str, *, estado: EstadoRes = "fallida",
             error: str | None = "otro", vv: ValoresVivos | None = None,
             ahora: Callable[[], datetime] = _ahora) -> Resultado:
    """Sin escribir nada: un único ``ejecucion`` con validate_only=False, ok=False."""
    _anotar(auditoria, p, False, False, detalle)
    desde = ahora() + _ESPERA_LIMITE_META if error == "limite_meta" else None
    return Resultado(estado, detalle, _no_intentadas(p.operaciones, vv, detalle), error=error,
                     reintentable_desde=desde)


def ejecutar(p: Propuesta, graph, almacen: Almacen, auditoria: Auditoria, *,
             ahora: Callable[[], datetime] = _ahora) -> Resultado:
    if p.tipo not in CAMPOS_POR_TIPO:
        return _rechazo(p, auditoria, f"tipo {p.tipo} no soportado por ejecutar", error="no_soportado")
    if not p.operaciones:
        return _rechazo(p, auditoria, "la propuesta no tiene operaciones")
    for op in p.operaciones:
        motivo = _forma(p, op)
        if motivo:
            return _rechazo(p, auditoria, motivo)

    try:
        vv = valores_vivos(p, graph, ahora=ahora)
    except EntidadAjena as e:
        return _rechazo(p, auditoria, f"entidad fuera de la cuenta: {e.entidad_id}")
    except LecturaIncompleta as e:
        return _rechazo(p, auditoria, f"lectura incompleta: {_texto_error(e)}")
    except ErrorRed as e:
        return _rechazo(p, auditoria, f"no se pudo leer Meta ({e.motivo})", error="red")
    except ErrorGraph as e:
        return _rechazo(p, auditoria, f"no se pudo leer Meta: {_texto_error(e)}", error=clasificar(e), ahora=ahora)
    except Exception as e:  # noqa: BLE001 — toda salida es un Resultado
        return _rechazo(p, auditoria, f"no se pudo leer Meta: {_texto_error(e)}")

    if any(op.campo in CAMPOS_IMPORTE for op in p.operaciones):
        if vv.cuenta.offset is None:
            return _rechazo(p, auditoria, f"moneda sin offset confirmado (P-21): {vv.cuenta.currency or '?'}",
                            error="moneda", vv=vv)
        for op in p.operaciones:
            if op.campo in CAMPOS_IMPORTE and op.moneda != vv.cuenta.currency:
                return _rechazo(p, auditoria, f"{_desc(op)}: moneda {op.moneda} distinta de la de la cuenta "
                                              f"({vv.cuenta.currency})", error="moneda", vv=vv)

    motivo = vv.obsoleta(p)
    if motivo:
        return _rechazo(p, auditoria, f"cambió desde que se envió: {motivo}", estado="obsoleta", error=None, vv=vv)

    resultados: list[ResultadoOp] = []
    for i, op in enumerate(p.operaciones):
        ro = _ejecutar_op(op, p, vv, graph, almacen, auditoria, ahora)
        resultados.append(ro)
        if ro.estado != "ejecutada":
            # Ante cualquier duda (STOP, fallo, discrepancia) no se sigue escribiendo.
            resto = p.operaciones[i + 1:]
            nota = "STOP: no se intentó" if ro.estado == "no_intentada" else "no se intentó: falló una anterior"
            resultados.extend(_no_intentadas(resto, vv, nota))
            break
    return _cerrar(p, resultados, vv, almacen, auditoria, ahora)


def _cerrar(p: Propuesta, ops: list[ResultadoOp], vv: ValoresVivos, almacen: Almacen, auditoria: Auditoria,
            ahora: Callable[[], datetime]) -> Resultado:
    estados = [o.estado for o in ops]
    parcial = "ejecutada" in estados and any(e != "ejecutada" for e in estados)
    error: str | None = None
    stop = any(o.error == "stop" for o in ops)
    if "discrepancia" in estados:
        estado: EstadoRes = "discrepancia"
    elif stop:
        estado, error, parcial = "fallida", "stop", True
    elif "fallida" in estados:
        estado = "fallida"
        error = next(o.error for o in ops if o.estado == "fallida") or "otro"
    else:
        estado = "ejecutada"
    partes = [o.detalle for o in ops if o.estado != "no_intentada"] or [ops[0].detalle]
    detalle = " | ".join(partes)

    nueva: dict | None = None
    pausadas = [o for o in ops if o.pausada_sin_pedir]
    if pausadas:
        nueva, aviso = _reactivar(p, pausadas, dict(vv.tipos), almacen, ahora)
        if aviso:
            detalle = f"{detalle} | {aviso}"
    desde = ahora() + _ESPERA_LIMITE_META if error == "limite_meta" else None
    resultado = Resultado(estado, detalle, tuple(ops), parcial=parcial, nueva_propuesta=nueva, error=error,
                          reintentable_desde=desde)
    _anotar(auditoria, p, False, estado == "ejecutada", f"{estado}: {detalle}")
    return resultado


