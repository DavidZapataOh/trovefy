"""Carga, validación y edición de ``config/economia.yaml``. Cada hoja es ``{valor, fuente, fecha}``.

``valor: null`` es «no medido»: lo que depende de él sale «no medido: falta <clave> en
config/economia.yaml», nunca un 0 ni un supuesto. Todos los números salen en ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.economia.modelo import Cifra, Costes, Tomas
from trovefy.secretos import buscar_secreto
from trovefy.vault.escritura import escribir_atomico

PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "economia.yaml"
RELATIVA = Path("config") / "economia.yaml"
EJES = ("resultado_sonado", "probabilidad_percibida", "tiempo", "esfuerzo", "avatar", "mecanismo", "precio",
        "prueba_garantia")
CAMPOS_HOJA = ("valor", "fuente", "fecha")
CABECERA = (
    "# Economía de la oferta: rutas de cobro, comisiones, reembolsos, tomas, reglas de CPA, escalera y autopsia.\n"
    "# Cada hoja lleva {valor, fuente, fecha}. valor null = no medido: la cifra que depende de él sale\n"
    "# «no medido: falta <clave> en config/economia.yaml», nunca un 0 ni un supuesto.\n"
    "# Para cambiar un valor: `trovefy economia fijar <clave> <valor> --fuente \"…\"` (la explicación va en la fuente).\n"
)
_CAMPOS_COSTE = ("comision_pct", "comision_fija_usd", "impuestos_pct")


class EconomiaInvalida(ValueError):
    """``config/economia.yaml`` no cumple el formato."""


@dataclass(frozen=True)
class ReglasEconomia:
    cpa_test_factor: Decimal
    cpa_escala_factor: Decimal
    be_minimo_usd: Decimal
    aov_objetivo_usd: Decimal


@dataclass(frozen=True)
class ReglasEscalera:
    front_eur: tuple[Decimal, Decimal]
    front_usd: tuple[Decimal, Decimal]
    precio_minimo: Decimal
    bump: Decimal
    u1: Decimal
    u2: Decimal
    u3: Decimal
    downsell: Decimal
    downsell_rango: tuple[Decimal, Decimal]
    bump_activo_test1: bool


@dataclass(frozen=True)
class ReglasAutopsia:
    pesos: dict[str, int]
    mejora_min_puntos: int
    mejora_eje_min: int
    cobertura_min: int
    nota_media: tuple[int, int]


@dataclass(frozen=True)
class PlataformaCostes:
    comision_pct: Decimal | None
    comision_fija_usd: Decimal | None
    impuestos_pct: Decimal | None
    upsells_por_plan: int | None
    admite_downsell: bool | None


@dataclass(frozen=True)
class ConfigEconomia:
    ruta_activa: str | None
    rutas: dict[str, tuple[str, ...]]
    plataformas: dict[str, PlataformaCostes]
    reembolsos_pct: Decimal
    tomas: Tomas
    reglas: ReglasEconomia
    escalera: ReglasEscalera
    autopsia: ReglasAutopsia


# --- validación de hojas -------------------------------------------------------------------------


def _es_hoja(nodo: Any) -> bool:
    return isinstance(nodo, dict) and any(c in nodo for c in CAMPOS_HOJA)


def _revisar_hojas(nodo: Any, clave: str) -> None:
    """Toda hoja del árbol trae exactamente ``valor``, ``fuente`` (texto) y ``fecha`` (AAAA-MM-DD)."""
    if _es_hoja(nodo):
        faltan = [c for c in CAMPOS_HOJA if c not in nodo]
        if faltan:
            raise EconomiaInvalida(f"{clave}: a la hoja le falta {', '.join(faltan)}")
        sobran = sorted(set(nodo) - set(CAMPOS_HOJA))
        if sobran:
            raise EconomiaInvalida(f"{clave}: campos desconocidos en la hoja: {', '.join(map(str, sobran))}")
        if not isinstance(nodo["fuente"], str) or not nodo["fuente"].strip():
            raise EconomiaInvalida(f"{clave}: la fuente está vacía")
        fecha = nodo["fecha"]
        if not isinstance(fecha, date):
            try:
                date.fromisoformat(str(fecha))
            except ValueError:
                raise EconomiaInvalida(f"{clave}: fecha ilegible ({fecha!r}), usa AAAA-MM-DD") from None
        return
    if not isinstance(nodo, dict):
        raise EconomiaInvalida(f"{clave}: no es una hoja {{valor, fuente, fecha}}")
    for k, v in nodo.items():
        _revisar_hojas(v, f"{clave}.{k}" if clave else str(k))


def _nodo(datos: dict, clave: str) -> Any:
    actual: Any = datos
    for parte in clave.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            raise EconomiaInvalida(f"falta {clave} en config/economia.yaml")
        actual = actual[parte]
    return actual


def _valor(datos: dict, clave: str) -> Any:
    hoja = _nodo(datos, clave)
    if not _es_hoja(hoja):
        raise EconomiaInvalida(f"{clave}: no es una hoja {{valor, fuente, fecha}}")
    return hoja["valor"]


def _dec(v: Any, clave: str, *, pct: bool = False, nulo: bool = False) -> Decimal | None:
    if v is None:
        if nulo:
            return None
        raise EconomiaInvalida(f"{clave}: hace falta un valor (no admite null)")
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise EconomiaInvalida(f"{clave}: número ilegible ({v!r})")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise EconomiaInvalida(f"{clave}: número ilegible ({v!r})") from None
    if not d.is_finite() or d < 0:
        raise EconomiaInvalida(f"{clave}: debe ser un número >= 0 ({v!r})")
    if pct and d > 1:
        raise EconomiaInvalida(f"{clave}: es un porcentaje entre 0 y 1 ({v!r})")
    return d


def _ent(v: Any, clave: str, *, nulo: bool = False) -> int | None:
    if v is None and nulo:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise EconomiaInvalida(f"{clave}: debe ser un entero >= 0 ({v!r})")
    return v


def _bool(v: Any, clave: str, *, nulo: bool = False) -> bool | None:
    if v is None and nulo:
        return None
    if not isinstance(v, bool):
        raise EconomiaInvalida(f"{clave}: debe ser true o false ({v!r})")
    return v


def _par(v: Any, clave: str, conv) -> tuple:
    if not isinstance(v, list) or len(v) != 2:
        raise EconomiaInvalida(f"{clave}: debe ser [mínimo, máximo]")
    lo, hi = conv(v[0], clave), conv(v[1], clave)
    if lo > hi:
        raise EconomiaInvalida(f"{clave}: el mínimo supera al máximo")
    return lo, hi


def _mapa(datos: dict, clave: str) -> dict:
    nodo = _nodo(datos, clave)
    if not isinstance(nodo, dict) or _es_hoja(nodo):
        raise EconomiaInvalida(f"{clave}: debe ser un mapa de hojas")
    return nodo


# --- construcción ----------------------------------------------------------------------------------


def _construir(datos: Any) -> ConfigEconomia:
    if not isinstance(datos, dict):
        raise EconomiaInvalida("config/economia.yaml no es un mapa")
    _revisar_hojas(datos, "")

    plataformas: dict[str, PlataformaCostes] = {}
    for nombre, nodo in _mapa(datos, "plataformas").items():
        base = f"plataformas.{nombre}"
        if not isinstance(nodo, dict) or _es_hoja(nodo):
            raise EconomiaInvalida(f"{base}: debe ser un mapa de hojas")
        pcts = {c: _dec(_valor(datos, f"{base}.{c}"), f"{base}.{c}", pct=c.endswith("_pct"), nulo=True)
                for c in _CAMPOS_COSTE}
        ups = _ent(_valor(datos, f"{base}.upsells_por_plan"), f"{base}.upsells_por_plan", nulo=True) \
            if "upsells_por_plan" in nodo else None
        down = _bool(_valor(datos, f"{base}.admite_downsell"), f"{base}.admite_downsell", nulo=True) \
            if "admite_downsell" in nodo else None
        plataformas[str(nombre)] = PlataformaCostes(**pcts, upsells_por_plan=ups, admite_downsell=down)

    rutas: dict[str, tuple[str, ...]] = {}
    for nombre in _mapa(datos, "rutas"):
        clave = f"rutas.{nombre}"
        capas = _valor(datos, clave)
        if not isinstance(capas, list) or not capas or not all(isinstance(c, str) and c for c in capas):
            raise EconomiaInvalida(f"{clave}: debe ser una lista de plataformas")
        desconocidas = [c for c in capas if c not in plataformas]
        if desconocidas:
            raise EconomiaInvalida(f"{clave}: plataformas que no están en plataformas: {', '.join(desconocidas)}")
        rutas[str(nombre)] = tuple(capas)

    ruta_activa = _valor(datos, "ruta_activa")
    if ruta_activa is not None and (not isinstance(ruta_activa, str) or ruta_activa not in rutas):
        raise EconomiaInvalida(f"ruta_activa: {ruta_activa!r} no está en rutas ({', '.join(rutas)})")

    def d(clave: str, pct: bool = False) -> Decimal:
        return _dec(_valor(datos, clave), clave, pct=pct)

    tomas = Tomas(d("tomas.bump", True), d("tomas.u1", True), d("tomas.downsell", True))
    reglas = ReglasEconomia(d("reglas.cpa_test_factor"), d("reglas.cpa_escala_factor"),
                            d("reglas.be_minimo_usd"), d("reglas.aov_objetivo_usd"))

    def par_dec(clave: str, pct: bool = False) -> tuple[Decimal, Decimal]:
        return _par(_valor(datos, clave), clave, lambda v, k: _dec(v, k, pct=pct))

    rango = par_dec("escalera.downsell_rango", True)
    escalera = ReglasEscalera(
        front_eur=par_dec("escalera.front_eur"),
        front_usd=par_dec("escalera.front_usd"),
        precio_minimo=d("escalera.precio_minimo"),
        bump=d("escalera.bump"),
        u1=d("escalera.u1"),
        u2=d("escalera.u2"),
        u3=d("escalera.u3"),
        downsell=d("escalera.downsell"),
        downsell_rango=rango,
        bump_activo_test1=_bool(_valor(datos, "escalera.bump_activo_test1"), "escalera.bump_activo_test1"),
    )
    if not rango[0] <= escalera.downsell <= rango[1]:
        raise EconomiaInvalida(f"escalera.downsell: {escalera.downsell} queda fuera de escalera.downsell_rango "
                               f"({rango[0]}–{rango[1]})")

    nodo_pesos = _mapa(datos, "autopsia.peso")
    if set(nodo_pesos) != set(EJES):
        raise EconomiaInvalida(f"autopsia.peso: los ejes deben ser exactamente {', '.join(EJES)}")
    pesos = {eje: _ent(_valor(datos, f"autopsia.peso.{eje}"), f"autopsia.peso.{eje}") for eje in EJES}
    if sum(pesos.values()) != 100:
        raise EconomiaInvalida(f"autopsia.peso: los pesos suman {sum(pesos.values())}, deben sumar 100")
    autopsia = ReglasAutopsia(
        pesos=pesos,
        mejora_min_puntos=_ent(_valor(datos, "autopsia.mejora_min_puntos"), "autopsia.mejora_min_puntos"),
        mejora_eje_min=_ent(_valor(datos, "autopsia.mejora_eje_min"), "autopsia.mejora_eje_min"),
        cobertura_min=_ent(_valor(datos, "autopsia.cobertura_min"), "autopsia.cobertura_min"),
        nota_media=_par(_valor(datos, "autopsia.nota_media"), "autopsia.nota_media", _ent),
    )

    return ConfigEconomia(ruta_activa=ruta_activa, rutas=rutas, plataformas=plataformas,
                          reembolsos_pct=d("reembolsos_pct", True), tomas=tomas, reglas=reglas,
                          escalera=escalera, autopsia=autopsia)


def _leer(vault: Path) -> tuple[Path, Any]:
    ruta = Path(vault) / RELATIVA
    if not ruta.is_file():
        raise FileNotFoundError("falta config/economia.yaml: ejecuta `trovefy economia iniciar`")
    try:
        return ruta, cargar_yaml(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EconomiaInvalida(f"config/economia.yaml no se puede leer: {exc}") from None


def cargar_economia(vault: Path) -> ConfigEconomia:
    return _construir(_leer(vault)[1])


def cargar_texto(texto: str) -> ConfigEconomia:
    """Valida el contenido de un economia.yaml con las mismas reglas que :func:`cargar_economia`."""
    try:
        return _construir(cargar_yaml(texto))
    except yaml.YAMLError as exc:
        raise EconomiaInvalida(f"config/economia.yaml no se puede leer: {exc}") from None


def iniciar_economia(vault: Path) -> Path:
    """Copia la plantilla a ``config/economia.yaml``; nunca sobrescribe."""
    ruta = Path(vault) / RELATIVA
    if ruta.exists():
        raise FileExistsError(f"ya existe {RELATIVA}: no se sobrescribe")
    escribir_atomico(ruta, PLANTILLA.read_text(encoding="utf-8"))
    return ruta


def fijar(vault: Path, clave: str, valor: str | None, fuente: str, hoy: date) -> None:
    """Cambia ``valor``, ``fuente`` y ``fecha`` de una hoja que ya existe y revalida todo antes de escribir.

    Reescribe con la ``CABECERA`` fija: los comentarios por clave no se conservan (la explicación va en
    ``fuente``). ``KeyError`` si la clave no es una hoja existente; ``EconomiaInvalida`` si el archivo
    resultante no valida. Si falla, el archivo queda intacto.
    """
    ruta, datos = _leer(vault)
    if not isinstance(datos, dict):
        raise EconomiaInvalida("config/economia.yaml no es un mapa")
    padre: Any = None
    actual: Any = datos
    for parte in clave.split("."):
        if not isinstance(actual, dict) or _es_hoja(actual) or parte not in actual:
            raise KeyError(f"{clave} no existe en config/economia.yaml")
        padre, actual = actual, actual[parte]
    if not _es_hoja(actual):
        raise KeyError(f"{clave} no es una hoja {{valor, fuente, fecha}} de config/economia.yaml")
    if not isinstance(fuente, str) or not fuente.strip():
        raise EconomiaInvalida(f"{clave}: la fuente está vacía")
    for texto in (fuente, valor or ""):
        if buscar_secreto(texto):
            raise ValueError(f"{clave}: el texto parece llevar un secreto; no se guarda")
    try:
        nuevo = None if valor is None else cargar_yaml(valor)
    except yaml.YAMLError:
        raise EconomiaInvalida(f"{clave}: valor ilegible ({valor!r})") from None
    if isinstance(nuevo, dict):
        raise EconomiaInvalida(f"{clave}: el valor no puede ser un mapa")
    padre[clave.split(".")[-1]] = {"valor": nuevo, "fuente": fuente.strip(), "fecha": hoy.isoformat()}
    _construir(datos)
    texto = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False, default_flow_style=None, width=120)
    escribir_atomico(ruta, CABECERA + texto)


# --- consultas -------------------------------------------------------------------------------------


def costes_de(config: ConfigEconomia) -> Costes | Cifra:
    """Suma las capas de la ruta activa; lo que falte sale «no medido» con su clave."""
    if config.ruta_activa is None:
        return Cifra(None, "no medido: falta ruta_activa en config/economia.yaml "
                           "(la decide el paso 10 o 10b de /arranque)")
    totales = dict.fromkeys(_CAMPOS_COSTE, Decimal(0))
    for plataforma in config.rutas[config.ruta_activa]:
        p = config.plataformas[plataforma]
        for campo in _CAMPOS_COSTE:
            v = getattr(p, campo)
            if v is None:
                return Cifra(None, f"no medido: falta plataformas.{plataforma}.{campo} en config/economia.yaml")
            totales[campo] += v
    return Costes(totales["comision_pct"], totales["comision_fija_usd"], totales["impuestos_pct"],
                  config.reembolsos_pct)


def _primera(config: ConfigEconomia) -> PlataformaCostes | None:
    if config.ruta_activa is None:
        return None
    return config.plataformas[config.rutas[config.ruta_activa][0]]


def upsells_permitidos(config: ConfigEconomia) -> int | None:
    p = _primera(config)
    return None if p is None else p.upsells_por_plan


def admite_downsell(config: ConfigEconomia) -> bool | None:
    p = _primera(config)
    return None if p is None else p.admite_downsell
