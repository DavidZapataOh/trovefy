"""Detección de idioma de un texto de anuncio (lingua, 100 % local, sin red)."""

from __future__ import annotations

from functools import lru_cache

# Constantes técnicas del detector (no son umbrales de negocio):
# - bajo este largo el texto no da señal fiable («PDF», «Compra ya»);
# - con los candidatos como único universo la confianza del ganador suele ser alta; por debajo de
#   este valor no se decide (mezcla de idiomas o texto ambiguo).
LARGO_MINIMO = 20
CONFIANZA_MINIMA = 0.6


@lru_cache(maxsize=16)
def _detector(candidatos: tuple[str, ...]):
    # Import y construcción perezosos y solo con los idiomas candidatos: cargar los 75 idiomas
    # cuesta cientos de MB y segundos.
    from lingua import IsoCode639_1, LanguageDetectorBuilder

    codigos = []
    for c in candidatos:
        try:
            codigos.append(getattr(IsoCode639_1, c.upper()))
        except AttributeError:
            continue
    if not codigos:
        return None
    if len(codigos) == 1:
        return None  # un único candidato no se puede contrastar
    return LanguageDetectorBuilder.from_iso_codes_639_1(*codigos).build()


def detectar(texto: str, candidatos: list[str]) -> str | None:
    """Código ISO-639-1 del idioma de ``texto`` entre ``candidatos``; None si el texto tiene menos
    de ``LARGO_MINIMO`` caracteres, la confianza es menor que ``CONFIANZA_MINIMA`` o no hay al menos
    dos candidatos reconocidos."""
    texto = (texto or "").strip()
    if len(texto) < LARGO_MINIMO:
        return None
    detector = _detector(tuple(sorted({c.lower() for c in candidatos})))
    if detector is None:
        return None
    confianzas = detector.compute_language_confidence_values(texto)
    if not confianzas or confianzas[0].value < CONFIANZA_MINIMA:
        return None
    return confianzas[0].language.iso_code_639_1.name.lower()
