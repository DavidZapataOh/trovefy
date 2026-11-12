"""Lectura viva de Meta antes de cualquier cambio (§5.2, resoluciones 10 y 20).

Solo lee (``leer``/``listar``/``cuenta``): nunca escribe. Todos los importes son enteros en unidades
mínimas de la moneda de la cuenta; un importe que no sea un entero decimal se omite (nunca float) y quien
consume los valores falla cerrado cuando falta.

Presupuestos diarios: ``presupuestos_activos`` y ``suma_diaria_activa`` solo suman ``daily_budget``
(conjuntos ABO y campañas CBO con ``effective_status == "ACTIVE"``). Un ``lifetime_budget`` no entra en
la suma diaria.
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
_CON_SUMA = frozenset({"presupuesto", "activar", "lote"})
_CON_ACTIVACION = frozenset({"activar", "lote"})
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
        ``ACTIVE`` y hoy no tiene ``effective_status == "ACTIVE"`` se atribuye a una sola operación: la
        primera que activa esa entidad o su campaña. Conservador: cuenta aunque no tenga anuncios activos.
        Un padre desconocido se da por ACTIVE. Solo ``activar`` y ``lote``; en el resto, ``{}``.
        """
        if p.tipo not in _CON_ACTIVACION:
            return {}
        final = self._final(p)
        salida: dict[str, int] = {}
        for op in p.operaciones:
            if _activa(op):
                salida.setdefault(op.id, 0)

        def tras(id_: str) -> str | None:
            return final.get(id_, self.status(id_))

        for id_, tipo in self.tipos.items():
            if tipo not in ("adset", "campaign"):
                continue
            monto = self._presupuesto_propio(id_)
            if monto is None or self.entidades[id_].get("effective_status") == "ACTIVE":
                continue
            padre = self.entidades[id_].get("campaign_id") if tipo == "adset" else None
            if tras(id_) != "ACTIVE" or (isinstance(padre, str) and tras(padre) not in ("ACTIVE", None)):
                continue
            for op in p.operaciones:
                if _activa(op) and op.id in (id_, padre):
                    salida[op.id] = salida.get(op.id, 0) + monto
                    break
        return salida

    def presupuesto_al_activar(self, p: Propuesta) -> int:
        return sum(self.presupuesto_al_activar_por_id(p).values())


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
                raise EntidadAjena(op.id, op.id)
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
            for h in lector.graph.listar(op.id, "adsets", CAMPOS_LECTURA["adset"]):
                if isinstance(h.get("id"), str):
                    lector.registrar(h["id"], "adset", h)


def _presupuestos_activos(p: Propuesta, graph) -> tuple[int | None, dict[str, int]]:
    if p.tipo not in _CON_SUMA:
        return None, {}
    activos: dict[str, int] = {}
    completo = True
    for arista in ("adsets", "campaigns"):
        filas = graph.listar(p.cuenta, arista, ("id", "daily_budget", "effective_status"),
                             filtros={"effective_status": ["ACTIVE"]})
        for f in filas:
            if f.get("effective_status") != "ACTIVE" or not isinstance(f.get("id"), str):
                continue
            if f.get("daily_budget") is None:
                continue  # sin presupuesto propio (ABO bajo CBO o campaña ABO, o solo vitalicio)
            monto = _entero(f["daily_budget"])
            if monto is None or monto < 0:
                completo = False
            elif monto > 0:
                activos[f["id"]] = monto
    return (sum(activos.values()) if completo else None), activos
