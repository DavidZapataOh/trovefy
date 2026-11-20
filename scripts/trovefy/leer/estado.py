"""``test → muerto | candidato`` y el surf vivo, tras leer lo que copió el ejecutor (plan 23, Tarea 7; base común 2).

Solo cambia el estado con un resultado del ejecutor: una pausa de campaña ``ejecutada`` (el ejecutor relee después y
solo la marca así si Meta la devuelve ``PAUSED``) pasa el país a ``muerto`` y cierra el test en ``config/caja.yaml``
(resolución 11). Aceptada pero fallida, rechazada o caducada: sigue en ``test`` y se dice. Un cambio de presupuesto
ejecutado actualiza ``paises.<PAIS>.lectura.surf`` y ``diario_usd`` del test vivo. ``candidato`` lo decide el parte
(días cerrados) y no espera a nadie: no hay escritura en Meta («no lo toques», C1 20:05).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trovefy.leer import SKILL


def _resultado(vault: Path, id_: str):
    from trovefy.montar.registro import leer_resultado

    return leer_resultado(vault, id_)


def estado_de(vault: Path):
    """Función ``id → estado`` del resultado copiado por el ejecutor (``None`` si aún no está)."""
    def _de(id_: str) -> str | None:
        r = _resultado(vault, id_)
        return r.estado if r is not None else None
    return _de


def aplicar_resultados(vault: Path, p_id: str, pais: str, memoria: dict, ahora: datetime) -> list[str]:
    """Lee los resultados de las propuestas de `/leer` y aplica lo que toca. Idempotente; marca ``aplicada``."""
    from trovefy.caja.tests import actualizar_test, cerrar_test
    from trovefy.montar.registro import _motivo_rechazo
    from trovefy.montar.tanda import bloque_pais
    from trovefy.vault.producto import actualizar_producto, avanzar_estado

    vault = Path(vault)
    lineas: list[str] = []
    bloque = bloque_pais(vault, p_id, pais)
    estado = bloque.get("estado")
    campana = str(((bloque.get("trafico") or {}).get("campana") or {}).get("id") or "")
    for k, p in sorted(memoria.get("propuestas", {}).items()):
        if p.get("aplicada") or k.startswith("alerta|"):
            continue
        r = _resultado(vault, p.get("id", ""))
        if r is None:
            continue
        if r.estado not in ("ejecutada", "fallida", "discrepancia", "rechazada", "caducada", "obsoleta"):
            continue
        p["aplicada"] = r.estado
        extra = p.get("extra") or {}
        if r.estado == "rechazada":
            archivo, cita = _motivo_rechazo(vault, r.id)
            lineas.append(f"{r.id} rechazada: nada cambia." + (f" Tu motivo: «{cita}» ({archivo})" if cita else ""))
            continue
        if r.estado != "ejecutada":
            lineas.append(f"{r.id} quedó {r.estado}: no se cambió nada en Meta; el país sigue en {estado}. "
                          f"{r.detalle}".strip())
            continue
        if p.get("tipo") == "pausar_campana":
            if estado == "test":
                parte = extra.get("parte") or f"wiki/analisis/partes/{ahora.date().isoformat()}.md"
                avanzar_estado(vault, p_id, pais, "test", "muerto",
                               [f"propuestas/{r.id}.md", str(extra.get("motivo") or "corte de /leer"),
                                f"stop: [[{parte.removesuffix('.md')}]]"], SKILL, ahora)
                estado = "muerto"
                if campana:
                    try:
                        cerrar_test(vault, campana)
                    except (OSError, ValueError, KeyError) as exc:
                        lineas.append(f"no se pudo cerrar el test en config/caja.yaml: {exc}")
                lineas.append(f"{r.id} ejecutada (campaña en PAUSED, releída): {p_id} {pais} pasa a muerto.")
            continue
        if p.get("tipo") == "surf":
            vivos = {str(i): int(v) for i, v in (extra.get("a") or {}).items()}
            surf = dict((bloque.get("lectura") or {}).get("surf") or {})
            surf.update({i: {"presupuesto": v, "propuesta": r.id, "fecha": ahora.isoformat(timespec="seconds")}
                         for i, v in vivos.items()})
            actualizar_producto(vault, p_id, {"paises": {pais: {"lectura": {"surf": surf}}}}, [], SKILL, ahora)
            bloque = bloque_pais(vault, p_id, pais)
            usd = extra.get("diario_usd")
            if usd is not None and campana:
                try:
                    actualizar_test(vault, campana, diario_usd=Decimal(str(usd)))
                except (OSError, ValueError, KeyError) as exc:
                    lineas.append(f"no se pudo actualizar diario_usd en config/caja.yaml: {exc}")
            lineas.append(f"{r.id} ejecutada: presupuesto vivo de {len(vivos)} conjunto(s) actualizado.")
            continue
        lineas.append(f"{r.id} ejecutada ({p.get('tipo')}).")
    return lineas


def pasar_a_candidato(vault: Path, p_id: str, pais: str, evidencia: list[str], ahora: datetime) -> bool:
    """``test → candidato`` con su evidencia (días con ventas y ROAS); ``False`` si el país no está en ``test``."""
    from trovefy.montar.tanda import bloque_pais
    from trovefy.vault.producto import avanzar_estado

    if bloque_pais(vault, p_id, pais).get("estado") != "test":
        return False
    avanzar_estado(vault, p_id, pais, "test", "candidato", evidencia, SKILL, ahora)
    return True
