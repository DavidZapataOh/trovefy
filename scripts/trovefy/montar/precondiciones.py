"""Precondiciones de «Activar» antes de depositar el montaje (§4.13 ``montado → test``; plan 22, Tarea 4).

**Qué hacen los vídeos:** «no lanzar sin píxel + checkout verificados»: Trusa perdió cuatro días sin ventas
(L2 0:19:45); el documento de campaña abre con el CPA break-even antes de la estructura (C1 18:10).

Se comprueba **antes** del montaje porque el ejecutor genera «Activar» él solo al terminar. En este orden y sin cortar
en el primero: (1) estado ``listo`` (o ``montado`` tras un veto, resolución 8); (2) `/listo` nuevo con
``listo_para_activar(informe, admitidas)`` (incluye caja, ejecutor y STOP, medidos en el instante); (3) BE y CPA_BE
medidos; (4) dataset y página en los límites del ejecutor, leído hace ≤ 7 días; (5) ningún montaje vivo.

**Excepciones para activar** (añadido, no cambia el método; mecanismo de la resolución 29): el usuario admite, con
sus palabras, activar con una excepción de `/listo` ya aprobada, en ``decisiones/<fecha>-activar-con-excepcion-<gate>.md``.
Solo valen los gates que admiten excepción (`EXCEPCION_DE_GATE`) y nunca los que miden la compra, la entrega, la caja,
el ejecutor, el STOP, los creativos o la landing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from trovefy.listo import EXCEPCION_DE_GATE
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import ruta_producto, secreto_en

NUNCA = frozenset({"compra", "entrega", "caja", "ejecutor", "stop", "creativos", "landing_movil"})
GATES_ADMISIBLES = frozenset(g for g, r in EXCEPCION_DE_GATE.items() if r is not None) - NUNCA
_DECISION = "activar_con_excepcion"
DIAS_DATASET = 7
COMANDO_DATASET = "sudo -u trovefy-exec /home/trovefy-exec/.local/bin/trovefy-ejecutor comprobar-dataset {dataset}"


@dataclass(frozen=True)
class ExcepcionActivar:
    gate: str
    palabras: str
    motivo: str
    ruta: str
    fecha: str


@dataclass
class Precondiciones:
    ok: bool = True
    lineas: list[str] = field(default_factory=list)
    bloqueos: list[str] = field(default_factory=list)

    def bien(self, texto: str) -> None:
        self.lineas.append(f"✓ {texto}")

    def mal(self, texto: str) -> None:
        self.ok = False
        self.lineas.append(f"✗ {texto}")
        self.bloqueos.append(texto)


def _carpeta(vault: Path, p_id: str) -> Path:
    return ruta_producto(vault, p_id).parent / "decisiones"


def registrar_excepcion_activar(vault: Path, p_id: str, pais: str, gate: str, palabras: str, motivo: str,
                                ahora: datetime) -> Path:
    """Escribe la decisión del usuario. ``ValueError`` (sin escribir) si el gate no se admite para activar, si faltan
    las palabras o el motivo, o si llevan algo con forma de secreto."""
    vault = Path(vault)
    if gate not in GATES_ADMISIBLES:
        raise ValueError(f"el gate «{gate}» no se admite para activar; solo: {', '.join(sorted(GATES_ADMISIBLES))}")
    for que, v in (("las palabras literales del usuario (--cita)", palabras), ("el motivo (--motivo)", motivo)):
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"faltan {que}")
    if secreto_en(palabras) or secreto_en(motivo):
        raise ValueError("aparece algo con forma de secreto; no se guarda nada")
    if not ruta_producto(vault, p_id).is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md")
    hoy = ahora.astimezone(ZONA_NEGOCIO).date().isoformat()
    meta = {"tipo": "decision", "decision": _DECISION, "fecha": hoy, "fuente": "usuario", "producto": p_id,
            "pais": pais, "gate": gate, "motivo": motivo.strip(), "palabras_del_usuario": palabras.strip()}
    cuerpo = "\n".join([
        f"# Activar con excepción · {gate} · {p_id} · {pais} ({hoy})", "",
        f"El usuario admite activar campañas con la excepción aprobada del gate «{gate}» de /listo. No cuenta como "
        "verde.", "", f"Motivo: {motivo.strip()}", "", "Palabras del usuario (cita literal):", "",
        *(f"> {x}" if x else ">" for x in palabras.strip().split("\n")), ""])
    carpeta = _carpeta(vault, p_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{hoy}-activar-con-excepcion-{gate}.md"
    escribir_atomico(destino, frontmatter.renderizar(meta, cuerpo))
    anadir_log(vault, "/montar", f"{p_id} {pais}: el usuario admite activar con la excepción de «{gate}»",
               [destino.relative_to(vault).as_posix()], ahora=ahora)
    return destino


def excepciones_para_activar(vault: Path, p_id: str, pais: str) -> dict[str, ExcepcionActivar]:
    """Las decisiones válidas (la más reciente por gate); lo ilegible o incompleto se salta."""
    vault = Path(vault)
    carpeta = _carpeta(vault, p_id)
    salida: dict[str, ExcepcionActivar] = {}
    for ruta in sorted(carpeta.glob("*-activar-con-excepcion-*.md")) if carpeta.is_dir() else ():
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(meta, dict):
            continue
        if (meta.get("tipo"), meta.get("decision"), meta.get("fuente")) != ("decision", _DECISION, "usuario"):
            continue
        if meta.get("producto") != p_id or meta.get("pais") != pais or meta.get("gate") not in GATES_ADMISIBLES:
            continue
        palabras, motivo = meta.get("palabras_del_usuario"), meta.get("motivo")
        if not (isinstance(palabras, str) and palabras.strip() and isinstance(motivo, str) and motivo.strip()):
            continue
        salida[meta["gate"]] = ExcepcionActivar(meta["gate"], palabras.strip(), motivo.strip(),
                                                ruta.relative_to(vault).as_posix(), str(meta.get("fecha")))
    return salida


def _bloque(vault: Path, p_id: str, pais: str) -> dict:
    from trovefy.montar.tanda import bloque_pais

    return bloque_pais(vault, p_id, pais)


def _estado_propuesta(vault: Path, id_: object) -> str | None:
    if not isinstance(id_, str):
        return None
    ruta = Path(vault) / "propuestas" / f"{id_}.md"
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    return meta.get("estado") if isinstance(meta, dict) else None


def vetado(trafico: dict, vault: Path) -> bool:
    """El último «Activar» de este montaje se rechazó (resolución 8)."""
    return _estado_propuesta(vault, trafico.get("activar")) == "rechazada"


def _dataset(vault: Path, p_id: str, pais: str, ahora: datetime, pre: Precondiciones, dataset: str | None) -> None:
    ruta = ruta_producto(vault, p_id).parent / "checkout" / pais / "TRACKING.md"
    comando = COMANDO_DATASET.format(dataset=dataset or "<dataset_id>")
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        pre.mal(f"no medido: falta TRACKING.md del país; el usuario ejecuta: {comando}")
        return
    ej = meta.get("ejecutor") if isinstance(meta, dict) else None
    if not isinstance(ej, dict):
        pre.mal(f"no medido: el ejecutor aún no comprobó el dataset; el usuario ejecuta: {comando}")
        return
    try:
        fecha = datetime.fromisoformat(str(ej.get("fecha")))
        if fecha.tzinfo is None:
            raise ValueError
    except ValueError:
        pre.mal(f"no medido: la comprobación del dataset no tiene fecha; el usuario ejecuta: {comando}")
        return
    faltan = [k for k in ("dataset_permitido", "pagina_permitida", "lectura_ok") if ej.get(k) is not True]
    if faltan:
        pre.mal(f"dataset y página en el ejecutor: falta {', '.join(faltan)} (TRACKING.md → ejecutor)")
    elif ahora - fecha > timedelta(days=DIAS_DATASET):
        pre.mal(f"la comprobación del dataset es de hace más de {DIAS_DATASET} días; el usuario ejecuta: {comando}")
    else:
        pre.bien("dataset y página en los límites del ejecutor")


def comprobar(vault: Path, p_id: str, pais: str, ahora: datetime, fuentes, *,
              evaluar: Callable | None = None, renovacion: bool = False) -> Precondiciones:
    """Las precondiciones, sin cortar en la primera. ``evaluar`` (para las pruebas) sustituye a
    ``trovefy.listo.veredicto.evaluar``. Con ``renovacion``, el país debe estar en ``test`` o ``candidato``."""
    from trovefy.listo import veredicto

    vault = Path(vault)
    pre = Precondiciones()
    bloque = _bloque(vault, p_id, pais)
    estado = bloque.get("estado")
    trafico = bloque.get("trafico") if isinstance(bloque.get("trafico"), dict) else {}
    # 1) estado
    if renovacion:
        if estado in ("test", "candidato"):
            pre.bien(f"estado {estado}: se puede renovar")
        else:
            pre.mal(f"estado {estado or 'sin estado'}: la renovación es para un test vivo (test o candidato)")
    elif estado == "listo":
        pre.bien("estado listo")
    elif estado == "montado" and vetado(trafico, vault):
        pre.bien("estado montado con «Activar» rechazado: se monta de nuevo (otra campaña; la anterior sigue en PAUSED)")
    else:
        pre.mal(f"estado {estado or 'sin estado'}: /montar solo monta desde listo (o montado tras un veto)")
    # 2) y 3) /listo para activar (incluye caja, ejecutor y STOP en el instante) y el BE
    admitidas = excepciones_para_activar(vault, p_id, pais)
    try:
        informe = (evaluar or veredicto.evaluar)(vault, p_id, pais, ahora, fuentes)
    except (OSError, ValueError) as exc:
        pre.mal(f"no medido: /listo no se pudo evaluar ({exc})")
        informe = None
    if informe is not None:
        for g in informe.gates:
            if g.estado == "ok":
                continue
            if g.estado == "excepcion" and g.clave in admitidas:
                x = admitidas[g.clave]
                pre.bien(f"{g.clave}: excepción admitida para activar con tus palabras («{x.palabras}», {x.ruta})")
            elif g.estado == "excepcion":
                admite = g.clave in GATES_ADMISIBLES
                pre.mal(f"{g.clave}: excepción de /listo no admitida para activar"
                        + (f" (si la admites: trovefy montar excepcion --gate {g.clave} --cita «tus palabras»)"
                           if admite else " (este gate no admite excepción para activar)"))
            else:
                pre.mal(f"{g.clave}: {g.texto}")
        if veredicto.listo_para_activar(informe, frozenset(admitidas)):
            pre.bien("/listo para activar")
        if informe.be_medido:
            pre.bien(f"economía: {informe.economia}")
        else:
            pre.mal(f"{informe.economia} (falta ruta_activa o comisiones en config/economia.yaml: Tarea 12, R1)")
    # 4) dataset y página en el ejecutor
    tracking = bloque.get("tracking") if isinstance(bloque.get("tracking"), dict) else {}
    _dataset(vault, p_id, pais, ahora, pre, tracking.get("dataset_id"))
    # 5) ningún montaje vivo
    if not renovacion and trafico.get("montaje"):
        est = _estado_propuesta(vault, trafico.get("montaje"))
        if est in (None, "recibida", "enviada", "aceptada", "ejecutando"):
            pre.mal(f"hay un montaje en curso ({trafico['montaje']}): espera a que el ejecutor termine")
        elif est == "ejecutada" and not vetado(trafico, vault):
            pre.mal(f"ya hay una campaña montada ({trafico['montaje']}); no se monta otra")
    return pre


def hoy_negocio(ahora: datetime) -> date:
    return ahora.astimezone(ZONA_NEGOCIO).date()
