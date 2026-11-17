"""Cierre de ``/producto``: todas las piezas aptas, versiones en ``PRODUCTO.md`` y ``modelado → producido``.

Falla cerrado: sin PDF, sin ``pdfinfo``, con un desborde, sin el veredicto ``ok`` de ``revisor`` y
``nativo`` para esa misma versión, o con un PDF que cambió después del QC, no hay cierre. Solo cuentan los
veredictos (gates, maqueta, revisor, nativo) cuyo ``sha256`` es el del PDF que hay hoy en disco. Las piezas
salen de ``FICHA.md`` (resolución 13); si la oferta o la escalera piden una pieza que la ficha no trae,
tampoco. El estado va por ``trovefy.vault.producto.avanzar_estado`` y el resto por
``actualizar_producto`` (resoluciones 1 y 2). Si el país ya está después de ``producido``, se anotan las
versiones y el estado no se toca. Otro país con el mismo idioma solo cierra si además paga en la misma
moneda que el país de la ficha (Ruling L5).
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trovefy.config import mercados
from trovefy.modelar.salida import cargar_escalera, cargar_oferta
from trovefy.pdf.render import nombre_pdf
from trovefy.producto.ficha import ESTADOS_PRODUCIBLES, Ficha, leer_ficha
from trovefy.producto.qc_registro import REGISTROS, leer_qc
from trovefy.producto.rutas import UPSELLS, pieza
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log
from trovefy.vault.producto import (
    actualizar_producto,
    avanzar_estado,
    estado_pais,
    ruta_producto,
)

TITULO_VERSIONES = "## Versiones del entregable"
_SKILL = "producto"
_PAIS = re.compile(r"[A-Z]{2}")
_ENTERO = re.compile(r"\d+")
_SIN_PDF = {
    "principal": "es el producto que se vende",
    "bono": "cada bono tiene su entregable real",
    "bump": "el bump siempre lleva entregable, aunque esté apagado",
    "upsell": "cada upsell tiene su entregable real",
}


@dataclass(frozen=True)
class EstadoPieza:
    id: str
    version: int | None
    pdf: str | None  # relativo a productos/<p-id>/
    paginas: int | None  # medidas con pdfinfo
    gates: str | None
    revisor: str | None
    nativo: str | None
    desbordes: int | None
    maqueta: str | None = None
    puntuacion: int | None = None
    pdf_intacto: bool = False  # el sha256 del PDF es el que se anotó en el QC

    @property
    def apta(self) -> bool:
        return (self.version is not None and self.pdf is not None and self.paginas is not None
                and self.gates == self.revisor == self.nativo == self.maqueta == "ok"
                and self.desbordes == 0 and self.pdf_intacto)


def _con_zona(ahora: datetime) -> datetime:
    if not isinstance(ahora, datetime) or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError(f"ahora sin zona horaria: {ahora!r} (usa un datetime con tzinfo)")
    return ahora


def _entero(texto: str | None) -> int | None:
    return int(texto) if isinstance(texto, str) and _ENTERO.fullmatch(texto) else None


def _ultimo_pdf(raiz: Path, ficha: Ficha, pieza_id: str) -> tuple[int, Path] | None:
    base = nombre_pdf(ficha, pieza_id, 1).removesuffix("-v1.pdf")
    patron = re.compile(rf"{re.escape(base)}-v([1-9]\d*)\.pdf")
    if not raiz.is_dir():
        return None
    versiones = [(int(m.group(1)), f) for f in raiz.iterdir() if (m := patron.fullmatch(f.name))]
    return max(versiones, key=lambda x: x[0]) if versiones else None


def _estado_pieza(vault: Path, p_id: str, ficha: Ficha, pieza_id: str) -> EstadoPieza:
    raiz = pieza(vault, p_id, pieza_id).raiz
    ultimo = _ultimo_pdf(raiz, ficha, pieza_id)
    if ultimo is None:
        return EstadoPieza(pieza_id, None, None, None, None, None, None, None)
    version, pdf = ultimo
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.is_file() and not pdf.is_symlink() else None
    # solo cuentan las anotaciones de esta versión hechas sobre este mismo PDF (Ruling M1)
    secciones = [s for s in leer_qc(raiz) if s.version == version and sha is not None
                 and s.datos.get("sha256") == sha]
    ultima = {s.agente: s for s in secciones}
    maqueta = ultima["maqueta"].datos if "maqueta" in ultima else {}
    gates = ultima["gates"].datos if "gates" in ultima else {}
    intacto = "maqueta" in ultima and maqueta.get("pdf") == pdf.name
    veredicto = {a: (ultima[a].veredicto if a in ultima else None) for a in REGISTROS}
    rel = pdf.relative_to(ruta_producto(vault, p_id).parent).as_posix()
    return EstadoPieza(pieza_id, version, rel, _entero(maqueta.get("pdfinfo")), veredicto["gates"],
                       veredicto["revisor"], veredicto["nativo"], _entero(maqueta.get("desbordes")),
                       maqueta=veredicto["maqueta"], puntuacion=_entero(gates.get("puntuacion")),
                       pdf_intacto=intacto)


def revisar(vault: Path, p_id: str) -> list[EstadoPieza]:
    """Una por pieza de ``FICHA.md``, con su última versión con PDF. Sin PDF: ``version=None``, no apta."""
    vault = Path(vault)
    ficha = leer_ficha(vault, p_id)
    return [_estado_pieza(vault, p_id, ficha, p.id) for p in ficha.piezas]


def _motivos(e: EstadoPieza, tipo: str) -> list[str]:
    if e.version is None:
        clave = "principal" if e.id == "principal" else tipo
        return [f"{e.id}: sin PDF ({_SIN_PDF.get(clave, 'cada pieza tiene su entregable real')})"]
    quien = f"{e.id} v{e.version}"
    motivos = []
    if not e.pdf_intacto:
        motivos.append(f"{quien}: el PDF cambió después del QC o no tiene QC de maqueta: vuelve a producirlo")
    for nombre, valor in (("gates", e.gates), ("maqueta", e.maqueta), ("revisor", e.revisor),
                          ("nativo", e.nativo)):
        if valor is None:
            motivos.append(f"{quien}: {nombre} no medido")
        elif valor != "ok":
            motivos.append(f"{quien}: {nombre} pide corregir")
    if e.paginas is None:
        motivos.append(f"{quien}: pdfinfo no medido")
    if e.desbordes is None:
        motivos.append(f"{quien}: desbordes no medidos")
    elif e.desbordes:
        motivos.append(f"{quien}: desborda en {e.desbordes} página(s) fija(s)")
    return motivos or ([] if e.apta else [f"{quien}: no es apta"])


def _piezas_pedidas(vault: Path, p_id: str, pais: str, ficha: Ficha) -> list[str]:
    """Piezas que la oferta y la escalera piden hoy y la ficha no trae (ficha desfasada)."""
    core = cargar_oferta(vault, p_id).get("core")
    bonos = core.get("bonos") if isinstance(core, dict) else None
    bloque = cargar_escalera(vault, p_id).get(pais)
    pasos = bloque.get("pasos") if isinstance(bloque, dict) else None
    if not isinstance(pasos, dict):
        return [f"ESCALERA.md no trae los pasos de {pais}: /modelar"]
    pedidas = ["principal", *(f"bono-{n}" for n in range(1, len(bonos or []) + 1)), "bump"]
    pedidas += [u for u in UPSELLS if isinstance(pasos.get(u), dict) and pasos[u].get("activo") is True]
    tiene = {p.id for p in ficha.piezas}
    return [f"{x}: no está en FICHA.md y la oferta o la escalera lo piden: rehaz el paso 1"
            for x in pedidas if x not in tiene]


def _ya_anotada(previa: object, e: EstadoPieza) -> bool:
    return (isinstance(previa, dict) and previa.get("version") == e.version and previa.get("pdf") == e.pdf
            and previa.get("paginas") == e.paginas and isinstance(previa.get("fecha"), str))


def _vigentes(vault: Path, p_id: str, idioma: str) -> dict:
    meta, _ = frontmatter.leer(ruta_producto(vault, p_id))
    previas = ((meta.get("entregable") if isinstance(meta, dict) else None) or {})
    previas = previas.get(idioma) if isinstance(previas, dict) else None
    return previas if isinstance(previas, dict) else {}


def _vigente_perdido(previa: object, e: EstadoPieza) -> str | None:
    """Motivo si ``PRODUCTO.md`` ya anotó una versión más alta que el último PDF que queda (Ruling L4)."""
    version = previa.get("version") if isinstance(previa, dict) else None
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    if e.version is None or version > e.version:
        return f"{e.id}: el PDF vigente v{version} ya no existe"
    return None


def cerrar(vault: Path, p_id: str, pais: str, ahora: datetime) -> tuple[bool, list[str]]:
    """``(True, mensajes)`` si todas las piezas son aptas y se anotaron; ``(False, motivos)`` si no.

    Las versiones se escriben en ``PRODUCTO.md`` antes que el estado: si ``avanzar_estado`` falla (otro
    proceso movió el estado), las versiones ya anotadas se quedan, porque las piezas son aptas igual.
    """
    vault, ahora = Path(vault), _con_zona(ahora)
    pais = pais.strip().upper() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(pais):
        raise ValueError("país mal escrito: usa su código de dos letras")
    try:
        ficha = leer_ficha(vault, p_id)
    except (FileNotFoundError, ValueError) as exc:
        return False, [str(exc)]
    ruta_mercados = vault / "config" / "mercados.yaml"
    if not ruta_mercados.is_file():
        return False, ["falta config/mercados.yaml"]
    mercado = mercados.cargar(ruta_mercados).get(pais)
    if mercado is None:
        return False, [f"{pais} no está en config/mercados.yaml"]
    if mercado.idioma != ficha.idioma:
        idioma = mercado.idioma
        return False, [f"{pais} habla {idioma} y el entregable está en {ficha.idioma}: produce la versión {idioma}"]
    if pais != ficha.pais:
        origen = mercados.cargar(ruta_mercados).get(ficha.pais)
        if origen is None:
            return False, [f"{ficha.pais} (el país de la ficha) no está en config/mercados.yaml"]
        if origen.moneda != mercado.moneda:
            motivo = (f"{pais} paga en {mercado.moneda} y el entregable se hizo para {ficha.pais} en "
                      f"{origen.moneda}: produce la versión de {pais}")
            return False, [motivo]
    estado = estado_pais(vault, p_id, pais)
    if estado not in ESTADOS_PRODUCIBLES:
        return False, [f"{pais} está en «{estado or 'sin estado'}»: primero /modelar"]

    try:
        motivos = _piezas_pedidas(vault, p_id, pais, ficha)
        estados = revisar(vault, p_id)
    except (FileNotFoundError, ValueError) as exc:
        return False, [str(exc)]
    previas = _vigentes(vault, p_id, ficha.idioma)
    tipos = {p.id: p.tipo for p in ficha.piezas}
    for e in estados:
        if (perdido := _vigente_perdido(previas.get(e.id), e)) is not None:
            motivos.append(perdido)
        if not e.apta:
            motivos += _motivos(e, tipos[e.id])
    if motivos:
        return False, motivos

    fecha = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    nuevas = [e for e in estados if not _ya_anotada(previas.get(e.id), e)]
    vigentes = {e.id: {"version": e.version, "pdf": e.pdf, "paginas": e.paginas, "fecha": fecha} for e in nuevas}
    lineas = [f"- {fecha} · {e.id} v{e.version} · {e.pdf} · {e.paginas} págs · gates {e.puntuacion} · "
              f"revisor {e.revisor} · nativo {e.nativo}" for e in nuevas]
    if nuevas:
        actualizar_producto(vault, p_id, {"entregable": {ficha.idioma: vigentes}}, [TITULO_VERSIONES, *lineas],
                            _SKILL, ahora)
        mensajes = [f"{len(estados)} piezas aptas en {ficha.idioma}; versiones nuevas en PRODUCTO.md: "
                    + ", ".join(f"{e.id} v{e.version}" for e in nuevas)]
    else:
        mensajes = [f"{len(estados)} piezas aptas en {ficha.idioma}; sus versiones ya estaban en PRODUCTO.md"]
    if estado == "modelado":
        evidencia = [f"productos/{p_id}/{e.pdf}" for e in estados]
        avanzar_estado(vault, p_id, pais, "modelado", "producido", evidencia, _SKILL, ahora)
        mensajes.append(f"{pais}: modelado → producido")
    else:
        mensajes.append(f"{pais} ya está en «{estado}»: se anotan las versiones y el estado no cambia")
    anadir_log(vault, _SKILL, f"{p_id} {pais}: cierre del entregable ({len(estados)} piezas, estado {estado}"
               + (" → producido)" if estado == "modelado" else ", sin cambios)"),
               [ruta_producto(vault, p_id).relative_to(vault).as_posix()], ahora=ahora)
    return True, mensajes
