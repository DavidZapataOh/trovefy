"""Carga estricta de limites.yaml (§5.6, D-37): importes por cuenta, en su moneda."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .dinero import Moneda, moneda_configurada
from .esquema import CUENTA_RE
from .modelo import TIPOS

_OFFSETS = (1, 10, 100, 1000)

CLAVES_GLOBALES: frozenset[str] = frozenset({
    "paso_max_pct", "cadencia_min_presupuesto_min", "enfriamiento_puja_estructura_h", "max_cambios_hora_conjunto"})
CLAVES_CUENTA: frozenset[str] = frozenset({
    "tope_gasto_diario_total", "max_presupuesto_conjunto", "max_presupuesto_campana_cbo",
    "spend_cap_test", "spend_cap_test_prorroga"})

_GLOBALES = {"version", "cuentas_permitidas", "acciones_permitidas", "montaje_status_forzado", "cuentas"} | CLAVES_GLOBALES
_CUENTA = {"moneda", "offset", "zona_horaria", "paginas_permitidas", "datasets_permitidos"} | CLAVES_CUENTA


class LimitesInvalidos(Exception):
    pass


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
    zona = d["zona_horaria"]
    try:
        if type(zona) is not str or not zona:
            raise ZoneInfoNotFoundError(zona)
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError, OSError) as e:
        raise LimitesInvalidos(f"{donde}zona_horaria: {zona!r} no es una zona conocida") from e
    importes = {k: _entero(d, k, donde) for k in sorted(CLAVES_CUENTA)}
    return LimitesCuenta(cuenta=cid, moneda_codigo=moneda, offset=off, zona_horaria=zona,
                         paginas_permitidas=_lista_ids(d, "paginas_permitidas", donde),
                         datasets_permitidos=_lista_ids(d, "datasets_permitidos", donde), **importes)


def cargar_limites(ruta: Path, *, exigir_0600: bool = True) -> Limites:
    ruta = Path(ruta)
    try:
        if exigir_0600 and ruta.stat().st_mode & 0o077:
            raise LimitesInvalidos(f"permisos: {ruta} debe ser 0600 (sin acceso de grupo ni otros)")
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise LimitesInvalidos(f"archivo: no se puede leer {ruta}: {e}") from e
    if not isinstance(crudo, dict):
        raise LimitesInvalidos("archivo: debe ser un mapa YAML")
    _revisar_claves(crudo, _GLOBALES, "")
    if type(crudo["version"]) is not int or crudo["version"] != 1:
        raise LimitesInvalidos("version: debe ser 1")
    nums = {k: _entero(crudo, k, "", 100 if k == "paso_max_pct" else None) for k in sorted(CLAVES_GLOBALES)}
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
