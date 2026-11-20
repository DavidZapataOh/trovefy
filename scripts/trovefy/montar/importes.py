"""Importes del test en la moneda de la cuenta, con la TRM del día y contra los límites del ejecutor (plan 22, Tarea 2).

**Qué hacen los vídeos:** «TESTEO — 4 o 5 anuncios de US$ 5 por día. US$ 20–25 diarios por producto» (C1 20:05);
«Techo $100 · Plazo 1 semana» (C1 0:18:10). Las cuentas de los vídeos están en USD; la del usuario, en COP ([D-37]),
por eso los USD se convierten con la TRM (base común 5): todo techo pasa a la moneda de la cuenta **a la baja**.

Los límites del ejecutor (``estado/limites.json``) **no recortan el método en silencio**: si el techo de US$ 100 o el
presupuesto por conjunto no caben, se para y se dice cómo subirlos (propuesta ``limite_ejecutor``, Tarea 12 R2).
Solo ``Decimal`` e ``int``; nunca ``float``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trovefy_ejecutor.dinero import Moneda, formatear

from trovefy.aprobaciones.fuentes import Lectura
from trovefy.montar import MontajeInvalido, NoMedido
from trovefy.trm import Trm, usd_centavos_a_cop


@dataclass(frozen=True)
class Importes:
    moneda: str
    offset: int
    conjuntos: int
    diario_conjunto: int  # unidades mínimas
    spend_cap: int  # unidades mínimas
    usd_diario: Decimal  # por conjunto
    usd_spend_cap: Decimal
    trm: Trm | None
    hoy: date

    def a_dict(self) -> dict:
        d = {"moneda": self.moneda, "offset": self.offset, "conjuntos": self.conjuntos,
             "diario_conjunto": self.diario_conjunto, "spend_cap": self.spend_cap,
             "usd_diario": str(self.usd_diario), "usd_spend_cap": str(self.usd_spend_cap)}
        if self.trm is not None:
            d.update(trm=str(self.trm.cop_por_usd), trm_fecha=self.trm.desde.isoformat())
        return d


def _usd_a_minima(usd: Decimal, moneda: str, offset: int, trm: Trm | None, hoy: date) -> int:
    centavos = int((usd * 100).to_integral_value())
    if moneda == "USD":
        return centavos * offset // 100
    if moneda != "COP":
        raise NoMedido(f"moneda de la cuenta {moneda} sin conversión (solo COP o USD)")
    if trm is None:
        raise NoMedido(f"sin TRM del {hoy.isoformat()}: no se convierte a COP y no se monta")
    return int(usd_centavos_a_cop(centavos, trm)) * offset


def _a_usd(unidades: int, moneda: str, offset: int, trm: Trm | None) -> Decimal:
    valor = Decimal(unidades) / offset
    if moneda == "USD":
        return valor
    assert trm is not None
    return (valor / trm.cop_por_usd).quantize(Decimal("0.01"))


def _fmt_usd(v: Decimal) -> str:
    return f"US$ {v.quantize(Decimal('0.01'))}".replace(".", ",")


def calcular(cuenta: str, meta: Lectura, limites: Lectura, trm: Trm | None, hoy: date, *, conjuntos: int,
             usd_conjunto: Decimal, usd_tope: Decimal, usd_vivos: Decimal = Decimal(0)) -> Importes:
    """Importes del test. ``NoMedido`` sin moneda confirmada o sin TRM; ``MontajeInvalido`` si un límite del
    ejecutor recortaría el método. ``usd_vivos``: presupuesto diario de los tests vivos de ``config/caja.yaml``."""
    m = meta.datos
    if m is None or m.get("cuenta") != cuenta or not isinstance(m.get("currency"), str) \
            or type(m.get("offset")) is not int:
        raise NoMedido("moneda de la cuenta sin confirmar: ejecuta comprobar-meta (paso 13)")
    moneda, offset = m["currency"], m["offset"]
    diario = _usd_a_minima(Decimal(usd_conjunto), moneda, offset, trm, hoy)
    tope = _usd_a_minima(Decimal(usd_tope), moneda, offset, trm, hoy)
    vivos = _usd_a_minima(Decimal(usd_vivos), moneda, offset, trm, hoy) if usd_vivos else 0
    lim = limites.datos
    lc = ((lim or {}).get("cuentas") or {}).get(cuenta) if isinstance(lim, dict) else None
    if not isinstance(lc, dict):
        raise NoMedido(f"límites del ejecutor de la cuenta sin leer ({limites.motivo or 'sin la cuenta'})")
    if lc.get("moneda") != moneda:
        raise MontajeInvalido(f"los límites del ejecutor están en {lc.get('moneda')} y la cuenta en {moneda}")
    errores = []
    cap = lc.get("spend_cap_test")
    if type(cap) is int and tope > cap:
        errores.append(f"el límite del ejecutor ({_fmt_usd(_a_usd(cap, moneda, offset, trm))}) recorta el techo de "
                       f"{_fmt_usd(Decimal(usd_tope))} de los vídeos (C1 0:18:10): propón subir spend_cap_test a "
                       f"{tope} (Tarea 12, R2)")
    maximo = lc.get("max_presupuesto_conjunto")
    if type(maximo) is int and diario > maximo:
        errores.append(f"el presupuesto por conjunto ({diario}) supera max_presupuesto_conjunto ({maximo}) del "
                       "ejecutor: no se recorta en silencio; propón subirlo (Tarea 12, R2)")
    total = lc.get("tope_gasto_diario_total")
    if type(total) is int and conjuntos * diario + vivos > total:
        errores.append(f"no cabe en el tope diario del ejecutor: {conjuntos} × {diario} + {vivos} de tests vivos > "
                       f"{total} (tope_gasto_diario_total)")
    if errores:
        raise MontajeInvalido("; ".join(errores))
    return Importes(moneda, offset, conjuntos, diario, tope, Decimal(usd_conjunto), Decimal(usd_tope), trm, hoy)


def texto_importes(i: Importes) -> list[str]:
    mon = Moneda(i.moneda, i.offset)
    lineas = [(f"{i.conjuntos} × {formatear(i.diario_conjunto, mon)}/día ({_fmt_usd(i.usd_diario)} c/u) · "
               f"techo {formatear(i.spend_cap, mon)} ({_fmt_usd(i.usd_spend_cap)}) · plazo 1 semana")]
    if i.trm is not None:
        lineas.append(i.trm.etiqueta(i.hoy))
    return lineas
