"""Carga estricta de limites.yaml (§5.6, D-37): importes por cuenta, en su moneda."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .dinero import (
    OFFSETS_OFICIALES,
    Moneda,
    MonedaNoConfigurada,
    es_importe,
    formatear,
    moneda_configurada,
)
from .esquema import CLAVES_LIMITE_CUENTA, CLAVES_LIMITE_GLOBALES, CUENTA_RE
from .modelo import TIPOS, Operacion, Propuesta

if TYPE_CHECKING:
    from .estado import Almacen

_OFFSETS = (1, 10, 100, 1000)

CLAVES_GLOBALES: frozenset[str] = CLAVES_LIMITE_GLOBALES
CLAVES_CUENTA: frozenset[str] = CLAVES_LIMITE_CUENTA
# Cotas superiores de las claves enteras (además de > 0). Las comparten cargar_limites y comprobar,
# para que un limite_ejecutor aceptado nunca deje un limites.yaml que no carga.
COTAS_MAX: Mapping[str, int] = MappingProxyType({"paso_max_pct": 100})

_GLOBALES = {"version", "cuentas_permitidas", "acciones_permitidas", "montaje_status_forzado", "cuentas"} | CLAVES_GLOBALES
_CUENTA = {"moneda", "offset", "zona_horaria", "paginas_permitidas", "datasets_permitidos"} | CLAVES_CUENTA


class LimitesInvalidos(Exception):
    pass


class _CargadorEstricto(yaml.SafeLoader):
    pass


def _mapa_sin_repetidas(loader: yaml.SafeLoader, nodo: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(nodo)
    vistas: set = set()
    for clave_nodo, _ in nodo.value:
        clave = loader.construct_object(clave_nodo, deep=True)
        if clave in vistas:
            raise LimitesInvalidos(f"{clave}: clave repetida")
        vistas.add(clave)
    return loader.construct_mapping(nodo, deep)


_CargadorEstricto.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapa_sin_repetidas)


@dataclass(frozen=True)
class LimitesCuenta:
    cuenta: str
    moneda_codigo: str
    offset: int | None
    zona_horaria: str
    tope_gasto_diario_total: int
    max_presupuesto_conjunto: int
    max_presupuesto_campana_cbo: int
    spend_cap_test: int
    spend_cap_test_prorroga: int
    paginas_permitidas: frozenset[str]
    datasets_permitidos: frozenset[str]

    def moneda(self) -> Moneda:
        return moneda_configurada(self.moneda_codigo, self.offset)


@dataclass(frozen=True)
class Limites:
    cuentas_permitidas: frozenset[str]
    paso_max_pct: int
    cadencia_min_presupuesto_min: int
    enfriamiento_puja_estructura_h: int
    max_cambios_hora_conjunto: int
    acciones_permitidas: frozenset[str]
    montaje_status_forzado: str
    cuentas: dict[str, LimitesCuenta]


def _revisar_claves(d: dict, permitidas: set[str], donde: str) -> None:
    for k in d:
        if isinstance(k, str) and k.endswith("_usd"):
            raise LimitesInvalidos(f"{donde}{k}: D-37: los importes van por cuenta, en su moneda")
    for k in d:
        if k not in permitidas:
            raise LimitesInvalidos(f"{donde}{k}: clave desconocida")
    for k in sorted(permitidas - set(d)):
        raise LimitesInvalidos(f"{donde}{k}: falta la clave")


def _entero(d: dict, clave: str, donde: str, maximo: int | None = None) -> int:
    v = d[clave]
    if type(v) is not int or v <= 0 or (maximo is not None and v > maximo):
        extra = f" y <= {maximo}" if maximo else ""
        raise LimitesInvalidos(f"{donde}{clave}: debe ser un entero > 0{extra}")
    return v


def _lista_ids(d: dict, clave: str, donde: str) -> frozenset[str]:
    v = d[clave]
    if not isinstance(v, list) or not all(type(x) is str and x for x in v):
        raise LimitesInvalidos(f"{donde}{clave}: debe ser una lista de textos")
    return frozenset(v)


def _cuenta(cid: str, d: object) -> LimitesCuenta:
    donde = f"cuentas.{cid}."
    if not isinstance(d, dict):
        raise LimitesInvalidos(f"cuentas.{cid}: debe ser un mapa")
    _revisar_claves(d, _CUENTA, donde)
    moneda = d["moneda"]
    if type(moneda) is not str or not re.fullmatch(r"[A-Z]{3}", moneda):
        raise LimitesInvalidos(f"{donde}moneda: código de 3 letras mayúsculas")
    off = d["offset"]
    if off is not None and (type(off) is not int or off not in _OFFSETS):
        raise LimitesInvalidos(f"{donde}offset: debe ser null o uno de {list(_OFFSETS)}")
    if off is not None:
        if moneda not in OFFSETS_OFICIALES:
            raise LimitesInvalidos(f"{donde}offset: moneda sin offset oficial conocido (P-21)")
        if off != OFFSETS_OFICIALES[moneda]:
            raise LimitesInvalidos(f"{donde}offset: {moneda} usa {OFFSETS_OFICIALES[moneda]}, no {off}")
    zona = d["zona_horaria"]
    try:
        if type(zona) is not str or not zona:
            raise ZoneInfoNotFoundError(zona)
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError, OSError) as e:
        raise LimitesInvalidos(f"{donde}zona_horaria: {zona!r} no es una zona conocida") from e
    importes = {k: _entero(d, k, donde, COTAS_MAX.get(k)) for k in sorted(CLAVES_CUENTA)}
    return LimitesCuenta(cuenta=cid, moneda_codigo=moneda, offset=off, zona_horaria=zona,
                         paginas_permitidas=_lista_ids(d, "paginas_permitidas", donde),
                         datasets_permitidos=_lista_ids(d, "datasets_permitidos", donde), **importes)


def cargar_limites(ruta: Path, *, exigir_0600: bool = True) -> Limites:
    ruta = Path(ruta)
    try:
        if exigir_0600 and ruta.stat().st_mode & 0o077:
            raise LimitesInvalidos(f"permisos: {ruta} debe ser 0600 (sin acceso de grupo ni otros)")
        crudo = yaml.load(ruta.read_text(encoding="utf-8"), Loader=_CargadorEstricto)
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise LimitesInvalidos(f"archivo: no se puede leer {ruta}: {e}") from e
    if not isinstance(crudo, dict):
        raise LimitesInvalidos("archivo: debe ser un mapa YAML")
    _revisar_claves(crudo, _GLOBALES, "")
    if type(crudo["version"]) is not int or crudo["version"] != 1:
        raise LimitesInvalidos("version: debe ser 1")
    nums = {k: _entero(crudo, k, "", COTAS_MAX.get(k)) for k in sorted(CLAVES_GLOBALES)}
    if crudo["montaje_status_forzado"] != "PAUSED":
        raise LimitesInvalidos("montaje_status_forzado: debe ser PAUSED")
    acc = crudo["acciones_permitidas"]
    if not isinstance(acc, list) or not all(type(a) is str for a in acc):
        raise LimitesInvalidos("acciones_permitidas: debe ser una lista de textos")
    for a in acc:
        if a not in TIPOS:
            raise LimitesInvalidos(f"acciones_permitidas: {a!r} no es un tipo conocido")
    perm = crudo["cuentas_permitidas"]
    if not isinstance(perm, list) or not perm or not all(type(c) is str and re.fullmatch(CUENTA_RE, c) for c in perm):
        raise LimitesInvalidos("cuentas_permitidas: lista no vacía de ids act_<dígitos>")
    secciones = crudo["cuentas"]
    if not isinstance(secciones, dict):
        raise LimitesInvalidos("cuentas: debe ser un mapa")
    for cid in secciones:
        if type(cid) is not str or not re.fullmatch(CUENTA_RE, cid):
            raise LimitesInvalidos(f"cuentas.{cid}: clave de cuenta inválida")
    for cid in perm:
        if cid not in secciones:
            raise LimitesInvalidos(f"cuentas.{cid}: cuenta permitida sin sección")
    return Limites(cuentas_permitidas=frozenset(perm), acciones_permitidas=frozenset(acc),
                   montaje_status_forzado="PAUSED",
                   cuentas={cid: _cuenta(cid, d) for cid, d in secciones.items()}, **nums)



_CUENTA_PUBLICA = ("tope_gasto_diario_total", "max_presupuesto_conjunto", "max_presupuesto_campana_cbo",
                   "spend_cap_test", "spend_cap_test_prorroga")


def limites_a_dict(l: Limites) -> dict:
    """(extra) Contenido de ``estado/limites.json`` (resolución 12): claves globales y, por cuenta, moneda,
    offset, zona e importes en unidades mínimas. Sin páginas ni datasets; serializable a JSON."""
    d: dict = {"version": 1, "cuentas_permitidas": sorted(l.cuentas_permitidas),
               "acciones_permitidas": sorted(l.acciones_permitidas),
               "montaje_status_forzado": l.montaje_status_forzado}
    d.update({k: getattr(l, k) for k in sorted(CLAVES_GLOBALES)})
    d["cuentas"] = {cid: {"moneda": lc.moneda_codigo, "offset": lc.offset, "zona_horaria": lc.zona_horaria,
                          **{k: getattr(lc, k) for k in _CUENTA_PUBLICA}}
                    for cid, lc in sorted(l.cuentas.items())}
    return d


# --- Validación del ejecutor (§5.2, Tarea 7) -----------------------------------------------------
# Falla cerrada: un valor vivo ausente o mal tipado es una violación, nunca un «pasa». Todas las
# comparaciones son enteras, en unidades mínimas de la moneda de la cuenta; nada pasa a float.

MARGEN_RELOJ = timedelta(minutes=5)
CAMPOS_CAMBIO = ("daily_budget", "bid_amount", "estructura")  # contrato con el plan 11 (registrar_cambio)
_MAPAS = ("valores", "presupuestos_activos", "presupuesto_al_activar", "ultimos_cambios", "cambios_ultima_hora")


@dataclass(frozen=True)
class ContextoVivo:
    ahora: datetime
    stop: bool
    valores: Mapping[tuple[str, str], int | str]
    presupuestos_activos: Mapping[str, int]
    presupuesto_al_activar: Mapping[str, int]
    ultimos_cambios: Mapping[tuple[str, str], datetime]
    cambios_ultima_hora: Mapping[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.ahora, datetime) or self.ahora.utcoffset() is None:
            raise ValueError("ContextoVivo.ahora: se exige datetime con zona horaria")
        if type(self.stop) is not bool:
            raise ValueError("ContextoVivo.stop: debe ser booleano")
        for nombre in _MAPAS:
            object.__setattr__(self, nombre, MappingProxyType(dict(getattr(self, nombre))))


def _no_negativo(v: object) -> bool:
    return type(v) is int and v >= 0


def _es_presupuesto(op: Operacion) -> bool:
    return op.campo == "daily_budget" and op.entidad in ("adset", "campaign")


def _es_activar(op: Operacion) -> bool:
    return op.campo == "status" and op.a == "ACTIVE"


@dataclass(frozen=True)
class _Caso:
    p: Propuesta
    lim: Limites
    ctx: ContextoVivo
    lc: LimitesCuenta | None

    def fmt(self, n: int) -> str:
        try:
            return formatear(n, self.lc.moneda()) if self.lc else f"{n} (unidades mínimas)"
        except MonedaNoConfigurada:
            return f"{n} (unidades mínimas)"

    def simular(self) -> tuple[int, int, str | None]:
        """Total diario activo antes y después de aplicar las operaciones; y qué no se sabe calcular.

        El resultado no depende del orden: un cambio de presupuesto sobre una entidad inactiva queda
        pendiente y se usa si esa misma entidad se activa en la propuesta. Si queda alguno pendiente
        mientras se activa otra entidad (p. ej. su campaña), no se sabe qué empezaría a gastar: se
        devuelve ``"mezcla"``. ``"activar"`` = se activa algo cuyo presupuesto al activar se desconoce.
        """
        sim = dict(self.ctx.presupuestos_activos)
        if not all(_no_negativo(v) for v in sim.values()):
            return 0, 0, "activos"
        antes = sum(sim.values())
        inactivos_con_presupuesto = {op.id for op in self.p.operaciones if _es_presupuesto(op) and op.id not in sim}
        activados = {op.id for op in self.p.operaciones if _es_activar(op) and op.id not in sim}
        if inactivos_con_presupuesto and activados - inactivos_con_presupuesto:
            return antes, antes, "mezcla"
        pendientes: dict[str, int] = {}
        motivo: str | None = None
        for op in self.p.operaciones:
            if _es_presupuesto(op):
                if op.id in sim:
                    sim[op.id] = op.a
                else:
                    pendientes[op.id] = op.a
            elif _es_activar(op) and op.id not in sim:
                v = self.ctx.presupuesto_al_activar.get(op.id)
                if not _no_negativo(v):
                    motivo = "activar"
                    continue
                # Con un cambio pendiente se cuenta lo mayor: nunca se infravalora lo que empezará a gastar.
                sim[op.id] = max(v, pendientes.pop(op.id, 0))
        return antes, sum(sim.values()), motivo


Regla = Callable[[_Caso], list[str]]


def _r_futuro(c: _Caso) -> list[str]:
    if c.p.creada > c.ctx.ahora + MARGEN_RELOJ:
        return [(f"creada_en_el_futuro: creada {c.p.creada.isoformat()} va más de 5 min por delante "
                f"del reloj del ejecutor ({c.ctx.ahora.isoformat()})")]
    return []


def _r_stop(c: _Caso) -> list[str]:
    return ["stop_activo: STOP activo; no se ejecuta nada hasta /reanudar"] if c.ctx.stop else []


def _r_cuenta(c: _Caso) -> list[str]:
    if c.p.cuenta is None:
        if c.p.tipo == "limite_ejecutor":
            return []
        return ["cuenta_no_permitida: la propuesta no indica cuenta"]
    if c.p.cuenta not in c.lim.cuentas_permitidas or c.lc is None:
        return [f"cuenta_no_permitida: {c.p.cuenta} no está en cuentas_permitidas"]
    return []


def _r_tipo(c: _Caso) -> list[str]:
    if c.p.tipo not in c.lim.acciones_permitidas:
        return [f"tipo_no_permitido: {c.p.tipo} no está en acciones_permitidas"]
    return []


def _tiene_importes(c: _Caso) -> bool:
    if c.p.estructura is not None or any(op.unidad is not None for op in c.p.operaciones):
        return True
    if any(_es_activar(op) for op in c.p.operaciones):
        antes, despues, motivo = c.simular()
        return motivo is not None or despues > antes
    return False


def _moneda_limite_ejecutor(c: _Caso) -> list[str]:
    """Cada clave de dinero va en la moneda de la cuenta que cambia (su ``id``), con offset confirmado."""
    v: list[str] = []
    for op in c.p.operaciones:
        lc = c.lim.cuentas.get(op.id)
        if op.unidad is None or lc is None:
            continue  # clave entera, o cuenta desconocida (lo dice clave_limite_desconocida)
        try:
            lc.moneda()
        except MonedaNoConfigurada:
            v.append(f"moneda_no_configurada: {lc.moneda_codigo} sin offset confirmado (P-21)")
            continue
        if op.moneda != lc.moneda_codigo:
            v.append(f"moneda_distinta: {op.campo} de {op.id} en {op.moneda}; la cuenta usa {lc.moneda_codigo}")
    return v


def _r_moneda(c: _Caso) -> list[str]:
    if c.p.tipo == "limite_ejecutor":
        return _moneda_limite_ejecutor(c)
    if not _tiene_importes(c):
        return []
    if c.lc is None:
        return ["cuenta_no_permitida: importes sin cuenta de la que tomar la moneda"]
    try:
        c.lc.moneda()
    except MonedaNoConfigurada:
        return [f"moneda_no_configurada: {c.lc.moneda_codigo} sin offset confirmado (P-21)"]
    codigo = c.lc.moneda_codigo
    v = [f"moneda_distinta: operación sobre {op.id} en {op.moneda}; la cuenta usa {codigo}"
         for op in c.p.operaciones if op.unidad is not None and op.moneda != codigo]
    if c.p.estructura is not None and c.p.estructura.moneda != codigo:
        v.append(f"moneda_distinta: estructura en {c.p.estructura.moneda}; la cuenta usa {codigo}")
    return v


def _op_presupuesto(c: _Caso, op: Operacion) -> list[str]:
    lc, lim, ctx, v = c.lc, c.lim, c.ctx, []
    maximo = lc.max_presupuesto_conjunto if op.entidad == "adset" else lc.max_presupuesto_campana_cbo
    nombre = "max_presupuesto_conjunto" if op.entidad == "adset" else "max_presupuesto_campana_cbo"
    if op.a > maximo:
        v.append(f"importe_sobre_limite: {op.entidad} {op.id} a {c.fmt(op.a)} supera {nombre} ({c.fmt(maximo)})")
    vivo = ctx.valores.get((op.id, "daily_budget"))
    if not es_importe(vivo):
        v.append(f"valor_vivo_desconocido: no se conoce el daily_budget vivo de {op.id}")
    elif op.a * 100 > vivo * (100 + lim.paso_max_pct):
        v.append(f"paso_excesivo: {op.id} de {c.fmt(vivo)} a {c.fmt(op.a)} sube más del {lim.paso_max_pct} %")
    ultimo = ctx.ultimos_cambios.get((op.id, "daily_budget"))
    if ultimo is not None and ctx.ahora - ultimo < timedelta(minutes=lim.cadencia_min_presupuesto_min):
        hace = int((ctx.ahora - ultimo).total_seconds() // 60)
        v.append(f"cadencia_presupuesto: {op.id} cambió de presupuesto hace {hace} min "
                 f"(mínimo {lim.cadencia_min_presupuesto_min} min)")
    n = ctx.cambios_ultima_hora.get(op.id, 0)
    if type(n) is not int or n >= lim.max_cambios_hora_conjunto:
        v.append(f"max_cambios_hora: {op.id} lleva {n} cambios de presupuesto en la última hora "
                 f"(máximo {lim.max_cambios_hora_conjunto})")
    return v


def _op_puja(c: _Caso, op: Operacion) -> list[str]:
    horas = c.lim.enfriamiento_puja_estructura_h
    v = []
    for campo in ("bid_amount", "estructura"):
        ultimo = c.ctx.ultimos_cambios.get((op.id, campo))
        if ultimo is not None and c.ctx.ahora - ultimo < timedelta(hours=horas):
            hace = int((c.ctx.ahora - ultimo).total_seconds() // 3600)
            v.append(f"enfriamiento_puja_estructura: {op.id} cambió {campo} hace {hace} h (mínimo {horas} h)")
    return v


def _sube_gasto_fuera_de_activos(c: _Caso, op: Operacion) -> list[str]:
    """Subir presupuesto o puja de algo que no figura entre los activos solo si se sabe que está PAUSED."""
    if op.id in c.ctx.presupuestos_activos:
        return []
    vivo = c.ctx.valores.get((op.id, op.campo))
    if es_importe(vivo) and op.a <= vivo:
        return []
    if c.ctx.valores.get((op.id, "status")) == "PAUSED":
        return []
    return [(f"valor_vivo_desconocido: {op.id} no figura entre los presupuestos activos y no se sabe "
            f"que esté PAUSED; no se sube su {op.campo}")]


def _r_operaciones(c: _Caso) -> list[str]:
    v: list[str] = []
    for op in c.p.operaciones:
        if (_es_presupuesto(op) or op.campo == "bid_amount") and type(op.a) is int:
            v += _sube_gasto_fuera_de_activos(c, op)
        if _es_presupuesto(op) and c.lc is not None:
            v += _op_presupuesto(c, op)
        elif _es_activar(op) and not _no_negativo(c.ctx.presupuesto_al_activar.get(op.id)):
            v.append(f"valor_vivo_desconocido: no se sabe qué presupuesto empezaría a gastar {op.id} al activarse")
        elif op.campo == "bid_amount":
            v += _op_puja(c, op)
        elif op.entidad == "campaign" and op.campo == "spend_cap" and c.lc is not None:
            if op.a > c.lc.spend_cap_test_prorroga:
                v.append(f"importe_sobre_limite: spend_cap de {op.id} a {c.fmt(op.a)} supera "
                         f"spend_cap_test_prorroga ({c.fmt(c.lc.spend_cap_test_prorroga)})")
        elif op.entidad == "ejecutor":
            ok = ((op.id == "global" and op.campo in CLAVES_GLOBALES)
                  or (op.id in c.lim.cuentas_permitidas and op.campo in CLAVES_CUENTA))
            if not ok:
                v.append(f"clave_limite_desconocida: {op.campo} no es una clave de límite de {op.id}")
            elif type(op.a) is not int or op.a <= 0 or op.a > COTAS_MAX.get(op.campo, op.a):
                extra = f" y <= {COTAS_MAX[op.campo]}" if op.campo in COTAS_MAX else ""
                v.append(f"limite_fuera_de_cota: {op.campo} = {op.a!r}; debe ser un entero > 0{extra}")
    return v


def _r_tope(c: _Caso) -> list[str]:
    if c.lc is None or not c.p.operaciones:
        return []
    if not all(_no_negativo(x) for x in c.ctx.presupuestos_activos.values()):
        return ["valor_vivo_desconocido: presupuestos_activos con valores que no son enteros"]
    antes, despues, motivo = c.simular()
    if motivo == "mezcla":
        return [("valor_vivo_desconocido: la propuesta cambia el presupuesto de una entidad inactiva y activa "
                "otra; no se sabe qué gasto diario empezaría")]
    tope = c.lc.tope_gasto_diario_total
    # Solo frena lo que sube el gasto: pausar o bajar con la cuenta ya por encima del tope reduce el riesgo.
    if despues > tope and despues > antes:
        return [(f"tope_diario_cuenta: el gasto diario activo pasaría de {c.fmt(antes)} a {c.fmt(despues)}, "
                f"por encima de tope_gasto_diario_total ({c.fmt(tope)})")]
    return []


def _r_estructura(c: _Caso) -> list[str]:
    e, lc = c.p.estructura, c.lc
    if e is None or lc is None:
        return []
    v = []
    if e.pagina_id not in lc.paginas_permitidas:
        v.append(f"pagina_no_permitida: {e.pagina_id} no está en paginas_permitidas")
    if e.dataset_id not in lc.datasets_permitidos:
        v.append(f"dataset_no_permitido: {e.dataset_id} no está en datasets_permitidos")
    if e.campana.spend_cap > lc.spend_cap_test:
        v.append(f"spend_cap_sobre_limite: spend_cap {c.fmt(e.campana.spend_cap)} supera "
                 f"spend_cap_test ({c.fmt(lc.spend_cap_test)})")
    if e.campana.tipo_presupuesto == "CBO":
        presupuestos = [e.campana.daily_budget]
        if e.campana.daily_budget > lc.max_presupuesto_campana_cbo:
            v.append(f"importe_sobre_limite: campaña {c.fmt(e.campana.daily_budget)} supera "
                     f"max_presupuesto_campana_cbo ({c.fmt(lc.max_presupuesto_campana_cbo)})")
    else:
        presupuestos = [cj.daily_budget for cj in e.conjuntos]
        for cj in e.conjuntos:
            if cj.daily_budget > lc.max_presupuesto_conjunto:
                v.append(f"importe_sobre_limite: conjunto «{cj.nombre}» {c.fmt(cj.daily_budget)} supera "
                         f"max_presupuesto_conjunto ({c.fmt(lc.max_presupuesto_conjunto)})")
    total = sum(presupuestos)
    if total > lc.tope_gasto_diario_total:
        v.append(f"tope_diario_cuenta: la estructura sola suma {c.fmt(total)} al día, por encima de "
                 f"tope_gasto_diario_total ({c.fmt(lc.tope_gasto_diario_total)})")
    return v


# (regla, corta): si una regla que corta devuelve algo, no se mira más.
_NOTIFICACION: tuple[tuple[Regla, bool], ...] = ((_r_futuro, False), (_r_tipo, False))
_BASICAS: tuple[tuple[Regla, bool], ...] = (
    (_r_futuro, False), (_r_stop, False), (_r_cuenta, True), (_r_tipo, False), (_r_moneda, True))
_COMPLETAS = _BASICAS + ((_r_operaciones, False), (_r_tope, False), (_r_estructura, False))
_SOLO_BASICAS = frozenset({"agenda", "regla_meta"})  # su contenido lo valida el plan 11 (P-07)


def comprobar(propuesta: Propuesta, limites: Limites, ctx: ContextoVivo) -> list[str]:
    """Violaciones ``codigo: detalle`` de §5.2, sin duplicados y en orden estable; vacía si pasa."""
    lc = limites.cuentas.get(propuesta.cuenta) if propuesta.cuenta is not None else None
    caso = _Caso(propuesta, limites, ctx, lc)
    if propuesta.clase == "notificacion":
        reglas = _NOTIFICACION
    elif propuesta.tipo in _SOLO_BASICAS:
        reglas = _BASICAS
    else:
        reglas = _COMPLETAS
    v: list[str] = []
    for regla, corta in reglas:
        nuevas = regla(caso)
        v += nuevas
        if corta and nuevas:
            break
    return list(dict.fromkeys(v))


def contexto_para(p: Propuesta, almacen: Almacen, *, ahora: datetime, stop: bool,
                  valores: Mapping[tuple[str, str], int | str], presupuestos_activos: Mapping[str, int],
                  presupuesto_al_activar: Mapping[str, int]) -> ContextoVivo:
    """(extra) Completa el contexto con la cadencia guardada en el Almacen.

    Contrato con el plan 11: al ejecutar con éxito registra ``registrar_cambio(id, campo)`` con los
    campos de ``CAMPOS_CAMBIO``, y ``"estructura"`` en cada objeto creado por ``crear_estructura_pausada``.
    """
    ids = list(dict.fromkeys(op.id for op in p.operaciones if op.entidad not in ("ejecutor", "account")))
    ultimos: dict[tuple[str, str], datetime] = {}
    for id_ in ids:
        for campo in CAMPOS_CAMBIO:
            u = almacen.ultimo_cambio(id_, campo)
            if u is not None:
                ultimos[(id_, campo)] = u
    hora = ahora - timedelta(hours=1)
    cambios = {id_: almacen.cambios_desde(id_, "daily_budget", hora) for id_ in ids}
    return ContextoVivo(ahora=ahora, stop=stop, valores=valores, presupuestos_activos=presupuestos_activos,
                        presupuesto_al_activar=presupuesto_al_activar, ultimos_cambios=ultimos,
                        cambios_ultima_hora=cambios)
