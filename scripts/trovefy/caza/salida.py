"""Salida de la caza (§4.3): informe por región, fichas de oferta y el resto de archivos del vault.

Regla anti-*minería* (§1.4): lo que no se midió se escribe «no medido: <motivo>» en el texto y
``null``/celda vacía en frontmatter, CSV y SQLite; nunca un 0 ni una estimación. Una cota inferior
se escribe «≥ N» en el texto y, en el frontmatter, el número con su nombre en ``cota_inferior``.

Al vault solo van enlaces (la Biblioteca y la URL pública de cada anuncio): nunca imágenes ni
vídeos de terceros.

``render_informe`` y ``render_ficha`` son puras (las prueban los *golden files*); ``escribir``
hace toda la escritura con ``escribir_atomico``/``frontmatter.escribir`` y una línea en ``log.md``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from trovefy.caza import snapshots
from trovefy.caza.biblioteca import url_biblioteca
from trovefy.caza.destino import motivo_dudoso, veredicto_landing
from trovefy.caza.filtros import Descarte
from trovefy.caza.hueco import HuecoPais
from trovefy.caza.nota import Nota
from trovefy.caza.oferta import Oferta
from trovefy.caza.senales import Medida, Senales
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico

CIERRE = "La decisión de modelar es tuya: escríbela en veredicto.md"
_ANUNCIO = "https://www.facebook.com/ads/library/?id="
_ESTADOS = ("A", "B", "observar", "descartada")


@dataclass
class Consulta:
    """Una búsqueda por palabra clave: alimenta ``palabras.csv`` (podar las que no rinden)."""

    palabra: str
    pais: str
    resultados: int | None  # anuncios que dio Meta; None = no medido (bloqueo o error)
    enlace: str  # url_biblioteca de la búsqueda
    ofertas: list[str] = field(default_factory=list)  # oferta_id de los candidatos que salieron de ella
    aproximado: bool = False  # ``resultados`` es el total aproximado del texto de Meta («~230»)
    sin_recuento: bool = False  # Meta respondió (hay candidatas) pero no dio recuento


@dataclass
class CifraPagina:
    """De dónde salen las cifras de la oferta en una página y país (O2: el enlace reproduce la cifra)."""

    enlace: str  # la URL que dio la cifra de la oferta: el recuento con frase si lo hubo; si no, la página
    pagina: str  # la URL de la página en el país (todas sus ofertas)
    total_pagina: int | None = None  # anuncios activos de la página según Meta (exacto); None = no exacto
    leidos_pagina: int | None = None  # anuncios de la página leídos en esa lectura
    otras_ofertas: bool = False  # la página lleva otras ofertas o anuncios sin atribuir
    # anuncios activos EXACTOS de la oferta en la página (recuento con frase completo o página
    # completa solo suya); None = no exacto. Es el mismo número que suma la fila Total.
    exacto_oferta: int | None = None


@dataclass
class ResultadoOferta:
    """Una oferta evaluada en un país.

    Campos añadidos al contrato del plan (todos con valor por defecto):

    - ``dia``: día de la medición (``escribir`` pone el de la ``Ejecucion`` si falta).
    - ``total_meta``: número EXACTO de anuncios activos según Meta (el mismo que recibió
      ``calcular_senales``); es lo único que se guarda como ``Snapshot.total``. None = no exacto.
    - ``completo``: la lectura fue completa (``ResultadoBusqueda.completo``). Sin ella
      ``Snapshot.activos`` es NULL y los recuentos por página de los competidores son cota inferior.

    ``senales.nuevos``/``parados`` ya vienen del llamador (``registrar_vistos(..., completo=True)``
    antes de ``calcular_senales``, con la ventana de ``dia_anterior`` en su motivo): aquí solo se
    copian. Las banderas de ``filtros.banderas`` las une el llamador a ``senales.banderas``.
    """

    oferta: Oferta
    pais: str
    senales: Senales
    nota: Nota
    decision: str
    explicacion: str
    descarte: Descarte | None
    huecos: list[HuecoPais]
    enlace: str
    dia: date | None = None
    total_meta: int | None = None
    completo: bool = False
    # Crecimiento en 7 días de cada PÁGINA de la oferta, con el total exacto de Meta de la página
    # (todas sus ofertas): ``(page_id, Medida, enlace de la página)``. Es un dato de la página, no de
    # la oferta: no entra en la nota, ni en Snapshot.total, ni en las señales de la oferta.
    crecimiento_pagina: list[tuple[str, Medida, str]] = field(default_factory=list)
    # page_id → de dónde salen las cifras de la oferta en esa página (sin dato: la página entera).
    paginas_cifras: dict[str, CifraPagina] = field(default_factory=dict)


@dataclass
class Ejecucion:
    """Una ejecución de la caza en una región.

    Añadidos al contrato del plan: ``via`` (búsquedas por vía: ``firecrawl``/``playwright``) y
    ``creditos`` (créditos de Firecrawl gastados; None = no informados) para la cabecera (D-11b);
    ``consultas`` (``palabras.csv``) y ``vara`` (``("C8", 15)``: la señal y el mínimo del perfil,
    de ``config/umbrales.yaml``) para la señal «ya se vende» de R16.
    """

    dia: date
    region: str
    modo: str
    perfil: str
    busquedas: int
    bloqueos: int
    vacios: int
    errores: list[str]
    resultados: list[ResultadoOferta]
    pendientes: int
    via: dict[str, int] = field(default_factory=dict)
    creditos: int | None = None
    consultas: list[Consulta] = field(default_factory=list)
    vara: tuple[str, float] | None = None
    # Motivo por el que la ejecución se detuvo (bloqueo de Meta o, solo en este proceso, errores
    # seguidos o navegador caído); None si terminó. Lo que quedó sin medir sale en ``errores``.
    parada: str | None = None
    # «meta» (bloqueo de Meta: dura el día) o «errores» (red/Firecrawl/navegador: solo este proceso).
    tipo_parada: str | None = None
    # Motivo si se acabó la cuota de búsquedas del día (tuya o de la rutina): es un final normal, no
    # una parada; lo que no cupo queda pendiente para otra caza.
    cuota: str | None = None
    # Candidatas sin evaluar por motivo: «tope_nuevas» (R14), «cuota» (búsquedas del día) y
    # «landing_sin_abrir» (tope de landings por ejecución). La suma es ``pendientes``.
    pendientes_por: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------- formato


def _num(x: float, decimales: int | None = None) -> str:
    """Número con coma decimal. Sin ``decimales``: entero si lo es; si no, hasta 3 decimales."""
    if decimales is not None:
        return f"{x:.{decimales}f}".replace(".", ",")
    if float(x).is_integer():
        return str(int(x))
    return f"{round(x, 3):g}".replace(".", ",")


def formatear_numero(x: float, decimales: int | None = None) -> str:
    """Número con coma decimal (forma pública de ``_num`` para otros módulos)."""
    return _num(x, decimales)


def _comas(texto: str) -> str:
    """Decimales con coma en textos que vienen de otros módulos («nota 67.1 < 70»)."""
    return re.sub(r"\b(nota|C7|C8) (\d+)\.(\d)", r"\1 \2,\3", texto)


def _no_medido(motivo: str | None) -> str:
    motivo = (motivo or "sin motivo").strip()
    return motivo if motivo.startswith("no medido") else f"no medido: {motivo}"


def formatear_medida(m: Medida) -> str:
    """«≥ 60» si es suelo; «no medido: <motivo>» si no hay valor; coma decimal siempre."""
    if m.valor is None:
        return _no_medido(m.motivo)
    texto = ("≥ " if m.suelo else "") + _num(m.valor)
    return f"{texto} ({m.motivo})" if m.motivo else texto


def _entero(m: Medida) -> int | float | None:
    if m.valor is None:
        return None
    return int(m.valor) if float(m.valor).is_integer() else m.valor


def _dinero(precio: float | None, moneda: str | None) -> str:
    if precio is None:
        return "no medido: sin precio visible en la landing ni en el checkout"
    return f"{_num(precio, 2)} {moneda}" if moneda else f"{_num(precio, 2)} (no medido: moneda)"


def _host(url: str | None) -> str | None:
    return (urlsplit(url).hostname or None) if url else None


_SENALES = (
    ("C8", "c8", "anuncios activos con 8 días o más: la oferta se sostiene"),
    ("C7", "c7", "anuncios activos con 7 días o más"),
    ("Total", "total", "anuncios activos de la oferta en el país"),
    ("Supervivencia", "supervivencia", "parte de los anuncios que llega a 7 días (de 0 a 1)"),
    ("Semanas escalonadas", "escalonado_semanas",
     "semanas distintas en que arrancaron los anuncios activos con 7 días o más"),
    ("Edad máxima (días)", "edad_max_dias", "días que lleva el anuncio activo más antiguo"),
    ("Vida mediana (días)", "vida_mediana_dias", "cuánto duraron los anuncios que ya pararon"),
    ("Crecimiento en 7 días", "crecimiento_7d", "cambio de anuncios activos frente a hace una semana"),
    ("Expansión", "expansion", "países, idiomas y páginas que llevan la oferta"),
    ("Duplicación", "duplicacion", "copias extra del mismo anuncio que agrupa Meta"),
    ("Alcance UE", "alcance_ue", "alcance declarado en la Unión Europea"),
    ("Nuevos", "nuevos", "anuncios que aparecieron desde la corrida completa anterior"),
    ("Parados", "parados", "anuncios que desaparecieron desde la corrida completa anterior"),
)

_PARTES = {
    "c8": "C8",
    "longevidad": "Longevidad",
    "crecimiento_7d": "Crecimiento en 7 días",
    "expansion": "Expansión",
    "duplicacion": "Duplicación",
    "alcance_ue": "Alcance UE",
    "supervivencia": "Supervivencia",
}

_MULTIPLICADORES = {
    "supervivencia_baja": "supervivencia baja",
    "cayendo": "la oferta está cayendo",
    "vida_corta": "los anuncios duran poco",
}

_BANDERAS = {
    "acelerando": "los anuncios activos crecen rápido frente a hace una semana",
    "cayendo": "los anuncios activos caen frente a hace una semana",
    "moneda_distinta": "el precio está en otra moneda que la del país",
    "academia": "parece una academia o curso grande",
    "saturado": "un mismo jugador tiene muchísimos anuncios: sirve como fuente, no como rival de frente",
    "estacional": "depende de una fecha o temporada",
    "precio_bajo": ("precio de entrada bajo (informa, no descarta: la copia se relanza a nuestro precio, "
                    "la banda de mercados.yaml)"),
    "mismo_operador": ("otra página lleva al mismo sitio: mismo operador o su socio (informa, no es una "
                       "copia)"),
}

_ORIGINAL = {
    "traducido": "ya traducido al idioma local",
    "sin_traducir": "sin traducir",
    "ausente_reciente": "sin anuncios aquí; los suyos son recientes",
    "ausente": "sin anuncios activos aquí",
    "no_medido": "no medido",
}

_DESCARTES = {
    "ya_visto": "ya vista",
    "destino_social": "destino en una red social",
    "producto_fisico": "producto físico",
    "marca_personal": "marca personal",
    "cebo_backend": "cebo de un back-end caro",
    "embudo_no_verificable": "embudo no verificable",
    "cloaker": "cloaker",
    "tracker": "tracker",
    "posible_copia": "posible copia",
}


def _tabla_senales(s: Senales, paginas: int = 1) -> list[str]:
    filas = ["| Señal | Valor | Qué significa |", "|---|---|---|"]
    for etiqueta, attr, que in _SENALES:
        valor = formatear_medida(getattr(s, attr))
        if attr == "total" and paginas > 1 and s.total.valor is not None:
            valor += f" (suma de {paginas} páginas)"
        filas.append(f"| {etiqueta} | {valor} | {que} |")
    return filas


def _varias_paginas(r: ResultadoOferta) -> bool:
    return len(r.oferta.page_ids) > 1


def _cifra(r: ResultadoOferta, page_id: str) -> CifraPagina:
    cp = r.paginas_cifras.get(page_id)
    if cp is not None:
        return cp
    u = url_biblioteca(r.pais, page_id=page_id)
    return CifraPagina(u, u)


def _link_pais(r: ResultadoOferta) -> str:
    """Enlace único del país (``paises.XX.link_biblioteca``): el que da la cifra. Con varias páginas,
    el de la página original en ese país (cada página tiene además el suyo con su recuento)."""
    o = r.oferta
    if _varias_paginas(r):
        return _cifra(r, o.original_page_id or o.page_ids[0]).enlace
    return r.enlace


def _pagina_pais(r: ResultadoOferta) -> str:
    """URL de la página (original) en el país, aparte del enlace de la cifra."""
    o = r.oferta
    return _cifra(r, o.original_page_id or o.page_ids[0]).pagina


def _otras_ofertas(r: ResultadoOferta, cp: CifraPagina, n: int) -> str:
    if cp.total_pagina is not None:
        total = str(cp.total_pagina)
    elif cp.leidos_pagina:
        total = f"≥ {cp.leidos_pagina}"
    else:
        total = "no medido"
    propios = str(n) if r.completo else f"≥ {n}"
    d = r.oferta.destino
    host = _host(d.url_final or d.url_anuncio) if d else None
    return (f"la página lleva otras ofertas: de los {total} anuncios del enlace, {propios} son de esta "
            f"(destino {host or 'no medido'})")


def _paginas(r: ResultadoOferta) -> list[str]:
    """Una línea por página: papel, anuncios activos de la oferta en el país y el enlace que da esa
    cifra (con la página aparte si la cifra sale de un recuento con frase)."""
    o = r.oferta
    lineas = []
    for p in o.page_ids:
        papel = " (original)" if p == o.original_page_id else (" (copia)" if p in o.copias else "")
        n = sum(1 for a in o.anuncios if a.page_id == p and a.activo and (r.pais == "ALL" or a.pais == r.pais))
        cp = _cifra(r, p)
        if cp.exacto_oferta is not None:
            n = cp.exacto_oferta
            cuenta = f"{n} anuncios activos"
        elif r.completo:
            cuenta = f"{n} anuncios activos"
        elif n:
            cuenta = f"≥ {n} anuncios activos"
        else:
            cuenta = "anuncios activos: no medido: no se leyó ningún anuncio de esta página"
        linea = f"{p}{papel}: {cuenta} — {cp.enlace}"
        if cp.enlace != cp.pagina:
            linea += f" · página: {cp.pagina}"
        elif cp.otras_ofertas:
            linea += f" · {_otras_ofertas(r, cp, n)}"
        lineas.append(linea)
    return lineas


def _crecimiento_pagina(r: ResultadoOferta) -> list[str]:
    if not r.crecimiento_pagina:
        return []
    lineas = ["", "Páginas de la oferta (dato de la página entera, no el total de esta oferta):", ""]
    for page_id, m, enlace in r.crecimiento_pagina:
        lineas.append(f"- {page_id}: crecimiento de la página (todas sus ofertas) en 7 días: "
                      f"{formatear_medida(m)} — {enlace}")
    return lineas


def _cifras(r: ResultadoOferta) -> list[str]:
    if not _varias_paginas(r):
        cp = r.paginas_cifras.get(r.oferta.page_ids[0]) if r.oferta.page_ids else None
        if cp is None or (cp.enlace == cp.pagina and not cp.otras_ofertas):
            return [f"Cifras de {r.pais} (enlace reproducible): {r.enlace}"]
        return [f"Cifras de {r.pais} (el enlace reproduce la cifra de esta oferta):", "", *[f"- {x}" for x in _paginas(r)]]
    n = len(r.oferta.page_ids)
    return [
        f"Cifras de {r.pais}: suma de {n} páginas; cada enlace reproduce su parte:",
        "",
        *[f"- {x}" for x in _paginas(r)],
        "",
        f"Búsqueda donde apareció la oferta: {r.enlace}",
    ]


def _titulo_nota(n: Nota) -> str:
    return "nota no medida" if n.valor is None else f"nota {_num(n.valor, 2)}"


def _desglose(n: Nota) -> list[str]:
    no_medidas = ", ".join(_PARTES.get(x, x) for x in n.no_medidas)
    if n.valor is None:
        return [
            "Nota: no medida. Ninguna parte de la nota se pudo medir; no se rellena con ceros.",
            "",
            f"Sin medir: {no_medidas}.",
        ]
    filas = [
        f"Nota {_num(n.valor, 2)} de 100, parte por parte:",
        "",
        "| Parte | Peso | Puntuación (0 a 1) | Aporte |",
        "|---|---|---|---|",
    ]
    for nombre, peso, puntos, aporte in n.desglose:
        filas.append(f"| {_PARTES.get(nombre, nombre)} | {_num(peso)} | {_num(puntos, 2)} | {_num(aporte, 2)} |")
    suma_aporte = sum(d[3] for d in n.desglose)
    suma_peso = sum(d[1] for d in n.desglose)
    base = 100 * suma_aporte / suma_peso
    calculo = f"Cálculo: 100 × {_num(suma_aporte, 2)} ÷ {_num(suma_peso)} (pesos medidos) = {_num(base, 2)}"
    for nombre, factor in n.multiplicadores:
        calculo += f" × {_num(factor)} ({_MULTIPLICADORES.get(nombre, nombre)})"
    if n.multiplicadores:
        calculo += f" = {_num(n.valor, 2)}"
    filas += ["", calculo + "."]
    if n.no_medidas:
        filas += ["", f"Sin medir (no cuentan en la nota ni restan): {no_medidas}."]
    return filas


def _hueco_texto(h: HuecoPais) -> str:
    if h.hueco is True:
        return "sí"
    if h.hueco is False:
        return "no"
    return "no comprobado"


def _por_que(h: HuecoPais) -> str:
    if not h.motivo:
        return "—"
    if h.motivo == h.competencia.motivo:
        return "falta medir la competencia local"
    return h.motivo


def _tabla_huecos(huecos: list[HuecoPais], titulo: bool = True) -> list[str]:
    if not huecos:
        return ["Hueco por país: no medido: no se buscó competencia local para esta oferta."]
    filas = ["Hueco por país:", ""] if titulo else []
    filas += [
        "| País | Competencia local | Original | Hueco | Por qué |",
        "|---|---|---|---|---|",
    ]
    for h in huecos:
        filas.append(
            f"| {h.pais} | {formatear_medida(h.competencia)} | {_ORIGINAL.get(h.original, h.original)} | "
            f"{_hueco_texto(h)} | {_por_que(h)} |"
        )
    for h in huecos:
        if h.enlaces:
            filas += ["", f"Búsquedas del hueco en {h.pais}:"]
            filas += [f"- {e}" for e in h.enlaces]
    return filas


def _ficha_escrita(r: ResultadoOferta) -> bool:
    """Lo ya visto, excluido o propio no se reescribe (su ficha, si la hay, manda)."""
    return not _ya_vista(r)


def _ya_vista(r: ResultadoOferta) -> bool:
    """Ya en el cerebro, excluida o propia: se informa aparte, no es un descarte ni cuenta en tasas."""
    return r.descarte is not None and r.descarte.codigo == "ya_visto"


def _juzgados(rs: list[ResultadoOferta]) -> list[ResultadoOferta]:
    return [r for r in rs if not _ya_vista(r)]


def _bloque_oferta(r: ResultadoOferta) -> list[str]:
    o = r.oferta
    lineas = [
        f"### {o.oferta_id} · {r.pais} · {_titulo_nota(r.nota)}",
        "",
        f"Decisión: **{r.decision}** — {_comas(r.explicacion)}",
        "",
        f"Ficha: [[wiki/ofertas/{o.oferta_id}]]",
        "",
        *_cifras(r),
        "",
        *_tabla_senales(r.senales, len(r.oferta.page_ids)),
        *_crecimiento_pagina(r),
        "",
        *_desglose(r.nota),
        "",
        *_tabla_huecos(r.huecos),
        "",
    ]
    return lineas


def _ya_se_vende(r: ResultadoOferta, vara: tuple[str, float] | None, perfil: str) -> str:
    if vara is None:
        return "no comprobado: falta el mínimo del perfil"
    etiqueta, minimo = vara
    m = r.senales.c7 if etiqueta == "C7" else r.senales.c8
    if m.valor is None:
        return _no_medido(m.motivo)
    detalle = f"{etiqueta} {formatear_medida(m)}, mínimo {_num(minimo)} del perfil {perfil}"
    if m.valor >= minimo:
        return f"sí ({detalle})"
    if m.suelo:
        return f"no comprobado ({detalle}; Meta tenía más anuncios de los leídos)"
    return f"no ({detalle})"


def _sin_prefijo(motivo: str | None) -> str:
    return (motivo or "sin motivo").removeprefix("no medido: ")


def _hay_hueco(r: ResultadoOferta) -> str:
    if not r.huecos:
        return "no medido: no se buscó competencia local"
    si = [h.pais for h in r.huecos if h.hueco is True]
    if si:
        return f"sí, en {', '.join(si)}"
    dudosos = [h for h in r.huecos if h.hueco is None]
    if dudosos:
        return "no comprobado. " + "; ".join(f"En {h.pais}: {_sin_prefijo(h.motivo)}" for h in dudosos) + "."
    return "no, en " + ", ".join(h.pais for h in r.huecos)


def _resumen(e: Ejecucion, estado: str) -> str:
    rs = [r for r in _juzgados(e.resultados) if r.decision == estado]
    if not rs:
        return "ninguna"
    return f"{len(rs)} — " + ", ".join(f"{r.oferta.oferta_id} ({r.pais})" for r in rs)


def _cabecera_via(e: Ejecucion) -> str:
    nombres = {"firecrawl": "Firecrawl", "playwright": "Playwright", "mcp": "MCP oficial"}
    partes = [f"{nombres.get(k, k)} {n}" for k, n in sorted(e.via.items()) if n]
    texto = f"Búsquedas en la Biblioteca: {e.busquedas}"
    if partes:
        texto += f" ({', '.join(partes)})"
    if e.creditos is not None:
        creditos = str(e.creditos)
    elif e.via.get("firecrawl"):
        creditos = "no medido: Firecrawl no informó los créditos"
    else:
        creditos = "ninguno (no se usó Firecrawl)"
    return f"{texto} · créditos de Firecrawl: {creditos}"


_PENDIENTES = {
    "tope_nuevas": "por el tope de ofertas nuevas por ejecución (R14)",
    "cuota": "porque no quedaban búsquedas hoy (cuota del día)",
    "landing_sin_abrir": "con la landing sin abrir (tope de landings por ejecución)",
    "bloqueo": "porque Meta bloqueó la búsqueda y la caza se paró por hoy",
    "interrumpida": "porque la ejecución se interrumpió (red, Firecrawl o navegador)",
}


def texto_pendientes(e: Ejecucion) -> str:
    """«Sin evaluar: N candidatas …» con cada motivo y cuántas por él."""
    por = {k: n for k, n in (e.pendientes_por or {"tope_nuevas": e.pendientes}).items() if n}
    nombre = "candidata" if e.pendientes == 1 else "candidatas"
    if len(por) == 1:
        (k, _), = por.items()
        detalle = f"{e.pendientes} {nombre} {_PENDIENTES.get(k, k)}"
    else:
        detalle = f"{e.pendientes} {nombre}: " + ", ".join(f"{n} {_PENDIENTES.get(k, k)}" for k, n in por.items())
    return f"Sin evaluar: {detalle}; salen en la próxima caza."


def _modelable(r: ResultadoOferta) -> bool | None:
    """True/False si la landing se verificó; None si no hay destino verificado."""
    d = r.oferta.destino
    if d is None or d.estado != "ok":
        return None
    return veredicto_landing(d) == "modelable"


def _tasas(e: Ejecucion) -> tuple[tuple[int, int, float | None], tuple[int, int, float | None]]:
    juzgados = _juzgados(e.resultados)
    leidos = [r for r in juzgados if r.senales.c7.valor is not None]
    con_cohorte = [r for r in leidos if r.senales.c7.valor > 0]
    verificados = [r for r in juzgados if _modelable(r) is not None]
    modelables = [r for r in verificados if _modelable(r)]
    senal = (len(con_cohorte), len(leidos), len(con_cohorte) / len(leidos) if leidos else None)
    modelo = (len(modelables), len(verificados), len(modelables) / len(verificados) if verificados else None)
    return senal, modelo


def render_informe(e: Ejecucion) -> str:
    dia = e.dia.isoformat()
    lineas = [
        f"# Caza del {dia} · {e.region}",
        "",
        f"Modo: {e.modo} · perfil: {e.perfil}",
        "",
        _cabecera_via(e),
        "",
        f"Búsquedas con acceso bloqueado: {e.bloqueos} · búsquedas sin resultados: {e.vacios}",
        "",
    ]
    if e.bloqueos:
        lineas += [
            (f"**Aviso:** Meta dejó el acceso bloqueado en {e.bloqueos} "
             f"{'búsqueda' if e.bloqueos == 1 else 'búsquedas'}. Todo lo que dependía de "
             f"{'ella' if e.bloqueos == 1 else 'ellas'} sale como «no medido», nunca como un número."),
            "",
        ]
    lineas += [
        ("Cómo leer este informe: «≥ N» quiere decir «al menos N» (Meta tenía más anuncios de los que se "
         "leyeron). «no medido: …» quiere decir que esa cifra no se pudo medir y por qué; nunca se "
         "rellena con un número. Cada tabla lleva el enlace de la Biblioteca que da sus cifras."),
        "",
        "## Resumen",
        "",
        f"- A: {_resumen(e, 'A')}",
        f"- B: {_resumen(e, 'B')}",
        f"- Observar: {_resumen(e, 'observar')}",
        f"- Descartadas: {_resumen(e, 'descartada')}",
    ]
    vistas = [r for r in e.resultados if _ya_vista(r)]
    if vistas:
        lineas.append(f"- Ya vistas: {len(vistas)} — " + ", ".join(f"{r.oferta.oferta_id} ({r.pais})" for r in vistas))
    if e.pendientes:
        lineas.append(f"- {texto_pendientes(e)}")
    lineas.append("")

    for titulo, estado in (("Ofertas A", "A"), ("Ofertas B", "B"), ("Observar", "observar")):
        lineas += [f"## {titulo}", ""]
        rs = [r for r in _juzgados(e.resultados) if r.decision == estado]
        if not rs:
            lineas += ["Ninguna.", ""]
        for r in rs:
            lineas += _bloque_oferta(r)

    lineas += ["## Descartadas", ""]
    descartadas = [r for r in _juzgados(e.resultados) if r.decision == "descartada"]
    if not descartadas:
        lineas += ["Ninguna.", ""]
    for r in descartadas:
        d = r.descarte
        motivo = f"{_DESCARTES.get(d.codigo, d.codigo)} — {d.detalle}" if d else _comas(r.explicacion)
        ficha = f" · ficha: [[wiki/ofertas/{r.oferta.oferta_id}]]" if _ficha_escrita(r) else ""
        lineas.append(f"- {r.oferta.oferta_id} ({r.pais}): {motivo} · cifras: {r.enlace}{ficha}")
    if descartadas:
        lineas.append("")
    if vistas:
        lineas += ["## Ya vistas", "",
                   ("Ya están en el cerebro (o en exclusiones o productos propios): no se vuelven a juzgar aquí; "
                    "su ficha manda."), ""]
        lineas += [f"- {r.oferta.oferta_id} ({r.pais}): ficha [[wiki/ofertas/{r.oferta.oferta_id}]] · cifras: "
                   f"{r.enlace}" for r in vistas]
        lineas.append("")

    lineas += ["## Palabras clave", ""]
    if not e.consultas:
        lineas += ["No hubo búsquedas por palabra clave en esta ejecución.", ""]
    else:
        lineas += ["| Palabra | País | Anuncios | Candidatas | Modelables | Enlace |", "|---|---|---|---|---|---|"]
        for c in e.consultas:
            candidatas, modelables = _rinde(c, e)
            nm = "no medido: búsqueda sin respuesta"
            if c.resultados is None:
                resultados = "no medido: sin recuento de Meta" if c.sin_recuento else nm
            else:
                resultados = f"≈ {c.resultados}" if c.aproximado else str(c.resultados)
            candidatas = nm if candidatas is None else candidatas
            modelables = nm if modelables is None else modelables
            lineas.append(f"| {c.palabra} | {c.pais} | {resultados} | {candidatas} | {modelables} | {c.enlace} |")
        lineas.append("")

    (cs, ls, ts), (mm, vm, tm) = _tasas(e)
    lineas += [
        "## Tasas",
        "",
        "- Tasa de señal (ofertas con anuncios de 7 días o más, sobre las leídas): "
        + (f"{cs} de {ls} = {_num(ts, 2)}" if ts is not None else "no medido: ninguna oferta con C7 medido"),
        "- Tasa de modelo (landings modelables, sobre las verificadas): "
        + (f"{mm} de {vm} = {_num(tm, 2)}" if tm is not None else "no medido: ninguna landing verificada"),
        "",
        "## Tres señales (R16)",
        "",
        ("Para modelar una oferta hacen falta tres señales: ya se vende, hay hueco por país y la oferta se "
         "puede mejorar."),
        "",
    ]
    candidatas = [r for r in _juzgados(e.resultados) if r.decision in ("A", "B", "observar")]
    if not candidatas:
        lineas += ["Ninguna oferta candidata en esta ejecución.", ""]
    for r in candidatas:
        lineas += [
            f"### {r.oferta.oferta_id} · {r.pais}",
            "",
            f"1. Ya se vende: {_ya_se_vende(r, e.vara, e.perfil)}",
            f"2. Hay hueco por país: {_hay_hueco(r)}",
            "3. La oferta se puede mejorar: pendiente: la confirma /modelar",
            "",
        ]

    if e.errores:
        lineas += ["## Errores", ""] + [f"- {x}" for x in e.errores] + [""]

    lineas += [CIERRE, ""]
    return "\n".join(lineas)


def _rinde(c: Consulta, e: Ejecucion) -> tuple[int | None, int | None]:
    """(candidatas, modelables); (None, None) si la búsqueda no respondió: nunca un 0 inventado."""
    if c.resultados is None and not c.sin_recuento:
        return None, None
    por_id = {r.oferta.oferta_id: r for r in e.resultados}
    vistas = {r.oferta.oferta_id for r in e.resultados if _ya_vista(r)}
    candidatas = [oid for oid in c.ofertas if oid not in vistas]  # las ya vistas no son candidatas nuevas
    modelables = sum(
        1 for oid in candidatas if oid in por_id and por_id[oid].descarte is None and _modelable(por_id[oid])
    )
    return len(candidatas), modelables


# ---------------------------------------------------------------- ficha


def _cotas(s: Senales) -> list[str]:
    return [n for n, m in (("c8", s.c8), ("c7", s.c7), ("total", s.total), ("edad_max", s.edad_max_dias)) if m.suelo]


_RANGO = {"A": 0, "B": 1, "observar": 2, "descartada": 3}


def mejor_pais(paises: dict) -> str | None:
    """El país con el mejor estado (A > B > observar > descartada); a igual estado, la nota más alta.

    Es la regla de la ficha: su ``estado``, ``motivo`` y ``fuente`` son los de este país (también
    al recalcular con ``trovefy caza hueco``)."""
    def clave(item):
        pais, d = item
        nota = d.get("nota") if isinstance(d.get("nota"), (int, float)) else -1.0
        return _RANGO.get(d.get("estado"), 9), -nota, pais

    validos = [(k, d) for k, d in (paises or {}).items() if isinstance(d, dict)]
    return min(validos, key=clave)[0] if validos else None


_SECCION_PAIS = re.compile(r"^## Señales en (\S+) \(.*?(?=^## |\Z)", re.DOTALL | re.MULTILINE)


def secciones_de_pais(cuerpo: str | None) -> dict[str, str]:
    """``país → texto`` de las secciones «## Señales en XX (fecha)» de una ficha."""
    return {m.group(1): m.group(0).rstrip("\n") for m in _SECCION_PAIS.finditer(cuerpo or "")}


def linea_hueco(huecos: list[HuecoPais], pais: str) -> str:
    """«Hueco en XX: …» de la sección del país (``trovefy caza hueco`` la actualiza)."""
    h = next((x for x in huecos if x.pais == pais), None)
    if h is None:
        return f"Hueco en {pais}: no medido: no se buscó competencia local en {pais}"
    por_que = _por_que(h)
    return (f"Hueco en {pais}: {_hueco_texto(h)}" + (f" — {por_que}" if por_que != "—" else "")
            + " (detalle en «Hueco por país»)")


def _seccion_pais(r: ResultadoOferta, dia: str) -> list[str]:
    o, s = r.oferta, r.senales
    activos = sorted((a for a in o.anuncios if a.activo and a.pais == r.pais), key=lambda a: (a.inicio, a.library_id))
    lineas = [
        f"## Señales en {r.pais} ({dia})",
        "",
        f"Decisión en {r.pais}: **{r.decision}** — {_comas(r.explicacion)}",
        "",
        *_cifras(r),
        "",
        *_tabla_senales(s, len(o.page_ids)),
        *_crecimiento_pagina(r),
        "",
        f"### Nota en {r.pais}",
        "",
        *_desglose(r.nota),
        "",
        linea_hueco(r.huecos, r.pais),
        "",
        f"### Anuncios de ejemplo en {r.pais}",
        "",
    ]
    if activos:
        lineas += [f"- {_ANUNCIO}{a.library_id} — activo desde {a.inicio.isoformat()}" for a in activos[:3]]
    else:
        lineas.append(f"no medido: no se leyó ningún anuncio activo en {r.pais}")
    return lineas


def _seccion_resumida(pais: str, d: dict) -> list[str]:
    """País medido en otra caza cuya sección no está en el cuerpo previo: lo guardado en la ficha."""
    def cifra(nombre):
        v = d.get(nombre)
        if v is None:
            return "no medido"
        return ("≥ " if nombre in (d.get("cota_inferior") or []) else "") + _num(v)

    nota = d.get("nota")
    return [
        f"## Señales en {pais} ({d.get('fecha') or 'sin fecha'})",
        "",
        f"Decisión en {pais}: **{d.get('estado') or 'no medido'}** — {_comas(str(d.get('motivo') or 'sin motivo'))}",
        "",
        (f"Medido en otra caza: C8 {cifra('c8')}, C7 {cifra('c7')}, total {cifra('total')}, nota "
         f"{'no medida' if nota is None else _num(nota, 2)}. Enlace: {d.get('link_biblioteca') or 'no medido'}"),
    ]


def render_ficha(rs: ResultadoOferta | list[ResultadoOferta], previa: dict | None,
                 cuerpo_previo: str | None = None) -> tuple[dict, str]:
    """Frontmatter y cuerpo de ``wiki/ofertas/<oferta_id>.md``: UNA ficha por oferta con todos sus países.

    ``rs``: los resultados de la oferta en esta ejecución (uno por país). ``previa`` es el
    frontmatter de la ficha existente y ``cuerpo_previo`` su cuerpo: se conservan sus otros países
    (datos y sección), la ``primera_vez``, los idiomas, los ``page_ids`` y las claves que no son de
    esta función (``strikes``…). ``estado``, ``motivo`` y ``fuente`` son los del mejor país
    (:func:`mejor_pais`); una ficha ``podada`` sigue podada.
    """
    rs = [rs] if isinstance(rs, ResultadoOferta) else list(rs)
    if not rs:
        raise ValueError("render_ficha necesita al menos un resultado")
    if any(r.dia is None for r in rs):
        raise ValueError("render_ficha necesita ResultadoOferta.dia (escribir lo pone desde la Ejecucion)")
    r0 = rs[0]
    o = r0.oferta
    previa = dict(previa or {})
    d = o.destino
    dia = max(r.dia for r in rs).isoformat()
    paises = {k: v for k, v in (previa.get("paises") or {}).items()}
    for r in rs:
        s = r.senales
        paises[r.pais] = {
            "c8": _entero(s.c8),
            "c7": _entero(s.c7),  # lo usa `trovefy caza hueco` para recalcular la decisión (perfil santino)
            "total": _entero(s.total),
            "edad_max": _entero(s.edad_max_dias),
            "link_biblioteca": _link_pais(r),
            "pagina": _pagina_pais(r),
            "estado": r.decision,
            "motivo": r.explicacion,
            "nota": None if r.nota.valor is None else round(r.nota.valor, 2),
            "cota_inferior": _cotas(s),
            "fecha": r.dia.isoformat(),
        }
    mejor = mejor_pais(paises)
    m = paises[mejor]
    idiomas = list(previa.get("idiomas") or [])
    banderas: list[str] = []
    detalles: dict[str, str] = {}
    for r in rs:
        idiomas += [i for i in r.senales.idiomas if i not in idiomas]
        banderas += [b for b in r.senales.banderas if b not in banderas]
        for b, det in r.senales.detalles_banderas.items():
            detalles.setdefault(b, det)
    page_ids = [str(p) for p in previa.get("page_ids") or []]
    page_ids += [p for p in o.page_ids if p not in page_ids]
    podada = previa.get("estado") == "podada"
    meta = dict(previa)
    meta.update({
        "tipo": "oferta",
        "fecha": dia,
        "fuente": m.get("link_biblioteca"),
        "oferta_id": o.oferta_id,
        "page_ids": page_ids,
        "original_page_id": o.original_page_id,
        "origen": o.origen,
        "checkout": d.checkout if d else None,
        "gateway": d.gateway if d else None,
        "dominio": _host(d.url_final or d.url_anuncio) if d else None,
        "paises": paises,
        "idiomas": idiomas,
        "precio": d.precio if d else None,
        "moneda": d.moneda if d else None,
        "estado": "podada" if podada else m.get("estado"),
        "motivo": previa.get("motivo") if podada else m.get("motivo"),
        "primera_vez": previa.get("primera_vez") or dia,
        "ultima_vez": dia,
        "banderas": banderas,
    })

    if d is None:
        landing = checkout = "no medido: sin destino resuelto"
    else:
        landing = d.url_final or _no_medido(d.motivo)
        checkout = (f"{d.checkout} ({d.gateway})" if d.gateway else d.checkout) if d.checkout else (
            _no_medido(motivo_dudoso(d)))
    varios = len(paises) > 1
    etiqueta = f" (el mejor país: {mejor})" if varios else ""
    lineas = [
        f"# Oferta {o.oferta_id}",
        "",
        f"Estado: **{meta['estado']}** — {_comas(str(meta['motivo'] or 'sin motivo'))}{etiqueta}",
        "",
        (f"Enlace principal (página original en {mejor}): {m.get('link_biblioteca')}"
         if len(page_ids) > 1 else f"Fuente de las cifras ({mejor}): {m.get('link_biblioteca')}"),
        "",
        f"Vista por primera vez: {meta['primera_vez']} · última: {dia}",
        "",
        "## Destino",
        "",
        f"- Landing: {landing}",
        f"- Checkout: {checkout}",
        f"- Precio: {_dinero(d.precio, d.moneda) if d else _no_medido('sin destino resuelto')}",
        f"- Idiomas de los anuncios: {', '.join(idiomas) if idiomas else 'no medido: idioma no detectado'}",
        "",
    ]
    medidos = {r.pais: r for r in rs}
    previas = secciones_de_pais(cuerpo_previo)
    orden = sorted(paises, key=lambda k: (k != mejor, _RANGO.get(paises[k].get("estado"), 9), k))
    for pais in orden:
        if pais in medidos:
            lineas += _seccion_pais(medidos[pais], medidos[pais].dia.isoformat())
        elif pais in previas:
            lineas.append(previas[pais])
        elif isinstance(paises[pais], dict):
            lineas += _seccion_resumida(pais, paises[pais])
        lineas.append("")
    huecos = next((r.huecos for r in rs if r.huecos), r0.huecos)
    lineas += [
        "## Hueco por país",
        "",
        *_tabla_huecos(huecos, titulo=False),
        "",
        "## Banderas",
        "",
    ]
    lineas += [(f"- {b}: {_BANDERAS[b]}" if b in _BANDERAS else f"- {b}") + (f" — {detalles[b]}" if b in detalles else "")
               for b in banderas] or ["ninguna"]
    lineas.append("")
    return meta, "\n".join(lineas)


# ---------------------------------------------------------------- escritura


def _libre(ruta: Path) -> Path:
    """``ruta`` si no existe; si no, ``-2``, ``-3``… (raw/ es inmutable)."""
    if not ruta.exists():
        return ruta
    n = 2
    while (candidata := ruta.with_name(f"{ruta.stem}-{n}{ruta.suffix}")).exists():
        n += 1
    return candidata


def _render_raw(e: Ejecucion) -> str:
    lineas = [
        f"# Mediciones de la caza del {e.dia.isoformat()} · {e.region}",
        "",
        (f"Modo {e.modo}, perfil {e.perfil}. {_cabecera_via(e)}. Bloqueos {e.bloqueos}, vacías {e.vacios}, "
         f"sin evaluar {e.pendientes}."),
        "",
    ]
    for c in e.consultas:
        res = "no medido" if c.resultados is None else c.resultados
        lineas.append(f"- consulta «{c.palabra}» ({c.pais}): {res} anuncios · {c.enlace} · ofertas: "
                      f"{', '.join(c.ofertas) or 'ninguna'}")
    for r in e.resultados:
        o = r.oferta
        lineas += [
            "",
            f"## {o.oferta_id} · {r.pais}",
            "",
            f"- enlace: {r.enlace}",
            (f"- lectura completa: {'sí' if r.completo else 'no'} · total exacto de Meta: "
             f"{r.total_meta if r.total_meta is not None else 'no medido'}"),
            f"- clave: {o.clave} · páginas: {', '.join(o.page_ids)} · origen: {o.origen}",
            *[f"- página {x}" for x in _paginas(r)],
            f"- decisión: {r.decision} — {r.explicacion}",
        ]
        lineas += [f"- {attr}: {formatear_medida(getattr(r.senales, attr))}" for _, attr, _ in _SENALES]
        lineas += [f"- página {p}: crecimiento de la página (todas sus ofertas) {formatear_medida(m)} · {u}"
                   for p, m, u in r.crecimiento_pagina]
        lineas.append(f"- nota: {'no medida' if r.nota.valor is None else _num(r.nota.valor, 4)}")
        for d in o.destinos or ([o.destino] if o.destino else []):
            estado = "medido" if d.estado == "ok" else "no medido"
            lineas.append(f"- destino: {d.url_anuncio} → {d.url_final or 'no medido'} · checkout "
                          f"{d.checkout or 'no medido'} · {estado}{' · ' + d.motivo if d.motivo else ''}")
        for h in r.huecos:
            lineas.append(f"- hueco {h.pais}: competencia {formatear_medida(h.competencia)}, original "
                          f"{_ORIGINAL.get(h.original, h.original)}, hueco {_hueco_texto(h)} · "
                          f"{' | '.join(h.enlaces) or 'sin enlaces'}")
    lineas += ["", "Errores:" if e.errores else "Sin errores.", *[f"- {x}" for x in e.errores], ""]
    return "\n".join(lineas)


def _csv_valor(x) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return str(int(x)) if x.is_integer() else f"{round(x, 4):g}"
    return str(x)


def _anadir_csv(ruta: Path, cabecera: list[str], filas: list[list]) -> None:
    previo = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if not previo:
        w.writerow(cabecera)
    for f in filas:
        w.writerow([_csv_valor(x) for x in f])
    escribir_atomico(ruta, previo + buf.getvalue())


def anadir_al_indice(vault: Path, entradas: list[tuple[str, str, str]]) -> None:
    """``(sección, enlace, descripción)``: una línea por enlace; si ya está, se actualiza."""
    ruta = vault / "index.md"
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else ["# Índice del cerebro"]
    for seccion, enlace, descripcion in entradas:
        nueva = f"- {enlace} — {descripcion}"
        existente = next((i for i, x in enumerate(lineas) if x.startswith(f"- {enlace} ")), None)
        if existente is not None:
            lineas[existente] = nueva
            continue
        cab = f"## {seccion}"
        if cab not in lineas:
            if lineas and lineas[-1].strip():
                lineas.append("")
            lineas += [cab, ""]
        i = lineas.index(cab) + 1
        fin = i
        while fin < len(lineas) and not lineas[fin].startswith("## "):
            fin += 1
        ultimo = fin
        while ultimo > i and not lineas[ultimo - 1].strip():
            ultimo -= 1
        if ultimo == i:  # sección vacía: deja una línea en blanco tras el título
            lineas.insert(i, "")
            ultimo = i + 1
        lineas.insert(ultimo, nueva)
    escribir_atomico(ruta, "\n".join(lineas).rstrip("\n") + "\n")


def _dominios(o: Oferta) -> list[str]:
    hosts: list[str] = []
    for d in o.destinos or ([o.destino] if o.destino else []):
        for u in (d.url_final or d.url_anuncio, d.checkout):
            h = _host(u)
            if h and h not in hosts:
                hosts.append(h)
    return hosts


def _entidades(vault: Path, rs: list[ResultadoOferta]) -> bool:
    ruta = vault / "wiki/entidades.md"
    if not ruta.exists():
        return False
    texto = ruta.read_text(encoding="utf-8")
    lineas = texto.rstrip("\n").splitlines()
    cambio = False
    for r in rs:
        o = r.oferta
        dominios = _dominios(o)
        if len(o.page_ids) < 2 and len(dominios) < 2:
            continue
        paginas = ", ".join(f"{p} (original)" if p == o.original_page_id else p for p in o.page_ids)
        nueva = (f"- {o.oferta_id} · páginas {paginas} · dominios {', '.join(dominios) or 'no medido'} · "
                 f"fuente {r.enlace}")
        i = next((k for k, x in enumerate(lineas) if x.startswith(f"- {o.oferta_id} ·")), None)
        if i is None:
            if lineas and lineas[-1].strip() and not lineas[-1].startswith("- "):
                lineas.append("")
            lineas.append(nueva)
            cambio = True
        elif lineas[i] != nueva:
            lineas[i] = nueva
            cambio = True
    if cambio:
        escribir_atomico(ruta, "\n".join(lineas) + "\n")
    return cambio


def _competidores(vault: Path, rs: list[ResultadoOferta], dia: str) -> list[tuple[Path, str | None]]:
    """Una ficha por página. El ``total`` de arriba es el de la PÁGINA (exacto de Meta, todas sus
    ofertas) o null; las cifras de cada oferta van aparte en ``cifras.<oferta_id>.<país>``, sin pisar
    las de otra oferta de la misma página."""
    rutas: dict[Path, str | None] = {}
    for r in rs:
        if r.descarte is not None:
            continue
        o, d = r.oferta, r.oferta.destino
        hoy = r.dia or date.fromisoformat(dia)
        for pid in o.page_ids:
            propios = [a for a in o.anuncios if a.page_id == pid and a.pais == r.pais and a.activo]
            c7 = sum(1 for a in propios if (hoy - a.inicio).days >= 7)
            cp = _cifra(r, pid)
            ruta = vault / "wiki/competidores" / f"{pid}.md"
            previa, _ = frontmatter.leer(ruta) if ruta.exists() else ({}, "")
            ofertas = list(previa.get("ofertas") or [])
            if o.oferta_id not in ofertas:
                ofertas.append(o.oferta_id)
            cifras = {k: dict(v) for k, v in (previa.get("cifras") or {}).items() if isinstance(v, dict)}
            cifras.setdefault(o.oferta_id, {})[r.pais] = {
                # Recuentos de la oferta en la página: exactos solo con lectura completa; si no, cota inferior.
                "c7": c7 if propios else None,
                "total": len(propios) if (r.completo and propios) else None,
                "cota_inferior": [] if r.completo else (["c7"] if propios else []),
                "fecha": dia,
                "fuente": cp.enlace,
            }
            nombre = next((a.page_name for a in propios), previa.get("nombre"))
            meta = dict(previa)
            meta.pop("c7", None)  # cifra de una oferta: va en ``cifras``, nunca como de la página
            meta.update({
                "tipo": "competidor",
                "page_id": pid,
                "nombre": nombre,
                "pais": r.pais,
                "total": cp.total_pagina,  # la página entera según Meta; null si no se midió exacto
                "cota_inferior": [],
                "checkout": d.checkout if d else None,
                "precio": d.precio if d else None,
                "moneda": d.moneda if d else None,
                "fecha": dia,
                "fuente": cp.pagina,
                "ofertas": ofertas,
                "cifras": cifras,
            })
            lineas = [
                f"# Competidor {pid}" + (f" · {nombre}" if nombre else ""),
                "",
                f"Página en la Biblioteca de anuncios ({r.pais}): {cp.pagina}",
                "",
                ("Anuncios activos de la página (todas sus ofertas): "
                 + (str(cp.total_pagina) if cp.total_pagina is not None else "no medido: Meta no dio el total exacto")),
                "",
                "Ofertas que lleva (cifras de cada una en la página, con su enlace):",
                "",
            ]
            for oid in ofertas:
                lineas.append(f"- [[wiki/ofertas/{oid}]]")
                for pais, c in sorted((cifras.get(oid) or {}).items()):
                    cota = "≥ " if "c7" in (c.get("cota_inferior") or []) else ""
                    c7_txt = "no medido" if c.get("c7") is None else f"{cota}{c['c7']}"
                    total_txt = "no medido" if c.get("total") is None else str(c["total"])
                    lineas.append(f"  - {pais} ({c.get('fecha')}): C7 {c7_txt}, activos {total_txt} — {c.get('fuente')}")
            lineas.append("")
            frontmatter.escribir(ruta, meta, "\n".join(lineas))
            rutas[ruta] = nombre
    return list(rutas.items())


def _snapshot(r: ResultadoOferta, dia: date) -> snapshots.Snapshot:
    s = r.senales

    def exacta(m: Medida) -> int | None:
        return None if (m.valor is None or m.suelo) else int(m.valor)

    activos = sum(1 for a in r.oferta.anuncios if a.activo and (r.pais == "ALL" or a.pais == r.pais))
    return snapshots.Snapshot(
        r.oferta.oferta_id, r.pais, dia,
        total=r.total_meta,  # contrato de la Tarea 4: solo la cuenta exacta de Meta
        activos=activos if r.completo else None,
        c7=exacta(s.c7), c8=exacta(s.c8),
        # nuevos/parados solo de lecturas completas (registrar_vistos(..., completo=True)).
        nuevos=exacta(s.nuevos) if r.completo else None,
        parados=exacta(s.parados) if r.completo else None,
        alcance_ue=None if s.alcance_ue.suelo else s.alcance_ue.valor,
        fuente=" | ".join(dict.fromkeys(_cifra(r, p).enlace for p in r.oferta.page_ids))
        if _varias_paginas(r) else r.enlace,
    )


_MEDIDAS = ("total", "activos", "c7", "c8", "nuevos", "parados", "alcance_ue")


def _fusionar(previa: snapshots.Snapshot | None, nueva: snapshots.Snapshot) -> snapshots.Snapshot:
    """Misma oferta, país y día: nunca se pierde una cifra medida. Por campo gana la última medida;
    un NULL nuevo deja el valor anterior. ``fuente`` junta los enlaces de los que salen las cifras."""
    if previa is None:
        return nueva
    valores = {c: getattr(nueva, c) if getattr(nueva, c) is not None else getattr(previa, c) for c in _MEDIDAS}
    aporta = any(getattr(nueva, c) is not None for c in _MEDIDAS)
    queda = any(getattr(previa, c) is not None and getattr(nueva, c) is None for c in _MEDIDAS)
    if not aporta:
        fuente = previa.fuente
    elif queda and previa.fuente != nueva.fuente:
        fuente = f"{nueva.fuente} | {previa.fuente}"
    else:
        fuente = nueva.fuente
    fuente = " | ".join(dict.fromkeys(x.strip() for x in fuente.split(" | ") if x.strip()))
    return replace(nueva, **valores, fuente=fuente)


def escribir(vault: Path, e: Ejecucion) -> list[Path]:
    vault = Path(vault)
    dia = e.dia.isoformat()
    rs = [r if r.dia is not None else replace(r, dia=e.dia) for r in e.resultados]
    e = replace(e, resultados=rs)
    rutas: list[Path] = []

    raw = _libre(vault / "raw" / dia / f"caza-{e.region}.md")
    frontmatter.escribir(raw, {"tipo": "raw", "fecha": dia, "fuente": "trovefy caza (Biblioteca de anuncios)",
                               "region": e.region, "modo": e.modo}, _render_raw(e))
    rutas.append(raw)

    # Como raw/: una segunda ejecución del día en la misma región nunca pisa el informe anterior.
    informe = _libre(vault / "wiki/caza" / dia / f"{e.region}.md")
    fuentes = sorted({r.enlace for r in rs} | {c.enlace for c in e.consultas})
    frontmatter.escribir(informe, {"tipo": "caza", "fecha": dia, "fuente": fuentes or "sin búsquedas",
                                   "region": e.region, "modo": e.modo, "perfil": e.perfil}, render_informe(e))
    rutas.append(informe)

    veredicto = vault / "wiki/caza" / dia / "veredicto.md"
    if not veredicto.exists():
        frontmatter.escribir(
            veredicto,
            {"tipo": "veredicto", "fecha": dia, "fuente": "usuario (cita literal)", "decision": "pendiente"},
            f"# Veredicto de la caza del {dia}\n\nDecisión del usuario: pendiente\n\n"
            "Escribe aquí, con tus palabras, qué oferta quieres modelar y por qué. Trovefy no decide por ti.\n",
        )
        rutas.append(veredicto)

    indice: list[tuple[str, str, str]] = [
        ("Caza", f"[[wiki/caza/{dia}/{informe.stem}]]", f"caza del {dia} ({e.region})"
         + ("" if informe.stem == e.region else f", ejecución {informe.stem.rsplit('-', 1)[1]} del día")),
        ("Caza", f"[[wiki/caza/{dia}/veredicto]]", f"veredicto del {dia}: la decisión del usuario"),
    ]
    por_oferta: dict[str, list[ResultadoOferta]] = {}
    for r in rs:
        if _ficha_escrita(r):
            por_oferta.setdefault(r.oferta.oferta_id, []).append(r)
    for oid, grupo in por_oferta.items():  # una ficha por oferta, con todos sus países
        ruta = vault / "wiki/ofertas" / f"{oid}.md"
        previa, cuerpo_previo = frontmatter.leer(ruta) if ruta.exists() else (None, None)
        meta, cuerpo = render_ficha(grupo, previa, cuerpo_previo)
        if e.modo == "vigilar":
            meta["vigilada"] = dia  # gasta el turno del día de la vigilancia (no lo gastan nicho/barrido)
        frontmatter.escribir(ruta, meta, cuerpo)
        rutas.append(ruta)
        mejor = mejor_pais(meta["paises"])
        indice.append(("Ofertas", f"[[wiki/ofertas/{oid}]]", f"{meta['estado']} · {mejor} · {dia}"))

    for ruta, nombre in _competidores(vault, rs, dia):
        rutas.append(ruta)
        indice.append(("Competidores", f"[[wiki/competidores/{ruta.stem}]]", nombre or f"página {ruta.stem}"))

    if _entidades(vault, rs):
        rutas.append(vault / "wiki/entidades.md")

    db = vault / "data/caza/snapshots.sqlite"
    conn = snapshots.abrir(db)
    try:
        for r in rs:
            if not _ficha_escrita(r):  # ya visto: sus señales no se midieron en esta ejecución
                continue
            nueva = _snapshot(r, e.dia)
            previa = next((x for x in snapshots.historial(conn, nueva.oferta_id, nueva.pais, e.dia)
                           if x.dia == e.dia), None)
            snapshots.guardar(conn, _fusionar(previa, nueva))
    finally:
        conn.close()
    rutas.append(db)

    datos = vault / "data/caza"
    _anadir_csv(
        datos / "historico.csv",
        ["fecha", "region", "modo", "oferta_id", "pais", "decision", "motivo", "nota", "enlace"],
        [[dia, e.region, e.modo, r.oferta.oferta_id, r.pais, r.decision, r.explicacion,
          None if r.nota.valor is None else round(r.nota.valor, 2), r.enlace] for r in _juzgados(rs)],
    )
    (_, _, ts), (_, _, tm) = _tasas(e)
    cuenta = {k: sum(1 for r in _juzgados(rs) if r.decision == k) for k in _ESTADOS}
    _anadir_csv(
        datos / "tasas.csv",
        ["fecha", "region", "modo", "candidatos", "A", "B", "observar", "descartadas", "pendientes",
         "busquedas", "bloqueos", "vacios", "tasa_senal", "tasa_modelo", "creditos_firecrawl"],
        [[dia, e.region, e.modo, len(_juzgados(rs)) + e.pendientes, cuenta["A"], cuenta["B"], cuenta["observar"],
          cuenta["descartada"], e.pendientes, e.busquedas, e.bloqueos, e.vacios, ts, tm, e.creditos]],
    )
    _anadir_csv(
        datos / "palabras.csv",
        ["palabra", "pais", "resultados", "candidatos", "modelables", "fecha", "region", "enlace"],
        [[c.palabra, c.pais, c.resultados, *_rinde(c, e), dia, e.region, c.enlace] for c in e.consultas],
    )
    rutas += [datos / "historico.csv", datos / "tasas.csv", datos / "palabras.csv"]

    anadir_al_indice(vault, indice)
    rutas.append(vault / "index.md")

    anadir_log(
        vault, "cazar",
        f"caza {e.region} ({e.modo}): A {cuenta['A']}, B {cuenta['B']}, observar {cuenta['observar']}, "
        f"descartadas {cuenta['descartada']}; búsquedas {e.busquedas}, bloqueos {e.bloqueos}",
        [p.relative_to(vault).as_posix() for p in rutas],
    )
    return rutas
