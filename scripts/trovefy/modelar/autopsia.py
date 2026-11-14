"""Autopsia de 8 ejes de una oferta y tercera señal de R16 («se puede mejorar»).

Los pesos y umbrales vienen de ``config/economia.yaml`` (``autopsia.*``, ``ReglasAutopsia``):
aquí no hay ningún número de negocio. Una nota ``None`` es «no se pudo valorar» y no cuenta
ni en la nota ni en la cobertura.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from trovefy.economia.config import EJES, ReglasAutopsia

__all__ = ["EJES", "NOMBRES", "Autopsia", "EjeValorado", "puntuar", "senal_se_puede_mejorar",
           "vende_por_presupuesto"]

NOMBRES = {
    "resultado_sonado": "Resultado soñado",
    "probabilidad_percibida": "Probabilidad percibida",
    "tiempo": "Tiempo",
    "esfuerzo": "Esfuerzo",
    "avatar": "Avatar",
    "mecanismo": "Mecanismo",
    "precio": "Precio",
    "prueba_garantia": "Prueba y garantía",
}
_NOTA_MAX = 10  # escala de cada eje (0–10), no un umbral de negocio
_UN_DECIMAL = Decimal("0.1")


@dataclass(frozen=True)
class EjeValorado:
    """Nota 0–10 de un eje con su porqué; ``nota=None`` = no se pudo valorar (el porqué dice el motivo)."""

    eje: str
    nota: int | None
    porque: str

    def __post_init__(self) -> None:
        if self.nota is None:
            return
        if isinstance(self.nota, bool) or not isinstance(self.nota, int) or not 0 <= self.nota <= _NOTA_MAX:
            raise ValueError(f"{self.eje}: la nota va de 0 a {_NOTA_MAX} (entera), no {self.nota!r}")


@dataclass(frozen=True)
class Autopsia:
    nota: Decimal | None
    cobertura: int
    flojos: tuple[str, ...]
    desglose: tuple[tuple[str, int, int | None], ...]


def _num(valor: Decimal) -> str:
    return f"{valor:.1f}".replace(".", ",")


def puntuar(ejes: dict[str, EjeValorado], pesos: dict[str, int]) -> Autopsia:
    """Nota ponderada sobre los ejes valorados (``100 × Σ peso·nota/10 ÷ Σ pesos medidos``, a 1 decimal).

    Un eje ausente o con ``nota=None`` no se valoró. Los 3 más flojos se ordenan por nota, luego por
    mayor peso y luego por el orden de ``EJES``.
    """
    desconocidos = sorted(set(ejes) - set(EJES))
    if desconocidos:
        raise ValueError(f"ejes desconocidos: {', '.join(desconocidos)}")
    for clave, valorado in ejes.items():
        if valorado.eje != clave:
            raise ValueError(f"el eje {clave!r} trae dentro {valorado.eje!r}")
    desglose = tuple((eje, pesos[eje], ejes[eje].nota if eje in ejes else None) for eje in EJES)
    medidos = [(eje, peso, nota) for eje, peso, nota in desglose if nota is not None]
    cobertura = sum(peso for _, peso, _ in medidos)
    if not cobertura:
        return Autopsia(None, 0, (), desglose)
    suma = sum(Decimal(peso) * Decimal(nota) for _, peso, nota in medidos)
    nota = (suma * Decimal(100) / Decimal(_NOTA_MAX) / Decimal(cobertura)).quantize(_UN_DECIMAL, ROUND_HALF_UP)
    orden = sorted(medidos, key=lambda d: (d[2], -d[1], EJES.index(d[0])))
    return Autopsia(nota, cobertura, tuple(eje for eje, _, _ in orden[:3]), desglose)


def senal_se_puede_mejorar(original: Autopsia, nuestra: Autopsia, ejes_original: dict[str, EjeValorado],
                           ejes_nuestra: dict[str, EjeValorado], reglas: ReglasAutopsia) -> tuple[bool | None, str]:
    """Tercera señal de R16: ``None`` si la autopsia no cubre lo bastante; ``True``/``False`` con su motivo."""
    for quien, a in (("del original", original), ("de la nuestra", nuestra)):
        if a.cobertura < reglas.cobertura_min or a.nota is None:
            return None, (f"no medida: la autopsia {quien} cubre {a.cobertura} de 100 puntos "
                          f"(hacen falta {reglas.cobertura_min})")
    diferencia = nuestra.nota - original.nota
    signo = "+" if diferencia >= 0 else "−"
    puntos = f"{signo}{_num(abs(diferencia))} puntos"
    if diferencia < reglas.mejora_min_puntos:
        return False, f"no: {puntos} sobre el original (hacen falta {reglas.mejora_min_puntos})"
    subidas = []
    for eje in original.flojos:
        antes = ejes_original[eje].nota
        despues = ejes_nuestra[eje].nota if eje in ejes_nuestra else None
        if despues is None:
            return False, f"no: «{NOMBRES[eje]}», uno de sus 3 ejes más flojos, no se valoró en nuestra oferta"
        if despues - antes < reglas.mejora_eje_min:
            return False, (f"no: «{NOMBRES[eje]}», uno de sus 3 ejes más flojos, pasa de {antes} a {despues} "
                           f"(hace falta subir {reglas.mejora_eje_min})")
        subidas.append(f"{NOMBRES[eje]} {antes}→{despues}")
    return True, f"sí: {puntos} y mejora sus 3 ejes más flojos ({', '.join(subidas)})"


def vende_por_presupuesto(original: Autopsia, reglas: ReglasAutopsia) -> bool:
    """La oferta original tiene una nota media: vende por presupuesto de anuncios, no por oferta."""
    if original.nota is None:
        return False
    minimo, maximo = reglas.nota_media
    return minimo <= original.nota <= maximo
