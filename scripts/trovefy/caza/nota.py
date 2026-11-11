"""Nota desglosada (0–100) y decisión A/B/observar (§4.3, auditoría §4.6).

Lo no medido no cuenta en el denominador; nunca se puntúa como 0 (§1.4).

Una ``Medida`` con ``suelo=True`` es una cota inferior (≥): se puntúa como su valor, que es
conservador porque log-share y lineal son crecientes (el valor real puntuaría igual o más).
Los multiplicadores de castigo no se aplican sobre una cota inferior (el valor real podría
no estar bajo el umbral).

Por debajo del mínimo de C8 (o C7) del perfil una oferta nunca es A ni B: queda en «observar».
Si la cifra es una cota inferior (lectura parcial) el motivo pide volver a medir.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from trovefy.caza.filtros import Descarte
from trovefy.caza.senales import Medida, Senales
from trovefy.config.umbrales import Umbral


def log_share(x: float, tope: float) -> float:
    return min(math.log2(1 + max(x, 0.0)) / math.log2(1 + tope), 1.0)


def lineal(x: float, tope: float) -> float:
    return min(max(x, 0.0) / tope, 1.0)


@dataclass
class Nota:
    valor: float | None
    desglose: list[tuple[str, float, float, float]] = field(default_factory=list)
    multiplicadores: list[tuple[str, float]] = field(default_factory=list)
    no_medidas: list[str] = field(default_factory=list)


def _v(m: Medida) -> float | None:
    return m.valor


def _longevidad(s: Senales, u: dict[str, Umbral]) -> float | None:
    partes = []
    if _v(s.edad_max_dias) is not None:
        partes.append(lineal(s.edad_max_dias.valor, u["caza.tope.edad_dias"].valor))
    if _v(s.escalonado_semanas) is not None:
        partes.append(lineal(s.escalonado_semanas.valor, u["caza.tope.semanas"].valor))
    # Una sola mitad medida se usa sola (la otra no cuenta); ninguna = no medida.
    return sum(partes) / len(partes) if partes else None


def calcular_nota(s: Senales, u: dict[str, Umbral]) -> Nota:
    def f(clave: str, m: Medida, fn) -> float | None:
        return None if m.valor is None else fn(m.valor)

    señales: list[tuple[str, str, float | None]] = [
        ("c8", "caza.peso.c8", f("c8", s.c8, lambda x: log_share(x, u["caza.tope.c8"].valor))),
        ("longevidad", "caza.peso.longevidad", _longevidad(s, u)),
        ("crecimiento_7d", "caza.peso.crecimiento",
         f("g", s.crecimiento_7d, lambda g: min(max((g + 0.5) / 1.5, 0.0), 1.0))),
        ("expansion", "caza.peso.expansion",
         f("e", s.expansion, lambda x: log_share(x, u["caza.tope.expansion"].valor))),
        ("duplicacion", "caza.peso.duplicacion",
         f("d", s.duplicacion, lambda x: log_share(x, u["caza.tope.duplicacion"].valor))),
        ("alcance_ue", "caza.peso.alcance_ue",
         f("a", s.alcance_ue, lambda x: min(max(x, 0.0), 1.0))),
        ("supervivencia", "caza.peso.supervivencia",
         f("v", s.supervivencia, lambda x: lineal(x, u["caza.tope.supervivencia"].valor))),
    ]
    desglose: list[tuple[str, float, float, float]] = []
    no_medidas: list[str] = []
    for nombre, clave, sc in señales:
        if sc is None:
            no_medidas.append(nombre)
        else:
            peso = u[clave].valor
            desglose.append((nombre, peso, sc, peso * sc))
    total_pesos = sum(d[1] for d in desglose)
    if not desglose or total_pesos == 0:
        return Nota(None, [], [], no_medidas)
    valor = 100 * sum(d[3] for d in desglose) / total_pesos

    mult: list[tuple[str, float]] = []
    sv = s.supervivencia
    if sv.valor is not None and not sv.suelo and sv.valor < u["caza.supervivencia.min"].valor:
        mult.append(("supervivencia_baja", u["caza.mult.supervivencia_baja"].valor))
    if "cayendo" in s.banderas:
        mult.append(("cayendo", u["caza.mult.cayendo"].valor))
    vm = s.vida_mediana_dias
    if vm.valor is not None and not vm.suelo and vm.valor < u["caza.vida_mediana.min_dias"].valor:
        mult.append(("vida_corta", u["caza.mult.vida_corta"].valor))
    for _, m in mult:
        valor *= m
    return Nota(valor, desglose, mult, no_medidas)


_PERFIL = re.compile(r"^caza\.perfil\.([^.]+)\.c[78]_min$")


def perfiles(u: dict[str, Umbral]) -> list[str]:
    """Perfiles de umbral que hay en ``config/umbrales.yaml`` (los que tienen ``c8_min`` o ``c7_min``)."""
    return list(dict.fromkeys(m.group(1) for k in u if (m := _PERFIL.match(k))))


def validar_perfil(u: dict[str, Umbral], perfil: str) -> str:
    """El perfil normalizado (minúsculas, «-» → «_»); ValueError con la lista si no existe.

    Se llama antes de cualquier búsqueda: un perfil mal escrito no puede gastar el presupuesto."""
    clave = (perfil or "").strip().casefold().replace("-", "_")
    validos = perfiles(u)
    if clave not in validos:
        raise ValueError(f"perfil desconocido: «{perfil}»; los que hay son {', '.join(validos) or 'ninguno'}")
    return clave


def _n(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def decidir(
    nota: Nota,
    c8: Medida,
    perfil: str,
    hay_hueco: bool | None,
    descarte: Descarte | None,
    u: dict[str, Umbral],
    landing: Literal["modelable", "dudoso"] = "modelable",
    c7: Medida | None = None,
) -> tuple[Literal["A", "B", "observar", "descartada"], str]:
    if descarte is not None:
        return "descartada", f"{descarte.codigo}: {descarte.detalle}"
    if nota.valor is None:
        return "observar", "nada medido"
    clave = perfil.replace("-", "_")
    if f"caza.perfil.{clave}.c7_min" in u:  # el perfil santino se mide en C7
        etiqueta, medida, minimo = "C7", c7 if c7 is not None else Medida(None, "no medido: sin C7"), \
            u[f"caza.perfil.{clave}.c7_min"].valor
    else:
        etiqueta, medida, minimo = "C8", c8, u[f"caza.perfil.{clave}.c8_min"].valor

    faltas: list[str] = []
    # Bajo el mínimo del perfil nunca es A ni B: se observa. Con cota inferior (lectura parcial) no
    # se sabe si lo alcanza: hay que volver a medir; con la cifra exacta, no lo alcanza.
    bajo_minimo = medida.valor is not None and medida.valor < minimo
    if bajo_minimo:
        if medida.suelo:
            faltas.append(f"{etiqueta} ≥ {_n(medida.valor)} no alcanza {_n(minimo)} del perfil {perfil}: "
                          "lectura parcial, volver a medir")
        else:
            faltas.append(f"{etiqueta} {_n(medida.valor)} < {_n(minimo)} del perfil {perfil}")
    if nota.valor < u["caza.nota.a_min"].valor:
        faltas.append(f"nota {nota.valor:.1f} < {_n(u['caza.nota.a_min'].valor)} para A")
    if medida.valor is None:
        faltas.append(f"{etiqueta} no medido")
    if hay_hueco is None:
        faltas.append("sin hueco comprobado")
    elif hay_hueco is False:
        faltas.append("sin hueco")
    if landing != "modelable":
        faltas.append("landing dudosa")
    if not faltas:
        return "A", "cumple A"
    motivo = "; ".join(faltas)
    if not bajo_minimo and nota.valor >= u["caza.nota.b_min"].valor:
        return "B", motivo
    return "observar", motivo
