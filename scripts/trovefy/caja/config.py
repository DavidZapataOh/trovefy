"""Carga y validación de ``config/caja.yaml``. Todo importe sale en centavos de USD (``int``)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from trovefy.config.yaml_config import cargar_yaml
from trovefy.vault.escritura import escribir_atomico

SOBRES = ("herramientas", "tests", "reserva")
PLANTILLA = (
    Path(__file__).resolve().parents[3]
    / "templates"
    / "cerebro"
    / "config"
    / "caja.yaml"
)


class CajaInvalida(ValueError):
    """``config/caja.yaml`` no cumple el formato."""


@dataclass(frozen=True)
class CuentaCaja:
    id: str | None
    moneda: str | None


@dataclass(frozen=True)
class TestCaja:
    __test__ = False  # no es una clase de pytest

    producto: str
    pais: str
    campana_id: str | None
    estado: Literal["vivo", "cerrado"]
    prorroga: bool
    ventas: int | None
    presupuesto_diario: int


@dataclass(frozen=True)
class ConfigCaja:
    capital: int
    sobres: dict[str, int]
    techo_test: int
    prorroga_hasta: int
    diario_test: int
    diario_prescala: int
    tope_diario_ejecutor: int
    reserva_desbloqueada: bool
    apimart_aviso: int
    cuenta: CuentaCaja
    tests: tuple[TestCaja, ...]


def _centavos(valor: Any, campo: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise CajaInvalida(f"{campo}: importe ilegible ({valor!r})")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise CajaInvalida(f"{campo}: importe ilegible ({valor!r})") from None
    if not d.is_finite() or d < 0:
        raise CajaInvalida(f"{campo}: debe ser un importe >= 0 ({valor!r})")
    c = d * 100
    if c != c.to_integral_value():
        raise CajaInvalida(f"{campo}: máximo 2 decimales ({valor!r})")
    return int(c)


def _dict(raw: dict, clave: str) -> dict:
    v = raw.get(clave)
    if not isinstance(v, dict):
        raise CajaInvalida(f"{clave}: debe ser un mapa")
    return v


def _req(m: dict, clave: str, ctx: str) -> Any:
    if clave not in m:
        raise CajaInvalida(f"falta {ctx}{clave}")
    return m[clave]


def _test(t: Any, i: int) -> TestCaja:
    if not isinstance(t, dict):
        raise CajaInvalida(f"tests[{i}]: debe ser un mapa")
    ctx = f"tests[{i}]."
    estado = _req(t, "estado", ctx)
    if estado not in ("vivo", "cerrado"):
        raise CajaInvalida(f"{ctx}estado: {estado!r}")
    ventas = t.get("ventas")
    if ventas is not None and (
        isinstance(ventas, bool) or not isinstance(ventas, int) or ventas < 0
    ):
        raise CajaInvalida(f"{ctx}ventas: {ventas!r}")
    prorroga = t.get("prorroga", False)
    if not isinstance(prorroga, bool):
        raise CajaInvalida(f"{ctx}prorroga: {prorroga!r}")
    return TestCaja(
        producto=str(_req(t, "producto", ctx)),
        pais=str(_req(t, "pais", ctx)),
        campana_id=None if t.get("campana_id") is None else str(t["campana_id"]),
        estado=estado,
        prorroga=prorroga,
        ventas=ventas,
        presupuesto_diario=_centavos(_req(t, "diario_usd", ctx), f"{ctx}diario_usd"),
    )


def cargar_caja(vault: Path) -> ConfigCaja:
    ruta = Path(vault) / "config" / "caja.yaml"
    if not ruta.is_file():
        raise FileNotFoundError(
            "falta config/caja.yaml: ejecuta `trovefy caja iniciar`"
        )
    try:
        raw = cargar_yaml(ruta.read_text(encoding="utf-8"))
    except Exception as e:  # YAML mal formado
        raise CajaInvalida(f"config/caja.yaml ilegible: {e}") from e
    if not isinstance(raw, dict):
        raise CajaInvalida("config/caja.yaml: debe ser un mapa")
    sobres_raw = _dict(raw, "sobres_usd")
    if set(sobres_raw) != set(SOBRES):
        raise CajaInvalida(f"sobres_usd: deben ser exactamente {', '.join(SOBRES)}")
    sobres = {s: _centavos(sobres_raw[s], f"sobres_usd.{s}") for s in SOBRES}
    capital = _centavos(_req(raw, "capital_usd", ""), "capital_usd")
    if sum(sobres.values()) != capital:
        raise CajaInvalida("los sobres no suman el capital")
    test = _dict(raw, "test")
    cuenta = _dict(raw, "cuenta")
    for k in ("id", "moneda"):
        if cuenta.get(k) is not None and not isinstance(cuenta[k], str):
            raise CajaInvalida(f"cuenta.{k}: debe ser texto o null")
    reserva = _req(raw, "reserva_desbloqueada", "")
    if not isinstance(reserva, bool):
        raise CajaInvalida("reserva_desbloqueada: debe ser true o false")
    tests_raw = raw.get("tests") or []
    if not isinstance(tests_raw, list):
        raise CajaInvalida("tests: debe ser una lista")
    return ConfigCaja(
        capital=capital,
        sobres=sobres,
        techo_test=_centavos(_req(test, "techo_usd", "test."), "test.techo_usd"),
        prorroga_hasta=_centavos(
            _req(test, "prorroga_hasta_usd", "test."), "test.prorroga_hasta_usd"
        ),
        diario_test=_centavos(_req(test, "diario_usd", "test."), "test.diario_usd"),
        diario_prescala=_centavos(
            _req(raw, "prescala_diario_usd", ""), "prescala_diario_usd"
        ),
        tope_diario_ejecutor=_centavos(
            _req(raw, "tope_diario_ejecutor_usd", ""), "tope_diario_ejecutor_usd"
        ),
        reserva_desbloqueada=reserva,
        apimart_aviso=_centavos(
            _req(raw, "apimart_aviso_usd", ""), "apimart_aviso_usd"
        ),
        cuenta=CuentaCaja(cuenta.get("id"), cuenta.get("moneda")),
        tests=tuple(_test(t, i) for i, t in enumerate(tests_raw)),
    )


def iniciar_caja(vault: Path, act_id: str | None, moneda: str | None) -> Path:
    """Copia la plantilla rellenando ``cuenta``; nunca sobrescribe."""
    destino = Path(vault) / "config" / "caja.yaml"
    if destino.exists() or destino.is_symlink():
        raise FileExistsError(f"ya existe {destino}")
    texto = PLANTILLA.read_text(encoding="utf-8")
    vacio = "cuenta: {id: null, moneda: null}"
    if vacio not in texto:
        raise CajaInvalida("la plantilla no tiene la línea cuenta esperada")
    if act_id is not None or moneda is not None:

        def lit(v: str | None) -> str:
            return (
                "null"
                if v is None
                else '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
            )

        texto = texto.replace(
            vacio, f"cuenta: {{id: {lit(act_id)}, moneda: {lit(moneda)}}}"
        )
    escribir_atomico(destino, texto)
    return destino
