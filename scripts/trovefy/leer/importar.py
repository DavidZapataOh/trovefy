"""Instantáneas de Meta y de la tienda → lectura normalizada en USD (plan 23, Tarea 2).

**Qué hacen los vídeos:** la lectura es por conjunto con gasto, ROAS, CPM, CTR, CPC, visitas y pagos iniciados (C1
54:20); se cruzan las ventas reales con el gasto, anuncio por anuncio: «se guía por ventas reales, no por el píxel» (E2).

Claude guarda en ``~/.cache/trovefy/leer/<p-id>/<PAIS>/`` la respuesta cruda de cada lectura; aquí entran como
``dict`` con estas claves (todas opcionales; lo que falte queda «no medido»):

- ``meta-adset`` y ``meta-ad``: ``ads_get_ad_entities`` nivel conjunto y anuncio, de ``t0`` al día leído;
- ``meta-dia``: nivel conjunto, solo el día leído (hoy en la ronda intradía, para el surf);
- ``utm-campana`` y ``utm-anuncio``: ``impultienda_campanas_utm`` nivel campaña y anuncio, de ``t0`` al día leído;
- ``utm-dia``: nivel anuncio, solo el día leído;
- ``carritos``: ``impultienda_carritos_abandonados`` (``abandono_real``), de ``t0`` al día leído.

La campaña se empareja por el id que va detrás del ``|`` de ``utm_campaign`` y el anuncio por el de ``utm_content``
(resolución 17), nunca por el nombre. El gasto en COP pasa a centavos de USD **al alza** con la TRM del día del gasto
(base común 5); sin TRM, «no medido». Los ingresos de la tienda pasan a USD **a la baja** con el cambio del BCE.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path

from trovefy.leer.modelo import (
    Dia,
    LecturaConjunto,
    LecturaOferta,
    Metricas,
    a_dict,
    lectura_de_dict,
)
from trovefy.meta.insights import FilaInsight, leer_insights
from trovefy.trm import Trm, cop_a_usd_centavos

TrmDe = Callable[[date], "Trm | None"]
CambioDe = Callable[[date], object]  # trovefy.fx.Cambio | None
CLAVES = ("meta-adset", "meta-ad", "meta-dia", "utm-campana", "utm-anuncio", "utm-dia", "carritos")


def importar_meta(datos: dict | None, nivel: str) -> tuple[list[FilaInsight], list[str]]:
    """Envoltorio fino de `trovefy.meta.insights.leer_insights` (resolución 16)."""
    if datos is None:
        return [], [f"no medido: sin lectura de Meta nivel {nivel}"]
    return leer_insights(datos, nivel)


def _sufijo(texto: object) -> str | None:
    if not isinstance(texto, str) or "|" not in texto:
        return None
    return texto.rsplit("|", 1)[1].strip() or None


def _dec(v: object) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _contenido(datos: object) -> dict:
    if isinstance(datos, dict) and isinstance(datos.get("structuredContent"), dict):
        return datos["structuredContent"]
    return datos if isinstance(datos, dict) else {}


@dataclass(frozen=True)
class UtmLeido:
    ventas: int | None
    bruto: Decimal | None  # en ``moneda``
    moneda: str | None
    por_anuncio: dict[str, tuple[int, Decimal]] = field(default_factory=dict)  # ad_id → (ventas, ingresos)
    zona: str | None = None
    motivos: tuple[str, ...] = ()


def importar_utm(datos: dict | None, campana_id: str) -> UtmLeido:
    """Ventas aprobadas y su bruto **de esta campaña** (por el id de ``utm_campaign``), en la moneda de la tienda."""
    if datos is None:
        return UtmLeido(None, None, None, motivos=("no medido: sin lectura de la tienda (impultienda_campanas_utm)",))
    c = _contenido(datos)
    zona = (c.get("periodo") or {}).get("timezone") if isinstance(c.get("periodo"), dict) else None
    utm = c.get("utm")
    if not isinstance(utm, dict) or not isinstance(utm.get("filas"), list):
        return UtmLeido(None, None, None, zona=zona,
                        motivos=("no medido: forma de impultienda_campanas_utm desconocida",))
    moneda = utm.get("moneda")
    if not isinstance(moneda, str):
        return UtmLeido(None, None, None, zona=zona,
                        motivos=("no medido: la tienda devuelve ingresos sin una sola moneda",))
    motivos = []
    if utm.get("fx_incompleto"):
        motivos.append("no medido: la tienda no pudo convertir todos los ingresos a su moneda (fx_incompleto)")
    ventas, bruto, por_anuncio = 0, Decimal(0), {}
    for f in utm["filas"]:
        if not isinstance(f, dict) or _sufijo(f.get("utm_campaign")) != str(campana_id):
            continue
        n = f.get("ventas")
        ing = _dec(f.get("ingresos"))
        if type(n) is not int or ing is None:
            motivos.append("no medido: fila de la tienda sin ventas o ingresos")
            continue
        ventas += n
        bruto += ing
        ad = _sufijo(f.get("anuncio"))
        if ad:
            v0, b0 = por_anuncio.get(ad, (0, Decimal(0)))
            por_anuncio[ad] = (v0 + n, b0 + ing)
    if utm.get("filas_omitidas"):
        motivos.append(f"no medido: la tienda omitió {utm['filas_omitidas']} filas (sube limit)")
    if any(m.startswith("no medido: fila") or "omitió" in m or "fx_incompleto" in m for m in motivos):
        return UtmLeido(None, None, moneda, por_anuncio, zona, tuple(motivos))
    return UtmLeido(ventas, bruto, moneda, por_anuncio, zona, tuple(motivos))


def importar_carritos(datos: dict | None, campana_id: str) -> tuple[int | None, int | None, str | None, str | None]:
    """(sesiones que vieron el checkout, intentos rechazados, zona, motivo) de esta campaña."""
    if datos is None:
        return None, None, None, "no medido: sin lectura de carritos (impultienda_carritos_abandonados)"
    c = _contenido(datos)
    zona = (c.get("periodo") or {}).get("timezone") if isinstance(c.get("periodo"), dict) else None
    ar = c.get("abandono_real")
    if not isinstance(ar, dict) or not isinstance(ar.get("por_origen"), list):
        return None, None, zona, "no medido: la tienda no pudo leer las visitas del checkout (abandono_real)"
    ses = fal = 0
    for o in ar["por_origen"]:
        if isinstance(o, dict) and _sufijo(o.get("utm_campaign")) == str(campana_id):
            ses += int(o.get("sesiones_checkout") or 0)
            fal += int(o.get("intentos_fallidos") or 0)
    motivo = None
    if ar.get("origenes_omitidos"):
        motivo = f"aviso: la tienda omitió {ar['origenes_omitidos']} orígenes en abandono_real"
    return ses, fal, zona, motivo


def a_usd_tienda(importe: Decimal | None, moneda: str | None, cambio: object) -> Decimal | None:
    """Ingresos de la tienda → USD, a la baja al centavo, con el cambio del BCE (unidades por 1 EUR)."""
    if importe is None or moneda is None:
        return None
    if moneda == "USD":
        return importe
    tasas = getattr(cambio, "tasas", None)
    if not isinstance(tasas, dict) or "USD" not in tasas or (moneda != "EUR" and moneda not in tasas):
        return None
    por_eur = Decimal(1) if moneda == "EUR" else Decimal(str(tasas[moneda]))
    return (importe / por_eur * Decimal(str(tasas["USD"]))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def gasto_usd_c(filas: list[FilaInsight], dia: date, trm_de: TrmDe) -> tuple[int | None, Decimal | None, str | None,
                                                                            Trm | None]:
    """(centavos de USD al alza, gasto en la moneda de la cuenta, motivo, TRM usada). Cada fila con la TRM de su día
    (o del día leído si la fila no trae fecha)."""
    if not filas:
        return None, None, "no medido: sin filas de Meta", None
    total_c, total_m, usada = 0, Decimal(0), None
    for f in filas:
        if f.gasto is None:
            return None, None, "no medido: Meta no devolvió el gasto", None
        total_m += f.gasto
        moneda = (f.moneda or "").upper()
        if moneda == "USD":
            total_c += int((f.gasto * 100).to_integral_value(rounding=ROUND_CEILING))
            continue
        if moneda != "COP":
            return None, total_m, f"no medido: gasto en {moneda or 'moneda desconocida'} sin conversión", None
        d = f.fecha or dia
        trm = trm_de(d)
        if trm is None:
            return None, total_m, f"no medido: sin TRM del {d.isoformat()}", None
        usada = trm
        total_c += cop_a_usd_centavos(f.gasto, trm)
    return total_c, total_m, None, usada


def _suma(vals: list[int | None]) -> int | None:
    return None if not vals or any(v is None for v in vals) else sum(vals)


def _t0(trafico: dict) -> datetime | None:
    vals = []
    for k in ("activado", "inicio"):
        v = trafico.get(k)
        if isinstance(v, str):
            try:
                vals.append(datetime.fromisoformat(v))
            except ValueError:
                continue
    return max(vals) if vals else None


def construir_lectura(trafico: dict, p_id: str, pais: str, inst: dict[str, dict | None], ahora: datetime, dia: date,
                      *, intradia: bool, trm_de: TrmDe, cambio_de: CambioDe) -> LecturaOferta:
    """La lectura del producto-país. ``trafico`` es ``PRODUCTO.md → paises.<PAIS>.trafico`` del plan 22."""
    camp = str((trafico.get("campana") or {}).get("id") or "")
    if not camp:
        raise ValueError("no hay campaña registrada en paises.<PAIS>.trafico: primero `trovefy montar registrar`")
    motivos: list[str] = []
    adsets, m1 = importar_meta(inst.get("meta-adset"), "adset")
    ads, m2 = importar_meta(inst.get("meta-ad"), "ad")
    hoy_rows, m3 = (importar_meta(inst.get("meta-dia"), "adset") if inst.get("meta-dia") is not None
                    else ([], []))
    motivos += m1 + m2 + m3
    de_la_campana = lambda f: not f.campana_id or f.campana_id == camp
    adsets = [f for f in adsets if de_la_campana(f) and f.nivel == "conjunto"]
    ads = [f for f in ads if de_la_campana(f) and f.nivel == "anuncio"]
    hoy_rows = [f for f in hoy_rows if de_la_campana(f) and f.nivel == "conjunto"]
    utm = importar_utm(inst.get("utm-campana") or inst.get("utm-anuncio"), camp)
    utm_ad = importar_utm(inst.get("utm-anuncio"), camp) if inst.get("utm-anuncio") is not None else utm
    utm_dia = importar_utm(inst.get("utm-dia"), camp) if inst.get("utm-dia") is not None else None
    motivos += list(utm.motivos)
    ses, fal, zona_c, motivo_c = importar_carritos(inst.get("carritos"), camp)
    if motivo_c:
        motivos.append(motivo_c)
    cambio = cambio_de(dia) if utm.moneda not in (None, "USD") else None
    bruto = a_usd_tienda(utm.bruto, utm.moneda, cambio)
    if utm.bruto is not None and bruto is None:
        motivos.append(f"no medido: sin cambio del BCE para pasar {utm.moneda} a USD")

    nombres = {str(v): k for k, v in (trafico.get("conjuntos") or {}).items()}
    anuncios = {str(a.get("conjunto")): (str(a.get("id")), a.get("angulo"), n)
                for n, a in (trafico.get("anuncios") or {}).items() if isinstance(a, dict)}
    orden = list(nombres) + [f.id for f in adsets if f.id not in nombres]
    por_adset: dict[str, list[FilaInsight]] = {}
    for f in adsets:
        por_adset.setdefault(f.id, []).append(f)
    trm_usada = None
    conjuntos = []
    for sid in dict.fromkeys(orden):
        filas = por_adset.get(sid, [])
        ad_id, angulo, nombre_ad = anuncios.get(sid, (None, None, None))
        fila_ad = next((a for a in ads if a.conjunto_id == sid or (ad_id and a.id == ad_id)), None)
        ad_id = ad_id or (fila_ad.id if fila_ad else None)
        nombre = nombres.get(sid) or nombre_ad or (filas[0].nombre if filas else sid)
        if not filas:
            motivos.append(f"no medido: Meta no devolvió datos del conjunto {nombre}")
            met = Metricas(None, None, None, None, None, None, None, None)
        else:
            c, m, motivo, trm = gasto_usd_c(filas, dia, trm_de)
            trm_usada = trm or trm_usada
            if motivo:
                motivos.append(motivo)
            met = Metricas(c, m, filas[0].moneda, _suma([f.impresiones for f in filas]),
                           _suma([f.clics for f in filas]), _suma([f.visitas for f in filas]),
                           _suma([f.pagos_iniciados for f in filas]), _suma([f.compras_pixel for f in filas]))
        v_ad = utm_ad.por_anuncio.get(ad_id or "") if utm_ad.ventas is not None else None
        ventas = (v_ad[0] if v_ad else 0) if utm_ad.ventas is not None else None
        bruto_ad = a_usd_tienda(v_ad[1] if v_ad else Decimal(0), utm_ad.moneda, cambio) if ventas is not None else None
        hoy = None
        filas_hoy = [f for f in hoy_rows if f.id == sid]
        if filas_hoy or utm_dia is not None:
            gc = gasto_usd_c(filas_hoy, dia, trm_de)[0] if filas_hoy else None
            vd = utm_dia.por_anuncio.get(ad_id or "") if utm_dia and utm_dia.ventas is not None else None
            vh = (vd[0] if vd else 0) if utm_dia and utm_dia.ventas is not None else None
            bh = a_usd_tienda(vd[1] if vd else Decimal(0), utm_dia.moneda, cambio) if vh is not None else None
            hoy = Dia(gc, vh, bh)
        conjuntos.append(LecturaConjunto(
            adset_id=sid, ad_id=ad_id, nombre=nombre, angulo=angulo, estado_meta=filas[0].estado_meta if filas else None,
            metricas=met, ventas=ventas, bruto_usd=bruto_ad,
            presupuesto=next((f.presupuesto_diario for f in filas if f.presupuesto_diario), None),
            estado_anuncio=fila_ad.estado_meta if fila_ad else None, hoy=hoy))
    gasto = _suma([c.metricas.gasto_usd_c for c in conjuntos])
    ventas_pixel = _suma([c.metricas.compras_pixel for c in conjuntos])
    spend_cap = (trafico.get("spend_cap") or {}).get("minima")
    base = (trafico.get("diario_conjunto") or {}).get("minima")
    zona = utm.zona or zona_c
    return LecturaOferta(
        producto=p_id, pais=pais, campaign_id=camp, moneda=trafico.get("moneda") or (adsets[0].moneda if adsets else None),
        activacion=_t0(trafico), ahora=ahora, dia=dia, intradia=intradia, conjuntos=tuple(conjuntos),
        gasto_usd_c=gasto, ventas_tienda=utm.ventas, bruto_tienda_usd=bruto, ventas_pixel=ventas_pixel,
        pi_tienda=ses, intentos_fallidos=fal, ventas_dia=utm_dia.ventas if utm_dia else None,
        spend_cap=int(spend_cap) if isinstance(spend_cap, (int, str)) and str(spend_cap).isdigit() else None,
        base=int(base) if isinstance(base, (int, str)) and str(base).isdigit() else None,
        zona_tienda=zona, trm=trm_usada.etiqueta(dia) if trm_usada else None,
        motivos=tuple(dict.fromkeys(motivos)))


# --- disco -------------------------------------------------------------------------------------------------------


def carpeta_lecturas(vault: Path, p_id: str, pais: str) -> Path:
    from trovefy.vault.producto import ruta_producto

    return ruta_producto(vault, p_id).parent / "trafico" / pais / "lecturas"


def nombre_lectura(o: LecturaOferta) -> str:
    return f"{o.dia.isoformat()}T{o.ahora:%H%M}.json" if o.intradia else f"{o.dia.isoformat()}.json"


def guardar_lectura(vault: Path, o: LecturaOferta) -> Path:
    """Escribe la lectura normalizada (solo números, ids y nombres). Si aparece algo con forma de secreto no se
    escribe nada (``ValueError``); sin la revisión de secretos disponible, tampoco."""
    from trovefy.secretos import buscar_secreto
    from trovefy.vault.escritura import escribir_atomico

    texto = json.dumps(a_dict(o), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    nombre = buscar_secreto(texto)
    if nombre:
        raise ValueError(f"la lectura trae algo con forma de secreto ({nombre}): no se escribe")
    ruta = carpeta_lecturas(vault, o.producto, o.pais) / nombre_lectura(o)
    escribir_atomico(ruta, texto)
    return ruta


def cargar_lectura(ruta: Path) -> LecturaOferta:
    return lectura_de_dict(json.loads(Path(ruta).read_text(encoding="utf-8")))


def ultima_lectura(vault: Path, p_id: str, pais: str, *, dia: date | None = None,
                   intradia: bool | None = None) -> Path | None:
    """La lectura más reciente (del día ``dia`` si se da; solo diarias o solo intradía si se pide)."""
    carpeta = carpeta_lecturas(vault, p_id, pais)
    if not carpeta.is_dir():
        return None
    rutas = []
    for r in sorted(carpeta.glob("*.json")):
        es_intra = "T" in r.stem
        if intradia is not None and es_intra != intradia:
            continue
        if dia is not None and not r.stem.startswith(dia.isoformat()):
            continue
        rutas.append(r)
    return rutas[-1] if rutas else None


def ventas_por_dia(vault: Path, p_id: str, pais: str, hasta: date) -> dict[date, int]:
    """Ventas de la tienda de cada día cerrado ya leído (lecturas diarias), hasta ``hasta`` inclusive."""
    carpeta = carpeta_lecturas(vault, p_id, pais)
    salida: dict[date, int] = {}
    for r in sorted(carpeta.glob("????-??-??.json")) if carpeta.is_dir() else ():
        try:
            d = date.fromisoformat(r.stem)
            datos = json.loads(r.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d <= hasta and type(datos.get("ventas_dia")) is int:
            salida[d] = datos["ventas_dia"]
    return salida
