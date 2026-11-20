"""Lo que toca a `/montar` de la máquina de estados (§4.13, plan 22, Tarea 7): funciones puras.

**Qué hacen los vídeos:** se monta en pausa y lo prende el dueño (C1 0:51:00); desde que se prende cuenta la decisión
de 24–48 h (C1 0:20:05). Este módulo solo dice cuándo cambia el estado: ``listo → montado`` cuando el ejecutor
confirma el montaje y ``montado → test`` cuando confirma la activación aceptada por el usuario.

Cada función recibe el estado actual del producto-país y el resultado de la propuesta que copió el ejecutor
(cualquier objeto con ``estado`` y ``parcial``) y devuelve un `Paso`: el estado nuevo (o ``None`` si no cambia) y los
avisos para el usuario. Un estado de partida que no toca lanza ``ValueError``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ResultadoLike(Protocol):
    estado: str
    parcial: bool


@dataclass(frozen=True)
class Paso:
    nuevo: str | None
    avisos: tuple[str, ...] = ()
    veto: bool = False


def tras_montaje(estado: str, resultado: ResultadoLike) -> Paso:
    """``listo`` + montaje ``ejecutada`` → ``montado``; ``fallida``/``discrepancia`` → sin cambio, con aviso."""
    if estado != "listo":
        raise ValueError(f"el montaje solo avanza desde listo (el país está en {estado or 'sin estado'})")
    if resultado.estado == "ejecutada":
        return Paso("montado")
    if resultado.estado in ("fallida", "discrepancia"):
        if resultado.parcial or resultado.estado == "discrepancia":
            return Paso(None, ("estado parcial: el ejecutor pudo dejar algo creado en PAUSED; revísalo en el "
                               "histórico. No se vuelve a montar sin que lo digas.",))
        return Paso(None, ("el montaje falló sin crear nada: mira el detalle y corrige antes de volver a montar.",))
    return Paso(None, (f"el montaje sigue en {resultado.estado}: espera al ejecutor.",))


def tras_activar(estado: str, resultado: ResultadoLike) -> Paso:
    """``montado`` + activar ``ejecutada`` → ``test``; ``rechazada`` → veto; ``caducada``/``discrepancia`` → aviso."""
    if estado != "montado":
        raise ValueError(f"la activación solo avanza desde montado (el país está en {estado or 'sin estado'})")
    if resultado.estado == "ejecutada":
        return Paso("test")
    if resultado.estado == "rechazada":
        return Paso(None, ("rechazaste «Activar»: la campaña sigue en PAUSED (no se borra). Tu motivo queda como "
                           "veto de los creativos.",), veto=True)
    if resultado.estado == "caducada":
        return Paso(None, ("la propuesta de activar caducó sin tocar nada; cuando quieras: `trovefy montar activar`.",))
    if resultado.estado == "discrepancia":
        return Paso(None, ("la activación quedó en discrepancia: el ejecutor ya propuso cómo corregirla en Telegram.",))
    if resultado.estado in ("fallida", "obsoleta"):
        return Paso(None, (f"la activación quedó {resultado.estado}: no se activó nada; mira el detalle.",))
    return Paso(None, (f"la activación sigue en {resultado.estado}: espera tu toque en Telegram.",))
