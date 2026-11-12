"""Esquema estricto de las propuestas con operaciones (§5.2).

Ids ``P-AAAAMMDD-NNN`` (resolución 2): Claude (``trovefy buzon depositar``) usa 001-799, el
ejecutor 800-899 y el usuario por Telegram 900-999. ``cargar_propuesta`` acepta los tres rangos y
rechaza 000; quien deposita por el buzón lo limita a 001-799 (plan 12). Sin PyYAML (resolución 15).
El esquema no mira límites, cuenta permitida ni moneda de la cuenta: eso es de ``limites.comprobar``.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .dinero import es_importe
from .modelo import TIPOS, Operacion, Propuesta, clase_de

ID_RE = r"^P-\d{8}-\d{3}$"
CUENTA_RE = r"^act_\d{1,20}$"
ENTIDAD_ID_RE = r"^\d{1,20}$"
RANGO_CLAUDE = range(1, 800)
RANGO_EJECUTOR = range(800, 900)
RANGO_USUARIO = range(900, 1000)

TIPOS_CON_OPERACIONES = TIPOS - {"noop", "alerta", "crear_estructura_pausada"}
COMUNES = {"version", "id", "tipo", "creada", "origen"}
OPCIONALES = {"producto", "pais", "evidencia", "reinicia_aprendizaje", "prioridad", "expira_en_min"}
CLAVES_OP = {"entidad", "id", "campo", "de_esperado", "a", "unidad", "moneda", "parametros"}
OBLIGATORIAS_OP = ("entidad", "id", "campo", "de_esperado", "a")


class PropuestaInvalida(Exception):
    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def _err(texto: str) -> PropuestaInvalida:
    return PropuestaInvalida(f"esquema: {texto}")


@dataclass(frozen=True)
class ReglaOp:
    entidades: tuple[str, ...]
    campo: str  # o patrón regex si empieza por "re:"
    de: Any  # "importe" | "importe_o_null" | "null" | "int_o_null" | valor constante
    a: Any  # "importe" | "int_pos" | "null" | valor constante
    parametros: bool = False

    @property
    def es_importe(self) -> bool:
        return self.a == "importe"


_ESTADO = ("campaign", "adset", "ad")
REGLAS: dict[str, list[ReglaOp]] = {
    "presupuesto": [ReglaOp(("adset", "campaign"), "daily_budget", "importe", "importe")],
    "pausar": [ReglaOp(_ESTADO, "status", "ACTIVE", "PAUSED")],
    "activar": [ReglaOp(_ESTADO, "status", "PAUSED", "ACTIVE")],
    "puja": [ReglaOp(("adset", "campaign"), "bid_amount", "importe_o_null", "importe")],
    "spend_cap": [ReglaOp(("campaign",), "spend_cap", "importe_o_null", "importe")],
    "limite_cuenta": [ReglaOp(("account",), "spend_cap", "importe_o_null", "importe")],
    "limite_ejecutor": [ReglaOp(("ejecutor",), "re:^[a-z_]+$", "int_o_null", "int_pos")],
    "agenda": [ReglaOp(("adset", "campaign"), "budget_schedules", "null", "null", True)],
    "regla_meta": [ReglaOp(("account",), "adrules", "null", "null", True)],
}
REGLAS["lote"] = REGLAS["presupuesto"] + REGLAS["pausar"] + REGLAS["activar"]


def _texto(datos: dict, clave: str, minimo: int, maximo: int, obligatorio: bool = True) -> str | None:
    if clave not in datos:
        if obligatorio:
            raise _err(f"falta el campo {clave}")
        return None
    v = datos[clave]
    if not isinstance(v, str) or not minimo <= len(v) <= maximo:
        raise _err(f"{clave} debe ser texto de {minimo} a {maximo} caracteres")
    return v


def _fecha(valor: Any) -> datetime:
    if not isinstance(valor, str):
        raise _err("creada debe ser texto ISO 8601 con zona")
    try:
        f = datetime.fromisoformat(valor)
    except ValueError:
        raise _err(f"creada no es ISO 8601: {valor!r}") from None
    if f.tzinfo is None or f.utcoffset() is None:
        raise _err("creada sin zona horaria (se exige desfase, p. ej. -05:00)")
    return f


def _cumple_de(kind: Any, v: Any) -> bool:
    if kind == "importe":
        return es_importe(v)
    if kind == "importe_o_null":
        return v is None or es_importe(v)
    if kind == "null":
        return v is None
    if kind == "int_o_null":
        return v is None or type(v) is int
    if kind == "int_pos":
        return type(v) is int and v > 0
    return type(v) is str and v == kind


def _cumple(regla: ReglaOp, op: dict) -> bool:
    if op["entidad"] not in regla.entidades:
        return False
    campo = regla.campo
    if campo.startswith("re:"):
        if not (isinstance(op["campo"], str) and re.fullmatch(campo[3:], op["campo"])):
            return False
    elif op["campo"] != campo:
        return False
    return _cumple_de(regla.de, op["de_esperado"]) and _cumple_de(regla.a, op["a"])


def _validar_op(n: int, op: Any, tipo: str, cuenta: str | None) -> Operacion:
    pre = f"operación {n}"
    if not isinstance(op, dict):
        raise _err(f"{pre} debe ser un objeto")
    for k in op:
        if k not in CLAVES_OP:
            raise _err(f"campo no permitido: {k}")
    for k in OBLIGATORIAS_OP:
        if k not in op:
            raise _err(f"{pre}: falta el campo {k}")
    if not isinstance(op["entidad"], str) or not isinstance(op["id"], str) or not isinstance(op["campo"], str):
        raise _err(f"{pre}: entidad, id y campo deben ser texto")
    reglas = REGLAS[tipo]
    if op["entidad"] not in {e for r in reglas for e in r.entidades}:
        raise _err(f"{pre}: entidad {op['entidad']!r} no permitida para {tipo}")
    # id de la entidad
    if op["entidad"] == "account":
        if cuenta is None or op["id"] != cuenta.removeprefix("act_"):
            raise _err(f"{pre}: el id de la cuenta debe ser el número de la cuenta de la propuesta")
    elif op["entidad"] == "ejecutor":
        if op["id"] != "global" and not re.fullmatch(CUENTA_RE, op["id"]):
            raise _err(f"{pre}: el id debe ser global o una cuenta act_…")
    elif not re.fullmatch(ENTIDAD_ID_RE, op["id"]):
        raise _err(f"{pre}: id de entidad inválido")
    candidatas = [r for r in reglas if _cumple(r, op)]
    if not candidatas:
        # diagnóstico más preciso
        mismas = [r for r in reglas if op["entidad"] in r.entidades]
        r0 = mismas[0]
        if not any(r.campo == op["campo"] or r.campo.startswith("re:") for r in mismas):
            raise _err(f"{pre}: campo {op['campo']!r} no permitido para {tipo}")
        if not any(_cumple_de(r.a, op["a"]) for r in mismas):
            raise _err(f"{pre}: a no es válido para {tipo}" + (" (importe: entero > 0)" if r0.es_importe else ""))
        raise _err(f"{pre}: de_esperado no es válido para {tipo}" + (" (importe: entero > 0)" if r0.es_importe else ""))
    regla = candidatas[0]
    unidad = op.get("unidad")
    moneda = op.get("moneda")
    parametros = op.get("parametros")
    if regla.es_importe:
        if unidad != "minima":
            raise _err(f"{pre}: unidad debe ser \"minima\"")
        if not isinstance(moneda, str) or not re.fullmatch(r"[A-Z]{3}", moneda):
            raise _err(f"{pre}: moneda debe ser un código de 3 letras")
    else:
        if "unidad" in op or "moneda" in op:
            raise _err(f"{pre}: unidad y moneda solo van en operaciones de importe")
    if regla.parametros:
        if not isinstance(parametros, dict):
            raise _err(f"{pre}: parametros debe ser un objeto")
    elif "parametros" in op:
        raise _err(f"{pre}: parametros no va en {tipo}")
    return Operacion(op["entidad"], op["id"], op["campo"], op["de_esperado"], op["a"],
                     unidad, moneda, parametros)


def _opcional_tipado(datos: dict, clave: str, ok: Callable[[Any], bool], desc: str) -> Any:
    if clave in datos and not ok(datos[clave]):
        raise _err(f"{clave} {desc}")
    return datos.get(clave)


def cargar_propuesta(datos: dict) -> Propuesta:
    if not isinstance(datos, dict):
        raise _err("la propuesta debe ser un objeto")
    if datos.get("version") != 1 or type(datos.get("version")) is not int:
        raise _err("version debe ser 1")
    id_ = datos.get("id")
    if not isinstance(id_, str) or not re.fullmatch(ID_RE, id_) or int(id_[-3:]) not in range(1, 1000):
        raise _err(f"id inválido (formato P-AAAAMMDD-NNN, NNN 001-999): {id_!r}")
    tipo = datos.get("tipo")
    if not isinstance(tipo, str) or tipo not in TIPOS:
        raise _err(f"tipo desconocido: {tipo!r}")
    if tipo in ("alerta", "crear_estructura_pausada"):
        raise _err(f"tipo {tipo} aún no soportado por este esquema")
    creada = _fecha(datos.get("creada"))
    origen = _texto(datos, "origen", 1, 100)
    if tipo == "noop":
        permitidas = COMUNES | {"motivo", "prioridad", "expira_en_min"}
    else:
        permitidas = COMUNES | OPCIONALES | {"cuenta", "operaciones", "motivo"}
    for k in datos:
        if k not in permitidas:
            raise _err(f"campo no permitido: {k}")
    motivo = _texto(datos, "motivo", 1, 1000, obligatorio=tipo != "noop")
    prioridad = datos.get("prioridad", "normal")
    if prioridad not in ("normal", "alta") or not isinstance(prioridad, str):
        raise _err("prioridad debe ser normal o alta")
    expira = _opcional_tipado(datos, "expira_en_min", lambda v: type(v) is int and 1 <= v <= 1440,
                              "debe ser un entero entre 1 y 1440")
    base = {"version": 1, "id": id_, "tipo": tipo, "clase": clase_de(tipo), "creada": creada, "origen": origen,
                "motivo": motivo, "prioridad": prioridad, "expira_en_min": expira}
    if tipo == "noop":
        return Propuesta(**base, cuenta=None, producto=None, pais=None, operaciones=(), evidencia=None,
                         reinicia_aprendizaje=False)
    cuenta = datos.get("cuenta")
    if cuenta is None and "cuenta" not in datos:
        if tipo != "limite_ejecutor":
            raise _err("falta el campo cuenta")
    elif not isinstance(cuenta, str) or not re.fullmatch(CUENTA_RE, cuenta):
        raise _err(f"cuenta inválida (act_<número>): {cuenta!r}")
    producto = _opcional_tipado(datos, "producto", lambda v: isinstance(v, str) and 1 <= len(v) <= 100,
                                "debe ser texto de 1 a 100 caracteres")
    pais = _opcional_tipado(datos, "pais", lambda v: isinstance(v, str) and re.fullmatch(r"[A-Z]{2}", v) is not None,
                            "debe ser un código de 2 letras mayúsculas")
    evidencia = _opcional_tipado(datos, "evidencia", lambda v: isinstance(v, dict), "debe ser un objeto")
    reinicia = _opcional_tipado(datos, "reinicia_aprendizaje", lambda v: type(v) is bool, "debe ser booleano")
    ops = datos.get("operaciones")
    if not isinstance(ops, list) or not 1 <= len(ops) <= 40:
        raise _err("operaciones debe ser una lista de 1 a 40 elementos")
    operaciones = tuple(_validar_op(i, op, tipo, cuenta) for i, op in enumerate(ops, 1))
    vistos: set[tuple[str, str]] = set()
    for op in operaciones:
        par = (op.id, op.campo)
        if par in vistos:
            raise _err(f"operación repetida para ({op.id}, {op.campo})")
        vistos.add(par)
    return Propuesta(**base, cuenta=cuenta, producto=producto, pais=pais, operaciones=operaciones,
                     evidencia=copy.deepcopy(evidencia), reinicia_aprendizaje=bool(reinicia))


def _plano(v: Any) -> Any:
    if isinstance(v, dict) or hasattr(v, "keys"):
        return {k: _plano(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plano(x) for x in v]
    return v


def volcar_propuesta(p: Propuesta) -> dict:
    """Inversa de ``cargar_propuesta``; omite los opcionales ``None``."""
    d: dict[str, Any] = {"version": p.version, "id": p.id, "tipo": p.tipo, "creada": p.creada.isoformat(),
                         "origen": p.origen}
    for k in ("cuenta", "producto", "pais", "motivo"):
        if getattr(p, k) is not None:
            d[k] = getattr(p, k)
    if p.tipo != "noop":
        d["operaciones"] = [{k: _plano(v) for k, v in
                             (("entidad", o.entidad), ("id", o.id), ("campo", o.campo),
                              ("de_esperado", o.de_esperado), ("a", o.a), ("unidad", o.unidad),
                              ("moneda", o.moneda), ("parametros", o.parametros))
                             if k in OBLIGATORIAS_OP or v is not None} for o in p.operaciones]
        d["reinicia_aprendizaje"] = p.reinicia_aprendizaje
    if p.evidencia is not None:
        d["evidencia"] = _plano(p.evidencia)
    d["prioridad"] = p.prioridad
    if p.expira_en_min is not None:
        d["expira_en_min"] = p.expira_en_min
    return d
