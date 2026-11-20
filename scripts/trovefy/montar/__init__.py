"""`/montar` (plan 22): la tanda aprobada del plan 21 → campaña de test ABO en PAUSED por el ejecutor.

**Qué hacen los vídeos:** «5 conjuntos · 1 anuncio c/u · $5 por anuncio · Techo $100 · Plazo 1 semana» (C1 0:18:10),
objetivo Ventas, país e idioma locales, Audience Network y Threads fuera (L1 0:56:40), solo el catálogo apagado
(L1 1:03:43), nombres de L1 1:02:20 y salida a las 00:00 (L1 0:58:29). El admin monta en pausa y lo prende el dueño
(C1 0:51:00). Claude nunca escribe en Meta: deposita propuestas que ejecuta el ejecutor (§5.2, [D-21]).

Módulos: `tanda` (lee el ``manifest.csv`` del 21), `importes` (USD → moneda de la cuenta con la TRM), `estructura`
(el JSON de ``crear_estructura_pausada``, su huella y el resumen en seco), `precondiciones` (lo que exige activar),
`registro` (lo que copió el ejecutor → histórico, ``PRODUCTO.md``, estado y caja) y `config` (``config/montar.yaml``).
"""
from __future__ import annotations

SKILL = "/montar"


class NoMedido(ValueError):
    """Falta un dato para montar: el mensaje empieza por «no medido: »."""

    def __init__(self, motivo: str) -> None:
        texto = motivo if motivo.startswith("no medido") else f"no medido: {motivo}"
        super().__init__(texto)


class TandaInvalida(ValueError):
    """La tanda no se puede montar: el mensaje nombra el archivo y la fila."""


class MontajeInvalido(ValueError):
    """Los importes, la estructura o los límites no permiten montar sin cambiar el método."""
