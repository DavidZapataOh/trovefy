"""Render y escritura de ``OFERTA.md``, ``ESCALERA.md``, ``BRANDBOOK.md`` y ``comparativa.md``.

Lo creativo viene validado de ``modelar.yaml`` (``Modelado``); lo determinista (autopsia, escalera y
economía) se calcula aquí con ``trovefy.economia`` y ``trovefy.modelar.autopsia``. Los importes van en el
frontmatter como texto (``"13.90"``) y lo no medido como ``null`` con su ``<campo>_motivo``. Los formatos
son los de las resoluciones 4–7 del contrato de la fase 2; los leen los planes 17–20 con
``cargar_oferta``, ``cargar_escalera`` y ``cargar_brandbook``.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.config import mercados as mercados_cfg
from trovefy.economia.calculo import PASOS_ECONOMIA, Economia, economia_de
from trovefy.economia.config import (
    ConfigEconomia,
    admite_downsell,
    costes_de,
    upsells_permitidos,
)
from trovefy.economia.escalera import PASOS, EscaleraPais, a_usd, escalera_pais
from trovefy.economia.modelo import Cifra, Costes
from trovefy.fx import Cambio
from trovefy.modelar.autopsia import (
    NOMBRES,
    Autopsia,
    puntuar,
    senal_se_puede_mejorar,
    vende_por_presupuesto,
)
from trovefy.modelar.esquema import (
    IMPACTOS,
    Brandbook,
    Modelado,
    PiezaEscalera,
    token_css_inseguro,
)
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico
from trovefy.vault.producto import (
    ESTADOS_FASE2,
    EstadoInesperado,
    actualizar_producto,
    estado_pais,
    pais_elegido,
    ruta_producto,
)

ARCHIVOS = ("OFERTA", "ESCALERA", "BRANDBOOK", "comparativa")
ESTADOS_PERMITIDOS = ("aprobado", "modelado")
LINEA_CRITICA = "La nota de nuestra oferta la pone Claude: léela con ojo crítico."
CIERRE_TACITO = "Si no la rechazas en esta sesión, queda aprobada (aprobación tácita) y seguimos con el producto."
_ETIQUETA_PASO = {"front": "Front", "bump": "Bump", "u1": "U1", "u2": "U2", "u3": "U3", "downsell": "Downsell"}
_CAMPOS_ECONOMIA = ("aov_usd", "be_usd", "cpa_be_usd", "cpa_test_usd", "cpa_escala_usd", "roas_be")
_ID_OFERTA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Dato técnico: monedas con céntimos (el resto se cobra en unidades enteras).
_MONEDAS_CON_CENTIMOS = frozenset({"EUR", "USD"})
_CENTIMO = Decimal("0.01")
_SIN_CAMBIO = "no medido: sin cambio del BCE del día"
AVISO_ORIGINAL_ILEGIBLE = "comparación con el original: no medido (precio de la ficha no legible)"
# Estados de fase 2 en los que la oferta ya se está produciendo (después de ``modelado``).
_EN_PRODUCCION = ESTADOS_FASE2[ESTADOS_FASE2.index("modelado") + 1:]


# --- formato ---------------------------------------------------------------------------------------


def _txt(x: Decimal | None) -> str | None:
    """Importe para el YAML: texto con punto decimal (``"13.90"``) o ``None``."""
    return None if x is None else str(x)


def _coma(x: Decimal) -> str:
    return str(x).replace(".", ",")


def _celda(texto: object) -> str:
    return str(texto).replace("|", "\\|").replace("\n", " ")


def _precio_con_moneda(precio: Decimal | None, moneda: str | None) -> str:
    if precio is None:
        return "no medido"
    return f"{_coma(precio)} {moneda}" if moneda else f"{_coma(precio)} (moneda no medida)"


def _render(meta: dict, cuerpo: str) -> str:
    return frontmatter.renderizar(meta, cuerpo)


# --- OFERTA.md -------------------------------------------------------------------------------------


def _autopsia_meta(a: Autopsia) -> dict:
    return {"nota": _txt(a.nota), "cobertura": a.cobertura, "flojos": list(a.flojos)}


def _nota(a: Autopsia) -> str:
    return "no medida" if a.nota is None else f"{_coma(a.nota)}/100"


def _teardown_meta(m: Modelado) -> dict:
    t = m.teardown
    c = t.checkout
    return {
        "url": t.url,
        "anunciante": t.anunciante,
        "fecha_lectura": t.fecha_lectura,
        "checkout": {
            "plataforma": c.get("plataforma"),
            "precio": _txt(c.get("precio")),
            "moneda": c.get("moneda"),
            "bump": _txt(c.get("bump")),
            "upsells": [_txt(u) for u in c.get("upsells") or ()],
            "garantia_dias": c.get("garantia_dias"),
        },
        "promesa": t.promesa,
        "mecanismo": t.mecanismo,
        "avatar": t.avatar,
        "villano": t.villano,
        "secciones": [
            {"n": s.n, "tipo": s.tipo, "objetivo": s.objetivo, "palabras_aprox": s.palabras_aprox,
             "objeciones": list(s.objeciones), "prueba": s.prueba, "cta": s.cta}
            for s in t.secciones
        ],
    }


def _core_meta(m: Modelado) -> dict:
    c = m.core
    return {
        "promesa_h1": c.promesa_h1,
        "plazo": c.plazo,
        "sin": list(c.sin),
        "unidad_venta": c.unidad_venta,
        "big_idea": c.big_idea,
        "villano": c.villano,
        "mecanismo_nombre": c.mecanismo_nombre,
        "mecanismo_pasos": list(c.mecanismo_pasos),
        "entregables": list(c.entregables),
        "bonos": [{"nombre": b.nombre, "objecion": b.objecion} for b in c.bonos],
        "garantia_dias": c.garantia_dias,
        "garantia_como": c.garantia_como,
        "formato": c.formato,
        "avatar": c.avatar,
        "angulo": c.angulo,
    }


def _checkout_texto(c: dict) -> str:
    bump = "no tiene" if c.get("bump") is None else _coma(c["bump"])
    upsells = ", ".join(_coma(u) for u in c.get("upsells") or ()) or "ninguno"
    dias = c.get("garantia_dias")
    garantia = "no medida" if dias is None else f"{dias} días"
    return (f"{c.get('plataforma')}, precio {_precio_con_moneda(c.get('precio'), c.get('moneda'))}, "
            f"bump {bump}, upsells {upsells}, garantía {garantia}")


def render_oferta(m: Modelado, original: Autopsia, nuestra: Autopsia, senal: tuple[bool | None, str], hoy: date,
                  *, vende_por_presupuesto: bool = False) -> str:
    """``OFERTA.md``: teardown (solo estructura), autopsia de 8 ejes, tercera señal, core offer y landing."""
    valor, motivo = senal
    meta = {
        "tipo": "oferta",
        "producto": m.producto,
        "pais": m.pais,
        "fecha": hoy.isoformat(),
        "fuente": f"productos/{m.producto}/modelar.yaml",
        "aprobacion": "presentada",
        "autopsia": {"original": _autopsia_meta(original), "nuestra": _autopsia_meta(nuestra)},
        "se_puede_mejorar": valor,
        "se_puede_mejorar_motivo": motivo,
        "vende_por_presupuesto": vende_por_presupuesto,
        "teardown": _teardown_meta(m),
        "core": _core_meta(m),
        "angulos_referencia": list(m.angulos_referencia),
        "estructura_landing": [{"orden": s.orden, "tipo": s.tipo, "palabras": s.palabras, "cta": s.cta}
                               for s in m.estructura_landing],
    }
    t, c = m.teardown, m.core
    lineas = [
        f"# Oferta · {m.producto} · {m.pais}", "",
        f"Fuente: `productos/{m.producto}/modelar.yaml`. Aprobación: presentada.", "",
        "## Teardown del original", "",
        f"Solo la estructura, con nuestras palabras. Leído el {t.fecha_lectura} en {t.url}.", "",
        f"- Promesa: {t.promesa}",
        f"- Mecanismo: {t.mecanismo}",
        f"- Avatar: {t.avatar}",
        f"- Villano: {t.villano or 'no tiene'}",
        f"- Checkout: {_checkout_texto(t.checkout)}", "",
        "| N | Tipo | Objetivo | Palabras | Objeciones | CTA |",
        "|---|---|---|---|---|---|",
    ]
    for s in t.secciones:
        lineas.append(f"| {s.n} | {s.tipo} | {_celda(s.objetivo)} | {s.palabras_aprox} | "
                      f"{_celda(', '.join(s.objeciones) or '—')} | {'sí' if s.cta else 'no'} |")
    lineas += [
        "", "## Autopsia de 8 ejes", "",
        "| Eje | Peso | Original | Nuestra | Por qué (original) | Por qué (nuestra) |",
        "|---|---|---|---|---|---|",
    ]
    notas_nuestra = {eje: nota for eje, _, nota in nuestra.desglose}
    for eje, peso, nota in original.desglose:
        n_nuestra = notas_nuestra.get(eje)
        por_o = m.ejes_original[eje].porque if eje in m.ejes_original else "—"
        por_n = m.ejes_nuestra[eje].porque if eje in m.ejes_nuestra else "—"
        lineas.append(f"| {NOMBRES[eje]} | {peso} | {'—' if nota is None else nota} | "
                      f"{'—' if n_nuestra is None else n_nuestra} | {_celda(por_o)} | {_celda(por_n)} |")
    flojos = ", ".join(NOMBRES[e] for e in original.flojos) or "—"
    lineas += [
        "",
        f"- Nota del original: {_nota(original)} (cobertura {original.cobertura} de 100). Ejes más flojos: {flojos}.",
        f"- Nota de la nuestra: {_nota(nuestra)} (cobertura {nuestra.cobertura} de 100).",
        f"- **Se puede mejorar (tercera señal de R16):** {motivo}",
    ]
    if vende_por_presupuesto:
        lineas += ["", ("> **Vende por presupuesto.** La nota del original es media (`autopsia.nota_media` de "
                        "`config/economia.yaml`): vende por lo que gasta en anuncios, no por su oferta.")]
    lineas += [
        "", "## Core offer", "",
        f"**{c.promesa_h1}**", "",
        f"- Plazo: {c.plazo}",
        f"- Sin: {'; '.join(c.sin)}",
        f"- Unidad de venta: {c.unidad_venta}",
        f"- Big idea: {c.big_idea}",
        f"- Villano: {c.villano}",
        f"- Mecanismo: {c.mecanismo_nombre} — " + " → ".join(f"{i}. {p}" for i, p in enumerate(c.mecanismo_pasos, 1)),
        f"- Entregables: {'; '.join(c.entregables)}",
        f"- Garantía: {c.garantia_dias} días. {c.garantia_como}",
        f"- Formato: {c.formato}",
        f"- Avatar: {c.avatar}",
        f"- Ángulo: {c.angulo}",
        "", "### Bonos", "",
    ]
    lineas += [f"- bono-{i}: {b.nombre} (contra «{b.objecion}»)" for i, b in enumerate(c.bonos, 1)]
    lineas += ["", "## Ángulos de referencia", ""]
    lineas += [f"- {a}" for a in m.angulos_referencia] or ["- ninguno"]
    lineas += ["", "## Estructura de la landing", "", "| Orden | Tipo | Palabras | CTA |", "|---|---|---|---|"]
    lineas += [f"| {s.orden} | {s.tipo} | {s.palabras} | {'sí' if s.cta else 'no'} |" for s in m.estructura_landing]
    lineas += ["", "## Mapa de cambios", "", "| Qué | Por qué | Impacto |", "|---|---|---|"]
    lineas += [f"| {_celda(x.que)} | {_celda(x.por_que)} | {x.impacto} |" for x in _cambios_ordenados(m)]
    return _render(meta, "\n".join(lineas) + "\n")


def _cambios_ordenados(m: Modelado):
    return sorted(m.mapa_cambios, key=lambda x: IMPACTOS.index(x.impacto))


# --- ESCALERA.md -----------------------------------------------------------------------------------


def economia_pais(escalera: EscaleraPais, config: ConfigEconomia, cambio: Cambio | None) -> Economia:
    """La economía (en USD) de la escalera de un país: los pasos apagados no suman."""
    costes = costes_de(config)
    if escalera.pasos is None:
        return economia_de({"front": Cifra(None, escalera.motivo)}, costes, config.tomas, config.reglas)
    precios: dict[str, Cifra | None] = {}
    for nombre in PASOS_ECONOMIA:
        paso = escalera.pasos[nombre]
        precios[nombre] = a_usd(paso.precio, paso.moneda, cambio) if paso.activo else None
    return economia_de(precios, costes, config.tomas, config.reglas)


def _cifras(e: Economia) -> dict[str, Cifra]:
    return {"aov_usd": e.aov_usd, "be_usd": e.be_usd, "cpa_be_usd": e.be_usd, "cpa_test_usd": e.cpa_test_usd,
            "cpa_escala_usd": e.cpa_escala_usd, "roas_be": e.roas_be}


def _pais_meta(escalera: EscaleraPais, economia: Economia, piezas: dict[str, PiezaEscalera]) -> dict:
    bloque: dict = {"moneda": escalera.moneda or None}
    if not escalera.moneda:
        bloque["moneda_motivo"] = escalera.motivo
    if escalera.pasos is None:
        bloque["fuente_precio"] = None
        bloque["fuente_precio_motivo"] = escalera.motivo
    else:
        bloque["fuente_precio"] = escalera.fuente_precio
    bloque["front_eur"] = _txt(escalera.front_eur.valor)
    if escalera.front_eur.valor is None:
        bloque["front_eur_motivo"] = escalera.front_eur.motivo
    if escalera.pasos is None:
        bloque["pasos"] = None
        bloque["pasos_motivo"] = escalera.motivo
    else:
        bloque["pasos"] = {}
        for nombre in PASOS:
            p = escalera.pasos[nombre]
            pieza = piezas.get(nombre)
            bloque["pasos"][nombre] = {
                "precio": _txt(p.precio), "activo": p.activo, "motivo_inactivo": p.motivo_inactivo,
                "titulo": pieza.titulo if pieza else None, "entregable": pieza.entregable if pieza else None,
            }
    for campo, cifra in _cifras(economia).items():
        bloque[campo] = _txt(cifra.valor)
        if cifra.valor is None:
            bloque[f"{campo}_motivo"] = cifra.motivo
    bloque["avisos"] = [*escalera.avisos, *economia.avisos]
    return bloque


def _cambio_meta(cambio: Cambio | None) -> dict:
    if cambio is None:
        return {"fuente": "BCE", "fecha": None, "fecha_motivo": _SIN_CAMBIO, "url": None, "url_motivo": _SIN_CAMBIO}
    return {"fuente": "BCE", "fecha": cambio.fecha, "url": cambio.url}


def _cifra_texto(cifra: Cifra, unidad: str = " USD") -> str:
    return cifra.motivo if cifra.valor is None else f"{_coma(cifra.valor)}{unidad}"


def _formula_be(e: Economia, costes: Costes | Cifra | None) -> str:
    if e.be_usd.valor is None or not isinstance(costes, Costes) or e.cobros is None:
        return f"BE = AOV × (1 − comisión − impuestos − reembolsos) − comisión fija × cobros: {_cifra_texto(e.be_usd)}"
    return (f"BE = AOV {_coma(e.aov_usd.valor)} × (1 − {_coma(costes.comision_pct)} − {_coma(costes.impuestos_pct)} "
            f"− {_coma(costes.reembolsos_pct)}) − {_coma(costes.comision_fija_usd)} × cobros {_coma(e.cobros)} "
            f"→ {_coma(e.be_usd.valor)} USD (a la baja al céntimo)")


def render_escalera(escaleras: dict[str, EscaleraPais], economias: dict[str, Economia], cambio: Cambio | None,
                    hoy: date, *, producto: str, piezas: tuple[PiezaEscalera, ...],
                    costes: Costes | Cifra | None = None) -> str:
    """``ESCALERA.md``: precios por país con su pieza (resolución 6), economía en USD, cambio y avisos."""
    por_paso = {p.paso: p for p in piezas}
    meta = {
        "tipo": "escalera",
        "producto": producto,
        "fecha": hoy.isoformat(),
        "fuente": f"productos/{producto}/modelar.yaml, config/economia.yaml, config/mercados.yaml",
        "paises": {pais: _pais_meta(e, economias[pais], por_paso) for pais, e in escaleras.items()},
        "cambio": _cambio_meta(cambio),
    }
    if cambio is None:
        linea_cambio = "Cambio: no medido (sin cambio del BCE del día): lo que depende de él sale «no medido»."
    else:
        linea_cambio = f"Cambio: BCE del {cambio.fecha} ({cambio.url})."
    lineas = [f"# Escalera de precios · {producto}", "", linea_cambio, ""]
    for pais, e in escaleras.items():
        eco = economias[pais]
        lineas += [f"## {pais} ({e.moneda or 'moneda no medida'})", ""]
        if e.pasos is None:  # sin escalera no hay nada más que contar: solo el motivo
            lineas += [f"Escalera: {e.motivo}", ""]
            continue
        lineas += [f"Precio del front: {e.fuente_precio}.", ""]
        lineas += ["| Paso | Pieza | Precio | Activo | Motivo |", "|---|---|---|---|---|"]
        for nombre in PASOS:
            p = e.pasos[nombre]
            pieza = por_paso.get(nombre)
            lineas.append(f"| {_ETIQUETA_PASO[nombre]} | {_celda(pieza.titulo if pieza else '—')} | "
                          f"{_coma(p.precio)} {p.moneda} | {'sí' if p.activo else 'no'} | "
                          f"{_celda(p.motivo_inactivo or '—')} |")
        lineas.append("")
        lineas += [
            "### Economía (USD)", "",
            f"- AOV: {_cifra_texto(eco.aov_usd)}",
            f"- BE (CPA de equilibrio): {_cifra_texto(eco.be_usd)}",
            f"- CPA de test: {_cifra_texto(eco.cpa_test_usd)}",
            f"- CPA de escala: {_cifra_texto(eco.cpa_escala_usd)}",
            f"- ROAS de equilibrio: {_cifra_texto(eco.roas_be, '')}",
            "", _formula_be(eco, costes), "", "### Avisos", "",
        ]
        avisos = [*e.avisos, *eco.avisos]
        lineas += [f"- {a}" for a in avisos] or ["- Sin avisos."]
        lineas.append("")
    return _render(meta, "\n".join(lineas))


# --- BRANDBOOK.md ----------------------------------------------------------------------------------


def render_brandbook(b: Brandbook, hoy: date, *, producto: str) -> str:
    """``BRANDBOOK.md``: 7 secciones; ``tokens_css`` del frontmatter es la fuente (el bloque css es copia).

    Defensa en profundidad: un token fuera de la lista blanca del esquema lanza ``ValueError`` y no se pinta.
    """
    for clave, valor in b.tokens_css.items():
        motivo = token_css_inseguro(clave, valor)
        if motivo:
            raise ValueError(f"brandbook.tokens_css.{clave}: {motivo}; no se escribe el brandbook")
    meta = {
        "tipo": "brandbook",
        "producto": producto,
        "fecha": hoy.isoformat(),
        "fuente": f"productos/{producto}/modelar.yaml",
        "nombre_local": b.nombre_local,
        "idioma": b.idioma,
        "significado": b.significado,
        "paleta": dict(b.paleta),
        "tipografias": [dict(t) for t in b.tipografias],
        "tono": b.tono,
        "iconografia": b.iconografia,
        "mockup": b.mockup,
        "tokens_css": dict(b.tokens_css),
    }
    lineas = [f"# Brandbook · {b.nombre_local}", "", "## 1. Nombre local", "",
              f"**{b.nombre_local}** ({b.idioma}). {b.significado}", "", "## 2. Paleta", ""]
    lineas += [f"- {nombre}: `{color}`" for nombre, color in b.paleta.items()]
    lineas += ["", "## 3. Tipografías", ""]
    for t in b.tipografias:
        subconjuntos = ", ".join(t.get("subconjuntos") or ())
        lineas.append(f"- {t.get('uso')}: {t.get('familia')} ({subconjuntos}; licencia {t.get('licencia')})")
    lineas += ["", "## 4. Tono", "", b.tono, "", "## 5. Iconografía", "", b.iconografia, "",
               "## 6. Mockup", "", b.mockup, "", "## 7. Tokens CSS", "",
               "La fuente es `tokens_css` del frontmatter; este bloque es una copia para leer.", "",
               "```css", ":root {"]
    lineas += [f"  {clave}: {valor};" for clave, valor in b.tokens_css.items()]
    lineas += ["}", "```", ""]
    return _render(meta, "\n".join(lineas))


# --- comparativa.md --------------------------------------------------------------------------------


def render_comparativa(m: Modelado, original: Autopsia, nuestra: Autopsia, escaleras: dict[str, EscaleraPais],
                       hoy: date) -> str:
    """``comparativa.md`` en español: qué ofrecía el original, qué ofrecemos, por qué es mejor y el precio."""
    meta = {"tipo": "comparativa", "producto": m.producto, "pais": m.pais, "fecha": hoy.isoformat(),
            "fuente": f"productos/{m.producto}/modelar.yaml"}
    t, c = m.teardown, m.core
    dias = t.checkout.get("garantia_dias")
    lineas = [
        f"# Comparativa · {m.producto} · {m.pais}", "",
        "## Qué ofrecía el original", "",
        f"- Promesa: {t.promesa}",
        f"- Mecanismo: {t.mecanismo}",
        f"- Avatar: {t.avatar}",
        f"- Precio: {_precio_con_moneda(t.checkout.get('precio'), t.checkout.get('moneda'))}",
        f"- Garantía: {'no medida' if dias is None else f'{dias} días'}",
        f"- Landing: {len(t.secciones)} secciones",
        "", "## Qué ofrecemos", "",
        f"- Promesa: {c.promesa_h1}",
        f"- Mecanismo: {c.mecanismo_nombre} ({'; '.join(c.mecanismo_pasos)})",
        f"- Avatar: {c.avatar}",
        f"- Bonos: {'; '.join(b.nombre for b in c.bonos)}",
        f"- Garantía: {c.garantia_dias} días. {c.garantia_como}",
        f"- Formato: {c.formato}",
        f"- Landing: {len(m.estructura_landing)} secciones",
        "", "| Aspecto | Original | Nuestra |", "|---|---|---|",
    ]
    lineas += [f"| {_celda(a)} | {_celda(o)} | {_celda(n)} |" for a, o, n in m.comparativa]
    lineas += ["", "## Por qué es mejor", ""]
    lineas += [f"- **{x.que}** (impacto {x.impacto}): {x.por_que}" for x in _cambios_ordenados(m)]
    lineas += ["", "## Precio", ""]
    for pais, e in escaleras.items():
        if e.pasos is None:
            lineas.append(f"- {pais}: {e.motivo}")
        else:
            front = e.pasos["front"]
            lineas.append(f"- {pais}: front {_coma(front.precio)} {front.moneda} ({e.fuente_precio})")
        lineas += [f"  - {a}" for a in e.avisos]
    lineas += [
        "", "## Notas de la autopsia", "",
        f"- Original: {_nota(original)} (cobertura {original.cobertura} de 100)",
        f"- Nuestra: {_nota(nuestra)} (cobertura {nuestra.cobertura} de 100)",
        "", LINEA_CRITICA, "", CIERRE_TACITO, "",
    ]
    return _render(meta, "\n".join(lineas))


# --- escritura -------------------------------------------------------------------------------------


def _precio_original(vault: Path, p_id: str) -> tuple[tuple[Decimal, str | None] | None, bool]:
    """``((precio, moneda), False)`` de ``wiki/ofertas/<oferta_id>.md``; moneda ausente → ``None``.

    Sin ``oferta_id`` o sin ficha: ``(None, False)`` (no hay con qué comparar). Con ficha pero con un precio
    que no se lee, no es finito o es ≤ 0: ``(None, True)``, y la comparación sale «no medido». Un float del
    YAML (``9.0``) pasa por ``str`` para no arrastrar el error binario.
    """
    meta = frontmatter.leer(ruta_producto(vault, p_id))[0] or {}
    oferta_id = meta.get("oferta_id")
    if not isinstance(oferta_id, str) or not _ID_OFERTA.fullmatch(oferta_id) or ".." in oferta_id:
        return None, False
    ficha = Path(vault) / "wiki" / "ofertas" / f"{oferta_id}.md"
    if not ficha.is_file():
        return None, False
    datos = frontmatter.leer(ficha)[0] or {}
    crudo = datos.get("precio")
    precio: Decimal | None = None
    if isinstance(crudo, str):
        try:
            precio = Decimal(crudo.strip().replace(",", "."))
        except InvalidOperation:
            precio = None
    elif isinstance(crudo, (int, float, Decimal)) and not isinstance(crudo, bool):
        precio = crudo if isinstance(crudo, Decimal) else Decimal(str(crudo))
    if precio is None or not precio.is_finite() or precio <= 0:
        return None, True
    moneda = datos.get("moneda")
    moneda = moneda.strip().upper() if isinstance(moneda, str) and moneda.strip() else None
    return (precio, moneda), False


def _precio_manual(precio: Decimal | float, moneda: str) -> Decimal:
    """EUR/USD al céntimo (``13.9`` → ``13.90``, ``15`` → ``15.00``); las monedas sin céntimos, tal cual."""
    importe = precio if isinstance(precio, Decimal) else Decimal(str(precio))
    return importe.quantize(_CENTIMO) if moneda.upper() in _MONEDAS_CON_CENTIMOS else importe


def _sin_mercado(pais: str) -> EscaleraPais:
    """La reserva que no está en ``config/mercados.yaml``: sin escalera, con su motivo."""
    motivo = f"no medido: {pais} no está en config/mercados.yaml"
    return EscaleraPais(pais, "", None, Cifra(None, motivo), "", (), motivo)


def _con_avisos(escalera: EscaleraPais, *avisos: str) -> EscaleraPais:
    return dataclasses.replace(escalera, avisos=(*escalera.avisos, *avisos)) if avisos else escalera


def _version_libre(versiones: Path, nombre: str, hoy: date, ocupadas: set[Path]) -> Path:
    base = f"{nombre}-{hoy.isoformat()}"
    ruta, n = versiones / f"{base}.md", 1
    while ruta.exists() or ruta in ocupadas:
        n += 1
        ruta = versiones / f"{base}-{n}.md"
    return ruta


def escribir_modelado(vault: Path, p_id: str, m: Modelado, config: ConfigEconomia, cambio: Cambio | None,
                      precios_manuales: dict[str, Decimal], hoy: date, ahora: datetime) -> list[Path]:
    """Escribe los 4 archivos (versionando los previos) y anota la oferta en ``PRODUCTO.md`` sin tocar el estado.

    Solo con el país elegido en ``aprobado`` o ``modelado`` (rehacer); si no, ``EstadoInesperado`` y nada escrito.
    """
    vault = Path(vault)
    pais, reserva, _ = pais_elegido(vault, p_id)
    if m.pais != pais:
        raise ValueError(f"modelar.yaml es de {m.pais} y el país elegido es {pais}")
    if m.producto != p_id:
        raise ValueError(f"modelar.yaml es de {m.producto} y se está escribiendo {p_id}")
    estado = estado_pais(vault, p_id, pais)
    if estado not in ESTADOS_PERMITIDOS:
        motivo = f"{pais} está en {estado or 'sin estado'}: /modelar solo trabaja en aprobado (o en modelado, para rehacer)"
        if estado in _EN_PRODUCCION:
            motivo += "; la oferta ya pasó a producción y no se rehace"
        raise EstadoInesperado(motivo)

    paises = [pais] + ([reserva] if reserva and reserva != pais else [])
    ajenos = sorted(set(precios_manuales) - set(paises))
    if ajenos:
        raise ValueError(f"precio manual para {', '.join(ajenos)}, que no es el país elegido ni la reserva "
                         f"({', '.join(paises)})")
    ruta_mercados = vault / "config" / "mercados.yaml"
    if not ruta_mercados.is_file():
        raise FileNotFoundError("falta config/mercados.yaml")
    mercados = mercados_cfg.cargar(ruta_mercados)
    if pais not in mercados:
        raise ValueError(f"falta {pais} en config/mercados.yaml")
    # La reserva que falta en mercados.yaml no bloquea el país elegido: sale «no medido» con su motivo.
    sin_mercado = [p for p in paises if p not in mercados]
    con_precio = sorted(set(sin_mercado) & set(precios_manuales))
    if con_precio:
        raise ValueError(f"precio manual para {', '.join(con_precio)}, que no está en config/mercados.yaml")
    manuales = {p: _precio_manual(v, mercados[p].moneda) for p, v in precios_manuales.items()}

    original_precio, original_ilegible = _precio_original(vault, p_id)
    idioma = mercados[pais].idioma
    escaleras: dict[str, EscaleraPais] = {}
    for p in paises:
        if p in sin_mercado:
            escalera = _sin_mercado(p)
        else:
            escalera = escalera_pais(mercados[p], config.escalera, cambio, original_precio, manuales.get(p),
                                     upsells_permitidos(config), admite_downsell(config))
            if p != pais and escalera.pasos is not None and mercados[p].idioma != idioma:
                escalera = _con_avisos(escalera, f"títulos en {idioma}: se traducen al lanzar este país")
        if original_ilegible:
            escalera = _con_avisos(escalera, AVISO_ORIGINAL_ILEGIBLE)
        escaleras[p] = escalera
    economias = {p: economia_pais(e, config, cambio) for p, e in escaleras.items()}
    original = puntuar(m.ejes_original, config.autopsia.pesos)
    nuestra = puntuar(m.ejes_nuestra, config.autopsia.pesos)
    senal = senal_se_puede_mejorar(original, nuestra, m.ejes_original, m.ejes_nuestra, config.autopsia)

    textos = {
        "OFERTA": render_oferta(m, original, nuestra, senal, hoy,
                                vende_por_presupuesto=vende_por_presupuesto(original, config.autopsia)),
        "ESCALERA": render_escalera(escaleras, economias, cambio, hoy, producto=p_id, piezas=m.escalera_piezas,
                                    costes=costes_de(config)),
        "BRANDBOOK": render_brandbook(m.brandbook, hoy, producto=p_id),
        "comparativa": render_comparativa(m, original, nuestra, escaleras, hoy),
    }
    for nombre, texto in textos.items():
        patron = buscar_secreto(texto)  # RevisionSecretosNoDisponible: no se escribe nada
        if patron:
            raise ValueError(f"{nombre}.md: aparece un secreto ({patron}); no se escribe nada")

    # Orden de escritura: versiones previas → los 4 archivos → PRODUCTO.md → log.md. Ventana residual (sin
    # bloqueo ni transacción, R-6b): si el proceso muere a mitad, pueden quedar algunos de los 4 archivos
    # nuevos sin la anotación en PRODUCTO.md, o todo escrito sin la línea de log.md. El estado no cambia,
    # así que repetir /modelar lo arregla (en modelado rehace y versiona lo que haya).
    carpeta = ruta_producto(vault, p_id).parent
    if estado == "modelado":
        print(f"{pais} ya está en modelado: se rehace la oferta; los archivos anteriores pasan a versiones/ "
              "y la oferta vuelve a presentada.")
    versionadas: list[Path] = []
    for nombre in ARCHIVOS:
        actual = carpeta / f"{nombre}.md"
        if actual.is_file():
            destino = _version_libre(carpeta / "versiones", nombre, hoy, set(versionadas))
            escribir_atomico(destino, actual.read_text(encoding="utf-8"))
            versionadas.append(destino)
    escritas = []
    for nombre, texto in textos.items():
        ruta = carpeta / f"{nombre}.md"
        escribir_atomico(ruta, texto)
        escritas.append(ruta)

    valor, motivo = senal
    oferta: dict = {"aprobacion": "presentada", "fecha": hoy.isoformat()}
    if estado == "modelado":  # al rehacer, la aprobación anterior ya no vale (R-T7b)
        oferta |= {"aprobacion_cita": None, "aprobacion_fecha": None}
    actualizar_producto(
        vault, p_id,
        {"oferta": oferta,
         "senales": {"se_puede_mejorar": valor, "motivo": motivo, "fuente": f"productos/{p_id}/OFERTA.md"}},
        [f"- {etiqueta}: [[productos/{p_id}/{nombre}]]"
         for etiqueta, nombre in zip(("Oferta", "Escalera", "Brandbook", "Comparativa"), ARCHIVOS, strict=True)],
        "modelar", ahora)

    que = f"{p_id} {pais}: oferta presentada (OFERTA, ESCALERA, BRANDBOOK, comparativa)"
    if versionadas:
        que += f"; {len(versionadas)} versiones previas guardadas"
    anadir_log(vault, "modelar", que, [r.relative_to(vault).as_posix() for r in escritas + versionadas], ahora=ahora)
    return escritas


# --- lectores para los planes 17–20 ----------------------------------------------------------------


def _leer_meta(vault: Path, p_id: str, nombre: str) -> dict:
    ruta = ruta_producto(vault, p_id).parent / f"{nombre}.md"
    if not ruta.is_file():
        raise FileNotFoundError(f"falta {nombre}.md: /modelar")
    meta, _ = frontmatter.leer(ruta)
    return dict(meta or {})


def cargar_oferta(vault: Path, p_id: str) -> dict:
    """Frontmatter de ``OFERTA.md``."""
    return _leer_meta(vault, p_id, "OFERTA")


def cargar_escalera(vault: Path, p_id: str) -> dict[str, dict]:
    """``paises`` del frontmatter de ``ESCALERA.md`` (bloque por país)."""
    paises = _leer_meta(vault, p_id, "ESCALERA").get("paises")
    return dict(paises) if isinstance(paises, dict) else {}


def cargar_brandbook(vault: Path, p_id: str) -> dict:
    """Frontmatter de ``BRANDBOOK.md``."""
    return _leer_meta(vault, p_id, "BRANDBOOK")
