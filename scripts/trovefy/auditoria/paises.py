"""Puntuación por país, «no tirar», las tres señales de R16 y la recomendación (§4.5, D-13).

Lo no medido no puntúa ni se estima: la nota se reescala sobre los pesos medidos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from trovefy.caza.hueco import HuecoPais
from trovefy.caza.senales import Medida
from trovefy.config.umbrales import Umbral

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
    precio_local: Medida | None = None  # el precio en EUR llevado a la moneda del país
    moneda_local: str | None = None
    hueco_medido: str | None = None  # «medido el AAAA-MM-DD (…); hoy no se volvió a buscar» si se reutilizó


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


def tres_senales(decision_caza: str | None, paises: list[PaisAuditado]) -> dict[str, bool | None]:
    """``ya_se_vende`` es None («pendiente») si la ficha no trae la decisión de la caza."""
    huecos = [p.hueco.hueco for p in paises]
    if any(h is True for h in huecos):
        hueco = True
    elif huecos and all(h is False for h in huecos):
        hueco = False
    else:
        hueco = None
    return {
        "ya_se_vende": decision_caza in ("A", "B") if decision_caza else None,
        "hueco_por_pais": hueco,
        # pendiente: la confirma la autopsia de /modelar (Fase 2)
        "se_puede_mejorar": None,
    }


def cobertura(p: PaisAuditado) -> str | None:
    """«medida sobre 45 de 100 puntos»: cuánto peso se midió (lo demás no puntúa); None sin desglose."""
    if not p.desglose:
        return None
    medidos = sum(peso for _, peso, s, _ in p.desglose if s is not None)
    total = sum(peso for _, peso, _, _ in p.desglose)

    def n(x: float) -> str:
        return str(int(x)) if float(x).is_integer() else f"{x:g}".replace(".", ",")

    return f"medida sobre {n(medidos)} de {n(total)} puntos"


def _nota_txt(p: PaisAuditado) -> str:
    c = cobertura(p)
    return f"nota {p.nota:.0f}" + (f", {c}" if c else "")


def _y(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + f" y {xs[-1]}"


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}".rstrip("0").rstrip(",.").replace(".", ",")


# Desempates entre países con la misma nota, en este orden (sin pesos nuevos): el bonus R8 del original
# que anuncia sin traducir, menos competencia local medida y más precio soportable.
_DESEMPATES = (
    ("original sin traducir (bonus R8)", lambda p: 0 if p.hueco.original == "sin_traducir" else 1,
     lambda p: "sin traducir" if p.hueco.original == "sin_traducir" else "no"),
    ("menos competencia local", lambda p: p.hueco.competencia.valor if p.hueco.competencia.valor is not None
     else float("inf"), lambda p: _fmt(p.hueco.competencia.valor) if p.hueco.competencia.valor is not None
     else "no medida"),
    ("más precio soportable", lambda p: -(p.precio_s.valor if p.precio_s.valor is not None else -1),
     lambda p: _fmt(p.precio_s.valor) if p.precio_s.valor is not None else "no medido"),
)


def _elegir(candidatos: list[PaisAuditado]) -> tuple[PaisAuditado | None, list[PaisAuditado], str]:
    """El país de nota más alta; con empate, el que gana los desempates en orden.

    Devuelve ``(elegido, empatados, explicación)``: ``elegido`` es None si siguen empatados tras
    todos los desempates (entonces ``empatados`` son los que la auditoría no distingue)."""
    mejor = max(p.nota for p in candidatos)
    grupo = sorted((p for p in candidatos if math.isclose(p.nota, mejor, abs_tol=1e-9)), key=lambda p: p.pais)
    if len(grupo) == 1:
        return grupo[0], [], ""
    todos = [p.pais for p in grupo]
    pasos: list[str] = []
    for nombre, clave, valor in _DESEMPATES:
        top = min(clave(p) for p in grupo)
        ganan = [p for p in grupo if clave(p) == top]
        detalle = ", ".join(f"{p.pais} {valor(p)}" for p in grupo)
        if len(ganan) < len(grupo):
            pasos.append(f"{nombre}: {detalle} → {_y([p.pais for p in ganan])}")
            grupo = ganan
            if len(grupo) == 1:
                otros = _y([x for x in todos if x != grupo[0].pais])
                return grupo[0], [], (f"empata a nota {mejor:.0f} con {otros} (la nota no los distingue); "
                                      "desempate en orden — " + "; ".join(pasos))
        else:
            pasos.append(f"{nombre}: igual — {detalle}")
    return None, grupo, (f"{_y([p.pais for p in grupo])} empatan a nota {mejor:.0f} y en todos los "
                         "desempates (" + "; ".join(pasos) + ")")


def recomendar(paises: list[PaisAuditado]) -> tuple[str | None, str | None, str]:
    """``(principal, reserva, explicación)``. Solo países con hueco comprobado y sin «no tirar».

    Nunca desempata por orden alfabético: si la nota y los desempates no distinguen a los primeros,
    no recomienda ninguno («empate: elige tú»)."""
    candidatos = [
        p for p in paises if p.hueco.hueco is True and p.no_tirar is None and p.nota is not None
    ]
    if not candidatos:
        falta = ("antes hay que medir lo que falta (ver «Qué medir»)" if any(p.hueco.hueco is None for p in paises)
                 else "en todos los auditados hay competencia local o el original ya está traducido")
        return None, None, ("Ningún país tiene el hueco comprobado y sin motivo para no tirar, así que no se "
                            f"recomienda ninguno: {falta}.")
    principal, empatados, por_que = _elegir(candidatos)
    if principal is None:
        return None, None, (f"empate: elige tú. {por_que}: la auditoría no los distingue y no recomienda "
                            f"ninguno como principal. Opciones: {_y([p.pais for p in empatados])}.")
    texto = f"Recomendado: {principal.pais} ({_nota_txt(principal)}) — " + (
        por_que or "la nota más alta entre los países con hueco comprobado")
    resto = [p for p in candidatos if p is not principal]
    reserva = None
    if resto:
        reserva, empatados_r, por_que_r = _elegir(resto)
        if reserva is None:
            texto += f"; reserva: empate entre {_y([p.pais for p in empatados_r])}: elige tú — {por_que_r}"
        else:
            texto += f"; reserva: {reserva.pais} ({_nota_txt(reserva)})" + (f" — {por_que_r}" if por_que_r else "")
    return principal.pais, reserva.pais if reserva else None, texto + "."


def _sugerencia(pais: str, motivo: str) -> str:
    m = motivo.lower()
    if "frases" in m and "faltan" in m:
        return f'escribe 2 frases cortas en el idioma local y audita con --pais {pais} --frases {pais}:"f1|f2"'
    if "paradadeldia" in m or "meta bloqueó" in m or "sesionbloqueada" in m or "bloqueo de meta" in m:
        return "Meta bloqueó: hoy no se busca más; se retoma mañana"
    if "cuota del día" in m or "presupuesto" in m:
        return "vuelve a auditar mañana con la misma orden: sigue por aquí y lo ya medido no se repite"
    if "interrumpid" in m or "errores" in m or "navegador" in m:
        return f"fallo de red o del navegador: vuelve a intentarlo más tarde con --pais {pais}"
    if "intentos con frases distintas" in m:
        return "añade una segunda frase local distinta para confirmar que no hay competencia"
    if "idioma no detectable" in m:
        return "revisa a mano los anuncios enlazados o prueba frases locales más precisas"
    if "más anuncios que los leídos" in m:
        return "hubo más anuncios de los que se leen: prueba frases locales más precisas"
    if "traducido" in m:
        return "vuelve a medir la página del original en ese país (mañana si hoy hubo cortes)"
    return "vuelve a medir con frases locales nuevas"


def que_medir(paises: list[PaisAuditado]) -> list[str]:
    """Una línea por país con el hueco sin comprobar: por qué no se midió y qué hacer para medirlo."""
    return [f"{p.pais}: {p.hueco.motivo or MOTIVO_HUECO} → {_sugerencia(p.pais, p.hueco.motivo or '')}"
            for p in paises if p.hueco.hueco is None]
