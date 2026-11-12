"""Ejecución de propuestas de una o varias operaciones sobre Meta (§5.5, §5.10; resoluciones 9, 11 y 13).

Por cada operación: forma → lectura viva → moneda → precondición → ``validate_only`` → **una** escritura
real → relectura nueva a Graph. Las escrituras nunca se reintentan: tras un fallo de red después de
enviar se relee y se decide con lo leído; si tampoco se puede releer, ``discrepancia`` (estado
desconocido). Ante cualquier duda, falla cerrado y no escribe.

``lote``: precondición de todas antes de escribir ninguna; luego op por op, sin reintentar las fallidas;
solo token y STOP detienen el resto. ``noop``/``alerta``/``limite_ejecutor`` nunca llaman a Graph;
``agenda``/``regla_meta`` se rechazan (P-07); ``crear_estructura_pausada`` lanza ``ValueError``.

No mira STOP ni límites ni hace transiciones (resolución 9): eso lo hace el servicio (plan 12) antes
y después. Solo reacciona a ``DetenidoPorStop`` del cliente (resolución 11).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from trovefy_ejecutor.auditoria import EV_EJECUCION, Auditoria, redactar
from trovefy_ejecutor.esquema import (
    CLAVES_LIMITE_CUENTA,
    CLAVES_LIMITE_GLOBALES,
    PropuestaInvalida,
    cargar_propuesta,
)
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.graph import (
    DetenidoPorStop,
    ErrorGraph,
    ErrorRed,
    clasificar,
    es_rechazo_definitivo,
)
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
    "presupuesto": {("adset", "daily_budget"), ("campaign", "daily_budget")},
    "puja": {("adset", "bid_amount")},
    "spend_cap": {("campaign", "spend_cap")},
    "limite_cuenta": {("account", "spend_cap")},
    "pausar": {(e, "status") for e in _ESTADOS},
    "activar": {(e, "status") for e in _ESTADOS},
}
# Lote: solo formas de presupuesto y pausar (esquema: presupuesto + pausar + activar; activar se excluye
# a propósito, más estricto que el esquema: un lote nunca pone ACTIVE).
CAMPOS_POR_TIPO["lote"] = CAMPOS_POR_TIPO["presupuesto"] | CAMPOS_POR_TIPO["pausar"]
_STATUS_POR_TIPO = {"pausar": "PAUSED", "activar": "ACTIVE", "lote": "PAUSED"}
# Errores de una operación que detienen el resto del lote (las demás quedan no_intentada, sin llamar).
_DETIENEN_LOTE = frozenset({"token", "stop", "limite_meta"})
_NOTA_DETENIDO = {"stop": "STOP: no se intentó", "token": "no se intentó: token caducado",
                  "limite_meta": "no se intentó: Meta pide frenar"}
TIPOS_SOPORTADOS: frozenset[str] = frozenset({
    "presupuesto", "pausar", "activar", "puja", "spend_cap", "limite_cuenta", "lote", "noop", "alerta",
    "limite_ejecutor"})
NO_SOPORTADO_P07 = "no soportado aún (P-07)"
# Campo de la regla de cadencia (limites) que cuenta cada cambio. status y spend_cap no tienen regla.
CAMPO_CADENCIA = {"daily_budget": "daily_budget", "bid_amount": "bid_amount"}

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
                 ahora: Callable[[], datetime], status_confirmados: Mapping[str, str] | None = None) -> ResultadoOp:
    """Valida, escribe una sola vez y relee. Nunca reenvía una escritura real ni deja escapar errores
    de Graph: el resultado lo dice ``ResultadoOp.estado``. ``no_intentada`` = STOP (quien llama para).

    ``status_confirmados``: status que operaciones anteriores del mismo lote dejaron confirmados
    (relectura); mandan sobre la foto previa al decidir si Meta pausó la entidad sin pedirlo."""
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
        return _tras_rechazo(op, graph, almacen, ahora, antes, r, e)
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
    if op.entidad in _ESTADOS and not isinstance(crudo.get("status"), str):
        _cadencia(almacen, op, ahora)
        return r("discrepancia", "estado desconocido: la relectura no trae status")
    despues = _normal(op.campo, crudo.get(op.campo))
    status_antes = (status_confirmados or {}).get(op.id, vv.status(op.id))
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


def _tras_rechazo(op: Operacion, graph, almacen: Almacen, ahora: Callable[[], datetime], antes: object,
                  r: Callable[..., ResultadoOp], e: ErrorGraph) -> ResultadoOp:
    """Meta rechazó la escritura real: se relee por si la aplicó igualmente (nunca se reenvía).

    Si no se puede releer: con un rechazo definitivo (``es_rechazo_definitivo``) no se aplicó, ``fallida``;
    con un error ambiguo (1, 2, 5xx…) pudo aplicarse, ``discrepancia`` (estado desconocido)."""
    error = clasificar(e)
    texto = f"Meta rechazó la escritura: {_texto_error(e)}"
    try:
        crudo = _releer(graph, op)
    except Exception as ex:  # noqa: BLE001
        _cadencia(almacen, op, ahora)  # lado seguro
        if not es_rechazo_definitivo(e):
            return r("discrepancia", f"estado desconocido: Meta devolvió un error ambiguo ({e.codigo}) y no se "
                                     f"pudo releer ({_texto_error(ex)})", error=error)
        return r("fallida", f"{texto}; no se pudo releer ({_texto_error(ex)})", error=error)
    despues = _normal(op.campo, crudo.get(op.campo))
    sin_status = op.entidad in _ESTADOS and not isinstance(crudo.get("status"), str)
    if despues != antes or sin_status:
        _cadencia(almacen, op, ahora)
    if despues == antes and not sin_status:
        return r("fallida", f"{texto}; la relectura dice {despues}: no se aplicó", despues, error=error)
    return r("discrepancia", f"{texto}; pero la relectura dice {despues}", despues, error=error)


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


def _sin_meta(p: Propuesta, auditoria: Auditoria, detalle: str) -> Resultado:
    """``noop``/``alerta``: nada que hacer en Meta; un único ``ejecucion`` final."""
    if p.operaciones:
        return _rechazo(p, auditoria, f"{p.tipo} no lleva operaciones")
    if not _anotar(auditoria, p, False, True, detalle) and p.tipo == "noop":
        # noop prueba el circuito entero, auditoría incluida: si no se pudo anotar, el circuito falla.
        return Resultado("fallida", "auditoría no disponible: el circuito no está bien", error="otro")
    return Resultado("ejecutada", detalle)


def _limite_ejecutor(p: Propuesta, auditoria: Auditoria) -> Resultado:
    """Devuelve el cambio para que el servicio (plan 12) escriba ``limites.yaml``. Nunca llama a Graph.

    Falla cerrado ante cualquier forma inesperada (el esquema ya la valida; esto es la segunda barrera)
    o si la auditoría no puede anotarlo."""
    if len(p.operaciones) != 1:
        return _rechazo(p, auditoria, "limite_ejecutor lleva exactamente una operación")
    op = p.operaciones[0]
    if op.entidad != "ejecutor" or not isinstance(op.id, str) or not (
            op.id == "global" or re.fullmatch(r"act_[0-9]+", op.id)):
        return _rechazo(p, auditoria, f"{_desc(op)}: el id debe ser global o una cuenta act_…")
    if op.campo not in CLAVES_LIMITE_CUENTA and op.campo not in CLAVES_LIMITE_GLOBALES:
        return _rechazo(p, auditoria, f"{_desc(op)}: no es una clave de límite del ejecutor")
    if not (_es_importe_valido(op.de_esperado) and _es_importe_valido(op.a)):
        return _rechazo(p, auditoria, f"{_desc(op)}: de_esperado y a deben ser enteros > 0")
    cambio: dict = {"clave": op.campo, "id": op.id, "de": op.de_esperado, "a": op.a}
    if op.campo in CLAVES_LIMITE_CUENTA:
        if op.unidad != "minima" or not isinstance(op.moneda, str) or not re.fullmatch(r"[A-Z]{3}", op.moneda):
            return _rechazo(p, auditoria, f"{_desc(op)}: importe con unidad \"minima\" y moneda de 3 letras")
        cambio.update(moneda=op.moneda, unidad=op.unidad)
    elif op.unidad is not None or op.moneda is not None:
        return _rechazo(p, auditoria, f"{_desc(op)}: una clave global no lleva unidad ni moneda")
    detalle = f"límite {op.id} {op.campo}: {op.de_esperado} → {op.a}; nada cambió en Meta"
    if not _anotar(auditoria, p, False, True, detalle):
        return Resultado("fallida", "auditoría no disponible: no se cambia el límite",
                         _no_intentadas(p.operaciones, None, "auditoría no disponible"), error="otro")
    return Resultado("ejecutada", detalle, cambio_limite=cambio)


def ejecutar(p: Propuesta, graph, almacen: Almacen, auditoria: Auditoria, *,
             ahora: Callable[[], datetime] = _ahora) -> Resultado:
    """Ejecuta ``p`` y devuelve siempre un ``Resultado``; la única excepción es
    ``crear_estructura_pausada``, que lanza ``ValueError`` (se ejecuta con ``montaje.montar``)."""
    if p.tipo == "crear_estructura_pausada":
        raise ValueError("crear_estructura_pausada se ejecuta con montaje.montar")
    if p.tipo in ("agenda", "regla_meta"):
        # §5.8 depende de P-07 (budget_schedules, reglas por API) sin verificar: se rechaza sin llamar.
        return _rechazo(p, auditoria, NO_SOPORTADO_P07, error="no_soportado")
    if p.tipo == "noop":
        return _sin_meta(p, auditoria, "circuito probado; nada cambió en Meta")
    if p.tipo == "alerta":
        return _sin_meta(p, auditoria, "notificación; nada cambió en Meta")
    if p.tipo == "limite_ejecutor":
        return _limite_ejecutor(p, auditoria)
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
        # El spend_cap de la cuenta va en la unidad principal de la moneda, no en mínimas: con offset ≠ 1
        # no se sabe convertir sin confirmarlo (P-21). Con offset 1 (COP) ambas coinciden.
        if vv.cuenta.offset != 1 and any((op.entidad, op.campo) == ("account", "spend_cap")
                                         for op in p.operaciones):
            return _rechazo(p, auditoria, "spend_cap de cuenta con offset ≠ 1 sin confirmar la unidad (P-21)",
                            error="moneda", vv=vv)

    motivo = vv.obsoleta(p)
    if motivo:
        return _rechazo(p, auditoria, f"cambió desde que se envió: {motivo}", estado="obsoleta", error=None, vv=vv)

    resultados: list[ResultadoOp] = []
    confirmados: dict[str, str] = {}  # status confirmados por ops anteriores del lote
    for i, op in enumerate(p.operaciones):
        ro = _ejecutar_op(op, p, vv, graph, almacen, auditoria, ahora, confirmados)
        resultados.append(ro)
        if p.tipo == "lote":
            # Lote: op por op; una fallida o en discrepancia no se reintenta y el lote sigue. Solo token,
            # STOP y limite_meta detienen: las restantes quedan no_intentada sin llamar.
            if ro.estado == "ejecutada" and op.campo == "status" and isinstance(ro.despues, str):
                confirmados[op.id] = ro.despues
            if ro.estado == "no_intentada" or ro.error in _DETIENEN_LOTE:
                motivo_corte = "stop" if ro.estado == "no_intentada" else ro.error
                resultados.extend(_no_intentadas(p.operaciones[i + 1:], vv, _NOTA_DETENIDO[motivo_corte]))
                break
            continue
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
    if p.tipo == "lote":
        # (extra) en un lote la discrepancia no detiene: el error conserva STOP/token aunque el estado sea
        # discrepancia, token manda sobre el primer error, y si no, el primer error de una op fallida.
        if stop:
            error = "stop"
        elif any(o.error == "token" for o in ops):
            error = "token"
        elif "fallida" in estados:
            error = next(o.error for o in ops if o.estado == "fallida") or "otro"
    partes = [o.detalle for o in ops if o.estado != "no_intentada"] or [ops[0].detalle]
    if p.tipo == "lote":
        aplicadas = estados.count("ejecutada")
        cuenta = f"{aplicadas} de {len(ops)} aplicadas"
        partes.insert(0, f"parcial: {cuenta}" if parcial else f"lote: {cuenta}")
    detalle = " | ".join(partes)

    nueva: dict | None = None
    pausadas = [o for o in ops if o.pausada_sin_pedir]
    if pausadas:
        try:
            nueva, aviso = _reactivar(p, pausadas, dict(vv.tipos), almacen, ahora)
        except Exception as e:  # noqa: BLE001 — nada tras una escritura real puede escapar
            nueva = None
            aviso = f"no se pudo preparar la propuesta de reactivar ({_texto_error(e)}): crea la propuesta a mano"
        if aviso:
            detalle = f"{detalle} | {aviso}"
    # Reintentable solo si no se aplicó nada: con algo aplicado, repetir la propuesta no es seguro.
    desde = ahora() + _ESPERA_LIMITE_META if error == "limite_meta" and "ejecutada" not in estados else None
    resultado = Resultado(estado, detalle, tuple(ops), parcial=parcial, nueva_propuesta=nueva, error=error,
                          reintentable_desde=desde)
    _anotar(auditoria, p, False, estado == "ejecutada", f"{estado}: {detalle}")
    return resultado


