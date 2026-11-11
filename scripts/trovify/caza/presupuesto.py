"""Presupuesto de búsquedas: tope diario compartido, pausas con ruido y esperas tras error.

El tope es por día (America/Bogota) y lo comparten la sesión del usuario y la rutina: el contador
vive en ``<vault>/data/caza/presupuesto/AAAA-MM-DD.json`` (``{"usadas": n}``) y se lee y actualiza
con bloqueo de archivo en cada búsqueda. Un acierto de caché no llama a ``antes_de_buscar``.
"""

import fcntl
import json
import random
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from trovify.config import umbrales
from trovify.vault.escritura import ZONA_NEGOCIO, escribir_atomico

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
        contador: Path | None = None,
    ):
        """``contador``: archivo del día compartido entre procesos; sin él, el tope es de esta sesión."""
        self.max_busquedas = max_busquedas
        self.pausa_min_s = pausa_min_s
        self.pausa_max_s = pausa_max_s
        self._dormir = dormir
        self._azar = azar or random.Random()
        self.usadas = 0  # búsquedas de esta sesión (el total del día está en ``contador``)
        self.contador = Path(contador) if contador is not None else None
        self.bloqueos = 0
        self.vacios = 0
        self._errores = 0

    def antes_de_buscar(self) -> None:
        if self.contador is None:
            if self.usadas >= self.max_busquedas:
                raise PresupuestoAgotado(
                    f"Presupuesto de la sesión agotado: {self.max_busquedas} búsquedas."
                )
            self.usadas += 1
            return
        with self._bloqueo():
            hechas = self._leer()
            if hechas >= self.max_busquedas:
                raise PresupuestoAgotado(
                    f"Presupuesto del día agotado: {hechas} de {self.max_busquedas} búsquedas "
                    "(compartido entre tu sesión y la rutina; se renueva mañana)."
                )
            escribir_atomico(self.contador, json.dumps({"usadas": hechas + 1}) + "\n")
        self.usadas += 1

    def usadas_hoy(self) -> int | None:
        """Búsquedas del día según el contador compartido; None si no hay contador."""
        if self.contador is None:
            return None
        with self._bloqueo():
            return self._leer()

    @contextmanager
    def _bloqueo(self):
        self.contador.parent.mkdir(parents=True, exist_ok=True)
        cerrojo = self.contador.with_name(f".{self.contador.name}.lock")
        with open(cerrojo, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _leer(self) -> int:
        if not self.contador.exists():
            return 0
        try:
            n = json.loads(self.contador.read_text(encoding="utf-8"))["usadas"]
        except (OSError, ValueError, KeyError, TypeError):
            n = None
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            # Sin saber cuántas se hicieron hoy no se arriesga a Meta.
            raise PresupuestoAgotado(
                f"El contador de búsquedas del día ({self.contador.name}) no se puede leer; "
                "no se busca para no pasar el tope. Revísalo o bórralo si sabes que hoy no se buscó."
            )
        return n

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
        """Tope diario ``caza.max_busquedas_sesion`` contado en ``data/caza/presupuesto/<hoy>.json``.

        ``hoy`` por defecto es el día de negocio (America/Bogota)."""
        hoy = hoy or datetime.now(ZONA_NEGOCIO).date()
        maximo = int(umbrales.valor(vault, "caza.max_busquedas_sesion"))
        pmin = umbrales.valor(vault, "caza.pausa_min_s")
        pmax = umbrales.valor(vault, "caza.pausa_max_s")
        if maximo < 1:
            raise ValueError("caza.max_busquedas_sesion debe ser al menos 1.")
        if pmin < 0 or pmax < 0:
            raise ValueError("Las pausas de caza no pueden ser negativas.")
        if pmin > pmax:
            raise ValueError("caza.pausa_min_s no puede ser mayor que caza.pausa_max_s.")
        contador = Path(vault) / "data" / "caza" / "presupuesto" / f"{hoy.isoformat()}.json"
        return cls(maximo, pmin, pmax, contador=contador)
