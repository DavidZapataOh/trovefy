"""Lectura viva de Meta antes de cualquier cambio (§5.2, resoluciones 10 y 20).

Solo lee (``leer``/``listar``/``cuenta``): nunca escribe. Todos los importes son enteros en unidades
mínimas de la moneda de la cuenta; un importe que no sea un entero decimal se omite (nunca float) y quien
consume los valores falla cerrado cuando falta.

Presupuestos diarios: ``presupuestos_activos`` y ``suma_diaria_activa`` solo suman ``daily_budget``
(conjuntos ABO y campañas CBO que gastan). Algo que gasta solo con ``lifetime_budget`` no se puede
contar en la suma diaria: ``LecturaIncompleta`` (falla cerrado, nunca se infravalora el gasto).

Quien use esto debe tratar ``presupuesto_al_activar(p) is None`` como desconocido (nunca sumarlo ni
darlo por 0) y convertir ``LecturaIncompleta`` en un rechazo de la propuesta. El estado «gastando» es
una lista negra local (``_NO_GASTA``): el servidor no filtra por estado, así que un estado nuevo de Meta
cuenta como gasto.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from trovefy_ejecutor.graph import InfoCuenta
from trovefy_ejecutor.modelo import Operacion, Propuesta

CAMPOS_LECTURA: dict[str, tuple[str, ...]] = {
    "campaign": ("id", "account_id", "status", "effective_status", "daily_budget", "lifetime_budget", "spend_cap"),
    "adset": ("id", "account_id", "status", "effective_status", "daily_budget", "lifetime_budget", "bid_amount",
              "campaign_id"),
    "ad": ("id", "account_id", "status", "effective_status", "adset_id", "campaign_id"),
    "account": ("id", "currency", "spend_cap", "account_status", "amount_spent"),
}
CAMPOS_IMPORTE = frozenset({"daily_budget", "lifetime_budget", "bid_amount", "spend_cap"})
_ENTEROS = CAMPOS_IMPORTE | {"amount_spent", "account_status"}
_TIPOS_META = ("campaign", "adset", "ad")
_CON_SUMA = frozenset({"presupuesto", "puja", "activar", "lote"})
_CON_ACTIVACION = frozenset({"activar", "lote"})
# «Gastando» = status propio ACTIVE y effective_status fuera de estos (IN_PROCESS, WITH_ISSUES,
# PENDING_REVIEW, PREAPPROVED y PENDING_BILLING_INFO cuentan: contar de más es el lado seguro).
_NO_GASTA = frozenset({"PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "DELETED", "ARCHIVED", "DISAPPROVED"})
_LIMITE_LISTADO = 500
_ENTERO = re.compile(r"-?[0-9]+")


class EntidadAjena(Exception):
    def __init__(self, entidad_id: str, cuenta_viva: str | None):
        self.entidad_id = entidad_id
        self.cuenta_viva = cuenta_viva
        super().__init__(f"la entidad {entidad_id} pertenece a otra cuenta ({cuenta_viva or 'desconocida'})")


def _entero(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and _ENTERO.fullmatch(v):
        return int(v)
    return None


def _normalizar(campo: str, v: object) -> int | str | None:
    if v is None:
        return None
    if campo in _ENTEROS:
        return _entero(v)
    return v if isinstance(v, str) else str(v)


def _gasta(status: object, efectivo: object) -> bool:
    """Un status ausente se da por ACTIVE (contar de más es seguro); effective_status ausente, igual."""
    return (status is None or status == "ACTIVE") and efectivo not in _NO_GASTA


def _activa(op: Operacion) -> bool:
    return op.entidad in _TIPOS_META and op.campo == "status" and op.a == "ACTIVE"


@dataclass(frozen=True)
class ValoresVivos:
    leido_en: datetime
    cuenta: InfoCuenta
    entidades: Mapping[str, Mapping[str, object]]
    suma_diaria_activa: int | None
    presupuestos_activos: Mapping[str, int]
    tipos: Mapping[str, str] = field(default_factory=dict)
    cuenta_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entidades", MappingProxyType({k: MappingProxyType(dict(v))
                                                                for k, v in self.entidades.items()}))
        object.__setattr__(self, "presupuestos_activos", MappingProxyType(dict(self.presupuestos_activos)))
        object.__setattr__(self, "tipos", MappingProxyType(dict(self.tipos)))

    # -- consultas simples -------------------------------------------------------------------
    def valor(self, op: Operacion) -> int | str | None:
        v = self.entidades.get(op.id, {}).get(op.campo)
        return v if isinstance(v, (int, str)) and not isinstance(v, bool) else None

    def status(self, entidad_id: str) -> str | None:
        v = self.entidades.get(entidad_id, {}).get("status")
        return v if isinstance(v, str) else None

    def obsoleta(self, p: Propuesta) -> str | None:
        for op in p.operaciones:
            if op.entidad not in _TIPOS_META and op.entidad != "account":
                continue
            esperado = _normalizar(op.campo, op.de_esperado) if op.de_esperado is not None else None
            vivo = self.valor(op)
            if esperado != vivo:
                return f"{op.id} {op.campo}: esperado {op.de_esperado}, vivo {vivo}"
        return None

    # -- para limites.comprobar --------------------------------------------------------------
    def valores_para_limites(self) -> dict[tuple[str, str], int | str]:
        """``(id, campo) -> valor`` de cada entidad leída (y la cuenta); importes como ``int``."""
        salida: dict[tuple[str, str], int | str] = {}
        for id_, campos in self.entidades.items():
            for campo, v in campos.items():
                if campo != "id" and isinstance(v, (int, str)) and not isinstance(v, bool):
                    salida[(id_, campo)] = v
        return salida

    def _final(self, p: Propuesta) -> dict[str, str]:
        final: dict[str, str] = {}
        for op in p.operaciones:
            if op.entidad in _TIPOS_META and op.campo == "status" and isinstance(op.a, str):
                final[op.id] = op.a
        return final

    def _presupuesto_propio(self, id_: str) -> int | None:
        v = self.entidades.get(id_, {}).get("daily_budget")
        return v if type(v) is int and v > 0 else None

    def presupuesto_al_activar_por_id(self, p: Propuesta) -> dict[str, int]:
        """Presupuesto diario que empezaría a gastar cada operación que activa algo.

        Cada conjunto ABO o campaña CBO que, tras aplicar ``p``, tendría su status y el de su campaña en
        ``ACTIVE`` y hoy no gasta (ver ``_gasta``) se atribuye a una sola operación: la primera que activa
        esa entidad o su campaña; si ninguna, la primera operación que activa algo. Conservador: cuenta
        aunque no tenga anuncios activos. Un padre desconocido se da por ACTIVE.
        Si lo que empezaría a gastar no tiene ``daily_budget`` positivo (solo vitalicio o ninguno, sin
        campaña con presupuesto) no se sabe cuánto: la clave de esa operación queda FUERA del resultado
        (``limites.comprobar`` rechaza con ``valor_vivo_desconocido``). Solo ``activar`` y ``lote``;
        en el resto, ``{}``.
        """
        return self._calcular(p)[0]

    def _calcular(self, p: Propuesta) -> tuple[dict[str, int], bool]:
        if p.tipo not in _CON_ACTIVACION:
            return {}, False
        activas = [op for op in p.operaciones if _activa(op)]
        if not activas:
            return {}, False
        final = self._final(p)
        total: dict[str, int] = {op.id: 0 for op in activas}
        desconocidas: set[str] = set()

        def tras(id_: str) -> str | None:
            return final.get(id_, self.status(id_))

        for id_, tipo in self.tipos.items():
            if tipo not in ("adset", "campaign"):
                continue
            ent = self.entidades[id_]
            if _gasta(ent.get("status"), ent.get("effective_status")):
                continue  # ya gasta hoy: no hay gasto nuevo
            padre = ent.get("campaign_id") if tipo == "adset" else None
            padre = padre if isinstance(padre, str) else None
            if tras(id_) != "ACTIVE" or (padre is not None and tras(padre) not in ("ACTIVE", None)):
                continue
            monto = self._presupuesto_propio(id_)
            if monto is None:
                if tipo == "campaign":
                    continue  # sin presupuesto propio: lo que gaste lo dicen sus conjuntos
                if padre is not None and self._presupuesto_propio(padre) is not None:
                    continue  # CBO: lo cuenta la campaña
            op = next((o for o in activas if o.id in (id_, padre)), activas[0])
            if monto is None:
                desconocidas.add(op.id)
            else:
                total[op.id] += monto
        return {k: v for k, v in total.items() if k not in desconocidas}, bool(desconocidas)

    def presupuesto_al_activar(self, p: Propuesta) -> int | None:
        """Suma de ``presupuesto_al_activar_por_id``; ``None`` si alguna operación que activa algo no
        tiene clave (no se sabe cuánto gastaría). ``0`` para tipos sin activación."""
        por_id = self.presupuesto_al_activar_por_id(p)
        if p.tipo in _CON_ACTIVACION and any(_activa(op) and op.id not in por_id for op in p.operaciones):
            return None
        return sum(por_id.values())


def _ahora() -> datetime:
    return datetime.now(UTC)


class _Lector:
    def __init__(self, p: Propuesta, graph) -> None:
        self.p = p
        self.graph = graph
        self.entidades: dict[str, dict[str, object]] = {}
        self.tipos: dict[str, str] = {}

    def registrar(self, id_: str, tipo: str, crudo: Mapping[str, object]) -> None:
        cuenta = crudo.get("account_id")
        viva = f"act_{cuenta}" if isinstance(cuenta, (str, int)) and str(cuenta) else None
        if viva != self.p.cuenta:
            raise EntidadAjena(id_, viva)
        if id_ in self.entidades:
            return
        limpio: dict[str, object] = {}
        for campo in CAMPOS_LECTURA[tipo]:
            n = _normalizar(campo, crudo.get(campo))
            if n is not None:
                limpio[campo] = n
        self.entidades[id_] = limpio
        self.tipos[id_] = tipo

    def leer(self, id_: str, tipo: str) -> dict[str, object]:
        if id_ not in self.entidades:
            self.registrar(id_, tipo, self.graph.leer(id_, CAMPOS_LECTURA[tipo]))
        return self.entidades[id_]


def valores_vivos(p: Propuesta, graph, *, ahora: Callable[[], datetime] = _ahora) -> ValoresVivos:
    """Lee la cuenta y cada entidad distinta de ``p.operaciones`` (una lectura por id)."""
    if p.cuenta is None:
        raise ValueError("la propuesta no indica cuenta")
    cuenta = p.cuenta
    info = graph.cuenta(cuenta)
    lector = _Lector(p, graph)
    for op in p.operaciones:
        if op.entidad == "account":
            if op.id != cuenta:
                raise EntidadAjena(op.id, None)
        elif op.entidad in _TIPOS_META:
            lector.leer(op.id, op.entidad)
    if p.tipo in _CON_ACTIVACION:
        _leer_contexto_activar(p, lector)
    suma, activos = _presupuestos_activos(p, graph)

    cuenta_vals: dict[str, object] = {"currency": info.currency, "account_status": info.account_status}
    if info.spend_cap is not None:
        cuenta_vals["spend_cap"] = info.spend_cap
    if info.amount_spent is not None:
        cuenta_vals["amount_spent"] = info.amount_spent
    entidades = {**lector.entidades, cuenta: cuenta_vals}
    return ValoresVivos(leido_en=ahora(), cuenta=info, entidades=entidades, suma_diaria_activa=suma,
                        presupuestos_activos=activos, tipos={**lector.tipos, cuenta: "account"},
                        cuenta_id=cuenta)


def _leer_contexto_activar(p: Propuesta, lector: _Lector) -> None:
    """Padres de lo que se activa y, si se activa una campaña, sus conjuntos."""
    for op in p.operaciones:
        if not _activa(op):
            continue
        ent = lector.leer(op.id, op.entidad)
        if op.entidad == "ad" and isinstance(ent.get("adset_id"), str):
            lector.leer(ent["adset_id"], "adset")
        if op.entidad in ("ad", "adset"):
            padre = ent.get("campaign_id")
            if padre is None and op.entidad == "ad":
                padre = lector.entidades.get(str(ent.get("adset_id")), {}).get("campaign_id")
            if isinstance(padre, str):
                lector.leer(padre, "campaign")
        if op.entidad == "campaign":
            for h in lector.graph.listar(op.id, "adsets", CAMPOS_LECTURA["adset"], limite=_LIMITE_LISTADO):
                if isinstance(h.get("id"), str):
                    lector.registrar(h["id"], "adset", h)


def _presupuestos_activos(p: Propuesta, graph) -> tuple[int | None, dict[str, int]]:
    """``daily_budget`` de cada conjunto y campaña que gasta (``_gasta``). Un importe ilegible o negativo
    en algo que gasta lanza ``LecturaIncompleta``; también algo que gasta sin ``daily_budget`` positivo
    pero con ``lifetime_budget`` (su gasto diario no se puede contar en el tope: falla cerrado)."""
    if p.tipo not in _CON_SUMA:
        return None, {}
    return presupuestos_activos_cuenta(graph, p.cuenta)


def presupuestos_activos_cuenta(graph, cuenta: str) -> tuple[int, dict[str, int]]:
    """(extra, plan 12) Suma diaria activa y presupuestos activos de una cuenta, sin propuesta (``/estado``).
    Mismas reglas y excepciones que ``_presupuestos_activos``."""
    activos: dict[str, int] = {}
    for arista in ("adsets", "campaigns"):
        filas = graph.listar(cuenta, arista,
                             ("id", "status", "effective_status", "daily_budget", "lifetime_budget"),
                             limite=_LIMITE_LISTADO)  # sin filtro de estado en el servidor: lista negra local
        for f in filas:
            id_ = f.get("id")
            if not isinstance(id_, str) or not _gasta(f.get("status"), f.get("effective_status")):
                continue
            monto = 0
            if f.get("daily_budget") is not None:
                monto = _entero(f["daily_budget"])
                if monto is None or monto < 0:
                    raise LecturaIncompleta(f"presupuesto diario ilegible en {id_}")
            if monto > 0:
                activos[id_] = monto
                continue
            # Sin presupuesto diario propio: ABO bajo CBO (lo cuenta la campaña) o solo vitalicio.
            vitalicio = f.get("lifetime_budget")
            if vitalicio is not None:
                v = _entero(vitalicio)
                if v is None or v < 0:
                    raise LecturaIncompleta(f"presupuesto total ilegible en {id_}")
                if v > 0:
                    raise LecturaIncompleta(f"{id_} gasta con presupuesto total (lifetime_budget): su gasto "
                                            "diario no se puede contar en el tope")
    return sum(activos.values()), activos


class LecturaIncompleta(Exception):
    """Un importe de lo que gasta no se pudo leer: no se calcula el gasto diario (falla cerrado)."""
