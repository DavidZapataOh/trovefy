"""Receta imprimible para lo que hace el usuario en su propio navegador (plan 19, Tarea 6).

Los vídeos dejan al humano «pegar las claves» y «mover la plata» (V2 0:28:45) y cierran con la lista de lo que
falta y quién lo hace (V1 1:14:15). trovefy nunca entra al panel: imprime los pasos exactos, con el valor entre
«», y el login del panel como texto (``https://impultienda.ar/login``; ``app.impultienda.ar`` no es el panel).
"""
from __future__ import annotations

from dataclasses import dataclass

from trovefy.secretos import buscar_secreto

LOGIN = "https://impultienda.ar/login"
_NO_PANEL = "app.impultienda.ar"  # no es el panel: solo para rechazarlo


@dataclass(frozen=True)
class PasoReceta:
    n: int
    donde: str
    campo: str
    valor: str
    nota: str = ""


def _linea(p: PasoReceta) -> list[str]:
    cabeza = f"{p.n}. {p.donde}"
    if p.campo:
        cabeza += f" → «{p.campo}»"
    if p.valor:
        cabeza += f": «{p.valor}»"
    return [cabeza, *(f"   {x}" for x in p.nota.splitlines() if x.strip())]


def imprimir_receta(titulo: str, pasos: list[PasoReceta]) -> str:
    """Los pasos numerados (1, 2, 3…), cada uno «dónde → «campo»: «valor»» y su nota debajo.

    ``ValueError`` si no hay pasos, si la numeración salta, si el texto lleva algo con forma de secreto o si
    menciona ``app.impultienda.ar`` (no es el panel)."""
    if not pasos:
        raise ValueError("la receta no tiene pasos")
    if [p.n for p in pasos] != list(range(1, len(pasos) + 1)):
        raise ValueError("la numeración de la receta debe ir 1, 2, 3… sin saltos")
    lineas = [titulo, f"Tu panel de Impultienda: {LOGIN} (lo abres tú, en tu navegador; trovefy no entra)", ""]
    for p in pasos:
        lineas += _linea(p)
    texto = "\n".join(lineas) + "\n"
    if _NO_PANEL in texto:
        raise ValueError(f"la receta menciona {_NO_PANEL}, que no es el panel: usa {LOGIN}")
    patron = buscar_secreto(texto)
    if patron:
        raise ValueError(f"la receta lleva algo con forma de secreto ({patron}): no la imprimo")
    return texto
