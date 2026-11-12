"""Ritmo de envío: tope por hora, horario de silencio y resúmenes (§5.5, plan 10 Tarea 9)."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .modelo import Propuesta
from .reloj import en_silencio

_VENTANA = timedelta(minutes=60)


@dataclass(frozen=True)
class Decision:
    enviar: bool
    sonido: bool
    motivo: Literal["normal", "alta", "urgente", "silencio", "ritmo"]


class Ritmo:
    def __init__(self, max_por_hora: int = 6, max_por_resumen: int = 5) -> None:
        self.max_por_hora = max_por_hora
        self.max_por_resumen = max_por_resumen
        self._envios: deque[datetime] = deque()

    def _en_ventana(self, ahora: datetime) -> int:
        corte = ahora - _VENTANA
        return sum(1 for t in self._envios if corte < t <= ahora)

    def _purgar(self) -> None:
        if self._envios:
            corte = max(self._envios) - _VENTANA
            self._envios = deque(sorted(t for t in self._envios if t > corte))

    def decidir(self, p: Propuesta, ahora: datetime) -> Decision:
        # Alertas: el silencio lo decide `nivel`; `prioridad` se ignora (plan 09, Tarea 4).
        if p.tipo == "alerta":
            if p.alerta is not None and p.alerta.nivel == "urgente":
                return Decision(True, True, "urgente")
        elif p.prioridad == "alta":
            return Decision(True, True, "alta")
        if en_silencio(ahora):
            return Decision(False, False, "silencio")
        if self._en_ventana(ahora) >= self.max_por_hora:
            return Decision(False, False, "ritmo")
        return Decision(True, True, "normal")

    def anotar_envio(self, ahora: datetime) -> None:
        self._envios.append(ahora)
        self._purgar()

    def sembrar(self, envios: Iterable[datetime]) -> None:
        """Re-siembra tras un reinicio con los envíos recientes (los de hace > 60 min se descartan)."""
        self._envios = deque(envios)
        self._purgar()

    def toca_resumen(self, ahora: datetime, en_cola: int) -> bool:
        return en_cola > 0 and not en_silencio(ahora) and self._en_ventana(ahora) < self.max_por_hora
