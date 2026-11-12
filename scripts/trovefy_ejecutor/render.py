"""Mensaje de propuesta de §5.4: texto plano, sin parse_mode, con los valores vivos que leyó el ejecutor."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from .dinero import Moneda, formatear
from .esquema import RANGO_USUARIO
from .modelo import Operacion, Propuesta
from .reloj import ZONA_COT

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
