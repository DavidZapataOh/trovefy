"""Recomendación de límites y propuestas ``limite_ejecutor`` / ``limite_cuenta`` (solo propone; no ejecuta).

Importes de la caja en centavos de USD; las propuestas, en unidades mínimas de la moneda de la cuenta
(``meta.json``). Dato ausente = «no medido: <motivo>», nunca 0 ni estimación.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from trovefy_ejecutor.dinero import Moneda, formatear

from trovefy.aprobaciones.fuentes import Lectura
from trovefy.caja.calculo import EstadoCaja
from trovefy.caja.config import ConfigCaja
from trovefy.trm import FUENTE, Trm, usd_centavos_a_cop
from trovefy.vault.escritura import ZONA_NEGOCIO

_USD = Moneda("USD", 100)
_SOLO_COP = "no medido: el límite de la cuenta solo se propone en COP hasta confirmar la unidad (P-21)"


@dataclass(frozen=True)
class Recomendacion:
    tope_diario: int | None
    limite_cuenta_restante: int | None
    motivos: tuple[str, ...]
    huecos: int | None = None


def recomendar(estado: EstadoCaja, config: ConfigCaja) -> Recomendacion:
    motivos = list(estado.motivos)
    tope: int | None = None
    if estado.huecos is None:
        motivos.append("no medido: huecos de test (gasto de los tests sin medir)")
    else:
        tope = config.diario_test * min(2, estado.vivos + estado.huecos)
        if config.reserva_desbloqueada:
            tope += config.diario_prescala
        tope = min(config.tope_diario_ejecutor, tope)
        if tope <= 0:
            tope = None
            motivos.append("sin tests ni reserva: no se propone un tope de 0")
    r_tests, comprometido, r_reserva = estado.restante["tests"], estado.comprometido, estado.restante["reserva"]
    restante: int | None = None
    if r_tests is not None and comprometido is not None:
        restante = r_tests + comprometido
        if config.reserva_desbloqueada:
            restante = None if r_reserva is None else restante + r_reserva
    return Recomendacion(tope, restante, tuple(motivos), estado.huecos)


def _entero(v: object) -> int | None:
    return v if type(v) is int else None


_META_VIGENCIA = timedelta(hours=24)
_DESFASE = timedelta(minutes=5)  # reloj del ejecutor algo adelantado


def _fecha_meta(v: object, ahora: datetime) -> tuple[datetime | None, str]:
    """(fecha si meta.json tiene ≤ 24 h, texto de la fecha para mostrar)."""
    try:
        f = datetime.fromisoformat(str(v)) if isinstance(v, str) else None
    except ValueError:
        f = None
    if f is None or f.tzinfo is None:
        return None, "— (sin fecha válida)"
    texto = f"{f.astimezone(ZONA_NEGOCIO):%Y-%m-%d %H:%M}"
    edad = ahora - f
    return (f if -_DESFASE <= edad <= _META_VIGENCIA else None), texto


def propuestas_de_limites(
    rec: Recomendacion, config: ConfigCaja, trm: Trm | None, hoy: date, limites: Lectura, meta: Lectura,
    ahora: datetime | None = None,
) -> tuple[list[dict], list[str]]:
    """Dicts sin ``id``/``creada`` (los asigna el buzón) y la lista de «no medido»."""
    nm: list[str] = list(rec.motivos) if (rec.tope_diario is None or rec.limite_cuenta_restante is None) else []
    act = config.cuenta.id
    if act is None:
        return [], [*nm, "no medido: falta la cuenta en config/caja.yaml"]
    m = meta.datos if meta.datos is not None else {}
    moneda_c, offset = m.get("currency"), m.get("offset")
    if type(offset) is not int or not isinstance(moneda_c, str) or m.get("cuenta") != act:
        return [], [*nm, "no medido: moneda de la cuenta sin confirmar (paso 13, comprobar-meta)"]
    try:
        moneda = Moneda(moneda_c, offset)
    except ValueError:
        return [], [*nm, "no medido: moneda de la cuenta sin confirmar (paso 13, comprobar-meta)"]
    if moneda_c == "COP":
        if trm is None:
            return [], [*nm, f"no medido: sin TRM del {hoy}"]

        def unidades(c: int) -> int:
            return int(usd_centavos_a_cop(c, trm)) * offset
    elif moneda_c == "USD" and offset == 100:
        def unidades(c: int) -> int:
            return c
    else:
        return [], [*nm, f"no medido: la caja no convierte USD a {moneda_c}"]

    etiqueta = trm.etiqueta(hoy) if trm is not None else "sin conversión (cuenta en USD)"
    evidencia: dict = {"fuente": FUENTE if trm is not None else "cuenta en USD"}
    if trm is not None:
        evidencia.update(trm=trm.etiqueta(hoy), trm_fecha=trm.desde.isoformat())
    else:
        evidencia.update(trm="sin TRM (cuenta en USD)", trm_fecha=hoy.isoformat())
    if rec.huecos is not None:
        evidencia["huecos"] = rec.huecos

    def texto(c: int, u: int) -> str:
        return f"{formatear(c, _USD)} ≈ {formatear(u, moneda)}"

    def base(tipo: str, motivo: str, op: dict) -> dict:
        return {"tipo": tipo, "origen": "/caja", "prioridad": "normal", "cuenta": act,
                "motivo": f"{motivo} ({etiqueta})", "evidencia": dict(evidencia), "operaciones": [op]}

    props: list[dict] = []
    if ahora is None:
        ahora = datetime.combine(hoy, time.max, ZONA_NEGOCIO)

    # -- limite_ejecutor: tope diario total ---------------------------------------------------------
    viva = None
    offset_lim: object = None
    if limites.datos is None:
        nm.append(limites.motivo or "no medido: limites.json sin leer")
    else:
        cuenta_l = (limites.datos.get("cuentas") or {}).get(act)
        if isinstance(cuenta_l, dict):
            offset_lim = cuenta_l.get("offset")
        if not isinstance(cuenta_l, dict):
            nm.append("no medido: la cuenta no figura en limites.json")
        elif cuenta_l.get("moneda") != moneda_c or cuenta_l.get("offset") != offset:
            nm.append(f"no medido: la moneda de limites.json ({cuenta_l.get('moneda')}) no coincide con "
                      f"meta.json ({moneda_c}, offset {offset})")
        else:
            viva = _entero(cuenta_l.get("tope_gasto_diario_total"))
            if viva is None:
                nm.append("no medido: limites.json sin tope_gasto_diario_total vivo")
    if rec.tope_diario is not None and viva is not None:
        a = unidades(rec.tope_diario)
        if a > 0 and a != viva:
            props.append(base(
                "limite_ejecutor",
                f"Tope diario total recomendado {texto(rec.tope_diario, a)} (hoy {formatear(viva, moneda)})",
                {"entidad": "ejecutor", "id": act, "campo": "tope_gasto_diario_total", "de_esperado": viva,
                 "a": a, "unidad": "minima", "moneda": moneda_c}))

    # -- limite_cuenta: spend_cap de Meta, acumulado ------------------------------------------------
    fecha_meta, fecha_txt = _fecha_meta(m.get("fecha"), ahora)
    if offset != 1:
        nm.append(_SOLO_COP)
    elif type(offset_lim) is not int or offset_lim != offset:
        nm.append(f"no medido: el límite de la cuenta necesita limites.json con el mismo offset que meta.json "
                  f"({offset}); limites.json dice {offset_lim if offset_lim is not None else '—'}")
    elif fecha_meta is None:
        nm.append(f"no medido: gasto acumulado de la cuenta del {fecha_txt} "
                  "(repite trovefy-ejecutor comprobar-meta)")
    else:
        gastado = _entero(m.get("amount_spent"))
        if gastado is None:
            nm.append("no medido: el ejecutor aún no informa el gasto acumulado de la cuenta")
        elif rec.limite_cuenta_restante is not None:
            actual = _entero(m.get("spend_cap")) or None  # 0 = sin límite
            restante = rec.limite_cuenta_restante
            sobregasto = restante < 0
            a = gastado if sobregasto else gastado + unidades(restante)
            if a <= 0:
                nm.append("no medido: sobregasto sin gasto acumulado; no se puede fijar un límite de 0")
            elif a != actual:
                if sobregasto:
                    motivo = ("Sobregasto: los sobres no tienen saldo; el límite se fija en lo ya gastado y la "
                              f"cuenta deja de gastar (gastado {formatear(gastado, moneda)}, restante "
                              f"{formatear(restante, _USD)})")
                else:
                    motivo = (f"Límite de gasto de la cuenta: ya gastado {formatear(gastado, moneda)} + restante "
                              f"{texto(restante, a - gastado)} = {formatear(a, moneda)}")
                motivo += f"; gasto acumulado de la cuenta del {fecha_txt}"
                p = base(
                    "limite_cuenta", motivo,
                    {"entidad": "account", "id": act, "campo": "spend_cap", "de_esperado": actual,
                     "a": a, "unidad": "minima", "moneda": moneda_c})
                p["evidencia"]["meta_fecha"] = m.get("fecha")
                props.append(p)
    return props, nm
