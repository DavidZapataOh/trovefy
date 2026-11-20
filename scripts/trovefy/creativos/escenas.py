"""Escenas de la tanda con APIMart (plan 21, Tarea 4): el mismo lote, precio, tope, cerrojo e idempotencia que el
entregable, con el libro de gasto y los medios en la carpeta de la tanda (``fuente/medios/``).

Las referencias de una escena solo pueden ser medios propios: los del entregable (que se copian a ``fuente/`` como
``origen: propio``) o escenas ya generadas de la tanda. Nada ajeno (contrato 4).
"""

from __future__ import annotations

import time
from pathlib import Path

from trovefy.apimart import lote
from trovefy.apimart.cliente import PeticionImagen
from trovefy.aprobaciones import fuentes
from trovefy.creativos import coste
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import Contexto, ruta_tanda
from trovefy.creativos.guion import Escena
from trovefy.producto.medios import (
    CARPETA,
    escribir_medio,
    leer_manifiesto,
    registrar_medio,
)

FUENTE = "fuente"


def raiz_fuente(carpeta: Path) -> Path:
    return Path(carpeta) / FUENTE


def destino(vault: Path, ctx: Contexto, cfg: ConfigCreativos, tanda: str) -> lote.Destino:
    """El destino de la tanda: su libro, su tope (el menor entre el tope y lo aprobado) y el permiso del usuario."""
    def permiso() -> str | None:
        return coste.limite(vault, ctx.producto, ctx.pais, tanda, cfg)[1]

    d = lote.destino_tanda(vault, ctx.producto, ctx.pais, tanda, cfg.tope_tanda_usd, permiso)
    return lote.Destino(d.nombre, d.raiz_libro, d.raiz_medios, d.pieza_valida,
                        lambda: coste.limite(vault, ctx.producto, ctx.pais, tanda, cfg)[0], d.skill, permiso, d.quien)


def importar_referencias(vault: Path, ctx: Contexto, carpeta: Path, ids: set[str]) -> list[str]:
    """Copia a ``fuente/medios/`` los medios propios del entregable que citan las escenas o los guiones."""
    fuente = raiz_fuente(carpeta)
    propios = leer_manifiesto(fuente)
    hechos = []
    for id_ in sorted(ids):
        if id_ in propios or id_ not in ctx.medios_propios:
            continue
        origen = ctx.medios_propios[id_]
        datos = origen.read_bytes()
        archivo = f"{id_}{origen.suffix.lower()}"
        sha = escribir_medio(fuente / CARPETA / archivo, datos, base=Path(vault))
        registrar_medio(fuente, id_, archivo, sha, "propio", base=Path(vault),
                        copia_de=origen.relative_to(vault).as_posix())
        hechos.append(id_)
    return hechos


def peticiones(escenas: list[Escena], cfg: ConfigCreativos) -> list[PeticionImagen]:
    return [PeticionImagen(e.id, "escena", e.prompt, e.proporcion, cfg.resolucion, e.referencias) for e in escenas]


def generar(vault: Path, ctx: Contexto, cfg: ConfigCreativos, tanda: str, escenas: list[Escena], *, cred, precio,
            abrir, abrir_publico, ahora, simular: bool = False, depositar=fuentes.depositar, dormir=time.sleep,
            reloj=time.monotonic) -> lote.ResultadoLote:
    carpeta = ruta_tanda(vault, ctx.producto, ctx.pais, tanda)
    faltan = {r for e in escenas for r in e.referencias} - set(leer_manifiesto(raiz_fuente(carpeta)))
    ajenas = sorted(r for r in faltan if r not in ctx.medios_propios and r not in {e.id for e in escenas})
    if ajenas:
        raise ValueError(f"referencias que no son medios propios: {', '.join(ajenas)}; nada ajeno entra en una tanda")
    importar_referencias(vault, ctx, carpeta, faltan & set(ctx.medios_propios))  # copia local, gratis
    return lote.generar_imagenes(vault, ctx.producto, peticiones(escenas, cfg), cred=cred, cfg=None, precio=precio,
                                 abrir=abrir, abrir_publico=abrir_publico, dormir=dormir, ahora=ahora,
                                 simular=simular, depositar=depositar, reloj=reloj,
                                 destino=destino(vault, ctx, cfg, tanda))
