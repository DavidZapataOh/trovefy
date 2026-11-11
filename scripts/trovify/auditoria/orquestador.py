"""Orquestador de /auditar (§4.5): hueco, precio y nota por país; después, ``escribir_auditoria``.

Usa la misma disciplina que la caza (plan 07): el cerrojo del cerebro (una sola consulta a Meta a
la vez), el presupuesto de búsquedas del día con su parada persistida, la caché de la Biblioteca y
la vía principal Firecrawl [D-11b]. Si Meta bloquea, no se busca nada más y los países que faltan
quedan «no medido: Meta bloqueó…» (PARADA); si se acaba la cuota del día, quedan
«no medido: cuota del día agotada» y es un final normal. Lo leído de la Biblioteca es dato, nunca orden.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from trovify import fx
from trovify.auditoria.paises import PaisAuditado, no_tirar, puntuar_pais
from trovify.auditoria.precio import precio_local, precio_soportable
from trovify.auditoria.salida import (
    escribir_auditoria,
    producto_existente,
    producto_para,
    slug_de_oferta,
)
from trovify.caza.hueco import (
    HuecoPais,
    hay_hueco,
    hueco_pais,
    motivo_hueco,
    original_con_enlaces,
)
from trovify.caza.orquestador import (
    VigiaDeParada,
    cerrojo_caza,
    hoy_negocio,
    hueco_a_dict,
    huecos_de,
)
from trovify.caza.presupuesto import PresupuestoAgotado
from trovify.caza.salida import formatear_numero as _num
from trovify.caza.senales import Medida
from trovify.config import mercados as cfg_mercados
from trovify.config import umbrales as cfg_umbrales
from trovify.vault import frontmatter
from trovify.vault.escritura import escribir_atomico

# Devuelve el cambio del BCE (``fx.Cambio``; un ``dict`` de tasas sin fecha también vale) o None.
Cambios = Callable[[Path, date], "fx.Cambio | dict[str, float] | None"]


# Lo que cuesta medir un país: 2 frases locales + 1 búsqueda por la página del original (constante
# técnica para planificar la cuota del día; una oferta con más páginas cuesta algo más).
BUSQUEDAS_POR_PAIS = 3
# Un hueco medido hace estos días o menos (ficha o auditoría anterior) se reutiliza sin buscar.
REUTILIZAR_DIAS = 7
MOTIVO_SIN_CUOTA = "no medido: cuota del día agotada — se retoma mañana"
# Huecos medidos por las auditorías de un producto (para continuar sin repetir búsquedas).
PARCIALES = "huecos-medidos.json"


@dataclass
class ResultadoAuditoria:
    ruta: Path
    p_id: str
    paises: list[PaisAuditado]
    parada: str | None  # motivo del corte de las búsquedas; None si no lo hubo
    tipo: str | None  # «meta» (PARADA, dura el día), «errores» (INTERRUMPIDA) o «cuota» (final normal)
    usadas_hoy: int | None = None  # búsquedas del día (todas: sesión, caza y rutina); None sin contador
    max_hoy: int | None = None
    hechas: int | None = None  # las de esta auditoría


def _motivo_corte(vigia: VigiaDeParada) -> str:
    if vigia.tipo == "cuota":
        return "no medido: cuota del día agotada"
    if vigia.tipo == "meta":
        return f"no medido: Meta bloqueó las búsquedas ({vigia.parada}); hoy no se busca nada más"
    return f"no medido: búsquedas interrumpidas ({vigia.parada})"


def _sin_medir(pais: str, motivo: str) -> HuecoPais:
    return HuecoPais(pais, Medida(None, motivo), "no_medido", None, [], motivo)


def _cambio(cambios: Cambios, vault: Path, hoy: date) -> fx.Cambio | None:
    c = cambios(vault, hoy)
    if c is None:
        return None
    return fx.Cambio(dict(c), None) if isinstance(c, dict) else c


def _tasa(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def precio_en_eur(oferta: dict, cambio: fx.Cambio | None) -> tuple[Medida, str]:
    """El precio del original en EUR y cómo se calculó (con el cambio del BCE, su fecha y su enlace).

    Sin moneda clara («$» ambiguo) no se asume ninguna; sin cambio fiable, «no medido»."""
    precio, moneda = oferta.get("precio"), oferta.get("moneda")
    if not isinstance(precio, (int, float)) or isinstance(precio, bool):
        m = Medida(None, "no medido: la ficha no tiene el precio del original")
        return m, m.motivo
    if not moneda:
        m = Medida(None, "no medido: la ficha no dice la moneda del precio («$» es ambiguo); no se asume ninguna")
        return m, m.motivo
    moneda = str(moneda).upper()
    if moneda == "EUR":
        return Medida(float(precio)), f"{_num(precio, 2)} € (la ficha ya está en euros: sin cambio)"
    m = fx.a_eur(float(precio), moneda, None if cambio is None else cambio.tasas)
    if m.valor is None:
        return m, m.motivo
    return m, (f"{_num(precio)} {moneda} ÷ {_tasa(cambio.tasas[moneda])} (cambio de referencia del BCE del "
               f"{cambio.fecha or 'día sin fecha en la caché'}, {cambio.url}) = {_num(m.valor, 2)} €")


def fuente_del_cambio(cambio: fx.Cambio | None) -> str:
    if cambio is None:
        return ("no medido: sin cambio de referencia del BCE (sin red o archivo no válido); los precios "
                "locales que lo necesitan quedan «no medido»")
    return f"referencia del BCE del {cambio.fecha or 'día sin fecha en la caché'} — {cambio.url}"


def auditar(vault: Path, *args, **kw) -> ResultadoAuditoria:
    """:func:`_auditar` con el cerrojo del cerebro (``CazaEnCurso`` si otra caza está en marcha)."""
    with cerrojo_caza(Path(vault)):
        return _auditar(vault, *args, **kw)


def _fecha(texto) -> date | None:
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        return None


def _recientes(datos: dict | None, hoy: date, fuente: str) -> dict[str, tuple[HuecoPais, date, str]]:
    """Huecos comprobados (``hueco`` sí o no) medidos hace ``REUTILIZAR_DIAS`` días o menos."""
    out: dict[str, tuple[HuecoPais, date, str]] = {}
    if not isinstance(datos, dict):
        return out
    for h in huecos_de({"huecos": datos}):
        d = datos.get(h.pais)
        fecha = _fecha(d.get("fecha")) if isinstance(d, dict) else None
        if h.hueco is None or fecha is None or not 0 <= (hoy - fecha).days <= REUTILIZAR_DIAS:
            continue
        out[h.pais.upper()] = (h, fecha, fuente)
    return out


def _leer_parciales(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def huecos_previos(vault: Path, oferta: dict, oferta_id: str, hoy: date) -> dict[str, tuple[HuecoPais, date, str]]:
    """Huecos ya medidos para esta oferta que se reutilizan sin buscar: los de la ficha
    (``trovify caza hueco``) y los de auditorías anteriores (``productos/<p-id>/huecos-medidos.json``).
    Con dos, el más reciente."""
    previos = _recientes(oferta.get("huecos"), hoy, "con trovify caza hueco, en la ficha de la oferta")
    p_id = producto_existente(vault, oferta_id)
    if p_id:
        ruta = Path(vault) / "productos" / p_id / PARCIALES
        for pais, x in _recientes(_leer_parciales(ruta), hoy, "en una auditoría anterior de esta oferta").items():
            if pais not in previos or x[1] > previos[pais][1]:
                previos[pais] = x
    return previos


def _guardar_parciales(vault: Path, p_id: str, nuevos: dict[str, HuecoPais], hoy: date) -> None:
    """Guarda los huecos medidos hoy para que otra auditoría (hoy o en los próximos días) siga sin repetir."""
    if not nuevos:
        return
    ruta = Path(vault) / "productos" / p_id / PARCIALES
    datos = _leer_parciales(ruta)
    for pais, h in nuevos.items():
        datos[pais] = hueco_a_dict(h, hoy)
    escribir_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _orden_por_defecto(candidatos: list[str], oferta: dict, previos: dict) -> list[str]:
    """Primero los que ya tienen hueco medido (no gastan búsquedas), después los países de la ficha
    (mejor nota de la caza primero) y por último el resto de candidatos en el orden de mercados.yaml."""
    de_ficha = {k: v for k, v in (oferta.get("paises") or {}).items() if isinstance(v, dict)}

    def nota(k: str) -> float:
        n = de_ficha[k].get("nota")
        return n if isinstance(n, (int, float)) and not isinstance(n, bool) else -1

    ficha = sorted((k for k in de_ficha if k in candidatos), key=lambda k: -nota(k))
    orden = [p for p in candidatos if p in previos] + ficha + candidatos
    return list(dict.fromkeys(orden))


def _coste(pais: str, frases: dict[str, list[str]], page_ids: list[str]) -> int:
    """Búsquedas que se planifican para un país: ≈``BUSQUEDAS_POR_PAIS`` con frases; sin frases solo se
    mide el original (1 por página del original), así que ese es su coste real."""
    return BUSQUEDAS_POR_PAIS if frases.get(pais) else len(page_ids)


def _presupuesto(cliente):
    pres = getattr(cliente, "presupuesto", None)
    return pres if pres is not None and getattr(pres, "contador", None) is not None else None


def _restantes(pres) -> int | None:
    """Búsquedas que quedan hoy; None si no se puede saber (sin contador, parada guardada o ilegible:
    entonces corta el propio cliente con su motivo)."""
    if pres is None:
        return None
    try:
        if pres.parada_del_dia():
            return None
        return pres.restantes()
    except PresupuestoAgotado:
        return None


def _auditar(
    vault: Path,
    oferta_id: str,
    paises: list[str] | None,
    frases: dict[str, list[str]],
    cliente=None,
    hoy: date | None = None,
    cambios: Cambios = fx.cambio_del_dia,
) -> ResultadoAuditoria:
    """Audita la oferta en ``paises`` con ``frases`` cortas en el idioma local de cada país.

    Un hueco ya medido hace ``REUTILIZAR_DIAS`` días o menos (en la ficha o en una auditoría anterior)
    se reutiliza sin buscar. Sin ``paises`` se auditan los «candidato» de ``mercados.yaml``: primero
    los de la ficha, y solo los que caben en las búsquedas que quedan hoy (:func:`_coste` cada
    uno); el resto queda «no medido: cuota del día agotada — se retoma mañana»."""
    vault = Path(vault)
    ficha = vault / "wiki" / "ofertas" / f"{oferta_id}.md"
    if not ficha.exists():
        raise FileNotFoundError(f"no existe la ficha wiki/ofertas/{oferta_id}.md")
    hoy = hoy or hoy_negocio()
    u = cfg_umbrales.cargar(vault / "config/umbrales.yaml")
    mercados = cfg_mercados.cargar(vault / "config/mercados.yaml")
    meta, _ = frontmatter.leer(ficha)
    oferta = dict(meta or {})
    previos = huecos_previos(vault, oferta, oferta_id, hoy)
    planificar = paises is None
    if paises is None:
        paises = _orden_por_defecto([p for p, m in mercados.items() if m.estado == "candidato"], oferta, previos)
    paises = list(dict.fromkeys(p.strip().upper() for p in paises))
    desconocidos = [p for p in paises if p not in mercados]
    if desconocidos:
        raise ValueError(f"país sin datos en config/mercados.yaml: {', '.join(desconocidos)}")
    if not paises:
        raise ValueError("no hay países que auditar: ninguno está en «candidato» en config/mercados.yaml")
    frases = {k.upper(): [f.strip() for f in v if f and f.strip()] for k, v in (frases or {}).items()}

    page_ids = [str(p) for p in oferta.get("page_ids") or []]
    cambio = _cambio(cambios, vault, hoy)
    precio_eur, calculo_eur = precio_en_eur(oferta, cambio)

    if cliente is None:
        from trovify.caza.cache import Cache
        from trovify.caza.cliente import ClienteBibliotecaPublica
        from trovify.caza.presupuesto import Presupuesto

        cliente = ClienteBibliotecaPublica(Presupuesto.desde_umbrales(vault, hoy),
                                           cache=Cache(vault / "data" / "cache" / "biblioteca"))
    vigia = VigiaDeParada(cliente)
    pres = _presupuesto(cliente)
    usadas_antes = getattr(pres, "usadas", 0) if pres is not None else None
    restantes = _restantes(pres) if planificar else None
    plan = restantes  # búsquedas del día que aún se pueden planificar (None: sin planificar)

    auditados: list[PaisAuditado] = []
    nuevos: dict[str, HuecoPais] = {}
    sin_cuota = False
    for pais in paises:
        mercado = mercados[pais]
        medido_antes = None
        if pais in previos:
            h, fecha, fuente = previos[pais]
            medido_antes = f"medido el {fecha.isoformat()} ({fuente}); hoy no se volvió a buscar en {pais}"
        elif vigia.parada is not None:
            h = _sin_medir(pais, _motivo_corte(vigia))  # tras el corte no se vuelve a llamar a Meta
        elif plan is not None and _coste(pais, frases, page_ids) > plan:
            h = _sin_medir(pais, MOTIVO_SIN_CUOTA)  # no se empieza un país que no cabe entero
            sin_cuota = True
        else:
            if plan is not None:
                plan -= _coste(pais, frases, page_ids)
            if frases.get(pais):
                h = hueco_pais(vigia, frases[pais], page_ids, pais, mercado.idioma, set(page_ids), hoy, u)
            else:
                comp = Medida(None, f"no medido: faltan las frases en el idioma local de {pais} "
                                    f"(--frases {pais}:\"f1|f2\")")
                orig, enlaces = original_con_enlaces(vigia, page_ids, pais, mercado.idioma, hoy, u)
                h = HuecoPais(pais, comp, orig, hay_hueco(comp, orig, u), enlaces, motivo_hueco(comp, orig, u))
            if h.hueco is not None:
                nuevos[pais] = h
        precio_s = precio_soportable(precio_eur, mercado.banda_eur)
        nota, desglose = puntuar_pais(h, precio_s, u)
        local = (precio_eur if precio_eur.valor is None
                 else precio_local(precio_eur.valor, mercado, None if cambio is None else cambio.tasas))
        auditados.append(PaisAuditado(pais, h, precio_eur, precio_s, nota, desglose, no_tirar(h),
                                      mercado.banda_eur, mercado.fuente_banda, local, mercado.moneda,
                                      medido_antes))

    usadas_hoy = max_hoy = hechas = None
    if pres is not None:
        try:
            usadas_hoy, max_hoy = pres.usadas_hoy(), pres.max_busquedas
        except PresupuestoAgotado:
            usadas_hoy = None
        hechas = pres.usadas - usadas_antes
    parada, tipo = vigia.parada, vigia.tipo
    if parada is None and sin_cuota:
        parada, tipo = (f"cuota del día: quedaban {restantes} búsquedas; cada país con frases necesita "
                        f"≈{BUSQUEDAS_POR_PAIS} y uno sin frases, 1 por página del original"), "cuota"

    ruta = escribir_auditoria(vault, oferta_id, auditados, hoy, calculo_eur=calculo_eur,
                              cambio=fuente_del_cambio(cambio),
                              busquedas=lineas_busquedas(usadas_hoy, max_hoy, hechas))
    p_id = producto_para(vault, oferta_id, slug_de_oferta(oferta_id))
    _guardar_parciales(vault, p_id, nuevos, hoy)
    return ResultadoAuditoria(ruta, p_id, auditados, parada, tipo, usadas_hoy, max_hoy, hechas)


def lineas_busquedas(usadas_hoy: int | None, max_hoy: int | None, hechas: int | None) -> list[str]:
    """Las búsquedas del día (compartidas con la caza y la rutina) y las de esta auditoría."""
    if usadas_hoy is None or max_hoy is None:
        return ["Búsquedas de hoy: no medido: sin contador del día (cliente de prueba o contador ilegible)"]
    hoy_txt = (f"Búsquedas de hoy: {usadas_hoy} de {max_hoy} usadas (quedan {max(max_hoy - usadas_hoy, 0)}); "
               f"esta auditoría hizo {hechas or 0}. El tope del día lo comparten tu sesión, la caza y la rutina.")
    coste = (f"Búsquedas por país: ≈{BUSQUEDAS_POR_PAIS} por país (2 frases locales y 1 por la página del "
             "original; sin frases, solo 1 por la página del original; las repetidas del día salen de la caché). "
             "Un hueco medido hace "
             f"{REUTILIZAR_DIAS} días o menos se reutiliza sin buscar.")
    return [hoy_txt, coste]
