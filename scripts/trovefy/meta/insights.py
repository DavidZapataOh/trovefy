"""Lector único de las respuestas de ``ads_get_ad_entities`` y ``ads_get_ad_accounts`` del MCP oficial de Meta
(resolución 16 de la fase 3; lo comparten `/leer` y `/cierre`).

**Qué hacen los vídeos:** Claude lee la cuenta por el conector y responde con la tabla por conjunto (C1 54:20; «Hoy:
20,11 gastado · 6 ventas…», L2 19:15). Leer es lectura: Claude nunca escribe en Meta (T3 12:25).

Claude llama al MCP y guarda la respuesta cruda fuera del vault; este módulo solo la interpreta, sin red. La forma
exacta la fija la Tarea 0 del plan 23 con ``ads_get_field_context`` (``docs/notas/leer-campos-meta.md``): aquí se
aceptan solo los nombres de campo de esa nota, planos o dentro de ``insights``/``actions``. Una forma que no se
reconoce no inventa nada: ``[]`` y «no medido: forma de ads_get_ad_entities desconocida». Dinero en ``Decimal``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

Nivel = Literal["campana", "conjunto", "anuncio"]
FORMA_DESCONOCIDA = "no medido: forma de ads_get_ad_entities desconocida"
_NIVELES = {"campaign": "campana", "campana": "campana", "adset": "conjunto", "conjunto": "conjunto",
            "ad": "anuncio", "anuncio": "anuncio"}
_LISTAS = ("ad_entities", "entities", "data", "results", "items")
# Nombres de campo (docs/notas/leer-campos-meta.md). El primero que aparezca gana.
GASTO = ("amount_spent", "spend")
IMPRESIONES = ("impressions",)
CLICS = ("link_click", "inline_link_clicks", "clicks")
VISITAS = ("landing_page_view",)
PAGOS_INICIADOS = ("omni_initiated_checkout", "initiated_checkout", "offsite_conversion.fb_pixel_initiate_checkout")
COMPRAS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
VALOR_COMPRAS = ("omni_purchase_values", "omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")


@dataclass(frozen=True)
class FilaInsight:
    nivel: Nivel
    id: str
    nombre: str
    campana_id: str
    fecha: date | None
    gasto: Decimal | None
    moneda: str | None
    impresiones: int | None
    clics: int | None
    visitas: int | None
    pagos_iniciados: int | None
    compras_pixel: int | None
    valor_pixel: Decimal | None
    conjunto_id: str | None = None
    cpc: Decimal | None = None
    cpm: Decimal | None = None
    ctr: Decimal | None = None
    frecuencia: Decimal | None = None
    estado_meta: str | None = None
    presupuesto_diario: int | None = None  # unidades mínimas de la moneda de la cuenta


@dataclass(frozen=True)
class CuentaLeida:
    id: str
    moneda: str
    zona: str


def _dec(v: object) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d >= 0 else None


def _ent(v: object) -> int | None:
    d = _dec(v)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def _fecha(v: object) -> date | None:
    if isinstance(v, date):
        return v
    if not isinstance(v, str) or len(v) < 10:
        return None
    try:
        return datetime.fromisoformat(v[:10]).date()
    except ValueError:
        return None


def _acciones(lista: object) -> dict[str, object]:
    salida: dict[str, object] = {}
    if isinstance(lista, list):
        for a in lista:
            if isinstance(a, dict) and isinstance(a.get("action_type"), str):
                salida.setdefault(a["action_type"], a.get("value"))
    return salida


def _metricas(fila: dict) -> dict:
    """Las métricas planas de la fila, de ``insights`` (dict o ``{data: [dict]}``) y de ``actions``."""
    m: dict = {}
    ins = fila.get("insights")
    if isinstance(ins, dict) and isinstance(ins.get("data"), list):
        ins = ins["data"][0] if ins["data"] and isinstance(ins["data"][0], dict) else {}
    for fuente in (fila, ins if isinstance(ins, dict) else {}):
        for k, v in fuente.items():
            if k in ("actions", "action_values"):
                continue
            m.setdefault(k, v)
        acc = _acciones(fuente.get("actions"))
        for k, v in acc.items():
            m.setdefault(k, v)
        for k, v in _acciones(fuente.get("action_values")).items():
            m.setdefault(f"valor:{k}", v)
    return m


def _primero(m: dict, nombres: tuple[str, ...], conv):
    for n in nombres:
        if n in m:
            v = conv(m[n])
            if v is not None:
                return v
    return None


def _valor_compras(m: dict) -> Decimal | None:
    if "omni_purchase_values" in m:
        return _dec(m["omni_purchase_values"])
    for n in VALOR_COMPRAS:
        if f"valor:{n}" in m:
            return _dec(m[f"valor:{n}"])
    return None


def _lista(instantanea: object) -> list | None:
    datos = instantanea
    for _ in range(3):
        if isinstance(datos, list):
            return datos
        if not isinstance(datos, dict):
            return None
        if isinstance(datos.get("structuredContent"), dict):
            datos = datos["structuredContent"]
            continue
        if isinstance(datos.get("result"), dict):
            datos = datos["result"]
            continue
        siguiente = next((datos[k] for k in _LISTAS if k in datos), None)
        if siguiente is None:
            return None
        datos = siguiente
    return datos if isinstance(datos, list) else None


def _nivel(fila: dict, por_defecto: str | None) -> str | None:
    for k in ("level", "nivel", "object_type", "type"):
        v = fila.get(k)
        if isinstance(v, str) and v.lower() in _NIVELES:
            return _NIVELES[v.lower()]
    return _NIVELES.get(por_defecto or "")


def leer_insights(instantanea: dict, nivel: str | None = None) -> tuple[list[FilaInsight], list[str]]:
    """Filas por entidad (y por día, si la respuesta viene desglosada). ``nivel`` (``adset``/``ad``/``campaign``)
    vale cuando la fila no lo trae."""
    filas = _lista(instantanea)
    if filas is None:
        return [], [FORMA_DESCONOCIDA]
    moneda_global = instantanea.get("currency") if isinstance(instantanea, dict) else None
    salida: list[FilaInsight] = []
    motivos: list[str] = []
    for f in filas:
        if not isinstance(f, dict):
            continue
        n = _nivel(f, nivel)
        id_ = f.get("id") or f.get({"conjunto": "adset_id", "anuncio": "ad_id", "campana": "campaign_id"}.get(n or ""))
        if n is None or id_ is None:
            motivos.append("no medido: fila de ads_get_ad_entities sin nivel o sin id")
            continue
        m = _metricas(f)
        campana = f.get("campaign_id") or (id_ if n == "campana" else "")
        salida.append(FilaInsight(
            nivel=n, id=str(id_), nombre=str(f.get("name") or f.get("nombre") or ""), campana_id=str(campana or ""),
            fecha=_fecha(m.get("date_stop") or m.get("date_start") or m.get("fecha")),
            gasto=_primero(m, GASTO, _dec), moneda=(m.get("account_currency") or m.get("currency") or moneda_global),
            impresiones=_primero(m, IMPRESIONES, _ent), clics=_primero(m, CLICS, _ent),
            visitas=_primero(m, VISITAS, _ent), pagos_iniciados=_primero(m, PAGOS_INICIADOS, _ent),
            compras_pixel=_primero(m, COMPRAS, _ent), valor_pixel=_valor_compras(m),
            conjunto_id=str(f["adset_id"]) if f.get("adset_id") is not None else (str(id_) if n == "conjunto" else None),
            cpc=_dec(m.get("cpc")), cpm=_dec(m.get("cpm")), ctr=_dec(m.get("ctr")), frecuencia=_dec(m.get("frequency")),
            estado_meta=str(f.get("effective_status") or f.get("status") or "") or None,
            presupuesto_diario=_ent(f.get("daily_budget")),
        ))
    if filas and not salida:
        return [], [FORMA_DESCONOCIDA]
    return salida, list(dict.fromkeys(motivos))


def leer_cuenta(instantanea: dict, act_id: str) -> CuentaLeida | None:
    """Moneda y zona de ``act_id`` en la respuesta de ``ads_get_ad_accounts``; ``None`` si no está."""
    for f in _lista(instantanea) or []:
        if not isinstance(f, dict):
            continue
        ident = str(f.get("id") or f.get("account_id") or "")
        if ident not in (act_id, act_id.removeprefix("act_")):
            continue
        moneda, zona = f.get("currency"), f.get("timezone_name")
        if isinstance(moneda, str) and isinstance(zona, str):
            return CuentaLeida(act_id, moneda, zona)
    return None
