"""Respaldo manual guiado (plan 19, Tarea 12; cabecera del plan, punto 3).

Solo para el ajuste cuya herramienta del MCP falta o falla: el usuario lo hace en **su propio navegador** con la
receta exacta, pantalla a pantalla, y trovefy lo da por hecho con lo que el usuario pega (es el desvío que ya existía
antes del MCP). trovefy nunca abre el panel: imprime el login como texto.

Fuerza de la evidencia: una captura con sus valores confirmados queda ``captura``; solo las palabras del usuario
quedan ``dicho``, que vale para un «hecho» pero nunca para un precio.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from trovefy.checkout.fuera import EstadoFuera, leer_precio
from trovefy.checkout.receta import Ajuste, _texto, receta_manual
from trovefy.embudo.pegado import CLAVES
from trovefy.embudo.receta_texto import PasoReceta, imprimir_receta

_CAPTURA: tuple[tuple[str, str], ...] = (
    (r"producto\.front\.precio$|market\.[A-Z]{2}\.precio_front$", "ver-como"),
    (r"market\.", "market"),
    (r"producto\.", "producto"),
    (r"(?:checkout|tienda)\.", "checkout"),
    (r"postcompra\.(u[123])\.", r"upsell-\1"),
    (r"emails\.", "emails"),
    (r"bump\.", "bump"),
    (r"downsell\.", "downsell"),
    (r"tracking\.", "tracking-pixel"),
)


def clave_captura(clave_ajuste: str) -> str:
    """La clave de evidencia (`trovefy.embudo.pegado.CLAVES`) que prueba un ajuste hecho a mano."""
    for patron, clave in _CAPTURA:
        m = re.match(patron, clave_ajuste)
        if m:
            salida = m.expand(clave)
            assert salida in CLAVES
            return salida
    raise ValueError(f"ajuste sin evidencia conocida: {clave_ajuste}")


def _es_precio(clave: str) -> bool:
    return clave.endswith((".precio", ".precio_front"))


def _nombre_valor(clave: str) -> str:
    return clave.rsplit(".", 1)[-1]


def _ejemplo_valor(a: Ajuste) -> str:
    if _es_precio(a.clave):
        return f"precio=\"{str(a.valor).replace('.', ',')} €\""
    return f"{_nombre_valor(a.clave)}=\"{_texto(a.valor)}\""


def plan_manual(ajustes_manuales: Iterable[Ajuste], *, producto: str | None = None, pais: str | None = None) -> str:
    """El texto de ``RECETA-manual.md``: la receta del panel (`receta_manual` + `imprimir_receta`) y, por cada
    pantalla, la captura que hay que pegar con su comando ``trovefy checkout evidencia``."""
    ajustes = list(ajustes_manuales)
    if not ajustes:
        return "Nada va a mano: todo el checkout va por el MCP o se comprueba desde fuera.\n"
    pasos = [PasoReceta(p.n, p.pestana, "", "", p.instruccion) for p in receta_manual(ajustes)]
    texto = imprimir_receta("Checkout a mano (respaldo): hazlo tú en tu panel, en este orden", pasos)
    destino = f"--producto {producto or '<p-id>'} --pais {pais or '<PAIS>'}"
    por_clave: dict[str, list[Ajuste]] = {}
    for a in ajustes:
        por_clave.setdefault(clave_captura(a.clave), []).append(a)
    lineas = ["", "Capturas que hay que pegar (una por pantalla, sin tokens ni contraseñas a la vista):"]
    for clave, lista in por_clave.items():
        valores = " ".join(f"--valor {_ejemplo_valor(a)}" for a in lista)
        lineas.append(f"- {clave} ({', '.join(a.clave for a in lista)}): trovefy checkout evidencia {destino} "
                      f"--clave {clave} --desde <captura> {valores}")
    lineas += ["", ("Si no hay nada que leer (un «hecho»), bastan tus palabras: --dicho \"…\" en lugar de --desde. "
                    "Un precio nunca se da por bueno de palabra: va con captura."), ""]
    return texto + "\n".join(lineas)


def _decimal(texto: str) -> Decimal | None:
    try:
        return Decimal(str(texto)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def cerrar_manual(ajuste: Ajuste, indice: dict) -> EstadoFuera:
    """El estado de un ajuste hecho a mano según lo pegado (`trovefy.embudo.pegado.indice`): la última captura (o
    texto) con sus valores → ``captura`` (``falla`` si un valor no cuadra); solo palabras → ``dicho`` (para un precio,
    «no medido»); nada → «no medido» con el comando para pegarlo."""
    clave = clave_captura(ajuste.clave)
    esperado = _texto(ajuste.valor)
    pegados = indice.get(clave, [])
    prueba = next((p for p in reversed(pegados) if p.tipo in ("captura", "texto")), None)
    comando = f"trovefy checkout evidencia --clave {clave} --desde <captura> --valor {_ejemplo_valor(ajuste)}"
    if prueba is not None:
        if prueba.tipo == "captura" and not prueba.valores:
            return EstadoFuera(ajuste.clave, "no_medido", esperado, None,
                               f"no medido: la captura no lleva lo que se lee en ella: vuelve a registrarla con "
                               f"--valor ({comando})", None, prueba.ruta)
        if _es_precio(ajuste.clave):
            visto, _ = leer_precio(prueba.valores.get("precio"))
            if visto is None:
                return EstadoFuera(ajuste.clave, "no_medido", esperado, None,
                                   f"no medido: falta --valor precio=… en la captura ({comando})", None, prueba.ruta)
            igual = visto == _decimal(ajuste.valor)
            return EstadoFuera(ajuste.clave, "captura" if igual else "falla", esperado, str(visto),
                               "la captura cuadra" if igual else "la captura muestra otro precio",
                               "captura", prueba.ruta)
        visto = prueba.valores.get(_nombre_valor(ajuste.clave))
        if visto is not None and visto.casefold() != esperado.casefold():
            return EstadoFuera(ajuste.clave, "falla", esperado, visto, "la captura muestra otro valor", "captura",
                               prueba.ruta)
        return EstadoFuera(ajuste.clave, "captura", esperado, visto, "hecho a mano, con captura", "captura",
                           prueba.ruta)
    palabras = next((p for p in reversed(pegados) if p.tipo == "dicho"), None)
    if palabras is not None:
        if _es_precio(ajuste.clave):
            return EstadoFuera(ajuste.clave, "no_medido", esperado, None,
                               f"no medido: un precio no se da por bueno de palabra: pega la captura ({comando})",
                               None, palabras.ruta)
        return EstadoFuera(ajuste.clave, "dicho", esperado, None, "hecho a mano, según tus palabras", "dicho",
                           palabras.ruta)
    return EstadoFuera(ajuste.clave, "no_medido", esperado, None, f"no medido: falta la evidencia ({comando})")
