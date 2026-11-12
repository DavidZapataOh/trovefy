"""Mensaje de propuesta de §5.4: texto plano, sin parse_mode, con los valores vivos que leyó el ejecutor."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from .auditoria import redactar
from .callbacks import firmar
from .dinero import Moneda, formatear
from .esquema import RANGO_USUARIO
from .modelo import Estado, Operacion, Propuesta
from .reloj import ZONA_COT
from .telegram import Boton

MAX_PROPUESTA = 3800  # deja sitio a la línea de resultado
MAX_POR_QUE = 300

_SALTOS = re.compile(r"\r\n|\r|\n|\u2028|\u2029|\x85")

_VACIO: Mapping = MappingProxyType({})


class SinValorVivo(Exception):
    pass


class MensajeDemasiadoLargo(Exception):
    pass


@dataclass(frozen=True)
class DatosRender:
    moneda: Moneda
    leido: datetime
    caduca: datetime
    valores: Mapping[tuple[str, str, str], int | str]
    nombres: Mapping[str, str] = field(default_factory=lambda: _VACIO)
    gasto_cuenta_tras: int | None = None
    tope_cuenta: int | None = None


def _descartable(c: str) -> bool:
    o = ord(c)
    return (unicodedata.category(c) == "Cf" or c == "\u061c" or 0x2060 <= o <= 0x2064 or o == 0xAD
            or 0xE0000 <= o <= 0xE007F or o in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0xFEFF)
            or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069)


def limpiar_texto(texto: str, maximo: int) -> str:
    texto = _SALTOS.sub("\n", str(texto))
    sal = []
    for c in texto:
        if c == "\n" or c == " ":
            sal.append(c)
        elif c == "\t":
            sal.append(" ")
        elif _descartable(c) or unicodedata.category(c) == "Cc":
            continue
        else:
            sal.append(c)
    lineas = [re.sub(r" +", " ", ln).strip() for ln in "".join(sal).split("\n")]
    texto = " · ".join(ln for ln in lineas if ln)
    if len(texto) > maximo:
        texto = texto[: maximo - 1] + "…"
    return texto


_TITULOS = {
    "pausar": "PAUSAR", "activar": "ACTIVAR", "puja": "CAMBIAR PUJA",
    "spend_cap": "CAMBIAR LÍMITE DE GASTO DE LA CAMPAÑA", "limite_cuenta": "CAMBIAR LÍMITE DE GASTO DE LA CUENTA",
    "limite_ejecutor": "CAMBIAR LÍMITE DEL EJECUTOR", "agenda": "AGENDA DEL DÍA",
    "regla_meta": "REGLA AUTOMÁTICA DE META", "noop": "PRUEBA (no cambia nada en Meta)",
    "crear_estructura_pausada": "CREAR ESTRUCTURA PAUSADA",
}
_ENTIDADES = {"campaign": "Campaña", "adset": "Conjunto", "ad": "Anuncio", "account": "Cuenta"}
_ETIQUETAS = {"daily_budget": "Presupuesto diario", "lifetime_budget": "Presupuesto total", "bid_amount": "Puja",
              "spend_cap": "Límite de gasto", "status": "Estado"}
_NIVELES = {"info": "INFO", "aviso": "AVISO", "urgente": "URGENTE"}


def _sin_codigo(unidades: int, moneda: Moneda) -> str:
    return formatear(unidades, moneda).rsplit(" ", 1)[0]


def _hora(t: datetime) -> str:
    return t.astimezone(ZONA_COT).strftime("%H:%M")


def _fin4(id_: str) -> str:
    return "…" + id_[-4:]


def _nombre(vivo: DatosRender, id_: str) -> str:
    return limpiar_texto(vivo.nombres.get(id_) or id_, 64)


def render_alerta(p: Propuesta) -> str:
    a = p.alerta
    assert a is not None
    lineas = [f"{_NIVELES[a.nivel]} · {limpiar_texto(a.titulo, 120)}", limpiar_texto(a.texto, 1000)]
    if a.adjuntos:
        lineas.append(f"Adjuntos: {len(a.adjuntos)} (en el vault)")
    lineas.append(p.id)
    return "\n".join(lineas)


def _valor_vivo(op: Operacion, vivo: DatosRender) -> int | str:
    try:
        return vivo.valores[(op.entidad, op.id, op.campo)]
    except KeyError:
        raise SinValorVivo(f"{op.entidad} {_fin4(op.id)} {op.campo}") from None


def _pct(v: int, a: int) -> str:
    if v == 0:
        return ""
    return f" ({round((a - v) / v * 100):+d} %)"


def _cambio(op: Operacion, v: int | str, vivo: DatosRender, con_pct: bool) -> str:
    if op.campo == "status" or not isinstance(v, int) or not isinstance(op.a, int):
        return f"{v} (sin cambio)" if v == op.a else f"{v} → {op.a}"
    m = vivo.moneda
    if v == op.a:
        return f"{formatear(v, m)} (sin cambio)"
    return f"{_sin_codigo(v, m)} → {formatear(op.a, m)}" + (_pct(v, op.a) if con_pct else "")


def _titulo(p: Propuesta, vivo: DatosRender) -> str:
    if p.tipo == "lote":
        return f"LOTE ({len(p.operaciones)} operaciones)"
    if p.tipo == "presupuesto":
        pares = [(_valor_vivo(op, vivo), op.a) for op in p.operaciones]
        if all(isinstance(v, int) and isinstance(a, int) and a > v for v, a in pares):
            return "SUBIR PRESUPUESTO"
        if all(isinstance(v, int) and isinstance(a, int) and a < v for v, a in pares):
            return "BAJAR PRESUPUESTO"
        return f"CAMBIAR PRESUPUESTOS ({len(pares)})"
    return _TITULOS[p.tipo]


def _nombre_producto(slug: str, vivo: DatosRender) -> str:
    if slug in vivo.nombres:
        return limpiar_texto(vivo.nombres[slug], 64)
    partes = slug.split("-", 2)
    resto = partes[2] if len(partes) > 2 else slug
    return limpiar_texto(resto[:1].upper() + resto[1:], 64)


def _linea_contexto(p: Propuesta, vivo: DatosRender) -> str | None:
    partes = []
    if p.producto:
        corto = limpiar_texto("-".join(p.producto.split("-")[:2]), 64)
        partes.append(f"Producto: {_nombre_producto(p.producto, vivo)} ({corto})")
    if p.pais:
        partes.append(f"País: {limpiar_texto(p.pais, 8)}")
    if p.cuenta:
        partes.append(f"Cuenta: …{limpiar_texto(p.cuenta[-4:], 4)} ({vivo.moneda.codigo})")
    return " · ".join(partes) or None


def _lineas_limite(p: Propuesta, vivo: DatosRender) -> list[str]:
    """El valor actual sale de ``vivo.valores[("ejecutor", id, campo)]`` (id = ``global`` o ``act_…``)."""
    out = []
    for op in p.operaciones:
        actual = vivo.valores.get(("ejecutor", op.id, op.campo))
        if actual is None:
            raise SinValorVivo(f"ejecutor {limpiar_texto(op.id, 30)} {limpiar_texto(op.campo, 40)}")
        cuenta = limpiar_texto(op.id, 30)
        if op.unidad == "minima" and isinstance(op.a, int) and isinstance(actual, int):
            de, a = formatear(actual, vivo.moneda), formatear(op.a, vivo.moneda)
        else:
            de, a = str(actual), str(op.a)
        out.append(f"Límite: {limpiar_texto(op.campo, 40)} ({cuenta}): {de} → {a}")
    n = int(p.id[-3:])
    if n in RANGO_USUARIO and p.origen.startswith("telegram:"):
        out.append("Lo pide: tú (Telegram)")
    else:
        out.append(f"Lo pide: Claude ({limpiar_texto(p.origen, 100)})")
    return out


def _lineas_operaciones(p: Propuesta, vivo: DatosRender) -> list[str]:
    out = []
    if p.tipo == "lote":
        for i, op in enumerate(p.operaciones, 1):
            v = _valor_vivo(op, vivo)
            etiqueta = _ETIQUETAS.get(op.campo, op.campo)
            sep = " " if op.campo != "status" else ": "
            out.append(f"{i}. {_ENTIDADES[op.entidad]} {_nombre(vivo, op.id)} · "
                       f"{etiqueta}{sep}{_cambio(op, v, vivo, False)}")
        return out
    hora = _hora(vivo.leido)
    for op in p.operaciones:
        v = _valor_vivo(op, vivo)
        etiqueta = _ETIQUETAS.get(op.campo, op.campo)
        out.append(f"{_ENTIDADES[op.entidad]}: {_nombre(vivo, op.id)} · id {_fin4(op.id)}")
        out.append(f"{etiqueta}: {_cambio(op, v, vivo, True)}   [valor actual leído {hora}]")
    return out


def _caduca(vivo: DatosRender) -> str:
    c, ll = vivo.caduca.astimezone(ZONA_COT), vivo.leido.astimezone(ZONA_COT)
    cuando = c.strftime("%H:%M") if c.date() == ll.date() else c.strftime("%d/%m %H:%M")
    return f"Caduca: {cuando} (hora Colombia)"


def render_propuesta(p: Propuesta, vivo: DatosRender) -> str:
    if p.tipo == "alerta":
        return render_alerta(p)
    if p.tipo in ("agenda", "regla_meta"):
        raise ValueError("tipo no soportado aún (P-07)")
    lineas = [f"{p.id} · {_titulo(p, vivo)} · prioridad {p.prioridad}"]
    ctx = _linea_contexto(p, vivo)
    if ctx:
        lineas.append(ctx)
    if p.tipo == "limite_ejecutor":
        lineas += _lineas_limite(p, vivo)
    elif p.tipo != "noop":
        lineas += _lineas_operaciones(p, vivo)
    if vivo.gasto_cuenta_tras is not None:
        tope = "?" if vivo.tope_cuenta is None else _sin_codigo(vivo.tope_cuenta, vivo.moneda)
        lineas.append("Gasto diario total de la cuenta tras el cambio: "
                      f"{_sin_codigo(vivo.gasto_cuenta_tras, vivo.moneda)} / tope {tope}")
    lineas.append("Por qué: " + limpiar_texto(p.motivo or "", MAX_POR_QUE))
    if p.tipo == "noop":
        lineas.append(_caduca(vivo))
    else:
        lineas.append(f"Reinicia aprendizaje: {'sí' if p.reinicia_aprendizaje else 'no'} · {_caduca(vivo)}")
    texto = "\n".join(lineas)
    if len(texto) > MAX_PROPUESTA:
        raise MensajeDemasiadoLargo(f"{len(texto)} caracteres (máximo {MAX_PROPUESTA})")
    return texto


# --- Tarea 5: resultado, «ya procesada», /estado y resumen -------------------------------------------------

RECIBIDO = "Recibido"
PREGUNTA_MOTIVO = "{id} · ¿Motivo? (responde a este mensaje, opcional)"
STOP_ACTIVO = "STOP activo: no se ejecutó nada"
BOTON_NO_VALIDO = "Botón no válido: no se hizo nada"
AYUDA = "\n".join([  # noqa: FLY002
    "Comandos:",
    "/estado: gasto de hoy, propuestas pendientes y STOP",
    "/stop: parar todo al instante (no pausa campañas)",
    "/reanudar: quitar el STOP (pide confirmación)",
    "/pausar_todo: proponer pausar todas las campañas activas",
    "/limites: ver los límites del ejecutor",
    "/limites <clave> <valor>: proponer un cambio de límite",
    "/limites <act_…> <clave> <valor>: proponer un cambio de límite de una cuenta",
    "/emparejar: ver el estado del emparejamiento",
])

MAX_MENSAJE = 4096
MAX_RESUMEN = 5


@dataclass(frozen=True)
class Desenlace:
    estado: Literal["ejecutando", "ejecutada", "fallida", "discrepancia", "rechazada", "caducada", "obsoleta", "stop"]
    cuando: datetime
    relectura: str | None = None
    codigo: str | None = None
    nueva_propuesta: str | None = None
    lineas_lote: tuple[str, ...] = ()


def _externo(texto: str | None, maximo: int = 200) -> str:
    return limpiar_texto(redactar(limpiar_texto(texto or "", 100_000)), maximo)


def _linea_desenlace(d: Desenlace) -> str:
    hora = _hora(d.cuando)
    if d.estado == "ejecutando":
        return "EJECUTANDO…"
    if d.estado == "ejecutada":
        return f"EJECUTADA {hora} · relectura OK: {_externo(d.relectura)}"
    if d.estado == "fallida":
        return f"FALLÓ: {_externo(d.codigo)} · no se cambió nada"
    if d.estado == "discrepancia":
        return (f"DISCREPANCIA: Meta dice {_externo(d.relectura)} → nueva propuesta "
                f"{_externo(d.nueva_propuesta)}")
    if d.estado == "rechazada":
        return f"RECHAZADA {hora}"
    if d.estado == "caducada":
        return "CADUCADA, no se ejecutó nada"
    if d.estado == "obsoleta":
        return f"OBSOLETA: el valor cambió desde que se envió ({_externo(d.relectura)}); no se ejecutó nada"
    if d.estado == "stop":
        return STOP_ACTIVO
    raise ValueError(f"desenlace desconocido: {d.estado!r}")


def render_resultado(texto_original: str, d: Desenlace) -> str:
    base = texto_original + "\n\n" + _linea_desenlace(d)
    if not d.lineas_lote:
        return base
    lineas = [_externo(ln, 300) for ln in d.lineas_lote]
    completo = base + "".join("\n" + ln for ln in lineas)
    if len(completo) <= MAX_MENSAJE:
        return completo
    salida, usado = [], len(base)
    for i, ln in enumerate(lineas):
        resto = len(lineas) - i
        pie = f"\n… y {resto} más (detalle en el vault)"
        if usado + 1 + len(ln) + len(pie) > MAX_MENSAJE:
            break
        salida.append("\n" + ln)
        usado += 1 + len(ln)
    resto = len(lineas) - len(salida)
    return (base + "".join(salida) + f"\n… y {resto} más (detalle en el vault)")[:MAX_MENSAJE]


def texto_ya_procesada(estado: Estado) -> str:
    if estado == "caducada":
        return "Caducada: no se ejecutó nada"
    if estado == "recibida":
        return "Aún no enviada: no se hizo nada"
    return f"Ya procesada ({limpiar_texto(estado, 40)})"[:200]


def botones_propuesta(id: str, chat_id: int, clave: bytes) -> list[list[Boton]]:
    return [[Boton("Aceptar", firmar(id, "A", chat_id, clave)), Boton("Rechazar", firmar(id, "R", chat_id, clave))]]


@dataclass(frozen=True)
class ResumenEstado:
    gasto_hoy: Mapping[str, str]
    pendientes: Sequence[tuple[str, str, datetime]]
    stop: bool


def render_estado(r: ResumenEstado) -> str:
    lineas = ["STOP: activo" if r.stop else "STOP: no"]
    if r.gasto_hoy:
        lineas.append("Gasto de hoy:")
        lineas += [f"{limpiar_texto(c, 40)}: {limpiar_texto(v, 40)}" for c, v in r.gasto_hoy.items()]
    else:
        lineas.append("Gasto de hoy: sin datos")
    if r.pendientes:
        lineas.append(f"Pendientes ({len(r.pendientes)}):")
        lineas += [f"{limpiar_texto(i, 20)} · {limpiar_texto(t, 80)} · caduca {_hora(c)} (hora Colombia)"
                   for i, t, c in r.pendientes]
    else:
        lineas.append("Sin propuestas pendientes")
    return "\n".join(lineas)[:MAX_MENSAJE]


@dataclass(frozen=True)
class ItemResumen:
    id: str
    linea: str
    motivo: str
    caduca: datetime
    estado: Estado


def render_resumen(items: Sequence[ItemResumen], titulo: str, chat_id: int, clave: bytes,
                   maximo: int = MAX_MENSAJE) -> tuple[str, list[list[Boton]]]:
    if len(items) > MAX_RESUMEN:
        raise ValueError(f"un resumen admite como máximo {MAX_RESUMEN} propuestas")
    bloques, botones = [], []
    for n, it in enumerate(items, 1):
        if it.estado == "enviada":
            final = f"Caduca: {_hora(it.caduca)} (hora Colombia)"
            botones.append([
                Boton(f"Aceptar {n}", firmar(it.id, "A", chat_id, clave)),
                Boton(f"Rechazar {n}", firmar(it.id, "R", chat_id, clave)),
            ])
        else:
            final = f"Estado: {limpiar_texto(it.estado, 40).upper()}"
        bloques.append("\n".join([f"{n} · {limpiar_texto(it.id, 20)} · " + limpiar_texto(it.linea, 200), "Por qué: " + limpiar_texto(it.motivo, 120), final]))
    texto = "\n\n".join([limpiar_texto(titulo, 100)] + bloques)
    if len(texto) > maximo:
        raise MensajeDemasiadoLargo(f"{len(texto)} caracteres (máximo {maximo})")
    return texto, botones
