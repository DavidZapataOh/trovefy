"""Veredicto de `/listo` (plan 20, Tarea 4): los once gates en orden, las excepciones aprobadas y el texto del informe.

- `InformeListo.verde`: todos los gates en ``ok``, salvo ``creativos``, que puede estar en ``no_aplica`` (Decisión
  del plan 20). Una excepción **nunca** es verde.
- `InformeListo.pasa`: verde, o con excepciones aprobadas por el usuario en los gates que las admiten
  (`trovefy.listo.EXCEPCION_DE_GATE`). Es lo que permite el paso ``con_checkout → listo``.
- `listo_para_activar`: los once en ``ok`` (también ``creativos``), sin excepciones, y el BE medido (resolución 11).
  Lo usa la fase 3 antes de activar, sobre una evaluación nueva.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import yaml

from trovefy.listo import EXCEPCION_DE_GATE, GATES, gates, momento
from trovefy.listo.ficha import leer_ficha
from trovefy.listo.gates import Gate

MARCAS = {"ok": "✓", "falla": "✗", "no_medido": "?", "no_aplica": "–", "excepcion": "!"}
_NO_APLICA_PERMITIDO = frozenset({"creativos"})


@dataclass(frozen=True)
class FuentesListo:
    spool: Path
    abrir_landing: Callable
    trm_de: Callable[[date], object]


def fuentes_por_defecto(vault: Path) -> FuentesListo:
    from trovefy import trm as trm_mod
    from trovefy.aprobaciones.fuentes import ruta_spool

    return FuentesListo(spool=ruta_spool(), abrir_landing=momento._abrir_landing,
                        trm_de=lambda d: trm_mod.trm_del_dia(vault, d, abrir=trm_mod._abrir_seguro))


@dataclass(frozen=True)
class InformeListo:
    producto: str
    pais: str
    fecha: datetime
    gates: tuple[Gate, ...]
    economia: str = "no medido: sin ESCALERA.md"  # nota informativa, no es gate (resolución 11)
    be_medido: bool = False

    @property
    def verde(self) -> bool:
        return all(g.estado == "ok" or (g.estado == "no_aplica" and g.clave in _NO_APLICA_PERMITIDO)
                   for g in self.gates)

    @property
    def pasa(self) -> bool:
        return all(g.estado in ("ok", "excepcion") or (g.estado == "no_aplica" and g.clave in _NO_APLICA_PERMITIDO)
                   for g in self.gates)


def listo_para_activar(informe: InformeListo, admitidas: frozenset[str] = frozenset()) -> bool:
    """Los once gates en ``ok`` (nunca ``no_aplica``) y el BE medido: el criterio para activar campañas (fase 3,
    ``montado → test``), siempre sobre una evaluación nueva. ``admitidas`` (plan 22, Tarea 4): gates cuya excepción
    aprobada el usuario admitió **también para activar** (``decisiones/*-activar-con-excepcion-<gate>.md``); un gate
    en ``excepcion`` solo pasa si está ahí. Sin ``admitidas``, igual que antes: ninguna excepción."""
    return (tuple(g.clave for g in informe.gates) == GATES
            and all(g.estado == "ok" or (g.estado == "excepcion" and g.clave in admitidas) for g in informe.gates)
            and informe.be_medido)


def _con_excepcion(g: Gate, aprobadas: dict) -> Gate:
    requisito = EXCEPCION_DE_GATE.get(g.clave)
    if g.estado in ("ok", "no_aplica") or requisito is None or not g.cubre_excepcion:
        return g
    x = aprobadas.get(requisito)
    if x is None:
        return g
    return replace(g, estado="excepcion",
                   texto=(f"excepción aprobada por el usuario en «{requisito}», no es verde: «{x.palabras}» "
                          f"({x.ruta}); motivo: {x.motivo}; sin la excepción: {g.texto}"),
                   evidencia=(*g.evidencia, x.ruta))


def _economia(vault: Path, producto: str, pais: str) -> tuple[str, bool]:
    from trovefy.vault import frontmatter

    ruta = Path(vault) / "productos" / producto / "ESCALERA.md"
    if not ruta.is_file():
        return "no medido: falta ESCALERA.md (/trovefy:modelar)", False
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return "no medido: ESCALERA.md no se puede leer", False
    paises = meta.get("paises") if isinstance(meta, dict) else None
    b = paises.get(pais) if isinstance(paises, dict) else None
    if not isinstance(b, dict):
        return f"no medido: ESCALERA.md no trae {pais}", False
    be, cpa = b.get("be_usd"), b.get("cpa_be_usd")
    if be is None:
        motivo = str(b.get("be_usd_motivo") or "BE sin calcular")
        return (motivo if motivo.startswith("no medido") else f"no medido: {motivo}"), False
    return f"BE {be} USD · CPA de equilibrio {cpa if cpa is not None else 'no medido'} USD", True


def evaluar(vault: Path, producto: str, pais: str, ahora: datetime, fuentes: FuentesListo) -> InformeListo:
    """Los once gates, en el orden de `GATES`, con las excepciones aprobadas aplicadas. Un error inesperado dentro
    de un gate lo deja «no medido: error interno (<Tipo>)» sin tumbar los demás. `FileNotFoundError`, `ValueError`
    o `FichaIlegible` si el producto o el país están mal o ``PRODUCTO.md`` no se puede leer."""
    from trovefy.arranque.estado import cargar
    from trovefy.arranque.verificadores.dominio import dominio_guardado
    from trovefy.checkout.cierre import excepciones

    vault = Path(vault)
    f = leer_ficha(vault, producto, pais)

    def paso08():
        return next((p for p in cargar(vault) if p.id == "08"), None)

    def dataset():
        otros, notas = gates.datasets_de_otros(vault, producto, pais)
        return gates.gate_dataset(f, otros, notas)

    calculos: dict[str, Callable[[], Gate]] = {
        "landing_movil": lambda: momento.gate_landing_movil(f, abrir=fuentes.abrir_landing, ahora=ahora),
        "utm_checkout": lambda: gates.gate_utm(f),
        "compra": lambda: gates.gate_compra(f),
        "entrega": lambda: gates.gate_entrega(f),
        "reembolso": lambda: gates.gate_reembolso(f),
        "dominio": lambda: gates.gate_dominio(gates.campo(f.datos, "landing.url"), dominio_guardado(vault), paso08()),
        "dataset": dataset,
        "creativos": lambda: gates.gate_creativos(f),
        "caja": lambda: momento.gate_caja(vault, ahora.date(), fuentes.trm_de),
        "ejecutor": lambda: momento.gate_ejecutor(ahora, fuentes.spool),
        "stop": lambda: momento.gate_stop(vault, fuentes.spool),
    }
    try:
        aprobadas = excepciones(vault, producto, pais)
    except (OSError, ValueError):
        aprobadas = {}
    resultado = []
    for clave in GATES:
        try:
            g = calculos[clave]()
        except Exception as exc:  # noqa: BLE001 - un gate roto no tumba los demás
            g = Gate(clave, "no_medido", f"no medido: error interno ({type(exc).__name__})")
        resultado.append(_con_excepcion(g, aprobadas))
    texto_eco, be_ok = _economia(vault, producto, pais)
    return InformeListo(producto, pais, ahora, tuple(resultado), texto_eco, be_ok)


def resumen_gates(informe: InformeListo) -> dict:
    """``{clave: {estado, texto, evidencia}}`` para ``paises.<PAIS>.listo.gates``."""
    return {g.clave: {"estado": g.estado, "texto": g.texto, "evidencia": list(g.evidencia)} for g in informe.gates}


def texto_informe(informe: InformeListo) -> str:
    """Una línea por gate (✓ ok, ✗ falla, ? no medido, – no aplica, ! excepción), el veredicto, la nota de economía
    y, si hay, «Arreglos:»."""
    lineas = [f"{MARCAS[g.estado]} {g.clave}: {g.texto}" for g in informe.gates]
    if informe.verde:
        lineas.append("Veredicto: verde (se puede comprar).")
    elif informe.pasa:
        con = ", ".join(g.clave for g in informe.gates if g.estado == "excepcion")
        lineas.append(f"Veredicto: pasa con excepciones aprobadas por el usuario ({con}); no es verde.")
    else:
        lineas.append("Veredicto: rojo (aún no se puede comprar).")
    lineas.append(f"Economía (nota, no es gate): {informe.economia}")
    arreglos = [f"- {g.clave}: {g.arreglo}" for g in informe.gates
                if g.arreglo and g.estado in ("falla", "no_medido")]
    if arreglos:
        lineas += ["Arreglos:", *arreglos]
    return "\n".join(lineas)

