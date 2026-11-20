"""Subcomando `trovefy cierre` (plan 24): las 3 cifras del bot a las 23:30 y a las 08:30, ledgers y criterio de la fase.

Orden: ``preparar`` dice qué día se cierra y **las llamadas de lectura exactas** que hace Claude por el MCP, con la ruta
donde guardar cada respuesta cruda (``~/.cache/trovefy/cierre/<día>/``, fuera del vault) → ``calcular`` las interpreta,
hace *upsert* de los ledgers, calcula, escribe ``wiki/analisis/cierres/<día>.md`` y deposita el mensaje del bot como
``alerta``. ``tiendas``, ``esquema`` y ``prueba`` preparan ``config/cierre.yaml`` y el esquema P-20; ``ver`` imprime el
informe guardado; ``criterio`` da el veredicto del criterio de salida de la fase 3.

Esta CLI **nunca** llama a un MCP ni a Meta. Salida: 0 bien (aunque haya «—») · 1 falta una lectura obligatoria (o el
criterio no pasa) · 2 error de uso.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trovefy.cierre import SKILL, VENTANA_DIAS, ZONA_CUENTA_POR_DEFECTO, carpeta_cache
from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO

_MAX_BYTES = 8 << 20
MARGEN_MANANA = timedelta(hours=2)


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _mod(nombre: str):
    return getattr(sys.modules[__name__], nombre)


def _reloj(args) -> datetime:
    if getattr(args, "ahora", None):
        a = datetime.fromisoformat(args.ahora)
        if a.tzinfo is None:
            raise ValueError("--ahora sin zona horaria (p. ej. 2026-11-20T08:30:00-05:00)")
        return a.astimezone(ZONA_NEGOCIO)
    return _mod("_ahora")()


def _vault() -> Path:
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _trm(vault: Path, dia: date):
    from trovefy import trm

    return trm.trm_del_dia(vault, dia)


def _cambio(vault: Path, dia: date):
    from trovefy import fx

    return fx.cambio_del_dia(vault, dia)


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _dia(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ValueError(f"--dia no es una fecha AAAA-MM-DD: {texto!r}") from None


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", required=True, metavar="<acción>")
    p = sub.add_parser("preparar", help="qué día se cierra y qué lecturas hacer (solo lectura), con dónde guardarlas")
    p.add_argument("--dia", help="día a cerrar AAAA-MM-DD (por defecto, ayer en la zona de la cuenta)")
    p.add_argument("--noche", action="store_true", help="corte provisional de las 23:30: el día en curso")
    p.add_argument("--ahora", help="hora de referencia ISO con zona (pruebas)")
    t = sub.add_parser("tiendas", help="empareja las tiendas de Impultienda con su producto-país (config/cierre.yaml)")
    t.add_argument("--instantanea", type=Path, required=True, help="respuesta guardada de impultienda_listar_tiendas")
    e = sub.add_parser("esquema", help="guarda el esquema de pedidos de Impultienda (P-20)")
    e.add_argument("--instantanea", type=Path, required=True, help="respuesta guardada de impultienda_listar_ventas")
    e.add_argument("--ahora", help="hora de referencia ISO con zona (pruebas)")
    pr = sub.add_parser("prueba", help="apunta la compra de prueba (no cuenta como venta), con tus palabras")
    pr.add_argument("--tienda", required=True, help="store_id de la tienda")
    pr.add_argument("--orden", required=True, help="número de orden de la compra de prueba")
    pr.add_argument("--fuente", required=True, help="tus palabras y la fecha («usuario, 2026-11-20: «…»»)")
    c = sub.add_parser("calcular", help="ledgers, cálculo, página del cierre y mensaje del bot")
    c.add_argument("--dia", required=True, help="día a cerrar AAAA-MM-DD (el que dijo `preparar`)")
    c.add_argument("--noche", action="store_true", help="corte provisional de las 23:30")
    c.add_argument("--rutina", action="store_true", help="sin preguntas; deja el log de la rutina")
    c.add_argument("--sin-alerta", action="store_true", help="no deposita el mensaje en el buzón")
    c.add_argument("--export", type=Path, help="respaldo sin MCP: archivo de ventas exportado de tu panel")
    c.add_argument("--tienda", help="store_id al que corresponde --export (si hay varias tiendas)")
    c.add_argument("--ahora", help="hora de referencia ISO con zona (pruebas)")
    v = sub.add_parser("ver", help="imprime el informe guardado de un día")
    v.add_argument("--dia", help="AAAA-MM-DD (por defecto, el último cierre)")
    k = sub.add_parser("criterio", help="criterio de salida de la fase 3 (auditoría + registro de actividad de Meta)")
    k.add_argument("--desde", help="ignora activaciones anteriores a este día AAAA-MM-DD")
    k.add_argument("--actividad", type=Path, help="respuesta guardada de ads_account_get_activity_logs")
    k.add_argument("--ahora", help="hora de referencia ISO con zona (pruebas)")


# --- comunes ------------------------------------------------------------------------------------------------------


def _leer_json(ruta: Path) -> dict:
    ruta = Path(ruta).expanduser()
    if ruta.is_symlink() or not ruta.is_file():
        raise FileNotFoundError(f"no existe {ruta}")
    if ruta.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{ruta.name} es demasiado grande")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, (dict, list)):
        raise ValueError(f"{ruta.name} no es un objeto JSON")  # noqa: TRY004 - dato de un archivo
    return datos if isinstance(datos, dict) else {"data": datos}


def _cuenta(vault: Path) -> str | None:
    from trovefy.caja.config import cargar_caja

    try:
        return cargar_caja(vault).cuenta.id
    except Exception:  # noqa: BLE001 - sin caja no hay cuenta: se dice, no se cae
        return None


def _zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(ZONA_CUENTA_POR_DEFECTO)


def _ventana(dia: date) -> list[date]:
    return [dia - timedelta(days=i) for i in range(VENTANA_DIAS - 1, -1, -1)]


def _corto(store_id: str) -> str:
    return store_id.replace("-", "")[:8]


# --- preparar -----------------------------------------------------------------------------------------------------


def _preparar(args) -> int:
    from trovefy.aprobaciones.fuentes import enmascarar_cuentas
    from trovefy.cierre.tiendas import tiendas_de
    from trovefy.economia.comisiones import comisiones
    from trovefy.economia.config import cargar_economia

    vault, ahora = _vault(), _reloj(args)
    local = ahora.astimezone(_zona(ZONA_CUENTA_POR_DEFECTO))
    if args.dia:
        dia = _dia(args.dia)
    elif args.noche:
        dia = local.date()
    else:
        dia = (local - timedelta(days=1)).date()
        if local - local.replace(hour=0, minute=0, second=0, microsecond=0) < MARGEN_MANANA:
            print("Aviso: aún no pasaron 2 h desde que cerró el día de Meta; las cifras de ayer pueden moverse.")
    cuenta = _cuenta(vault)
    cache = f"~/.cache/trovefy/cierre/{dia.isoformat()}"
    print(f"Cierre del {dia:%d/%m/%Y} ({'provisional, hasta las 23:30' if args.noche else 'día cerrado'}) · "
          f"zona de la cuenta {ZONA_CUENTA_POR_DEFECTO} (la confirma ads_get_ad_accounts)")
    print(enmascarar_cuentas(f"Cuenta: {cuenta or '— (falta en config/caja.yaml: `trovefy caja iniciar`)'}"))
    try:
        tiendas = tiendas_de(vault)
    except (OSError, ValueError) as exc:
        return _error(exc)
    v = _ventana(dia)
    print(f"Relectura: {v[0].isoformat()} a {v[-1].isoformat()} (7 días: Meta y la tienda corrigen días pasados).")
    print(f"Guarda cada respuesta tal cual (0600) en {cache}/ y luego `trovefy cierre calcular --dia {dia.isoformat()}"
          f"{' --noche' if args.noche else ''}`. Solo estas lecturas; nada con requires_user_confirmation:")
    print(f"  {cache}/cuentas.json  ← ads_get_ad_accounts (moneda y timezone_name de la cuenta)")
    for d in v:
        print(f"  {cache}/meta-{d.isoformat()}.json  ← ads_get_ad_entities nivel campaign de la cuenta, todas las "
              f"campañas (sin filtrar por estado), time_range {d.isoformat()}..{d.isoformat()}, campos amount_spent, "
              "omni_purchase, omni_purchase_values")
    if not tiendas:
        print(f"  {cache}/tiendas.json  ← impultienda_listar_tiendas; después "
              f"`trovefy cierre tiendas --instantanea {cache}/tiendas.json` y vuelve a `preparar`")
    for t in tiendas:
        print(f"  {cache}/ventas-{_corto(t.store_id)}-p1.json  ← impultienda_listar_ventas store_id {t.store_id} "
              f"({t.producto} {t.pais}), desde {v[0].isoformat()} hasta {v[-1].isoformat()}, limit 200, offset 0; "
              f"si has_more, la siguiente página (next_offset) en ventas-{_corto(t.store_id)}-p2.json, p3…")
        print(f"  {cache}/utm-{_corto(t.store_id)}.json  ← (opcional) impultienda_campanas_utm store_id "
              f"{t.store_id}, desde {dia.isoformat()} hasta {dia.isoformat()}, nivel campana")
    try:
        c = comisiones(cargar_economia(vault))
    except Exception:  # noqa: BLE001 - economía ilegible: el neto saldrá «—»
        c = ["falta config/economia.yaml legible"]
    if isinstance(c, list):
        print(f"Aviso: sin comisiones fijadas ({'; '.join(c)}): el neto y la ganancia saldrán «—». "
              "Las fija el usuario (paso 0 de `/trovefy:leer`).")
    return 0


# --- tiendas / esquema / prueba ------------------------------------------------------------------------------------


def _tiendas(args) -> int:
    from trovefy.cierre.tiendas import emparejar_tiendas, escribir_tiendas
    from trovefy.vault.escritura import anadir_log

    vault = _vault()
    try:
        tiendas, avisos = emparejar_tiendas(_leer_json(args.instantanea), vault)
        ruta = escribir_tiendas(vault, tiendas) if tiendas else None
    except (OSError, ValueError) as exc:
        return _error(exc)
    for t in tiendas:
        print(f"Tienda {t.url or t.store_id} → {t.producto} {t.pais}")
    for a in avisos:
        print(f"Aviso: {a}")
    if ruta:
        anadir_log(vault, SKILL, f"tiendas del cierre ({len(tiendas)})", ["config/cierre.yaml"])
        print(f"Escrito: {ruta.relative_to(vault).as_posix()}")
    return 0 if tiendas else 1


def _esquema(args) -> int:
    from trovefy.cierre.tiendas import escribir_esquema, esquema_pedidos, validar_ventas
    from trovefy.vault.escritura import anadir_log

    vault, ahora = _vault(), _reloj(args)
    try:
        inst = _leer_json(args.instantanea)
        difs = validar_ventas(inst)
        ruta = escribir_esquema(vault, esquema_pedidos(inst), ahora.date())
    except (OSError, ValueError) as exc:
        return _error(exc)
    anadir_log(vault, SKILL, "esquema de pedidos de Impultienda (P-20)", [ruta.relative_to(vault).as_posix()],
               ahora=ahora)
    print(f"Escrito: {ruta.relative_to(vault).as_posix()}")
    for d in difs:
        print(f"Aviso: {d}")
    return 0


def _prueba(args) -> int:
    from trovefy.cierre.tiendas import registrar_prueba
    from trovefy.vault.escritura import anadir_log

    vault = _vault()
    try:
        ruta = registrar_prueba(vault, args.tienda.strip(), args.orden.strip(), args.fuente.strip())
    except (OSError, ValueError) as exc:
        return _error(exc)
    anadir_log(vault, SKILL, "compra de prueba apuntada (no cuenta como venta)", ["config/cierre.yaml"])
    print(f"Compra de prueba apuntada en {ruta.relative_to(vault).as_posix()}: no contará como venta.")
    return 0


# --- calcular -----------------------------------------------------------------------------------------------------


def _leido(ruta: Path, herramienta: str) -> dict:
    return {"herramienta": herramienta, "archivo": ruta.name,
            "leido": datetime.fromtimestamp(ruta.stat().st_mtime, ZONA_NEGOCIO).isoformat(timespec="minutes")}


def _caja_y_fijos(vault: Path, dia: date) -> tuple[str | None, str | None]:
    from decimal import Decimal

    from trovefy.caja.calculo import calcular
    from trovefy.caja.config import cargar_caja
    from trovefy.caja.gasto import gastos_de_tests
    from trovefy.caja.movimientos import leer_movimientos
    from trovefy.caja.salida import linea_informe

    try:
        cfg = cargar_caja(vault)
        movs = leer_movimientos(vault)
        linea = linea_informe(calcular(cfg, movs, gastos_de_tests(vault, cfg, lambda d: _mod("_trm")(vault, d))))
    except Exception:  # noqa: BLE001 - la caja no tumba el cierre: se dice
        return "no medido: no se pudo leer la caja (`trovefy caja ver`)", None
    mes = [m for m in movs if m.tipo == "herramienta" and m.fecha.astimezone(ZONA_NEGOCIO).strftime("%Y-%m") ==
           dia.strftime("%Y-%m")]
    fijos = f"{Decimal(sum(m.usd_centavos for m in mes)) / 100:.2f} USD en herramientas ({len(mes)} anotaciones)"
    return linea, fijos


def _movimientos(vault: Path) -> list[str]:
    from trovefy.aprobaciones.listado import grupo_de, listar

    try:
        filas, _ = listar(vault)
    except Exception:  # noqa: BLE001
        return ["no medido: no se pudieron leer las propuestas"]
    return [f"{f.id} {f.tipo} pendiente de tu Aceptar" for f in filas if grupo_de(f.estado) == "pendientes"
            and f.tipo not in ("alerta", "noop")]


def _calcular(args) -> int:
    from trovefy.aprobaciones.fuentes import (
        BuzonNoDisponible,
        depositar,
        enmascarar_cuentas,
    )
    from trovefy.cierre.calculo import calcular_cierre, contraste_utm
    from trovefy.cierre.lectura import todas_las_ventas
    from trovefy.cierre.ledger import upsert_gasto, upsert_ventas
    from trovefy.cierre.plataforma import LecturaVentas, leer_export, leer_ventas
    from trovefy.cierre.salida import alerta_de, escribir_cierre, informe
    from trovefy.cierre.tiendas import (
        cargar_esquema,
        pedidos_de_prueba,
        tiendas_de,
        validar_ventas,
    )
    from trovefy.economia.comisiones import comisiones
    from trovefy.economia.config import cargar_economia
    from trovefy.meta.insights import FORMA_DESCONOCIDA, leer_cuenta, leer_insights
    from trovefy.vault.escritura import anadir_log

    vault, ahora = _vault(), _reloj(args)
    dia = _dia(args.dia)
    momento = "noche" if args.noche else "manana"
    cache = carpeta_cache(dia.isoformat())
    faltan: list[str] = []
    fuentes: list[dict] = []
    cuenta = _cuenta(vault) or "sin-cuenta"

    zona_cuenta = ZONA_CUENTA_POR_DEFECTO
    ruta_c = cache / "cuentas.json"
    if ruta_c.is_file():
        try:
            leida = leer_cuenta(_leer_json(ruta_c), cuenta)
        except (OSError, ValueError) as exc:
            return _error(exc)
        fuentes.append(_leido(ruta_c, "ads_get_ad_accounts"))
        if leida:
            zona_cuenta = leida.zona

    filas, meta_completa, motivo_gasto = [], True, None
    for d in _ventana(dia):
        ruta = cache / f"meta-{d.isoformat()}.json"
        if not ruta.is_file():
            if d == dia:
                meta_completa, motivo_gasto = False, f"no medido: falta la lectura de Meta del {d:%d/%m}"
                faltan.append(f"meta-{d.isoformat()}.json")
            continue
        try:
            leidas, motivos = leer_insights(_leer_json(ruta), "campaign")
        except (OSError, ValueError) as exc:
            return _error(exc)
        fuentes.append(_leido(ruta, "ads_get_ad_entities"))
        if FORMA_DESCONOCIDA in motivos and d == dia:
            meta_completa, motivo_gasto = False, FORMA_DESCONOCIDA
        filas += [replace(f, fecha=f.fecha or d) for f in leidas if f.nivel == "campana" and (f.fecha or d) == d]
    try:
        tiendas = tiendas_de(vault)
    except (OSError, ValueError) as exc:
        return _error(exc)
    lecturas: list[LecturaVentas] = []
    if args.export:
        if len(tiendas) != 1 and not args.tienda:
            return _error("hay varias tiendas: di a cuál corresponde el archivo con --tienda")
        t = next((x for x in tiendas if x.store_id == args.tienda), None) if args.tienda else \
            (tiendas[0] if tiendas else None)
        if t is None:
            return _error("no conozco esa tienda: `trovefy cierre tiendas` primero")
        lecturas.append(leer_export(args.export, t, pedidos_de_prueba(vault, t.store_id)))
        fuentes.append({"herramienta": "archivo exportado del panel (respaldo)", "archivo": args.export.name,
                        "leido": ahora.isoformat(timespec="minutes")})
    else:
        esquema = cargar_esquema(vault)
        for t in tiendas:
            paginas = sorted(cache.glob(f"ventas-{_corto(t.store_id)}-p*.json"))
            if not paginas:
                faltan.append(f"ventas-{_corto(t.store_id)}-p1.json")
                lecturas.append(LecturaVentas([], None, None, False, [
                    f"no medido: falta la lectura de ventas de {t.producto} {t.pais}"], tienda=t.store_id))
                continue
            try:
                insts = [_leer_json(p) for p in paginas]
            except (OSError, ValueError) as exc:
                return _error(exc)
            fuentes += [_leido(p, "impultienda_listar_ventas") for p in paginas]
            difs = [d for inst in insts for d in validar_ventas(inst, esquema)]
            lec = leer_ventas(insts, t, pedidos_de_prueba(vault, t.store_id))
            if difs:
                lec = replace(lec, completa=False, motivos=[*lec.motivos, *(f"no medido: {d}" for d in difs)])
            lecturas.append(lec)
    if not tiendas and not args.export:
        faltan.append("config/cierre.yaml (tiendas)")
    if faltan and not args.rutina:
        return _error(f"falta la lectura obligatoria: {', '.join(faltan)} en {cache}. Hazla con `trovefy cierre "
                      f"preparar --dia {dia.isoformat()}`", 1)

    try:
        upsert_gasto(vault, filas, cuenta)
        for lec in lecturas:
            upsert_ventas(vault, lec, ahora)
        ventas_hist = todas_las_ventas(vault)
    except (OSError, ValueError) as exc:
        return _error(exc)
    ventas = [v for lec in lecturas for v in lec.ventas]
    ventas_completa = bool(lecturas) and all(lec.completa for lec in lecturas)
    motivo_ventas = next((m for lec in lecturas for m in lec.motivos), None) or (
        None if lecturas else "no medido: faltan las tiendas del cierre (`trovefy cierre tiendas`)")
    zonas_tienda = {lec.zona for lec in lecturas if lec.zona}
    zona_tienda = next(iter(zonas_tienda)) if len(zonas_tienda) == 1 else (
        ", ".join(sorted(zonas_tienda)) or None)
    desaparecidas = [v for v in ventas_hist if v.estado == "desaparecida" and v.detectada == dia]
    try:
        com = comisiones(cargar_economia(vault))
    except Exception:  # noqa: BLE001 - economía ilegible: neto «—»
        com = ["falta config/economia.yaml legible"]
    monedas = {f.moneda for f in filas if f.moneda} | {v.moneda for v in ventas}
    trm = _mod("_trm")(vault, dia) if "COP" in monedas else None
    cambio = _mod("_cambio")(vault, dia) if monedas - {"USD", "COP"} else None
    mercado = {}
    try:
        from trovefy.caja.config import cargar_caja

        mercado = {t.campana_id: f"{t.producto} {t.pais}" for t in cargar_caja(vault).tests if t.campana_id}
    except Exception:  # noqa: BLE001, S110 - sin caja, las campañas quedan «sin-asignar»
        pass
    cierre = calcular_cierre(dia, filas, ventas, desaparecidas, com, trm, cambio, zona_cuenta, zona_tienda,
                             meta_completa=meta_completa, ventas_completa=ventas_completa,
                             fuente_ventas="export" if args.export else "mcp", motivo_gasto=motivo_gasto,
                             motivo_ventas=motivo_ventas, mercado_de_campana=mercado)
    contraste = None
    for t in tiendas:
        ruta_u = cache / f"utm-{_corto(t.store_id)}.json"
        if ruta_u.is_file():
            try:
                contraste = contraste_utm(cierre, _leer_json(ruta_u)) or contraste
                fuentes.append(_leido(ruta_u, "impultienda_campanas_utm"))
            except (OSError, ValueError):
                contraste = "no medido: no se pudo leer el tablero de la tienda"
    movimientos = _movimientos(vault) if momento == "noche" else []
    texto = informe(cierre, momento, movimientos)
    alerta_id, bloqueo = None, None
    if args.sin_alerta:
        bloqueo = "no se depositó (--sin-alerta)"
    else:
        try:
            alerta_id = depositar(vault, alerta_de(cierre, texto, momento), lambda: ahora)
        except BuzonNoDisponible as exc:
            bloqueo = f"no se depositó: {exc}"
    caja, fijos = _caja_y_fijos(vault, dia)
    try:
        ruta = escribir_cierre(vault, cierre, texto, momento, ahora, alerta_id=alerta_id, fuentes=fuentes, caja=caja,
                               pendientes=_movimientos(vault), fijos_del_mes=fijos, contraste=contraste)
    except (OSError, ValueError) as exc:
        return _error(exc)
    rel = ruta.relative_to(vault).as_posix()
    archivos = [rel, *(f"ledger/gasto/{dia:%Y-%m}.csv",), "ledger/ventas/"]
    anadir_log(vault, SKILL, f"cierre del {dia.isoformat()} ({momento}, fiabilidad {cierre.fiabilidad})", archivos,
               ahora=ahora)
    print(enmascarar_cuentas(texto))
    print(f"Página: {rel} · fiabilidad {cierre.fiabilidad}")
    for m in cierre.anomalias + ([contraste] if contraste else []):
        print(f"Aviso: {m}")
    if alerta_id:
        print(f"Mensaje del bot depositado: {alerta_id}")
    if bloqueo:
        print(f"Mensaje del bot: {bloqueo}")
    if args.rutina:
        from trovefy.rutinas import registrar_ejecucion

        nota = f"; faltan lecturas: {', '.join(faltan)}" if faltan else ""
        registrar_ejecucion(vault, "cierre-noche" if args.noche else "cierre", ahora.date(),
                            f"{texto}\n\nFiabilidad {cierre.fiabilidad}{nota}" + (f"; {bloqueo}" if bloqueo else ""),
                            ok=not bloqueo or bool(args.sin_alerta), ahora=ahora)
    return 0


# --- ver / criterio -----------------------------------------------------------------------------------------------


def _ver(args) -> int:
    from trovefy.cierre.salida import leer_cierre

    vault = _vault()
    try:
        if args.dia:
            dia = _dia(args.dia)
        else:
            carpeta = vault / "wiki" / "analisis" / "cierres"
            paginas = sorted(carpeta.glob("????-??-??.md")) if carpeta.is_dir() else []
            if not paginas:
                return _error("aún no hay ningún cierre", 1)
            dia = date.fromisoformat(paginas[-1].stem)
        pagina = leer_cierre(vault, dia)
    except (OSError, ValueError) as exc:
        return _error(exc)
    if pagina is None:
        return _error(f"no hay cierre del {dia.isoformat()}", 1)
    meta, _ = pagina
    print(meta.get("informe") or "(sin informe)")
    print(f"Fiabilidad: {meta.get('fiabilidad', '—')}")
    return 0


def _criterio(args) -> int:
    from trovefy.cierre.criterio import comprobar, escribir_criterio
    from trovefy.vault.escritura import anadir_log

    vault, ahora = _vault(), _reloj(args)
    try:
        actividad = _leer_json(args.actividad) if args.actividad else None
        desde = _dia(args.desde) if args.desde else None
        v = comprobar(vault, ahora, actividad, desde)
        ruta = escribir_criterio(vault, v, ahora)
    except (OSError, ValueError) as exc:
        return _error(exc)
    rel = ruta.relative_to(vault).as_posix()
    anadir_log(vault, SKILL, f"criterio de la fase 3: {'pasa' if v.pasa else 'no pasa'}", [rel], ahora=ahora)
    print(f"Criterio de la fase 3: {'PASA' if v.pasa else 'NO PASA'}")
    if v.ventana:
        print(f"Ventana: {v.ventana[0]:%Y-%m-%d %H:%M} → {v.ventana[1]:%Y-%m-%d %H:%M}")
    print(f"Escrituras: {len(v.escrituras)} · sin Aceptar: {len(v.sin_aceptar)} · días sin cierre: "
          f"{len(v.dias_sin_cierre)} · cambios fuera de Trovefy: {len(v.fuera_de_trovefy)}")
    for m in v.motivos[:5]:
        print(f"  - {m}")
    print(f"Detalle: {rel}")
    return 0 if v.pasa else 1


_ACCIONES = {"preparar": _preparar, "tiendas": _tiendas, "esquema": _esquema, "prueba": _prueba,
             "calcular": _calcular, "ver": _ver, "criterio": _criterio}


def _ejecutar(args: argparse.Namespace) -> int:
    try:
        return _ACCIONES[args.accion](args)
    except ValueError as exc:  # --ahora o --dia mal escritos
        return _error(exc)


registrar("cierre", _configurar, _ejecutar, "cierre del día: Gasto Meta, Neto y Ganancia como el bot (plan 24)")
