"""Tipos de `/leer` (plan 23, Tarea 2): dataclasses congeladas, dinero en centavos de USD o ``Decimal``.

Dato ausente = ``None`` y su motivo en ``motivos`` («no medido: …»), nunca un número inventado. La lectura normalizada
se guarda en ``trafico/<PAIS>/lecturas/`` (solo números, ids y nombres) con ``a_dict`` y se recupera con
``lectura_de_dict``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

EstadoAnuncio = Literal["APAGAR", "ESPERAR", "MANTENER"]
EstadoOferta = Literal["test", "muerto_sin_ventas", "muerto_con_ventas", "plazo_cumplido", "candidato"]


@dataclass(frozen=True)
class Metricas:
    gasto_usd_c: int | None  # centavos de USD, al alza (nunca se infravalora lo gastado)
    gasto_moneda: Decimal | None  # en la moneda de la cuenta
    moneda: str | None
    impresiones: int | None
    clics: int | None
    visitas: int | None  # landing_page_view
    pi_pixel: int | None  # pagos iniciados del píxel
    compras_pixel: int | None
    valor_pixel_usd: Decimal | None = None

    @property
    def cpc_usd(self) -> Decimal | None:
        if self.gasto_usd_c is None or not self.clics:
            return None
        return (Decimal(self.gasto_usd_c) / 100 / self.clics).quantize(Decimal("0.01"))

    @property
    def cpm_usd(self) -> Decimal | None:
        if self.gasto_usd_c is None or not self.impresiones:
            return None
        return (Decimal(self.gasto_usd_c) * 10 / self.impresiones).quantize(Decimal("0.01"))

    @property
    def ctr(self) -> Decimal | None:
        """Clics en el enlace ÷ impresiones (fracción)."""
        if self.clics is None or not self.impresiones:
            return None
        return (Decimal(self.clics) / self.impresiones).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class Dia:
    """Lo de un día (hoy en la ronda intradía; el día cerrado en el parte) de un conjunto."""

    gasto_usd_c: int | None
    ventas: int | None
    bruto_usd: Decimal | None


@dataclass(frozen=True)
class LecturaConjunto:
    adset_id: str
    ad_id: str | None
    nombre: str
    angulo: str | None
    estado_meta: str | None  # del conjunto
    metricas: Metricas  # acumuladas desde la activación
    ventas: int | None = None  # de la tienda, por utm_content (resolución 17)
    bruto_usd: Decimal | None = None
    presupuesto: int | None = None  # daily_budget vivo, unidades mínimas de la cuenta
    estado_anuncio: str | None = None  # effective_status del anuncio (DISAPPROVED, WITH_ISSUES…)
    hoy: Dia | None = None


@dataclass(frozen=True)
class LecturaOferta:
    producto: str
    pais: str
    campaign_id: str
    moneda: str | None  # de la cuenta
    activacion: datetime | None  # t0 = max(trafico.activado, trafico.inicio)
    ahora: datetime
    dia: date  # el día de la cuenta que se lee (cerrado en el parte; hoy en la ronda)
    intradia: bool
    conjuntos: tuple[LecturaConjunto, ...]
    gasto_usd_c: int | None
    ventas_tienda: int | None
    bruto_tienda_usd: Decimal | None
    ventas_pixel: int | None
    pi_tienda: int | None  # sesiones que vieron el checkout (impultienda_carritos_abandonados)
    intentos_fallidos: int | None
    ventas_dia: int | None  # ventas de la tienda en ``dia``
    spend_cap: int | None  # techo de la campaña, unidades mínimas
    base: int | None  # presupuesto base del conjunto, unidades mínimas
    zona_tienda: str | None
    trm: str | None  # etiqueta de la TRM usada
    motivos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def horas(self) -> Decimal | None:
        if self.activacion is None:
            return None
        return Decimal((self.ahora - self.activacion).total_seconds()) / 3600

    @property
    def clics(self) -> int | None:
        vals = [c.metricas.clics for c in self.conjuntos]
        return None if not vals or any(v is None for v in vals) else sum(vals)

    @property
    def impresiones(self) -> int | None:
        vals = [c.metricas.impresiones for c in self.conjuntos]
        return None if not vals or any(v is None for v in vals) else sum(vals)

    @property
    def visitas(self) -> int | None:
        vals = [c.metricas.visitas for c in self.conjuntos]
        return None if not vals or any(v is None for v in vals) else sum(vals)

    @property
    def pi_pixel(self) -> int | None:
        vals = [c.metricas.pi_pixel for c in self.conjuntos]
        return None if not vals or any(v is None for v in vals) else sum(vals)


@dataclass(frozen=True)
class Veredicto:
    adset_id: str
    nombre: str
    estado: EstadoAnuncio
    por_que: str


@dataclass(frozen=True)
class Corte:
    tipo: Literal["pausar_campana", "pausar_conjuntos"]
    ids: tuple[str, ...]
    motivo: str
    prioridad: Literal["normal", "alta"]
    evidencia: dict


# --- (de)serialización ----------------------------------------------------------------------------------------


def _plano(v: object) -> object:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _plano(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plano(x) for x in v]
    return v


def a_dict(o: LecturaOferta) -> dict:
    return _plano(asdict(o))


def _d(v: object) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _metricas(d: dict) -> Metricas:
    return Metricas(d.get("gasto_usd_c"), _d(d.get("gasto_moneda")), d.get("moneda"), d.get("impresiones"),
                    d.get("clics"), d.get("visitas"), d.get("pi_pixel"), d.get("compras_pixel"),
                    _d(d.get("valor_pixel_usd")))


def _conjunto(d: dict) -> LecturaConjunto:
    hoy = d.get("hoy")
    return LecturaConjunto(
        d["adset_id"], d.get("ad_id"), d.get("nombre", ""), d.get("angulo"), d.get("estado_meta"),
        _metricas(d.get("metricas") or {}), d.get("ventas"), _d(d.get("bruto_usd")), d.get("presupuesto"),
        d.get("estado_anuncio"),
        Dia(hoy.get("gasto_usd_c"), hoy.get("ventas"), _d(hoy.get("bruto_usd"))) if isinstance(hoy, dict) else None)


def lectura_de_dict(d: dict) -> LecturaOferta:
    nombres = {f.name for f in fields(LecturaOferta)}
    x = {k: v for k, v in d.items() if k in nombres}
    x["activacion"] = datetime.fromisoformat(x["activacion"]) if x.get("activacion") else None
    x["ahora"] = datetime.fromisoformat(x["ahora"])
    x["dia"] = date.fromisoformat(x["dia"])
    x["conjuntos"] = tuple(_conjunto(c) for c in x.get("conjuntos") or [])
    x["bruto_tienda_usd"] = _d(x.get("bruto_tienda_usd"))
    x["motivos"] = tuple(x.get("motivos") or ())
    return LecturaOferta(**x)
