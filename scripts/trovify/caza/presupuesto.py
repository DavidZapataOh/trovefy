"""Presupuesto de sesión: tope de búsquedas, pausas con ruido y esperas tras error."""

import random
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from trovify.config import umbrales

_ESPERAS_ERROR_S = (30, 90)


class PresupuestoAgotado(RuntimeError):
    pass


class ParadaPorErrores(RuntimeError):
    pass


class Presupuesto:
    def __init__(
        self,
        max_busquedas: int,
        pausa_min_s: float,
        pausa_max_s: float,
        dormir: Callable[[float], None] = time.sleep,
        azar: random.Random | None = None,
    ):
        self.max_busquedas = max_busquedas
        self.pausa_min_s = pausa_min_s
        self.pausa_max_s = pausa_max_s
        self._dormir = dormir
        self._azar = azar or random.Random()
        self.usadas = 0
        self.bloqueos = 0
        self.vacios = 0
        self._errores = 0

    def antes_de_buscar(self) -> None:
        if self.usadas >= self.max_busquedas:
            raise PresupuestoAgotado(
                f"Presupuesto de la sesión agotado: {self.max_busquedas} búsquedas."
            )
        self.usadas += 1

    def exito(self) -> None:
        """El cliente la llama tras una búsqueda correcta: reinicia los errores seguidos."""
        self._errores = 0

    def pausa(self) -> float:
        s = self._azar.uniform(self.pausa_min_s, self.pausa_max_s)
        self._dormir(s)
        return s

    def tras_error(self) -> None:
        if self._errores >= len(_ESPERAS_ERROR_S):
            raise ParadaPorErrores("Tres errores seguidos: se detiene la sesión.")
        espera = _ESPERAS_ERROR_S[self._errores]
        self._errores += 1
        self._dormir(espera)

    @classmethod
    def desde_umbrales(cls, vault: Path, hoy: date | None = None) -> "Presupuesto":
        # `hoy` queda reservado: el plan 07 añade el contador diario persistente.
        maximo = int(umbrales.valor(vault, "caza.max_busquedas_sesion"))
        pmin = umbrales.valor(vault, "caza.pausa_min_s")
        pmax = umbrales.valor(vault, "caza.pausa_max_s")
        if maximo < 1:
            raise ValueError("caza.max_busquedas_sesion debe ser al menos 1.")
        if pmin < 0 or pmax < 0:
            raise ValueError("Las pausas de caza no pueden ser negativas.")
        if pmin > pmax:
            raise ValueError("caza.pausa_min_s no puede ser mayor que caza.pausa_max_s.")
        return cls(maximo, pmin, pmax)
