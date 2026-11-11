"""Salida de /auditar (§4.5): ``AUDITORIA.md``, ``PRODUCTO.md``, ``wiki/mercados`` y la elección.

Lo que no se midió se escribe «no medido: <motivo>», nunca 0 ni una estimación. Cada cifra va con
su enlace (la Biblioteca de la ficha de la oferta y las búsquedas del hueco). La elección del país
es del usuario: queda en ``decisiones/`` con su cita literal.

``render_auditoria`` es pura (la prueba el *golden file*); lo demás escribe con
``escribir_atomico``/``frontmatter.escribir`` y deja una línea en ``log.md`` por ejecución.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from trovify.auditoria.paises import PaisAuditado, cobertura, que_medir, tres_senales
from trovify.caza.salida import anadir_al_indice, formatear_medida
from trovify.caza.salida import formatear_numero as _num
from trovify.caza.senales import Medida
from trovify.vault import frontmatter
from trovify.vault.escritura import anadir_log, escribir_atomico

CIERRE = "La elección es tuya: dímela y la registro."
_PRODUCTO = re.compile(r"^p-(\d{4})-")
_NOMBRES = {
    "hueco": "Hueco",
    "precio": "Precio soportable",
    "demanda": "Demanda",
    "cpm": "CPM",
    "cultural": "Encaje cultural",
}
_ORIGINAL = {
    "traducido": "ya anuncia traducido al idioma local",
    "sin_traducir": "anuncia sin traducir (bonus)",
    "ausente_reciente": "anuncia sin traducir desde hace poco",
    "ausente": "sin anuncios activos ahora en el país",
    "no_medido": "no medido: no se pudo leer si está traducido",
}
_SENALES = (
    ("ya_se_vende", "Ya se vende (la caza la dejó en A o B)"),
    ("hueco_por_pais", "Hay hueco en algún país"),
    ("se_puede_mejorar", "Se puede mejorar"),
)
_PENDIENTE = {
    "ya_se_vende": "la ficha no tiene decisión de la caza",
    "hueco_por_pais": "ningún país tiene el hueco comprobado todavía",
    "se_puede_mejorar": "lo confirma la autopsia de /modelar",
}
_HUECO_CORTO = {True: "sí", False: "no", None: "no comprobado"}
# Estados desde los que una elección lleva un país a «aprobado» (§4.13); ``aprobado`` se queda igual.
APROBABLES = (None, "cazado", "auditado", "aprobado")
_P_ID = re.compile(r"p-\d{4}-[a-z0-9-]+")
# Las dos señales que se pueden medir hoy; ``se_puede_mejorar`` se exige en /modelar.
MEDIBLES = ("ya_se_vende", "hueco_por_pais")


# ---------------------------------------------------------------- formato


def _si_no(v: bool | None) -> str:
    return {True: "sí", False: "no", None: "pendiente"}[v]


def _nota(nota: float | None) -> str:
    return "no medida" if nota is None else f"{nota:.0f}"


def _nota_con_cobertura(p: PaisAuditado) -> str:
    c = cobertura(p)
    return _nota(p.nota) if p.nota is None or c is None else f"{_nota(p.nota)} ({c})"


def _lista(paises: list[str]) -> str:
    if len(paises) <= 1:
        return "".join(paises)
    return ", ".join(paises[:-1]) + f" ni {paises[-1]}"


def _competencia(m: Medida) -> str:
    if m.valor is None:
        return formatear_medida(m)
    return f"{formatear_medida(m)} anunciantes en el idioma local"


def _hueco(p: PaisAuditado) -> str:
    h = p.hueco
    texto = f"**{_HUECO_CORTO[h.hueco]}**"
    detalle = f"competencia local: {_competencia(h.competencia)} · original: {_ORIGINAL.get(h.original, h.original)}"
    if h.hueco is None and h.motivo:
        detalle += f" · por qué: {h.motivo}"
    return f"{texto} — {detalle}"


def _precio_pais(p: PaisAuditado) -> str:
    eur = formatear_medida(p.precio_eur) if p.precio_eur.valor is None else f"{_num(p.precio_eur.valor, 2)} €"
    if p.precio_s.valor is None:
        soportable = formatear_medida(p.precio_s)
    else:
        soportable = (f"{_num(p.precio_s.valor)} (1 = dentro de la banda de precios del país; "
                      "0 = muy lejos)")
    if p.banda is None:
        banda = f"banda de {p.pais}: no medido: sin banda en config/mercados.yaml"
    else:
        fuente = f"{p.fuente_banda}, config/mercados.yaml" if p.fuente_banda else "config/mercados.yaml"
        banda = f"banda de {p.pais}: {_num(p.banda[0], 2)}–{_num(p.banda[1], 2)} € (fuente: {fuente})"
    texto = f"Precio del original en EUR: {eur} · precio soportable: {soportable} · {banda}"
    if p.precio_local is not None:
        if p.precio_local.valor is None:
            local = formatear_medida(p.precio_local)
        elif p.moneda_local == "EUR":
            local = f"{_num(p.precio_local.valor, 2)} EUR"
        else:
            local = f"≈ {_num(p.precio_local.valor, 2)} {p.moneda_local} (al cambio del BCE de «La oferta»)"
        texto += f" · precio local en {p.pais}: {local}"
    return texto


def _motivo_caza(oferta: dict) -> str:
    """El motivo de la caza sin lo que dijo del hueco (lo mide esta auditoría, más abajo)."""
    partes = [x.strip() for x in str(oferta.get("motivo") or "").split(";")]
    partes = [x for x in partes if x and "hueco" not in x.lower()]
    motivo = f" — {'; '.join(partes)}" if partes else ""
    return f"{motivo} (el hueco por país lo mide esta auditoría, más abajo)"


def precio_original(oferta: dict) -> str:
    """El precio de la ficha tal cual: sin moneda clara no se asume ninguna."""
    precio, moneda = oferta.get("precio"), oferta.get("moneda")
    if not isinstance(precio, (int, float)) or isinstance(precio, bool):
        return "no medido: la ficha no tiene el precio del original"
    if not moneda:
        return f"{_num(precio, 2)} (moneda no medida: la landing no dice cuál es; «$» es ambiguo)"
    return f"{_num(precio) if float(precio).is_integer() else _num(precio, 2)} {moneda}"


_LANDING = re.compile(r"^- Landing: (https?://\S+)\s*$", re.MULTILINE)


def landing_de(meta: dict, cuerpo: str) -> str | None:
    """La URL completa de la landing: ``landing`` del frontmatter o la línea «- Landing:» de la ficha."""
    if isinstance(meta.get("landing"), str) and meta["landing"].startswith(("http://", "https://")):
        return meta["landing"]
    m = _LANDING.search(cuerpo or "")
    return m.group(1) if m else None


def _landing(oferta: dict) -> str:
    if oferta.get("landing"):
        return f"landing: {oferta['landing']}"
    dominio = f" (dominio: {oferta['dominio']})" if oferta.get("dominio") else ""
    return f"landing: no medido: la ficha no tiene el enlace de la landing{dominio}"


def _cifra(d: dict, nombre: str) -> str:
    v = d.get(nombre)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "no medido"
    return ("≥ " if nombre in (d.get("cota_inferior") or []) else "") + _num(v)


def _cifras_caza(oferta: dict) -> list[str]:
    paises = {k: v for k, v in (oferta.get("paises") or {}).items() if isinstance(v, dict)}
    if not paises:
        return ["- Cifras de la caza por país: no medido: la ficha no tiene países medidos"]
    lineas = ["- Cifras de la caza por país:"]
    for pais, d in sorted(paises.items()):
        lineas.append(
            f"  - {pais}: C8 {_cifra(d, 'c8')} · C7 {_cifra(d, 'c7')} · total {_cifra(d, 'total')} anuncios "
            f"activos · el más antiguo lleva {_cifra(d, 'edad_max')} días — "
            f"{d.get('link_biblioteca') or 'sin enlace: no medido'}"
        )
    return lineas


def orden_ranking(paises: list[PaisAuditado]) -> list[PaisAuditado]:
    """Primero los países con hueco comprobado y sin «no tirar»; luego los de hueco sin comprobar
    (su nota se midió sobre menos puntos y no se compara con la de arriba); al final los demás.
    Dentro de cada grupo, por nota y por puntos medidos (con empate, el texto de la recomendación manda)."""

    def grupo(p: PaisAuditado) -> int:
        if p.hueco.hueco is True and not p.no_tirar:
            return 0
        return 1 if p.hueco.hueco is None and not p.no_tirar else 2

    def medidos(p: PaisAuditado) -> float:
        return sum(peso for _, peso, s, _ in p.desglose if s is not None)

    return sorted(paises, key=lambda p: (grupo(p), p.nota is None, -(p.nota or 0), -medidos(p), p.pais))


_orden = orden_ranking


def _desglose(p: PaisAuditado) -> list[str]:
    lineas = ["| Parte | Peso | Valor (0 a 1) |", "|---|---|---|"]
    for nombre, peso, s, motivo in p.desglose:
        valor = _num(s) if s is not None else (motivo or "no medido: sin motivo")
        lineas.append(f"| {_NOMBRES.get(nombre, nombre)} | {_num(peso)} | {valor} |")
    medidos = [(peso, s) for _, peso, s, _ in p.desglose if s is not None]
    total = sum(peso for peso, _ in medidos)
    lineas.append("")
    if p.nota is None or total <= 0:
        lineas.append("Cálculo: nota no medida: no se midió ninguna parte.")
    else:
        suma = sum(peso * s for peso, s in medidos)
        nota = _num(p.nota) if float(p.nota).is_integer() else _num(p.nota, 2)
        lineas.append(f"Cálculo: 100 × {_num(suma)} ÷ {_num(total)} (solo los pesos medidos) = {nota}.")
    return lineas


def _seccion_pais(i: int, p: PaisAuditado) -> list[str]:
    lineas = [
        f"### {i}. {p.pais} — nota {_nota_con_cobertura(p)}",
        "",
        f"- Hueco: {_hueco(p)}",
        *([f"- Hueco reutilizado: {p.hueco_medido}"] if p.hueco_medido else []),
        f"- {_precio_pais(p)}",
    ]
    if p.no_tirar:
        lineas.append(f"- No tirar: {p.no_tirar}")
    if p.hueco.enlaces:
        lineas.append("- Búsquedas en la Biblioteca que dan estas cifras:")
        lineas += [f"  - {e}" for e in p.hueco.enlaces]
    else:
        lineas.append("- Búsquedas en la Biblioteca: ninguna (no se buscó en este país)")
    return [*lineas, "", *_desglose(p), ""]


def _pruebas_no_tirar(p: PaisAuditado) -> list[str]:
    """Los enlaces que prueban el motivo: la página del original si está traducido; si no, las frases."""
    de_pagina = [e for e in p.hueco.enlaces if "view_all_page_id=" in e]
    otras = [e for e in p.hueco.enlaces if e not in de_pagina]
    return (de_pagina if p.hueco.original == "traducido" else otras) or p.hueco.enlaces


def _frontmatter_auditoria(oferta: dict, orden: list[PaisAuditado], recomendacion, senales3: dict,
                           hoy: date) -> dict:
    oferta_id = str(oferta.get("oferta_id"))
    return {
        "tipo": "auditoria",
        "fecha": hoy.isoformat(),
        "fuente": f"wiki/ofertas/{oferta_id}.md",
        "oferta_id": oferta_id,
        "recomendado": recomendacion[0],
        "reserva": recomendacion[1],
        "senales": {k: senales3.get(k) for k, _ in _SENALES},
        "paises": {
            p.pais: {
                "puesto": i,
                "nota": None if p.nota is None else round(p.nota, 2),
                "hueco": p.hueco.hueco,
                "no_tirar": p.no_tirar,
            }
            for i, p in enumerate(orden, 1)
        },
    }


def render_auditoria(oferta: dict, paises: list[PaisAuditado], recomendacion, senales3: dict,
                     historial: list[str], hoy: date, *, calculo_eur: str | None = None,
                     cambio: str | None = None, busquedas: list[str] | None = None) -> str:
    """``AUDITORIA.md`` completo (frontmatter y cuerpo). Pura: la prueba el *golden file*.

    ``calculo_eur``: cómo se pasó el precio a EUR; ``cambio``: el cambio del BCE usado (fecha y
    enlace); ``busquedas``: líneas sobre las búsquedas del día."""
    oferta_id = str(oferta.get("oferta_id"))
    orden = _orden(paises)
    lineas = [
        f"# Auditoría de {oferta_id} ({hoy.isoformat()})",
        "",
        ("Dónde lanzar esta oferta, país por país. Lo que no se pudo medir se dice como tal y no puntúa: "
        "la nota de cada país se calcula solo con lo medido."),
        "",
        "## La oferta",
        "",
        f"- Ficha: [[wiki/ofertas/{oferta_id}]]",
        f"- Decisión de la caza: **{oferta.get('estado') or 'no medido'}**{_motivo_caza(oferta)}",
        f"- Precio del original: {precio_original(oferta)} — {_landing(oferta)}",
        f"- Precio del original en EUR: {calculo_eur or 'no medido: sin cálculo'}",
        f"- Cambio de moneda: {cambio or 'no medido: sin cambio de referencia'}",
        *_cifras_caza(oferta),
        "",
        "## Ranking de países",
        "",
    ]
    if orden:
        lineas += [
            ("Pesos de la nota: config/umbrales.yaml (auditar.peso.*, [D-13]). Lo no medido no puntúa ni "
            "resta: la nota se calcula sobre los puntos medidos."),
            "",
            "| # | País | Nota (0 a 100) | Hueco | No tirar |",
            "|---|---|---|---|---|",
        ]
        lineas += [
            f"| {i} | {p.pais} | {_nota_con_cobertura(p)} | {_HUECO_CORTO[p.hueco.hueco]} | {p.no_tirar or '—'} |"
            for i, p in enumerate(orden, 1)
        ]
        lineas.append("")
        for i, p in enumerate(orden, 1):
            lineas += _seccion_pais(i, p)
    else:
        lineas += ["no medido: no se auditó ningún país", ""]

    lineas += ["## No tirar", ""]
    vetados = [p for p in orden if p.no_tirar]
    for p in vetados:
        pruebas = _pruebas_no_tirar(p)
        lineas.append(f"- {p.pais}: {p.no_tirar}" + (f" — {' · '.join(pruebas)}" if pruebas else ""))
    if not vetados:
        lineas.append("Ninguno: ningún país auditado tiene un motivo para no tirar.")
    lineas += ["", "## Las tres señales", ""]
    for clave, nombre in _SENALES:
        v = senales3.get(clave)
        lineas.append(f"- {nombre}: **{_si_no(v)}**" + (f" — {_PENDIENTE[clave]}" if v is None else ""))
    lineas += [
        "",
        ("Si eliges con «ya se vende» o «hay hueco» en «no», la elección queda escrita como excepción "
        "en decisiones/."),
        "",
        "## Historial del cerebro",
        "",
    ]
    if historial:
        lineas += ["¿Ya lanzamos algo parecido allí? Sí:", ""]
        lineas += [f"- {x}" for x in historial]
    else:
        lineas.append(f"¿Ya lanzamos algo parecido allí? No: ningún producto del cerebro murió en "
                      f"{_lista([p.pais for p in orden]) or 'estos países'}.")
    if busquedas:
        lineas += ["", "## Búsquedas de hoy", "", *[f"- {x}" for x in busquedas]]
    lineas += ["", "## Qué medir", ""]
    pendientes = que_medir(orden)
    lineas += [f"- {x}" for x in pendientes] or ["Nada: todos los países auditados tienen el hueco comprobado."]
    lineas += [
        "",
        "## Recomendación",
        "",
        recomendacion[2],
        "",
        ("Primer test: 1 producto × 1 país (el capital no da para dos a la vez); la reserva es el país "
        "al que pasar si el primero no funciona."),
        "",
        CIERRE,
        "",
    ]
    meta = _frontmatter_auditoria(oferta, orden, recomendacion, senales3, hoy)
    return frontmatter.renderizar(meta, "\n".join(lineas))


# ---------------------------------------------------------------- productos


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return s[:40].strip("-") or "producto"


def slug_de_oferta(oferta_id: str) -> str:
    """``o-fise-terapie-3fa2b1`` → ``fise-terapie`` (sin prefijo ni huella)."""
    s = re.sub(r"^o-", "", oferta_id)
    s = re.sub(r"-[0-9a-f]{6}$", "", s)
    return _slug(s)


def _leer_meta(ruta: Path) -> dict:
    try:
        meta, _ = frontmatter.leer(ruta)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def producto_para(vault: Path, oferta_id: str, slug: str) -> str:
    """``p-NNNN-<slug>``; si ya hay un producto con ``oferta_id`` en su ``PRODUCTO.md``, ese."""
    base = Path(vault) / "productos"
    mayor = 0
    for d in sorted(base.glob("p-*")) if base.exists() else []:
        m = _PRODUCTO.match(d.name)
        if not d.is_dir() or not m:
            continue
        mayor = max(mayor, int(m.group(1)))
        if _leer_meta(d / "PRODUCTO.md").get("oferta_id") == oferta_id:
            return d.name
    return f"p-{mayor + 1:04d}-{_slug(slug)}"


def producto_existente(vault: Path, oferta_id: str) -> str | None:
    """El p-id del producto de ``oferta_id`` si ya existe (sin proponer uno nuevo)."""
    p_id = producto_para(vault, oferta_id, slug_de_oferta(oferta_id))
    return p_id if (Path(vault) / "productos" / p_id / "PRODUCTO.md").exists() else None


def historial_de(vault: Path, paises: list[str], excluir: str | None = None) -> list[str]:
    """Productos con estado ``MUERTO`` en esos países y su nota «stop» (§4.5 paso 5)."""
    out: list[str] = []
    base = Path(vault) / "productos"
    for ruta in sorted(base.glob("p-*/PRODUCTO.md")) if base.exists() else []:
        p_id = ruta.parent.name
        if p_id == excluir:
            continue
        datos = _leer_meta(ruta).get("paises") or {}
        if not isinstance(datos, dict):
            continue
        for pais in paises:
            d = datos.get(pais)
            if isinstance(d, dict) and str(d.get("estado") or "").upper() == "MUERTO":
                motivo = d.get("motivo") or "sin motivo escrito"
                stop = d.get("stop") or "sin enlace «stop»"
                out.append(f"[[productos/{p_id}/PRODUCTO]] en {pais}: MUERTO — {motivo} · stop: {stop}")
    return out


def _archivar(ruta: Path) -> Path | None:
    """La ``AUDITORIA.md`` anterior pasa a ``AUDITORIA-<su fecha>.md`` (``-2``, ``-3``… si ya existe)."""
    if not ruta.exists():
        return None
    fecha = _leer_meta(ruta).get("fecha")
    fecha = str(fecha) if fecha else "sin-fecha"
    destino = ruta.with_name(f"AUDITORIA-{fecha}.md")
    n = 2
    while destino.exists():
        destino = ruta.with_name(f"AUDITORIA-{fecha}-{n}.md")
        n += 1
    escribir_atomico(destino, ruta.read_text(encoding="utf-8"))
    return destino


def _actualizar_producto(vault: Path, p_id: str, oferta_id: str, paises: list[str], hoy: date) -> Path:
    ruta = Path(vault) / "productos" / p_id / "PRODUCTO.md"
    if ruta.exists():
        meta, cuerpo = frontmatter.leer(ruta)
        meta = dict(meta or {})
    else:
        meta, cuerpo = {}, (
            f"# Producto {p_id}\n\n"
            f"- Oferta: [[wiki/ofertas/{oferta_id}]]\n"
            f"- Auditoría: [[productos/{p_id}/AUDITORIA]]\n"
            "- Decisiones: carpeta decisiones/\n"
        )
    estados = {k: dict(v) for k, v in (meta.get("paises") or {}).items() if isinstance(v, dict)}
    for pais in paises:
        actual = estados.setdefault(pais, {})
        if actual.get("estado") in (None, "auditado"):
            actual["estado"] = "auditado"  # nunca baja a un país ya aprobado o más avanzado
    meta.update({
        "tipo": "producto",
        "fecha": meta.get("fecha") or hoy.isoformat(),
        "fuente": f"wiki/ofertas/{oferta_id}.md",
        "oferta_id": oferta_id,
        "paises": estados,
    })
    frontmatter.escribir(ruta, meta, cuerpo)
    return ruta


def _linea_mercado(p: PaisAuditado, oferta_id: str, p_id: str, hoy: date) -> str:
    h = p.hueco
    precio = "no medido" if p.precio_s.valor is None else _num(p.precio_s.valor)
    hueco = _HUECO_CORTO[h.hueco]
    enlace = h.enlaces[0] if h.enlaces else "sin búsquedas"
    return (f"- {hoy.isoformat()} · {oferta_id} ([[productos/{p_id}/AUDITORIA]]): competencia local "
            f"{formatear_medida(h.competencia)} · original {_ORIGINAL.get(h.original, h.original).split(' (')[0]} · "
            f"precio soportable {precio} · hueco {hueco} — {enlace}")


def _actualizar_mercado(vault: Path, p: PaisAuditado, oferta_id: str, p_id: str, hoy: date) -> Path:
    ruta = Path(vault) / "wiki" / "mercados" / f"{p.pais}.md"
    if ruta.exists():
        meta, cuerpo = frontmatter.leer(ruta)
        meta = dict(meta or {})
    else:
        meta, cuerpo = {}, f"# Mercado {p.pais}\n\n## Auditorías\n\n"
    if "## Auditorías" not in cuerpo:
        cuerpo = cuerpo.rstrip("\n") + "\n\n## Auditorías\n\n"
    nueva = _linea_mercado(p, oferta_id, p_id, hoy)
    prefijo = f"- {hoy.isoformat()} · {oferta_id} "
    lineas = cuerpo.rstrip("\n").split("\n")
    existente = next((i for i, x in enumerate(lineas) if x.startswith(prefijo)), None)
    if existente is not None:
        lineas[existente] = nueva  # la misma oferta el mismo día: se actualiza, no se duplica
    else:
        lineas.append(nueva)
    meta.update({"tipo": "mercado", "pais": p.pais, "fecha": hoy.isoformat(),
                 "fuente": "trovify auditar (Biblioteca de anuncios)"})
    frontmatter.escribir(ruta, meta, "\n".join(lineas) + "\n")
    return ruta


def escribir_auditoria(vault: Path, oferta_id: str, paises: list[PaisAuditado], hoy: date, **contexto) -> Path:
    """Escribe ``productos/<p-id>/AUDITORIA.md`` (archiva la anterior), ``PRODUCTO.md``,
    ``wiki/mercados/<pais>.md``, ``index.md`` y una línea en ``log.md``. Devuelve la ruta de la auditoría."""
    from trovify.auditoria.paises import recomendar

    vault = Path(vault)
    ficha = vault / "wiki" / "ofertas" / f"{oferta_id}.md"
    if not ficha.exists():
        raise FileNotFoundError(f"no existe la ficha wiki/ofertas/{oferta_id}.md")
    try:
        meta_ficha, cuerpo_ficha = frontmatter.leer(ficha)
    except (OSError, ValueError):
        meta_ficha, cuerpo_ficha = {}, ""
    oferta = dict(meta_ficha or {})
    oferta.setdefault("oferta_id", oferta_id)
    oferta["landing"] = landing_de(oferta, cuerpo_ficha)
    p_id = producto_para(vault, oferta_id, slug_de_oferta(oferta_id))
    nombres = [p.pais for p in paises]
    recomendacion = recomendar(paises)
    senales3 = tres_senales(str(oferta.get("estado") or "") or None, paises)
    historial = historial_de(vault, nombres, excluir=p_id)
    texto = render_auditoria(oferta, paises, recomendacion, senales3, historial, hoy, **contexto)

    ruta = vault / "productos" / p_id / "AUDITORIA.md"
    archivada = _archivar(ruta)  # copia: si la escritura nueva fallara, la anterior sigue en su sitio
    escribir_atomico(ruta, texto)
    producto = _actualizar_producto(vault, p_id, oferta_id, nombres, hoy)
    mercados = [_actualizar_mercado(vault, p, oferta_id, p_id, hoy) for p in paises]
    anadir_al_indice(vault, [
        ("Productos", f"[[productos/{p_id}/PRODUCTO]]", f"producto de {oferta_id}; última auditoría {hoy.isoformat()}"),
        ("Productos", f"[[productos/{p_id}/AUDITORIA]]", f"auditoría de {oferta_id} ({hoy.isoformat()})"),
        *[("Mercados", f"[[wiki/mercados/{p}]]", f"mercado {p}: auditorías por oferta") for p in nombres],
    ])
    archivos = [ruta, producto, *mercados] + ([archivada] if archivada else [])
    anadir_log(vault, "auditar",
               f"auditoría de {oferta_id} en {', '.join(nombres) or 'ningún país'}; "
               f"recomendado {recomendacion[0] or 'ninguno'}" + (f", reserva {recomendacion[1]}" if recomendacion[1] else ""),
               [a.relative_to(vault).as_posix() for a in archivos])
    return ruta


# ---------------------------------------------------------------- elección


def _ruta_eleccion(dir_: Path, hoy: date) -> Path:
    """``AAAA-MM-DD-eleccion.md`` es siempre la última del día (la que lee ``mercado_elegido``); una
    anterior del mismo día pasa a ``AAAA-MM-DD-N-eleccion.md``, que ordena antes."""
    ruta = dir_ / f"{hoy.isoformat()}-eleccion.md"
    if ruta.exists():
        n = 1
        while (dir_ / f"{hoy.isoformat()}-{n}-eleccion.md").exists():
            n += 1
        ruta.rename(dir_ / f"{hoy.isoformat()}-{n}-eleccion.md")
    return ruta


def _fuera_de_mercados(vault: Path, pais: str) -> bool:
    """True si ``pais`` no está en ``config/mercados.yaml`` (una errata como «RU» no se aprueba)."""
    from trovify.config import mercados as cfg_mercados

    ruta = Path(vault) / "config" / "mercados.yaml"
    if not ruta.exists():
        return False  # sin la lista no se puede saber; los demás avisos siguen valiendo
    return pais not in cfg_mercados.cargar(ruta)


def registrar_eleccion(vault: Path, p_id: str, pais: str, reserva: str | None, cita: str, hoy: date,
                       senales3: dict[str, bool] | None = None) -> Path:
    """Escribe ``productos/<p-id>/decisiones/AAAA-MM-DD-eleccion.md`` con la cita literal del usuario
    y pone ``paises.<pais>.estado: aprobado`` en ``PRODUCTO.md``.

    Advierte si el país está en «no tirar» o no tiene el hueco comprobado; si alguna de las dos
    señales medibles es ``False``, la elección queda como excepción. Sin ``senales3`` se leen de la
    última ``AUDITORIA.md``."""
    vault = Path(vault)
    if not cita or not cita.strip():
        raise ValueError("hace falta la cita literal del usuario (--cita)")
    pais = pais.strip().upper()
    reserva = reserva.strip().upper() if reserva and reserva.strip() else None
    if not re.fullmatch(r"[A-Z]{2}", pais) or (reserva and not re.fullmatch(r"[A-Z]{2}", reserva)):
        raise ValueError("los países van con su código de dos letras (por ejemplo RO)")
    if not _P_ID.fullmatch(p_id or ""):
        raise ValueError(f"producto mal escrito: «{p_id}»; usa su p-id (por ejemplo p-0001-fise-terapie)")
    dir_producto = vault / "productos" / p_id
    producto = dir_producto / "PRODUCTO.md"
    auditoria = dir_producto / "AUDITORIA.md"
    if not producto.exists() or not auditoria.exists():
        raise FileNotFoundError(f"no existe la auditoría de {p_id}: ejecuta antes «trovify auditar ejecutar»")
    am = _leer_meta(auditoria)
    if senales3 is None:
        senales3 = am.get("senales") or {}
    auditados = am.get("paises") or {}
    datos = auditados.get(pais) if isinstance(auditados, dict) else None
    datos = datos if isinstance(datos, dict) else {}

    avisos: list[str] = []
    fuera_de_mercados = _fuera_de_mercados(vault, pais)
    if fuera_de_mercados:
        avisos.append(f"Advertencia: {pais} no está en tus mercados (config/mercados.yaml); la decisión queda "
                      "escrita, pero el país no pasa a «aprobado»")
    if not datos:
        avisos.append(f"Advertencia: {pais} no está en la última auditoría de este producto")
    if datos.get("no_tirar"):
        avisos.append(f"Advertencia: {datos['no_tirar']}")
    if datos.get("hueco") is not True:
        avisos.append("Advertencia: este país no tiene hueco comprobado")
    faltan = [k for k in MEDIBLES if senales3.get(k) is False]
    if faltan:
        nombres = dict(_SENALES)
        avisos.append("Excepción: faltan " + ", ".join(f"{k} («{nombres[k]}»)" for k in faltan)
                      + " (se elige con menos de las tres señales)")
    pm, cuerpo_producto = frontmatter.leer(producto)
    pm = dict(pm or {})
    estados = {k: dict(v) for k, v in (pm.get("paises") or {}).items() if isinstance(v, dict)}
    actual = estados.get(pais, {}).get("estado")
    if actual not in APROBABLES:
        avisos.append(f"Advertencia: este país ya está en {actual}; el estado no cambia")
    for otro, d in sorted(estados.items()):
        if otro != pais and d.get("estado") not in APROBABLES:
            avisos.append(f"Advertencia: {otro} ya está en {d.get('estado')} (1 producto × 1 país)")

    cita_md = "\n".join(f"> {x}" if x else ">" for x in cita.split("\n"))
    lineas = [
        f"# Elección de país para {p_id} ({hoy.isoformat()})",
        "",
        f"País elegido: **{pais}** · reserva: {reserva or 'ninguna'}",
        "",
        "Palabras del usuario (cita literal):",
        "",
        cita_md,
        "",
    ]
    if avisos:
        lineas += [*avisos, ""]
    lineas.append(f"Auditoría: [[productos/{p_id}/AUDITORIA]] ({am.get('fecha') or 'sin fecha'})")
    lineas.append("")
    meta = {"tipo": "decision", "fecha": hoy.isoformat(), "fuente": "usuario", "pais": pais,
            "reserva": reserva, "producto": p_id}
    dir_decisiones = dir_producto / "decisiones"
    dir_decisiones.mkdir(parents=True, exist_ok=True)
    ruta = _ruta_eleccion(dir_decisiones, hoy)
    frontmatter.escribir(ruta, meta, "\n".join(lineas))

    if actual in APROBABLES and not fuera_de_mercados:
        for otro, d in estados.items():
            if otro != pais and d.get("estado") == "aprobado":
                d["estado"] = "auditado"  # 1 producto × 1 país: la elección nueva sustituye a la anterior
        estados.setdefault(pais, {})["estado"] = "aprobado"
    # Un país más allá de «aprobado» (test, en producción, MUERTO…) nunca se toca (§4.13).
    pm["paises"] = estados
    frontmatter.escribir(producto, pm, cuerpo_producto)
    anadir_log(vault, "auditar",
               f"elección de {p_id}: {pais}" + (f", reserva {reserva}" if reserva else "")
               + (f" ({'; '.join(avisos)})" if avisos else ""),
               [ruta.relative_to(vault).as_posix(), producto.relative_to(vault).as_posix()])
    return ruta
