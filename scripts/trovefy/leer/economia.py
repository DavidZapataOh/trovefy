"""Lo que `/leer` necesita de la economía (plan 23, Tarea 1): CPA_BE, comisiones para el ROAS neto y el corte de oferta.

**Qué hacen los vídeos:** el documento de la ABO empieza por «01 Tu CPA break-even» (C1 18:10); el ROAS neto descuenta
comisiones («lo que entra a tu cuenta después de comisiones ÷ lo que gastaste», T3 10:05) y es el que decide el surf y
el corte con ventas (T3 12:35, C1 34:25). El corte de oferta sin ventas es fijo, US$ 25 (C1 1:24:15), y no depende del
CPA_BE. La economía la fija el usuario (paso 0 de la fase, resolución 15): aquí solo se lee; sin comisiones, el ROAS
neto es «no medido» y no hay surf ni corte con ventas.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path

import yaml

from trovefy.leer import Umbrales, umbral


@dataclass(frozen=True)
class EconomiaLeer:
    cpa_be_usd: Decimal | None
    aov_usd: Decimal | None
    costes_pct: Decimal | None  # comisión + impuestos de la ruta activa (fracción)
    comision_fija_usd: Decimal | None  # por cobro
    motivo: str | None  # «no medido: …» si falta lo del ROAS neto

    @property
    def medida(self) -> bool:
        return self.costes_pct is not None and self.comision_fija_usd is not None


def _dec(v: object) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def leer_economia(vault: Path, p_id: str, pais: str) -> EconomiaLeer:
    """``ESCALERA.md → paises.<PAIS>`` (CPA_BE, AOV) y las comisiones de ``config/economia.yaml``."""
    from trovefy.economia.comisiones import Comisiones, comisiones
    from trovefy.economia.config import EconomiaInvalida, cargar_economia
    from trovefy.vault import frontmatter

    motivos: list[str] = []
    cpa = aov = None
    ruta = Path(vault) / "productos" / p_id / "ESCALERA.md"
    try:
        meta, _ = frontmatter.leer(ruta)
        b = ((meta or {}).get("paises") or {}).get(pais) or {}
        cpa, aov = _dec(b.get("cpa_be_usd")), _dec(b.get("aov_usd"))
        if cpa is None:
            m = str(b.get("cpa_be_usd_motivo") or b.get("be_usd_motivo") or "CPA_BE sin calcular")
            motivos.append(m if m.startswith("no medido") else f"no medido: {m}")
    except (OSError, ValueError, yaml.YAMLError, AttributeError):
        motivos.append("no medido: falta ESCALERA.md (/trovefy:modelar)")
    try:
        c = comisiones(cargar_economia(vault))
    except (OSError, EconomiaInvalida, ValueError) as exc:
        c = [f"config/economia.yaml ilegible ({exc})"]
    if isinstance(c, Comisiones):
        return EconomiaLeer(cpa, aov, c.pct + c.impuestos_pct, c.fija_usd, None)
    texto = "; ".join(c)
    return EconomiaLeer(cpa, aov, None, None, f"no medido: {texto} en config/economia.yaml (paso 0: fijar la economía)")


def corte_oferta_usd(u: Umbrales) -> tuple[Decimal, str]:
    """El corte de la oferta sin ventas: ``corte.oferta.sin_ventas_usd`` (25), C1 1:24:15. Sin factor de CPA_BE."""
    return umbral(u, "corte.oferta.sin_ventas_usd"), "C1 1:24:15 «un promedio de US$ 25»"


def neto_de(bruto_usd: Decimal | None, n_cobros: int | None, e: EconomiaLeer) -> Decimal | None:
    """Lo que entra tras comisiones: ``bruto × (1 − costes_pct) − fija × cobros``, a la baja al centavo; ``None`` si
    falta algo."""
    if bruto_usd is None or n_cobros is None or not e.medida:
        return None
    neto = bruto_usd * (1 - e.costes_pct) - e.comision_fija_usd * n_cobros
    return neto.quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def roas_neto(neto_usd: Decimal | None, gasto_usd_c: int | None) -> Decimal | None:
    """Neto ÷ gasto (T3 10:05); ``None`` sin neto, sin gasto medido o con gasto 0."""
    if neto_usd is None or not gasto_usd_c:
        return None
    return (neto_usd * 100 / Decimal(gasto_usd_c)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
