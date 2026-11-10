"""Estado de los pasos de /arranque en config/arranque.yaml.

Solo la evidencia de un verificador puede marcar un paso como «verificado».
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from trovify.arranque.catalogo import PASOS
from trovify.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico

Estado = Literal["pendiente", "hecho", "verificado", "bloqueado"]
_ESTADOS = ("pendiente", "hecho", "verificado", "bloqueado")
_COBRO = ("10", "10b")
_BASE_FASE0 = [i for i, _, f, _ in PASOS if f == 0 and i not in _COBRO and i != "16"]


class ArranqueCorrupto(Exception):
    """config/arranque.yaml no se puede leer; nunca se sobrescribe."""


class PasoDesconocido(KeyError):
    """El id no está en el catálogo."""

    def __str__(self) -> str:
        return f"no existe el paso «{self.args[0]}»"


@dataclass
class Paso:
    id: str
    nombre: str
    fase: int | None
    opcional: bool
    estado: Estado
    evidencia: list[str]
    fecha: str | None
    nota: str | None
    datos: dict[str, str]


@dataclass
class ResultadoVerificacion:
    ok: bool | None  # None = «no medido»
    evidencia: list[str]
    motivo: str
    arreglos: list[str]
    datos: dict[str, str] = field(default_factory=dict)
    lineas: list[str] = field(default_factory=list)  # para mostrar; no se guarda


def _ruta(vault: Path) -> Path:
    return Path(vault) / "config" / "arranque.yaml"


def _hoy() -> str:
    return datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d")


def _nuevo(id_: str, nombre: str, fase: int | None, opcional: bool) -> Paso:
    return Paso(id_, nombre, fase, opcional, "pendiente", [], None, None, {})


def _guardar(vault: Path, pasos: list[Paso]) -> None:
    texto = yaml.safe_dump({"pasos": [asdict(p) for p in pasos]}, allow_unicode=True, sort_keys=False)
    escribir_atomico(_ruta(vault), texto)


def _paso_desde(e: object, ruta: Path) -> Paso:
    if not isinstance(e, dict) or "id" not in e:
        raise ArranqueCorrupto(f"{ruta} tiene un paso sin id")
    estado = e.get("estado", "pendiente")
    if estado not in _ESTADOS:
        raise ArranqueCorrupto(f"{ruta}: estado desconocido «{estado}» en el paso {e['id']}")
    evidencia, datos = e.get("evidencia") or [], e.get("datos") or {}
    if not isinstance(evidencia, list) or not isinstance(datos, dict):
        raise ArranqueCorrupto(f"{ruta}: evidencia o datos mal formados en el paso {e['id']}")
    if estado == "verificado" and not evidencia:  # una edición a mano no certifica
        estado = "hecho"
    return Paso(
        id=str(e["id"]),
        nombre=str(e.get("nombre", "")),
        fase=e.get("fase"),
        opcional=bool(e.get("opcional", False)),
        estado=estado,
        evidencia=[str(x) for x in evidencia],
        fecha=None if e.get("fecha") is None else str(e["fecha"]),
        nota=None if e.get("nota") is None else str(e["nota"]),
        datos={str(k): str(v) for k, v in datos.items()},
    )


def cargar(vault: Path) -> list[Paso]:
    """Lee los pasos; crea el archivo desde el catálogo si falta y añade los que falten."""
    ruta = _ruta(vault)
    if not ruta.exists():
        pasos = [_nuevo(*p) for p in PASOS]
        _guardar(vault, pasos)
        return pasos
    try:
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ArranqueCorrupto(f"{ruta} no se puede leer: {exc}") from exc
    if not isinstance(crudo, dict) or not isinstance(crudo.get("pasos"), list):
        raise ArranqueCorrupto(f"{ruta} no tiene la lista «pasos»")
    pasos = [_paso_desde(e, ruta) for e in crudo["pasos"]]
    existentes = {p.id for p in pasos}
    faltan = [_nuevo(*p) for p in PASOS if p[0] not in existentes]
    if faltan:
        pasos += faltan
        pasos.sort(key=lambda p: _orden(p.id))
        _guardar(vault, pasos)
    return pasos


def _orden(id_: str) -> int:
    ids = [p[0] for p in PASOS]
    return ids.index(id_) if id_ in ids else len(ids)


def _buscar(pasos: list[Paso], id_: str) -> Paso:
    for p in pasos:
        if p.id == id_:
            return p
    raise PasoDesconocido(id_)


def _cambiar(vault: Path, pasos: list[Paso], p: Paso, antes: Estado, que: str) -> Paso:
    _guardar(vault, pasos)
    if p.estado != antes:
        anadir_log(vault, "arranque", f"paso {p.id} {antes} → {p.estado}: {que}", ["config/arranque.yaml"])
    return p


def marcar_hecho(vault: Path, id_: str, nota: str | None = None, datos: dict[str, str] | None = None) -> Paso:
    pasos = cargar(vault)
    p = _buscar(pasos, id_)
    antes = p.estado
    if p.estado != "verificado":  # «hecho» nunca baja un paso verificado
        p.estado = "hecho"
        p.fecha = _hoy()
    if nota is not None:
        p.nota = nota
    if datos:
        p.datos.update(datos)
    return _cambiar(vault, pasos, p, antes, nota or p.nombre)


def marcar_bloqueado(vault: Path, id_: str, motivo: str) -> Paso:
    pasos = cargar(vault)
    p = _buscar(pasos, id_)
    antes = p.estado
    p.estado = "bloqueado"
    p.fecha = _hoy()
    p.nota = motivo
    return _cambiar(vault, pasos, p, antes, motivo)


def _anotar(p: Paso, texto: str) -> None:
    """Un paso verificado o bloqueado conserva su nota: se añade una vez, no se pisa."""
    if p.estado in ("verificado", "bloqueado") and p.nota:
        if texto and texto not in p.nota:
            p.nota = f"{p.nota} · {texto}"
    elif texto:
        p.nota = texto


def aplicar_verificacion(vault: Path, id_: str, r: ResultadoVerificacion) -> Paso:
    pasos = cargar(vault)
    p = _buscar(pasos, id_)
    antes = p.estado
    if r.ok is True and r.evidencia:
        p.estado = "verificado"
        p.evidencia = list(dict.fromkeys(r.evidencia))
        p.datos.update({str(k): str(v) for k, v in r.datos.items()})
        p.fecha = _hoy()
        p.nota = r.motivo
    elif r.ok is True:
        _anotar(p, f"sin evidencia: {r.motivo}".strip(": "))
    elif r.ok is False:
        if p.estado == "verificado":
            p.estado = "hecho"
            p.evidencia = []  # la evidencia anterior ya no vale
        p.fecha = _hoy()
        if p.estado == "bloqueado":
            _anotar(p, r.motivo)  # conserva el motivo del bloqueo
        else:
            p.nota = r.motivo
    else:
        _anotar(p, r.motivo)
    return _cambiar(vault, pasos, p, antes, r.motivo)


def _cobro_verificado(pasos: list[Paso]) -> bool:
    return any(p.id in _COBRO and p.estado == "verificado" for p in pasos)


def porcentaje_fase(pasos: list[Paso], fase: int = 0) -> float:
    """Fracción (0–1) de pasos verificados; en la fase 0 el cobro cuenta como uno (denominador 12)."""
    if fase == 0:
        por_id = {p.id: p for p in pasos}
        hechos = sum(1 for i in _BASE_FASE0 + ["16"] if i in por_id and por_id[i].estado == "verificado")
        hechos += 1 if _cobro_verificado(pasos) else 0
        return hechos / (len(_BASE_FASE0) + 2)
    de_fase = [p for p in pasos if p.fase == fase]
    return sum(p.estado == "verificado" for p in de_fase) / len(de_fase) if de_fase else 0.0


def siguiente(pasos: list[Paso]) -> Paso | None:
    """Primer paso por hacer de la fase 0 (el cobro cuenta como uno: 10, o 10b solo si 10 está bloqueado).

    Salta los verificados, los bloqueados y los «hecho» (el usuario ya hizo su parte; espera verificación).
    """
    fase0 = sorted((p for p in pasos if p.fase == 0), key=lambda p: _orden(p.id))
    cobro_ok = _cobro_verificado(pasos)
    whop = next((p for p in pasos if p.id == "10"), None)
    for p in fase0:
        if p.id in _COBRO:
            if cobro_ok:
                continue
            if p.id == "10b" and (whop is None or whop.estado != "bloqueado"):
                continue  # Hotmart es el respaldo: solo si Whop está bloqueado
        elif p.estado == "verificado":
            continue
        if p.estado not in ("bloqueado", "hecho"):
            return p
    return None
