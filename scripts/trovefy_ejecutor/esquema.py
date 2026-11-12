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
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .dinero import es_importe
from .modelo import (
    TIPOS,
    Alerta,
    Anuncio,
    Campana,
    Conjunto,
    Estructura,
    Medio,
    Operacion,
    Propuesta,
    clase_de,
)

ID_RE = r"^P-[0-9]{8}-[0-9]{3}$"
CUENTA_RE = r"^act_[0-9]{1,20}$"
ENTIDAD_ID_RE = r"^[0-9]{1,20}$"
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


# --- crear_estructura_pausada y alerta (Tarea 4) -------------------------------------------------

REF_RE = r"[A-Za-z0-9_-]{1,40}"
SHA256_RE = r"[0-9a-f]{64}"
CODIGO_RE = r"[A-Z][A-Z0-9_]{0,59}"
UBICACION_RE = r"[a-z][a-z0-9_]{0,59}"
NIVELES = ("info", "aviso", "urgente")


def _exacto(obj: Any, nombre: str, obligatorias: tuple[str, ...], opcionales: tuple[str, ...] = ()) -> dict:
    if not isinstance(obj, dict):
        raise _err(f"{nombre} debe ser un objeto")
    for k in obj:
        if k not in obligatorias and k not in opcionales:
            raise _err(f"campo no permitido: {k}")
    for k in obligatorias:
        if k not in obj:
            raise _err(f"{nombre}: falta el campo {k}")
    return obj


def _cadena(obj: dict, clave: str, minimo: int = 1, maximo: int = 500, patron: str | None = None) -> str:
    v = obj[clave]
    if not isinstance(v, str) or not minimo <= len(v) <= maximo:
        raise _err(f"{clave} debe ser texto de {minimo} a {maximo} caracteres")
    if patron is not None and re.fullmatch(patron, v) is None:
        raise _err(f"{clave} no es válido: {v!r}")
    return v


def _importe(obj: dict, clave: str) -> int:
    v = obj[clave]
    if not es_importe(v):
        raise _err(f"{clave} debe ser un importe (entero > 0 en unidades mínimas)")
    return v


def _lista(obj: dict, clave: str, minimo: int, maximo: int) -> list:
    v = obj[clave]
    if not isinstance(v, list) or not minimo <= len(v) <= maximo:
        raise _err(f"{clave} debe ser una lista de {minimo} a {maximo} elementos")
    return v


def _ruta_vault(v: Any, clave: str) -> str:
    if (not isinstance(v, str) or not 1 <= len(v) <= 300 or v.startswith("/") or "\\" in v or "\0" in v
            or any(seg in ("", ".", "..") for seg in v.split("/"))):
        raise _err(f"{clave} debe ser una ruta relativa al vault, sin «..» ni «/» inicial: {v!r}")
    return v


def _validar_medio(m: Any) -> Medio:
    m = _exacto(m, "medio", ("ref", "ruta", "sha256"))
    ref = _cadena(m, "ref", patron=REF_RE)
    ruta = _ruta_vault(m["ruta"], "ruta")
    sha = _cadena(m, "sha256", 64, 64, SHA256_RE)
    return Medio(ref, ruta, sha)


def _validar_anuncio(a: Any, refs: set[str]) -> Anuncio:
    a = _exacto(a, "anuncio", ("nombre", "medio", "texto", "titulo", "descripcion", "cta", "url"))
    nombre = _cadena(a, "nombre", 1, 200)
    medio = _cadena(a, "medio", patron=REF_RE)
    if medio not in refs:
        raise _err(f"medio {medio!r} del anuncio no existe en medios")
    texto = _cadena(a, "texto", 1, 3000)
    titulo = _cadena(a, "titulo", 1, 500)
    descripcion = _cadena(a, "descripcion", 1, 500)
    cta = _cadena(a, "cta", patron=CODIGO_RE)
    url = _cadena(a, "url", 9, 2000)
    if not url.startswith("https://") or any(c.isspace() for c in url):
        raise _err("url debe empezar por https:// y no llevar espacios")
    return Anuncio(nombre, medio, texto, titulo, descripcion, cta, url)


def _validar_conjunto(c: Any, abo: bool, refs: set[str]) -> Conjunto:
    c = _exacto(c, "conjunto", ("nombre", "paises", "idiomas", "evento", "ubicaciones_excluidas", "anuncios"),
                ("daily_budget",))
    nombre = _cadena(c, "nombre", 1, 200)
    if abo:
        if "daily_budget" not in c:
            raise _err("conjunto: falta daily_budget (ABO)")
        presupuesto: int | None = _importe(c, "daily_budget")
    else:
        if "daily_budget" in c:
            raise _err("conjunto: daily_budget no va en CBO (va en la campaña)")
        presupuesto = None
    paises = _lista(c, "paises", 1, 50)
    if not all(isinstance(x, str) and re.fullmatch(r"[A-Z]{2}", x) for x in paises) or len(set(paises)) != len(paises):
        raise _err("paises debe ser una lista sin repetir de códigos de 2 letras mayúsculas")
    idiomas = _lista(c, "idiomas", 1, 20)
    if not all(isinstance(x, str) and re.fullmatch(r"[a-z]{2}", x) for x in idiomas):
        raise _err("idiomas debe ser una lista de códigos de 2 letras minúsculas")
    evento = _cadena(c, "evento", patron=CODIGO_RE)
    ubic = _lista(c, "ubicaciones_excluidas", 0, 20)
    if not all(isinstance(x, str) and re.fullmatch(UBICACION_RE, x) for x in ubic):
        raise _err("ubicaciones_excluidas debe ser una lista de identificadores en minúsculas")
    anuncios = tuple(_validar_anuncio(a, refs) for a in _lista(c, "anuncios", 1, 50))
    return Conjunto(nombre, presupuesto, tuple(paises), tuple(idiomas), evento, tuple(ubic), anuncios)


def _validar_campana(c: Any) -> Campana:
    c = _exacto(c, "campana", ("nombre", "objetivo", "tipo_presupuesto", "spend_cap", "bid_strategy"),
                ("daily_budget",))
    nombre = _cadena(c, "nombre", 1, 200)
    objetivo = _cadena(c, "objetivo", patron=CODIGO_RE)
    tipo = c["tipo_presupuesto"]
    if tipo not in ("ABO", "CBO") or not isinstance(tipo, str):
        raise _err("tipo_presupuesto debe ser ABO o CBO")
    tope = _importe(c, "spend_cap")
    puja = _cadena(c, "bid_strategy", patron=CODIGO_RE)
    if tipo == "CBO":
        if "daily_budget" not in c:
            raise _err("campana: falta daily_budget (CBO)")
        presupuesto: int | None = _importe(c, "daily_budget")
    else:
        if "daily_budget" in c:
            raise _err("campana: daily_budget solo va en CBO")
        presupuesto = None
    return Campana(nombre, objetivo, tipo, tope, puja, presupuesto)


def _validar_estructura(datos: dict) -> Estructura:
    for k in ("pagina_id", "dataset_id", "medios", "campana", "conjuntos", "unidad", "moneda"):
        if k not in datos:
            raise _err(f"falta el campo {k}")
    pagina = _cadena(datos, "pagina_id", patron=ENTIDAD_ID_RE)
    dataset = _cadena(datos, "dataset_id", patron=ENTIDAD_ID_RE)
    medios = tuple(_validar_medio(m) for m in _lista(datos, "medios", 1, 50))
    refs = [m.ref for m in medios]
    if len(set(refs)) != len(refs):
        raise _err("ref de medios repetida")
    campana = _validar_campana(datos["campana"])
    abo = campana.tipo_presupuesto == "ABO"
    conjuntos = tuple(_validar_conjunto(c, abo, set(refs)) for c in _lista(datos, "conjuntos", 1, 20))
    if datos["unidad"] != "minima" or not isinstance(datos["unidad"], str):
        raise _err('unidad debe ser "minima"')
    moneda = _cadena(datos, "moneda", 3, 3, r"[A-Z]{3}")
    solo = datos.get("solo_validar", False)
    if type(solo) is not bool:
        raise _err("solo_validar debe ser booleano (true o false)")
    return Estructura(pagina, dataset, medios, campana, conjuntos, "minima", moneda, solo)


def _validar_alerta(datos: dict) -> Alerta:
    for k in ("nivel", "titulo", "texto"):
        if k not in datos:
            raise _err(f"falta el campo {k}")
    nivel = datos["nivel"]
    if not isinstance(nivel, str) or nivel not in NIVELES:
        raise _err("nivel debe ser info, aviso o urgente")
    titulo = _cadena(datos, "titulo", 1, 120)
    texto = _cadena(datos, "texto", 1, 3000)
    adj = datos.get("adjuntos", [])
    if not isinstance(adj, list) or len(adj) > 10:
        raise _err("adjuntos debe ser una lista de como mucho 10 rutas")
    return Alerta(nivel, titulo, texto, tuple(_ruta_vault(a, "adjuntos") for a in adj))


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
    creada = _fecha(datos.get("creada"))
    origen = _texto(datos, "origen", 1, 100)
    if tipo == "noop":
        permitidas = COMUNES | {"motivo", "prioridad", "expira_en_min"}
    elif tipo == "alerta":
        permitidas = COMUNES | {"nivel", "titulo", "texto", "adjuntos", "prioridad", "expira_en_min"}
    elif tipo == "crear_estructura_pausada":
        permitidas = COMUNES | {"producto", "pais", "cuenta", "pagina_id", "dataset_id", "medios", "campana",
                                "conjuntos", "unidad", "moneda", "solo_validar", "prioridad", "expira_en_min"}
    else:
        permitidas = COMUNES | OPCIONALES | {"cuenta", "operaciones", "motivo"}
    for k in datos:
        if k not in permitidas:
            raise _err(f"campo no permitido: {k}")
    if tipo in ("alerta", "crear_estructura_pausada"):
        motivo = None
    else:
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
    if tipo == "alerta":
        return Propuesta(**base, cuenta=None, producto=None, pais=None, operaciones=(), evidencia=None,
                         reinicia_aprendizaje=False, alerta=_validar_alerta(datos))
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
    if tipo == "crear_estructura_pausada":
        return Propuesta(**base, cuenta=cuenta, producto=producto, pais=pais, operaciones=(), evidencia=None,
                         reinicia_aprendizaje=False, estructura=_validar_estructura(datos))
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


def _sin_none(d: dict) -> dict:
    return {k: v for k, v in _plano(d).items() if v is not None}


def volcar_propuesta(p: Propuesta) -> dict:
    """Inversa de ``cargar_propuesta``; omite los opcionales ``None``."""
    d: dict[str, Any] = {"version": p.version, "id": p.id, "tipo": p.tipo, "creada": p.creada.isoformat(),
                         "origen": p.origen}
    for k in ("cuenta", "producto", "pais", "motivo"):
        if getattr(p, k) is not None:
            d[k] = getattr(p, k)
    if p.tipo == "alerta":
        d.update(nivel=p.alerta.nivel, titulo=p.alerta.titulo, texto=p.alerta.texto)
        if p.alerta.adjuntos:
            d["adjuntos"] = list(p.alerta.adjuntos)
    elif p.tipo == "crear_estructura_pausada":
        e = p.estructura
        d.update(pagina_id=e.pagina_id, dataset_id=e.dataset_id, medios=_plano([asdict(m) for m in e.medios]),
                 campana=_sin_none(asdict(e.campana)), conjuntos=[_sin_none(asdict(c)) for c in e.conjuntos],
                 unidad=e.unidad, moneda=e.moneda)
        if e.solo_validar:
            d["solo_validar"] = True
    elif p.tipo != "noop":
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
