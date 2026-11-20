"""Coste de la tanda (plan 21, Tarea 4): tope, estimación, aprobación del usuario y límite de cada envío.

- **Tope** de la tanda: ``gasto.tope_tanda_usd`` (o ``tope_renovacion_usd`` en una renovación) de
  ``config/creativos.yaml``, salvo que el usuario fije otra cifra con sus palabras (``trovefy creativos tope``:
  ``decisiones/<fecha>-tope-creativos-<PAIS>-<tN|renovacion>.md``). Manda la última decisión con cita.
- **Estimación**: lo que costaría hacer la tanda como está escrita (escenas, clips por plantilla, voz, música),
  con precios medidos; lo que no tiene precio queda «no medido» y no deja aprobar.
- **Aprobación**: ``trovefy creativos aprobar-coste --cita`` guarda en ``TANDA.md`` la estimación vigente con las
  palabras del usuario. Sin ella **nada** de pago sale (APIMart ni ElevenLabs). En una renovación vale también el
  tope de renovación que el usuario aprobó (la rutina de 48 h gasta dentro de él sin preguntar).
- **Límite** de cada envío: lo gastado + lo estimado de ese envío ≤ el menor entre el tope y lo aprobado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import ruta_tanda
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import secreto_en

SKILL = "/creativos"
_DECISION = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})-tope-creativos-([A-Z]{2})-(t[1-9]\d{0,2}|renovacion)\.md")
SIN_APROBAR = ("falta tu «sí» al coste mostrado: enséñale al usuario la estimación (--simular) y, con sus palabras, "
               "`trovefy creativos aprobar-coste … --cita '…'`; no se envía nada")


def _importe(v: object) -> Decimal | None:
    if v is None or isinstance(v, (bool, float)):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() and d > 0 else None


def _decisiones(vault: Path, producto: str, pais: str) -> list[tuple[str, str, Decimal, Path]]:
    """(marca, tanda, importe, ruta) de cada decisión válida (con cita) del país, en orden de marca."""
    carpeta = Path(vault) / "productos" / producto / "decisiones"
    salida = []
    if not carpeta.is_dir():
        return []
    for ruta in carpeta.glob("*-tope-creativos-*.md"):
        m = _DECISION.fullmatch(ruta.name)
        if not m or m.group(2) != pais or ruta.is_symlink():
            continue
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        cita = meta.get("cita") if isinstance(meta, dict) else None
        usd = _importe(meta.get("tope_usd")) if isinstance(meta, dict) else None
        if isinstance(cita, str) and cita.strip() and usd is not None and meta.get("tanda") == m.group(3):
            salida.append((m.group(1), m.group(3), usd, ruta))
    return sorted(salida)


def tope_renovacion_aprobado(vault: Path, producto: str, pais: str) -> Decimal | None:
    """El tope de renovación que el usuario aprobó con sus palabras (``None`` si no lo hizo)."""
    validas = [d for d in _decisiones(vault, producto, pais) if d[1] == "renovacion"]
    return validas[-1][2] if validas else None


def tope_vigente(vault: Path, producto: str, pais: str, tanda: str, cfg: ConfigCreativos) -> Decimal:
    carpeta = ruta_tanda(vault, producto, pais, tanda)
    renovacion = tanda_md.tipo(carpeta) == "renovacion"
    claves = (tanda, "renovacion") if renovacion else (tanda,)
    validas = [d for d in _decisiones(vault, producto, pais) if d[1] in claves]
    if validas:
        return validas[-1][2]
    return cfg.tope_renovacion_usd if renovacion else cfg.tope_tanda_usd


def _cita_md(cita: str) -> str:
    return "\n".join(f"> {x}" if x else ">" for x in cita.split("\n"))


def _validar_cita(cita: str) -> None:
    if not isinstance(cita, str) or not cita.strip():
        raise ValueError("hace falta la cita literal del usuario")
    if any(0x80 <= ord(c) <= 0x9F for c in cita):
        raise ValueError("la cita lleva caracteres de control que no se ven: escríbela de nuevo")
    if buscar_secreto(cita):
        raise ValueError("la cita trae algo con forma de secreto; no se guarda")


def fijar_tope(vault: Path, producto: str, pais: str, tanda: str, usd: Decimal, cita: str, ahora: datetime) -> Path:
    """El tope de la tanda (o ``renovacion``: el de todas las renovaciones) con las palabras del usuario."""
    vault = Path(vault)
    if ahora.tzinfo is None:
        raise ValueError("fecha sin zona horaria")
    if tanda != "renovacion":
        ruta_tanda(vault, producto, pais, tanda)  # valida
    _validar_cita(cita)
    if not isinstance(usd, Decimal) or not usd.is_finite() or usd <= 0 or usd.as_tuple().exponent < -2:
        raise ValueError("el tope va en USD, mayor que 0 y con dos decimales como mucho")
    meta = {"tipo": "decision", "fecha": ahora.date().isoformat(), "registrada": ahora.isoformat(timespec="seconds"),
            "fuente": "usuario", "producto": producto, "pais": pais, "decision": "tope_creativos", "tanda": tanda,
            "tope_usd": str(usd), "cita": cita}
    que = "todas las renovaciones" if tanda == "renovacion" else f"la tanda {tanda}"
    cuerpo = "\n".join([f"# Tope de creativos · {producto} {pais} · {que}", "",
                        f"{usd} USD de APIMart (y ElevenLabs, si hace falta) para {que}.", "",
                        "Palabras del usuario (cita literal):", "", _cita_md(cita), ""])
    texto = frontmatter.renderizar(meta, cuerpo)
    if secreto_en(meta) or buscar_secreto(texto):
        raise ValueError("la decisión trae algo con forma de secreto; no se guarda")
    destino = vault / "productos" / producto / "decisiones" / f"{ahora:%Y-%m-%d-%H%M%S}-tope-creativos-{pais}-{tanda}.md"
    if destino.exists():
        raise FileExistsError(f"ya existe {destino.name}: espera un segundo y repite")
    escribir_atomico(destino, texto)
    anadir_log(vault, SKILL, f"{producto} {pais}: tope de creativos de {que} = {usd} USD con la cita del usuario",
               [destino.relative_to(vault).as_posix()], ahora=ahora)
    return destino


# --- estimación ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Partida:
    concepto: str
    cantidad: int
    unidad: str
    usd_unidad: Decimal | None
    fuente: str

    @property
    def total(self) -> Decimal | None:
        return None if self.usd_unidad is None else (self.usd_unidad * self.cantidad).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class Estimacion:
    partidas: tuple[Partida, ...]

    @property
    def no_medido(self) -> tuple[str, ...]:
        return tuple(f"no medido: precio de {p.concepto} ({p.fuente})" for p in self.partidas
                     if p.usd_unidad is None and p.cantidad)

    @property
    def total(self) -> Decimal:
        return sum((p.total or Decimal(0) for p in self.partidas), Decimal(0)).quantize(Decimal("0.01"),
                                                                                         rounding="ROUND_UP")

    @property
    def usa_elevenlabs(self) -> bool:
        return any(p.concepto.startswith("voz ElevenLabs") and p.cantidad for p in self.partidas)

    def lineas(self) -> list[str]:
        salida = []
        for p in self.partidas:
            if not p.cantidad:
                continue
            precio = "no medido" if p.usd_unidad is None else f"{p.usd_unidad} USD/{p.unidad}"
            total = "no medido" if p.total is None else f"{p.total} USD"
            salida.append(f"{p.concepto}: {p.cantidad} {p.unidad} × {precio} = {total} ({p.fuente})")
        return salida


def aprobacion(carpeta: Path) -> dict | None:
    meta, _, _ = tanda_md.leer(carpeta)
    a = meta.get("aprobacion")
    if not isinstance(a, dict) or not isinstance(a.get("cita"), str) or not a["cita"].strip():
        return None
    return a if _importe(a.get("total_usd")) is not None else None


def aprobar(vault: Path, producto: str, pais: str, tanda: str, est: Estimacion, tope: Decimal, cita: str,
            ahora: datetime) -> Path:
    """Guarda en ``TANDA.md`` la estimación vigente con la cita del usuario. ``ValueError`` si algo está sin
    medir o la estimación supera el tope (entonces el usuario decide: otra cifra con ``tope`` o menos piezas)."""
    _validar_cita(cita)
    if est.no_medido:
        raise ValueError("no se aprueba un coste con partes sin medir:\n" + "\n".join(f"- {m}" for m in est.no_medido))
    if est.total > tope:
        raise ValueError(f"la estimación ({est.total} USD) supera el tope de la tanda ({tope} USD): el tope solo lo "
                         "cambia el usuario con sus palabras (`trovefy creativos tope`)")
    carpeta = ruta_tanda(vault, producto, pais, tanda)
    datos = {"total_usd": str(est.total), "tope_usd": str(tope), "cita": cita,
             "fecha": ahora.isoformat(timespec="seconds"), "elevenlabs": est.usa_elevenlabs,
             "partidas": est.lineas()}
    ruta = tanda_md.actualizar(carpeta, {"aprobacion": datos},
                               f"coste aprobado por el usuario: {est.total} USD (tope {tope} USD)", ahora)
    anadir_log(vault, SKILL, f"{producto} {pais} {tanda}: coste aprobado {est.total} USD con la cita del usuario",
               [ruta.relative_to(vault).as_posix()], ahora=ahora)
    return ruta


def limite(vault: Path, producto: str, pais: str, tanda: str, cfg: ConfigCreativos) -> tuple[Decimal, str | None]:
    """(tope efectivo, motivo para no enviar). Tope efectivo = el menor entre el tope y lo aprobado."""
    carpeta = ruta_tanda(vault, producto, pais, tanda)
    tope = tope_vigente(vault, producto, pais, tanda, cfg)
    a = aprobacion(carpeta)
    if a is not None:
        return min(tope, _importe(a["total_usd"])), None
    if tanda_md.tipo(carpeta) == "renovacion":
        aprobado = tope_renovacion_aprobado(vault, producto, pais)
        if aprobado is not None:
            return min(tope, aprobado), None
    return tope, SIN_APROBAR


def elevenlabs_aprobado(carpeta: Path) -> bool:
    a = aprobacion(carpeta)
    return bool(a and a.get("elevenlabs") is True)
