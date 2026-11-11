"""Puntuación por país, «no tirar», las tres señales de R16 y la recomendación (§4.5, D-13).

Lo no medido no puntúa ni se estima: la nota se reescala sobre los pesos medidos.
"""

from __future__ import annotations

from dataclasses import dataclass

from trovify.caza.hueco import HuecoPais
from trovify.caza.senales import Medida
from trovify.config.umbrales import Umbral

# (componente, peso, s, motivo): ``motivo`` es None si se midió, «no medido: …» si no.
Desglose = list[tuple[str, float, float | None, str | None]]

MOTIVO_DEMANDA = "no medido: requiere /ads_archive"
MOTIVO_CPM = "no medido: sin historial en la cuenta"
MOTIVO_CULTURAL = "no medido: lo valora el usuario"
MOTIVO_HUECO = "no medido: hueco sin comprobar"


@dataclass
class PaisAuditado:
    pais: str
    hueco: HuecoPais
    precio_eur: Medida
    precio_s: Medida
    nota: float | None
    desglose: Desglose
    no_tirar: str | None
    banda: tuple[float, float] | None = None  # banda_eur del país (config/mercados.yaml)
    fuente_banda: str | None = None


def puntuar_pais(hueco: HuecoPais, precio_s: Medida, u: dict[str, Umbral]) -> tuple[float | None, Desglose]:
    s_hueco = None if hueco.hueco is None else (1 if hueco.hueco else 0)
    # demanda, CPM y encaje cultural no se pueden medir en la Fase 0.
    componentes = [
        ("hueco", s_hueco, hueco.motivo or MOTIVO_HUECO),
        ("precio", precio_s.valor, precio_s.motivo),
        ("demanda", None, MOTIVO_DEMANDA),
        ("cpm", None, MOTIVO_CPM),
        ("cultural", None, MOTIVO_CULTURAL),
    ]
    desglose: Desglose = [
        (n, u[f"auditar.peso.{n}"].valor, s, None if s is not None else m) for n, s, m in componentes
    ]
    medidos = [(p, s) for _, p, s, _ in desglose if s is not None]
    total = sum(p for p, _ in medidos)
    if not medidos or total <= 0:
        return None, desglose
    return 100 * sum(p * s for p, s in medidos) / total, desglose


def no_tirar(hueco: HuecoPais) -> str | None:
    if hueco.original == "traducido":
        return "el original ya anuncia traducido"
    if hueco.hueco is False and hueco.competencia.valor is not None:
        suelo = "≥" if hueco.competencia.suelo else ""
        return f"hay competencia local ({suelo}{int(hueco.competencia.valor)} anunciantes)"
    return None


def tres_senales(decision_caza: str, paises: list[PaisAuditado]) -> dict[str, bool | None]:
    huecos = [p.hueco.hueco for p in paises]
    if any(h is True for h in huecos):
        hueco = True
    elif huecos and all(h is False for h in huecos):
        hueco = False
    else:
        hueco = None
    return {
        "ya_se_vende": decision_caza in ("A", "B"),
        "hueco_por_pais": hueco,
        # pendiente: la confirma la autopsia de /modelar (Fase 2)
        "se_puede_mejorar": None,
    }


def recomendar(paises: list[PaisAuditado]) -> tuple[str | None, str | None, str]:
    candidatos = [
        p for p in paises if p.hueco.hueco is True and p.no_tirar is None and p.nota is not None
    ]
    candidatos.sort(key=lambda p: (-p.nota, p.pais))
    if not candidatos:
        return (
            None,
            None,
            "no hay país con hueco comprobado: ninguno tiene hueco medido y sin motivo para no tirar",
        )
    principal = candidatos[0]
    reserva = candidatos[1] if len(candidatos) > 1 else None
    texto = f"{principal.pais} es el mejor país con hueco comprobado (nota {principal.nota:.0f})"
    if reserva:
        texto += f"; reserva: {reserva.pais} (nota {reserva.nota:.0f})"
    return principal.pais, reserva.pais if reserva else None, texto + "."
