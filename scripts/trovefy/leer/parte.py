"""El parte diario e intradía en Markdown (plan 23, Tarea 8; §4.15).

**Qué hacen los vídeos:** tabla «Conjunto · Gasto · ROAS · CPM · CTR · CPC · Visitas / pagos iniciados · Estado · Por
qué» con el número puesto y el motivo (C1 54:20); «Movimientos para hoy» numerados (L2 21:25); «8:30 ganancia de ayer»
y ronda periódica «qué apagar y qué prender» (L2 22:40). Dato ausente: «—» y una nota al pie con el motivo.

El parte vive en ``wiki/analisis/partes/AAAA-MM-DD.md`` (la fecha del día en que sale, hora de Bogotá). Cada
producto-país tiene su sección; la ronda intradía **añade** su bloque, nunca reescribe lo anterior. Sin datos
personales: solo números, ids abreviados, nombres de anuncio y ángulos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from trovefy.leer import Umbrales, num, usd
from trovefy.leer.diagnostico import Hallazgo
from trovefy.leer.economia import EconomiaLeer, neto_de, roas_neto
from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import LecturaOferta, Veredicto
from trovefy.leer.reglas import falta_para_corte, ventas_oferta
from trovefy.leer.surf import Surf


@dataclass
class Informe:
    """Todo lo que sale en una sección del parte."""

    lectura: LecturaOferta
    fiabilidad: Fiabilidad
    economia: EconomiaLeer
    veredictos: list[Veredicto]
    estado_oferta: str
    notas: list[str] = field(default_factory=list)
    hallazgos: list[Hallazgo] = field(default_factory=list)
    surf: list[Surf] = field(default_factory=list)
    notas_surf: list[str] = field(default_factory=list)
    propuestas: list[str] = field(default_factory=list)  # «P-…: texto»
    renovar: list[str] = field(default_factory=list)
    resultados: list[str] = field(default_factory=list)  # lo que aplicó estado.aplicar_resultados


def _id(x: str | None) -> str:
    return f"…{str(x)[-4:]}" if x else "—"


def _pct(a: int | None, b: int | None) -> str:
    if a is None or not b:
        return "—"
    return f"{num(Decimal(a) * 100 / b, 1)} %"


def _tabla(i: Informe) -> list[str]:
    o, e = i.lectura, i.economia
    ver = {v.adset_id: v for v in i.veredictos}
    filas = [("| Conjunto | Ángulo | Gasto USD | ROAS neto | CPM | CTR | CPC | Visitas → PI | PI → compra | Estado | "
              "Por qué | ID |"), "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in o.conjuntos:
        m = c.metricas
        roas = roas_neto(neto_de(c.bruto_usd, c.ventas, e), m.gasto_usd_c)
        v = ver.get(c.adset_id)
        pi = m.pi_pixel if i.fiabilidad.pi_fiable else None
        compras = c.ventas if c.ventas is not None else m.compras_pixel
        ctr = f"{num(m.ctr * 100)} %" if m.ctr is not None else "—"
        filas.append(
            f"| {c.nombre} | {c.angulo or '—'} | {usd(m.gasto_usd_c)} | {num(roas)} | {num(m.cpm_usd)} | {ctr} | "
            f"{num(m.cpc_usd)} | {m.visitas if m.visitas is not None else '—'} → {pi if pi is not None else '—'} "
            f"({_pct(pi, m.visitas)}) | {compras if compras is not None else '—'} de {pi if pi is not None else '—'} | "
            f"{v.estado if v else '—'} | {v.por_que if v else '—'} | {_id(c.adset_id)} |")
    return filas


def seccion(i: Informe, u: Umbrales, titulo: str) -> str:
    o, f = i.lectura, i.fiabilidad
    ventas, _ = ventas_oferta(o)
    horas = o.horas
    raya = lambda x: "—" if x is None else x
    desde = o.activacion.isoformat(timespec="minutes") if o.activacion else "—"
    lin = [f"## {titulo}", "",
           (f"- Ventana: {desde} → {'hoy' if o.intradia else 'cierre de'} {o.dia.isoformat()} (hora de Bogotá, "
            "D-37). Atribución: 7 días clic + 1 día visualización (§4.15)."),
           (f"- Moneda: gasto en {o.moneda or '—'} convertido a USD al alza con la {o.trm or 'TRM: no medido'} "
            "(fuente Banco de la República)."),
           f"- **Fiabilidad: {f.nivel}**" + (f" ({'; '.join(f.motivos)})" if f.motivos else ""),
           (f"- Oferta: {usd(o.gasto_usd_c)} USD gastados · ventas tienda {raya(o.ventas_tienda)} · píxel "
            f"{raya(o.ventas_pixel)} · "
            + (f"{int(horas)} h desde la activación" if horas is not None else "sin hora de activación")),
           f"- Estado de la oferta: **{i.estado_oferta}**", ""]
    falta = falta_para_corte(o, u)
    if falta and ventas == 0:
        lin.insert(-1, f"- {falta}")
    lin += _tabla(i)
    if o.motivos or i.notas:
        lin += ["", "Notas:"] + [f"- {x}" for x in [*i.notas, *o.motivos]]
    if i.surf or i.notas_surf:
        lin += ["", "Surf (S1 10:27, S2 14:10, S2 14:40):"]
        lin += [f"- {s.nombre}: {s.de_minima} → {s.a_minima} {o.moneda or ''} · {s.motivo} ({s.regla})"
                for s in i.surf]
        lin += [f"- {x}" for x in i.notas_surf]
    if i.hallazgos:
        lin += ["", "Diagnóstico por etapa (R-014; avisa, no toca la campaña):"]
        lin += [f"- {h.texto} → {h.destino}" for h in i.hallazgos]
    if i.renovar:
        lin += ["", "Anuncios apagados que piden renovación (/creativos --renovar): " + ", ".join(i.renovar)]
    if i.resultados:
        lin += ["", "Resultados del ejecutor:"] + [f"- {x}" for x in i.resultados]
    lin += ["", "Movimientos propuestos (se aceptan o rechazan en Telegram; Claude no pausa ni sube nada):"]
    lin += [f"{n}. {p}" for n, p in enumerate(i.propuestas, 1)] or ["- ninguno"]
    return "\n".join(lin) + "\n"


def ruta_parte(vault: Path, dia: date) -> Path:
    return Path(vault) / "wiki" / "analisis" / "partes" / f"{dia.isoformat()}.md"


def _marcas(clave: str) -> tuple[str, str]:
    return f"<!-- leer:{clave} -->", f"<!-- /leer:{clave} -->"


def escribir_parte(vault: Path, dia: date, clave: str, texto: str, ahora: datetime, *, anadir: bool) -> Path:
    """Escribe la sección ``clave`` del parte del día. ``anadir`` (intradía) la añade al final; si no, sustituye la
    sección de ese producto-país (el parte diario se puede repetir sin duplicar)."""
    from trovefy.secretos import buscar_secreto
    from trovefy.vault import frontmatter
    from trovefy.vault.escritura import escribir_atomico

    ruta = ruta_parte(vault, dia)
    if ruta.is_file():
        meta, cuerpo = frontmatter.leer(ruta)
    else:
        previos = sorted(p for p in ruta.parent.glob("????-??-??.md") if p.stem < dia.isoformat()) \
            if ruta.parent.is_dir() else []
        anterior = f"Parte anterior: [[wiki/analisis/partes/{previos[-1].stem}]]\n" if previos else ""
        meta = {"tipo": "parte", "fecha": dia.isoformat(), "fuente": "/leer (Meta e Impultienda, solo lectura)"}
        cuerpo = f"\n# Parte · {dia.isoformat()}\n\n{anterior}"
    ini, fin = _marcas(clave)
    bloque = f"{ini}\n{texto.rstrip()}\n{fin}\n"
    if not anadir and ini in cuerpo and fin in cuerpo:
        a, b = cuerpo.index(ini), cuerpo.index(fin) + len(fin)
        cuerpo = cuerpo[:a] + bloque.rstrip("\n") + cuerpo[b:]
    else:
        cuerpo = cuerpo.rstrip("\n") + "\n\n" + bloque
    texto_final = frontmatter.renderizar(meta, cuerpo)
    if buscar_secreto(texto_final):
        raise ValueError("el parte trae algo con forma de secreto: no se escribe")
    escribir_atomico(ruta, texto_final)
    return ruta
