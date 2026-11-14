"""Escalera de precios por país (§4.6, §4.1): front, bump, U1–U3 y downsell con redondeo psicológico.

Reglas: front en el rango de ``config/economia.yaml`` (12–24 € o 17–27 USD) dentro de la banda del país,
nunca por debajo del mínimo (10); el resto sale de multiplicar el front (o el U1, para el downsell). El
cambio del BCE se pasa a ``Decimal``; sin cambio, lo que depende de él es «no medido».
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from trovefy.config.mercados import Mercado
from trovefy.economia.config import ReglasEscalera
from trovefy.economia.modelo import Cifra
from trovefy.fx import Cambio

PASOS = ("front", "bump", "u1", "u2", "u3", "downsell")
_DECIMALES = frozenset({"EUR", "USD"})
_CENTIMO = Decimal("0.01")
FUENTE_BANDA = "banda del país"
FUENTE_USUARIO = "usuario"
MOTIVO_BUMP = "apagado en el test 1: se enciende con ≥ 10 ventas, §4.1"


class PrecioInvalido(ValueError):
    """Un precio manual que rompe una regla de la escalera (por ejemplo, el mínimo de 10)."""


@dataclass(frozen=True)
class PasoEscalera:
    nombre: str
    precio: Decimal
    moneda: str
    activo: bool
    motivo_inactivo: str | None


@dataclass(frozen=True)
class EscaleraPais:
    pais: str
    moneda: str
    pasos: dict[str, PasoEscalera] | None
    front_eur: Cifra
    fuente_precio: str
    avisos: tuple[str, ...]
    motivo: str | None

    def __post_init__(self) -> None:
        if (self.pasos is None) != (self.motivo is not None):
            raise ValueError("una escalera sin pasos lleva motivo «no medido: …» y una con pasos no")


# --- redondeo y cambio ---------------------------------------------------------------------------


def _escalon(moneda: str) -> Decimal:
    return Decimal(1) if moneda.upper() in _DECIMALES else Decimal(10)


def _final(moneda: str) -> Decimal:
    return Decimal("0.90") if moneda.upper() in _DECIMALES else Decimal(9)


def redondear_psicologico(importe: Decimal, moneda: str) -> Decimal:
    """EUR/USD: el ``x,90`` más cercano; otra moneda: el entero acabado en 9 más cercano.

    Empate hacia arriba. Nunca devuelve ≤ 0 (lo más bajo es 0,90 o 9).
    """
    paso, final = _escalon(moneda), _final(moneda)
    bajo = ((importe - final) / paso).to_integral_value(rounding=ROUND_FLOOR) * paso + final
    alto = bajo + paso
    elegido = bajo if importe - bajo < alto - importe else alto
    if elegido <= 0:
        elegido = final
    return elegido.quantize(_CENTIMO) if moneda.upper() in _DECIMALES else elegido


def _tasa(moneda: str, cambio: Cambio | None) -> Decimal | None:
    if moneda == "EUR":
        return Decimal(1)
    if cambio is None or moneda not in cambio.tasas:
        return None
    return Decimal(str(cambio.tasas[moneda]))


def _sin_cambio(moneda: str) -> Cifra:
    return Cifra(None, f"no medido: sin cambio de referencia para {moneda or 'moneda desconocida'}")


def a_eur(importe: Decimal, moneda: str, cambio: Cambio | None) -> Cifra:
    """El importe en EUR con las tasas del BCE (unidades por 1 EUR). Sin decimales fijos."""
    moneda = (moneda or "").upper()
    tasa = _tasa(moneda, cambio)
    return _sin_cambio(moneda) if tasa is None else Cifra(importe / tasa)


def a_usd(importe: Decimal, moneda: str, cambio: Cambio | None) -> Cifra:
    """El importe en USD pasando por el euro."""
    moneda = (moneda or "").upper()
    if moneda == "USD":
        return Cifra(importe)
    eur = a_eur(importe, moneda, cambio)
    if eur.valor is None:
        return eur
    tasa_usd = _tasa("USD", cambio)
    return _sin_cambio("USD") if tasa_usd is None else Cifra(eur.valor * tasa_usd)


def _desde_eur(importe_eur: Decimal, moneda: str, cambio: Cambio | None) -> Decimal | None:
    tasa = _tasa(moneda, cambio)
    return None if tasa is None else importe_eur * tasa


# --- front ---------------------------------------------------------------------------------------


def _texto(x: Decimal) -> str:
    if x == x.to_integral_value():
        return str(x.to_integral_value())
    return _importe(x)


def _importe(x: Decimal) -> str:
    return f"{x.quantize(_CENTIMO, rounding=ROUND_HALF_UP):.2f}".replace(".", ",")


def _objetivo(banda: tuple[Decimal, Decimal], rango: tuple[Decimal, Decimal], simbolo: str
              ) -> tuple[Decimal, list[str], tuple[Decimal, Decimal]]:
    """Punto medio de la intersección banda ∩ rango, sus avisos y los límites donde debe quedar."""
    lo, hi = max(rango[0], banda[0]), min(rango[1], banda[1])
    if lo <= hi:
        return (lo + hi) / 2, [], (lo, hi)
    extremo = rango[1] if banda[0] > rango[1] else rango[0]
    aviso = (f"la banda de precios del país queda fuera del rango del front "
             f"({_texto(rango[0])}–{_texto(rango[1])} {simbolo})")
    return extremo, [aviso], rango


def front_objetivo_eur(banda_eur: tuple[Decimal, Decimal], reglas: ReglasEscalera
                       ) -> tuple[Decimal, list[str]]:
    """Punto medio de ``[max(12, banda_lo), min(24, banda_hi)]``; sin intersección, el extremo de 12–24 más
    cercano a la banda y el aviso."""
    objetivo, avisos, _ = _objetivo(banda_eur, reglas.front_eur, "€")
    return objetivo, avisos


def _front_calculado(mercado: Mercado, reglas: ReglasEscalera, cambio: Cambio | None
                     ) -> tuple[Decimal | None, list[str], str | None]:
    """Front en moneda local desde la banda del país; ``(None, [], motivo)`` sin cambio."""
    moneda = mercado.moneda.upper()
    banda_eur = (Decimal(str(mercado.banda_eur[0])), Decimal(str(mercado.banda_eur[1])))
    if moneda == "USD":
        tasa_usd = _tasa("USD", cambio)
        if tasa_usd is None:
            return None, [], _sin_cambio("USD").motivo
        objetivo, avisos, limites = _objetivo((banda_eur[0] * tasa_usd, banda_eur[1] * tasa_usd),
                                              reglas.front_usd, "USD")
        tasa = Decimal(1)  # límites ya en la moneda local
    else:
        tasa = _tasa(moneda, cambio)
        if tasa is None:
            return None, [], _sin_cambio(moneda).motivo
        objetivo, avisos, limites = _objetivo(banda_eur, reglas.front_eur, "€")
    lo, hi = limites[0] * tasa, limites[1] * tasa
    front = redondear_psicologico(objetivo * tasa, moneda)
    if not lo <= front <= hi:
        paso = _escalon(moneda)
        otro = front + paso if front < lo else front - paso
        if lo <= otro <= hi:
            front = otro
        else:
            avisos.append(f"ningún precio psicológico cabe en la banda del país: el front queda en "
                          f"{_texto(front)} {moneda}")
    return front, avisos, None


# --- escalera ------------------------------------------------------------------------------------


def _plural(n: int) -> str:
    return f"{n} upsell" if n == 1 else f"{n} upsells"


def _activo_upsell(minimo: int, upsells: int | None) -> tuple[bool, str | None]:
    if upsells is None:
        return False, "no medido: upsells del plan"
    if upsells >= minimo:
        return True, None
    return False, f"el plan de la tienda admite {_plural(upsells)}"


def _activo_downsell(admite: bool | None) -> tuple[bool, str | None]:
    if admite is True:
        return True, None
    if admite is None:
        return False, "no medido: P-05"
    return False, "el plan de la tienda no admite downsell"


def _importe_original(x: object) -> Decimal:
    """El precio del original puede llegar del YAML de la wiki como float (``9.0``): pasa por ``str``."""
    if isinstance(x, bool) or not isinstance(x, (Decimal, int, float)):
        raise ValueError(f"importe del original mal escrito: {x!r} (debe ser un número)")  # noqa: TRY004
    importe = x if isinstance(x, Decimal) else Decimal(str(x))
    if not importe.is_finite():
        raise ValueError(f"importe del original mal escrito: {x!r} (debe ser un número finito)")
    return importe


def escalera_pais(mercado: Mercado, reglas: ReglasEscalera, cambio: Cambio | None,
                  original: tuple[Decimal | float, str | None] | None, precio_manual: Decimal | None,
                  upsells_permitidos: int | None, admite_downsell: bool | None) -> EscaleraPais:
    """La escalera de un país en su moneda. ``PrecioInvalido`` si el precio manual baja del mínimo."""
    moneda = mercado.moneda.upper()
    avisos: list[str] = []
    if precio_manual is not None:
        if precio_manual <= 0:
            raise PrecioInvalido(f"el precio del front de {mercado.pais} debe ser mayor que 0")
        front, fuente = precio_manual, FUENTE_USUARIO
    else:
        front, avisos, motivo = _front_calculado(mercado, reglas, cambio)
        fuente = FUENTE_BANDA
        if front is None:
            return EscaleraPais(mercado.pais, moneda, None, Cifra(None, motivo), fuente, (), motivo)

    # Mínimo: en USD si el país vende en USD; si no, en EUR.
    if moneda == "USD":
        en_ref, simbolo = Cifra(front), "USD"
    else:
        en_ref, simbolo = a_eur(front, moneda, cambio), "€"
    if en_ref.valor is None:
        avisos.append(f"no se pudo comprobar el mínimo de {_texto(reglas.precio_minimo)}: sin cambio para {moneda}")
    elif en_ref.valor < reglas.precio_minimo:
        if precio_manual is not None:
            raise PrecioInvalido(
                f"el front de {mercado.pais} ({_texto(front)} {moneda}) queda por debajo del mínimo de "
                f"{_texto(reglas.precio_minimo)} {simbolo}")
        while en_ref.valor < reglas.precio_minimo:  # el calculado sube de escalón hasta el mínimo
            front += _escalon(moneda)
            en_ref = Cifra(front) if moneda == "USD" else a_eur(front, moneda, cambio)

    eur = a_eur(front, moneda, cambio)
    front_eur = eur if eur.valor is None else Cifra(eur.valor.quantize(_CENTIMO, rounding=ROUND_HALF_UP))

    precios = {"front": front}
    for paso in ("bump", "u1", "u2", "u3"):
        precios[paso] = redondear_psicologico(getattr(reglas, paso) * front, moneda)
    precios["downsell"] = redondear_psicologico(reglas.downsell * precios["u1"], moneda)

    estados = {
        "front": (True, None),
        "bump": (True, None) if reglas.bump_activo_test1 else (False, MOTIVO_BUMP),
        "u1": (True, None),
        "u2": _activo_upsell(2, upsells_permitidos),
        "u3": _activo_upsell(3, upsells_permitidos),
        "downsell": _activo_downsell(admite_downsell),
    }
    pasos = {p: PasoEscalera(p, precios[p], moneda, estados[p][0], estados[p][1]) for p in PASOS}

    if original is not None:
        importe, moneda_original = original
        importe = _importe_original(importe)
        if moneda_original is None:
            avisos.append("comparación con el original: no medido (moneda del original no medida)")
        else:
            original_eur = a_eur(importe, moneda_original, cambio)
            if original_eur.valor is None or front_eur.valor is None:
                falta = moneda_original.upper() if original_eur.valor is None else moneda
                avisos.append(f"comparación con el original: no medido (sin cambio de referencia para {falta})")
            elif eur.valor >= original_eur.valor:
                avisos.append(f"el original cuesta {_importe(original_eur.valor)} €: el front no queda por debajo; "
                              "la comparativa lo justifica por valor")

    return EscaleraPais(mercado.pais, moneda, pasos, front_eur, fuente, tuple(avisos), None)
