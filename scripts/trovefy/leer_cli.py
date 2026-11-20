"""Subcomando `trovefy leer` (plan 23): lectura, cortes y surf propuestos como en los vídeos.

Orden: Claude lee Meta y la tienda por los MCP (solo lectura) y guarda cada respuesta cruda en
``~/.cache/trovefy/leer/<p-id>/<PAIS>/`` (``trovefy leer preparar`` dice cuáles y con qué fechas) → ``importar`` las
normaliza en ``trafico/<PAIS>/lecturas/`` → ``parte`` (07:30, día cerrado), ``intradia`` (cada 2 h) o ``base``
(23:00 del país) aplican las reglas y **depositan propuestas** en el buzón. ``estado`` aplica lo que copió el
ejecutor; ``economia`` muestra lo que hace falta para el ROAS neto; ``completar`` añade al vault los umbrales nuevos.

Esta CLI **nunca** llama a un MCP ni a Meta: solo lee archivos y deposita por
``trovefy.aprobaciones.fuentes.depositar``. Salida: 0 sin propuestas · 1 con propuestas o alertas (o bloqueado) ·
2 error o dato imprescindible no medido.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO

_MAX_BYTES = 8 << 20
ORIGEN = {"parte": "/leer --parte", "intradia": "/leer --intradia", "base": "/leer --base"}


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _mod(nombre: str):
    return getattr(sys.modules[__name__], nombre)


def _reloj(args) -> datetime:
    if getattr(args, "ahora", None):
        a = datetime.fromisoformat(args.ahora)
        if a.tzinfo is None:
            raise ValueError("--ahora sin zona horaria (p. ej. 2026-11-20T07:30:00-05:00)")
        return a.astimezone(ZONA_NEGOCIO)
    return _mod("_ahora")()


def _trm(vault: Path, dia: date):
    from trovefy import trm

    return trm.trm_del_dia(vault, dia)


def _cambio(vault: Path, dia: date):
    from trovefy import fx

    return fx.cambio_del_dia(vault, dia)


def _limites(cuenta: str | None):
    from trovefy.aprobaciones.fuentes import leer_estado
    from trovefy.leer.surf import Limites

    lim = leer_estado("limites").datos or {}
    lc = ((lim.get("cuentas") or {}).get(cuenta) or {}) if isinstance(lim, dict) else {}
    maximo = lc.get("max_presupuesto_conjunto")
    paso = lim.get("paso_max_pct") if isinstance(lim, dict) else None
    return Limites(maximo if type(maximo) is int else None, paso if type(paso) is int else None)


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _vault() -> Path:
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _comunes(p: argparse.ArgumentParser, ahora: bool = True) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG…)")
    if ahora:
        p.add_argument("--ahora", help="hora de referencia ISO con zona (pruebas)")


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", required=True, metavar="<acción>")
    p = sub.add_parser("preparar", help="qué leer de Meta y de la tienda, con qué fechas y dónde guardarlo")
    _comunes(p)
    p.add_argument("--intradia", action="store_true", help="la ronda de hoy (por defecto, el día cerrado)")
    i = sub.add_parser("importar", help="normaliza las respuestas guardadas y escribe la lectura")
    _comunes(i)
    i.add_argument("--intradia", action="store_true", help="lectura de hoy (ronda intradía o base)")
    for clave, ayuda in (("meta-adset", "ads_get_ad_entities nivel conjunto, de t0 al día leído"),
                         ("meta-ad", "ads_get_ad_entities nivel anuncio, de t0 al día leído"),
                         ("meta-dia", "ads_get_ad_entities nivel conjunto, solo el día leído"),
                         ("utm-campana", "impultienda_campanas_utm nivel campana, de t0 al día leído"),
                         ("utm-anuncio", "impultienda_campanas_utm nivel anuncio, de t0 al día leído"),
                         ("utm-dia", "impultienda_campanas_utm nivel anuncio, solo el día leído"),
                         ("carritos", "impultienda_carritos_abandonados, de t0 al día leído")):
        i.add_argument(f"--{clave}", type=Path, help=ayuda)
    for nombre, ayuda in (("parte", "parte del día cerrado: reglas, fiabilidad, diagnóstico y propuestas"),
                          ("intradia", "ronda de cada 2 h: cortes por gasto y surf"),
                          ("base", "23:00 del país: todos los conjuntos a la base")):
        r = sub.add_parser(nombre, help=ayuda)
        _comunes(r)
        r.add_argument("--rutina", action="store_true", help="sin preguntas; deja el log de la rutina")
        r.add_argument("--seco", action="store_true", help="no deposita ni escribe: imprime lo que propondría")
    e = sub.add_parser("estado", help="aplica lo que copió el ejecutor y muestra el estado")
    _comunes(e)
    c = sub.add_parser("economia", help="CPA_BE, comisiones para el ROAS neto y corte de oferta")
    _comunes(c, ahora=False)
    sub.add_parser("completar", help="añade al config/umbrales.yaml del vault los umbrales nuevos (sin pisar nada)")


# --- comunes ------------------------------------------------------------------------------------------------------


def _bloque(vault: Path, p_id: str, pais: str) -> dict:
    from trovefy.montar.tanda import bloque_pais

    return bloque_pais(vault, p_id, pais)


def _dia_leido(ahora: datetime, intradia: bool) -> date:
    hoy = ahora.astimezone(ZONA_NEGOCIO).date()
    return hoy if intradia else hoy - timedelta(days=1)


def _comprobar_estado(bloque: dict) -> str | None:
    if bloque.get("estado") not in ("test", "candidato"):
        return f"/leer solo lee productos en test (este país está en {bloque.get('estado') or 'sin estado'})"
    if not ((bloque.get("trafico") or {}).get("campana") or {}).get("id"):
        return "no hay campaña registrada: `trovefy montar registrar --pendientes`"
    return None


def _leer_json(ruta: Path) -> dict:
    if ruta.is_symlink() or not ruta.is_file():
        raise ValueError(f"no existe {ruta}")
    if ruta.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{ruta.name} es demasiado grande")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, (dict, list)):
        raise ValueError(f"{ruta.name} no es un objeto JSON")  # noqa: TRY004 - dato de un archivo, no de tipos
    return datos if isinstance(datos, dict) else {"data": datos}


# --- preparar / importar ------------------------------------------------------------------------------------------


def _preparar(args) -> int:
    from trovefy.leer.importar import _t0

    vault, ahora, pais = _vault(), _reloj(args), args.pais.strip().upper()
    try:
        b = _bloque(vault, args.producto, pais)
    except (FileNotFoundError, ValueError) as exc:
        return _error(exc)
    problema = _comprobar_estado(b)
    if problema:
        return _error(problema)
    t = b["trafico"]
    t0 = _t0(t)
    dia = _dia_leido(ahora, args.intradia)
    desde = (t0.astimezone(ZONA_NEGOCIO).date() if t0 else dia).isoformat()
    cache = Path("~/.cache/trovefy/leer") / args.producto / pais
    marca = ahora.strftime("%Y%m%dT%H%M")
    camp = t["campana"]["id"]
    print(f"{args.producto} {pais}: campaña …{str(camp)[-4:]} · t0 {t0.isoformat() if t0 else '—'} · "
          f"día leído {dia.isoformat()} ({'hoy, ronda' if args.intradia else 'cerrado'})")
    print(f"Guarda cada respuesta cruda (0600) en {cache}/ y pásala a `trovefy leer importar`:")
    llamadas = [
        ("meta-adset", f"ads_get_ad_entities nivel adset de la campaña, object_state live, time_range {desde}..{dia}"),
        ("meta-ad", f"ads_get_ad_entities nivel ad de la campaña, object_state live, time_range {desde}..{dia}"),
        ("meta-dia", f"ads_get_ad_entities nivel adset, time_range {dia}..{dia}"),
        ("utm-campana", f"impultienda_campanas_utm nivel campana, desde {desde} hasta {dia}"),
        ("utm-anuncio", f"impultienda_campanas_utm nivel anuncio, desde {desde} hasta {dia}"),
        ("utm-dia", f"impultienda_campanas_utm nivel anuncio, desde {dia} hasta {dia}"),
        ("carritos", f"impultienda_carritos_abandonados, desde {desde} hasta {dia}"),
    ]
    for clave, que in llamadas:
        print(f"  --{clave} {cache}/{clave}-{marca}.json  ← {que}")
    print("Atribución: 7 días clic + 1 día visualización. Solo herramientas de lectura; nada con "
          "requires_user_confirmation.")
    return 0


def _importar(args) -> int:
    from trovefy.leer.importar import construir_lectura, guardar_lectura

    vault, ahora, pais = _vault(), _reloj(args), args.pais.strip().upper()
    try:
        b = _bloque(vault, args.producto, pais)
        problema = _comprobar_estado(b)
        if problema:
            return _error(problema)
        inst = {}
        for clave in ("meta-adset", "meta-ad", "meta-dia", "utm-campana", "utm-anuncio", "utm-dia", "carritos"):
            ruta = getattr(args, clave.replace("-", "_"))
            inst[clave] = _leer_json(Path(ruta).expanduser()) if ruta else None
        if inst["meta-adset"] is None:
            return _error("falta --meta-adset: sin el gasto de Meta no hay lectura")
        dia = _dia_leido(ahora, args.intradia)
        lectura = construir_lectura(b["trafico"], args.producto, pais, inst, ahora, dia, intradia=args.intradia,
                                    trm_de=lambda d: _mod("_trm")(vault, d),
                                    cambio_de=lambda d: _mod("_cambio")(vault, d))
        ruta = guardar_lectura(vault, lectura)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error(exc)
    print(f"Lectura guardada: {ruta.relative_to(vault).as_posix()}")
    for m in lectura.motivos:
        print(f"  {m}")
    return 0


# --- rondas -------------------------------------------------------------------------------------------------------


def _usd_de_minima(minima: int, moneda: str | None, trm) -> Decimal | None:
    if moneda == "USD":
        return (Decimal(minima) / 100).quantize(Decimal("0.01"))
    if moneda == "COP" and trm is not None:
        return (Decimal(minima) / trm.cop_por_usd).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    return None


def _ronda(args, modo: str) -> int:
    from trovefy.aprobaciones.fuentes import BuzonNoDisponible, depositar
    from trovefy.config.umbrales import UmbralFaltante
    from trovefy.leer import SKILL, cargar_umbrales, reglas
    from trovefy.leer import diagnostico as diag
    from trovefy.leer import estado as est
    from trovefy.leer import propuestas as prop
    from trovefy.leer.economia import leer_economia, neto_de, roas_neto
    from trovefy.leer.fiabilidad import evaluar
    from trovefy.leer.importar import cargar_lectura, ultima_lectura, ventas_por_dia
    from trovefy.leer.parte import Informe, escribir_parte, ruta_parte, seccion
    from trovefy.leer.surf import veredicto_surf, vuelta_a_la_base
    from trovefy.vault import frontmatter
    from trovefy.vault.escritura import anadir_log, escribir_atomico
    from trovefy.vault.producto import actualizar_producto, ruta_producto

    vault, ahora, pais, p_id = _vault(), _reloj(args), args.pais.strip().upper(), args.producto
    intradia = modo != "parte"
    try:
        b = _bloque(vault, p_id, pais)
    except (FileNotFoundError, ValueError) as exc:
        return _error(exc)
    problema = _comprobar_estado(b)
    if problema:
        return _error(problema)
    dia = _dia_leido(ahora, intradia)
    ruta_l = ultima_lectura(vault, p_id, pais, dia=dia, intradia=intradia)
    if ruta_l is None:
        return _error(f"no medido: falta la lectura de {dia.isoformat()}: `trovefy leer importar --producto {p_id} "
                      f"--pais {pais}{' --intradia' if intradia else ''} …`")
    try:
        o = cargar_lectura(ruta_l)
        u = cargar_umbrales(vault)
    except (OSError, ValueError, KeyError, UmbralFaltante) as exc:
        return _error(exc)
    trafico = b.get("trafico") or {}
    cuenta = trafico.get("cuenta")
    memoria = prop.cargar_memoria(vault, p_id, pais)
    resultados = [] if args.seco else est.aplicar_resultados(vault, p_id, pais, memoria, ahora)
    b = _bloque(vault, p_id, pais)
    if b.get("estado") not in ("test", "candidato"):
        print("\n".join(resultados) or f"{p_id} {pais}: ya no está en test")
        if not args.seco:
            prop.guardar_memoria(vault, p_id, pais, memoria)
        return 0
    e = leer_economia(vault, p_id, pais)
    try:
        tracking, _ = frontmatter.leer(ruta_producto(vault, p_id).parent / "checkout" / pais / "TRACKING.md")
    except (OSError, ValueError):
        tracking = {}
    try:
        fiab = evaluar(o, tracking, None, u)
        veredictos = [reglas.veredicto_conjunto(c, u, fiab.pi_fiable) for c in o.conjuntos]
        dias = sum(1 for v in ventas_por_dia(vault, p_id, pais, dia).values() if v > 0) if not intradia else 0
        estado_oferta, cortes, notas = reglas.veredicto_oferta(o, e, u, intradia, dias)
        if not cortes:
            c = reglas.cortes_conjuntos(o, u, fiab.pi_fiable)
            cortes = [c] if c else []
        surf, notas_surf = [], []
        if modo == "intradia" and not any(c.tipo == "pausar_campana" for c in cortes):
            lim = _limites(cuenta)
            vistas = memoria.get("surf", {}).get(dia.isoformat(), {})
            if all(c.hoy is None for c in o.conjuntos):
                notas_surf.append("surf no medido: falta la lectura de hoy (--meta-dia y --utm-dia)")
            for c in (x for x in o.conjuntos if x.hoy is not None):
                s, nota = veredicto_surf(c, int(vistas.get(c.adset_id, 0)), e, u, o.base, limites=lim,
                                         spend_cap=o.spend_cap)
                if s:
                    surf.append(s)
                if nota:
                    notas_surf.append(nota)
        elif modo == "base":
            surf = vuelta_a_la_base(o.conjuntos, o.base)
            if o.base is None:
                notas_surf.append("base no medida: falta trafico.diario_conjunto en PRODUCTO.md")
        hallazgos = diag.rechazados(o) + (diag.diagnosticar(o, fiab, u) if modo == "parte" else [])
    except UmbralFaltante as exc:
        return _error(f"{exc}: ejecuta `trovefy leer completar`")
    if not e.medida:
        notas.append(f"sin ROAS neto: {e.motivo}")

    origen = ORIGEN[modo]
    rel_parte = ruta_parte(vault, ahora.date()).relative_to(vault).as_posix()
    huella = {"ventas": o.ventas_tienda, "gasto_usd_c": o.gasto_usd_c}
    candidatas: list[tuple[str, dict, dict, str, dict | None]] = []  # (clave, datos, huella, tipo_mem, extra)
    for c in cortes:
        datos = prop.a_propuesta(c, o, fiab, cuenta, origen)
        candidatas.append((prop.clave(c.tipo, c.ids), datos, huella, c.tipo,
                           {"motivo": c.motivo, "parte": rel_parte}))
    if surf and cuenta:
        datos = prop.surf_a_propuesta(surf, o, fiab, cuenta, origen, base=modo == "base")
        trm = _mod("_trm")(vault, ahora.date())
        nuevos = {s.conjunto_id: s.a_minima for s in surf}
        total = sum(nuevos.get(c.adset_id, c.presupuesto or 0) for c in o.conjuntos
                    if (c.estado_meta or "").upper() == "ACTIVE")
        usd = _usd_de_minima(total, o.moneda, trm)
        k = prop.clave("base" if modo == "base" else "surf", [s.conjunto_id for s in surf])
        if modo == "base":
            k += f"|{dia.isoformat()}"
        h = {"ventas": sum((s.ventas_hoy or 0) for s in surf),
             "presupuesto": ",".join(f"{s.conjunto_id}:{s.de_minima}" for s in surf),
             **({"dia": dia.isoformat()} if modo == "base" else {})}
        candidatas.append((k, datos, h, "surf", {"a": nuevos, "diario_usd": str(usd) if usd is not None else None}))
    for hz in hallazgos:
        if hz.alerta:
            texto = f"{p_id} {pais}: {hz.texto}. Va a {hz.destino}; /leer no toca la campaña (R-014)."
            candidatas.append((f"alerta|{hz.etapa}|{hz.destino}",
                               prop.alerta(f"/leer: revisar {hz.destino}", texto, "aviso", origen),
                               {"dia": dia.isoformat()}, "alerta", None))
    if estado_oferta == "candidato":
        candidatas.append(("alerta|candidato|fase4",
                           prop.alerta("/leer: candidato", f"{p_id} {pais}: " + next(
                               (n for n in notas if n.startswith("candidato")), "candidato"), "info", origen),
                           {"dia": "candidato"}, "alerta", None))
    if not e.medida and args.rutina:
        candidatas.append(("alerta|economia|paso0",
                           prop.alerta("/leer: falta fijar la economía", f"{p_id} {pais}: {e.motivo}. Sin comisiones "
                                       "no hay ROAS neto ni surf; los cortes por gasto siguen.", "aviso", origen),
                           {"dia": dia.isoformat()}, "alerta", None))

    depositadas: list[str] = []
    bloqueo = None
    estado_de = est.estado_de(vault)
    for k, datos, h, tipo_mem, extra in candidatas:
        if not prop.debe_proponer(k, h, memoria, estado_de, ahora):
            continue
        resumen = datos.get("motivo") or datos.get("texto") or ""
        if args.seco:
            depositadas.append(f"(seco) {datos['tipo']}: {resumen}")
            continue
        if bloqueo:
            continue
        try:
            id_ = depositar(vault, datos, lambda: ahora)
        except BuzonNoDisponible as exc:
            bloqueo = str(exc)
            continue
        prop.anotar(memoria, k, id_, tipo_mem, h, ahora, datos.get("expira_en_min"), extra)
        depositadas.append(f"{id_}: {datos['tipo']} · {resumen}")
    if modo == "intradia":
        memoria.setdefault("surf", {})[dia.isoformat()] = {
            c.adset_id: max(c.hoy.ventas or 0, int(memoria.get("surf", {}).get(dia.isoformat(), {}).get(c.adset_id, 0)))
            for c in o.conjuntos if c.hoy is not None and c.hoy.ventas is not None}

    informe = Informe(o, fiab, e, veredictos, estado_oferta, notas, hallazgos, surf, notas_surf, depositadas,
                      diag.renovar(o, veredictos), resultados)
    titulo = (f"{p_id} · {pais} · día cerrado {dia.isoformat()}" if modo == "parte"
              else f"{p_id} · {pais} · {'ronda' if modo == 'intradia' else 'base'} {ahora:%H:%M}")
    texto = seccion(informe, u, titulo)
    if bloqueo:
        texto += f"\nNo se depositó nada: {bloqueo}\n"
    if args.seco:
        print(texto)
        return 1 if depositadas else 0

    ruta_p = escribir_parte(vault, ahora.date(), f"{p_id}:{pais}:{modo}", texto, ahora, anadir=intradia)
    evid_cand = [f"parte [[{rel_parte.removesuffix('.md')}]]",
                 next((n for n in notas if n.startswith("candidato")), "candidato")]
    if modo == "parte" and estado_oferta == "candidato" and est.pasar_a_candidato(vault, p_id, pais, evid_cand,
                                                                                    ahora):
        depositadas.append(f"{p_id} {pais} pasa a candidato (sin tocar la campaña)")
    apagados = [f"{c.nombre} ({c.angulo or 'ángulo —'})" for c in o.conjuntos
                if (c.estado_meta or "").upper() in ("PAUSED", "ADSET_PAUSED")]
    actualizar_producto(vault, p_id, {"paises": {pais: {"lectura": {
        "ultima": ahora.isoformat(timespec="seconds"), "dia": dia.isoformat(), "fiabilidad": fiab.nivel,
        "estado_oferta": estado_oferta, "anuncios_apagados": apagados,
        "parte": f"[[{rel_parte.removesuffix('.md')}]]"}}}}, [], SKILL, ahora, archivos_log=[rel_parte])
    ventana = f"{o.activacion.date().isoformat() if o.activacion else '—'}..{dia.isoformat()}"
    anuncios = []
    for c, v in zip(o.conjuntos, veredictos, strict=True):
        roas = roas_neto(neto_de(c.bruto_usd, c.ventas, e), c.metricas.gasto_usd_c)
        anuncios.append({"nombre": c.nombre, "ad_id": c.ad_id, "estado": v.estado,
                         "gasto": str(Decimal(c.metricas.gasto_usd_c) / 100) if c.metricas.gasto_usd_c is not None
                         else None, "ventas": c.ventas, "pi": c.metricas.pi_pixel if fiab.pi_fiable else None,
                         "roas_neto": str(roas) if roas is not None else None,
                         "ctr": str(c.metricas.ctr) if c.metricas.ctr is not None else None,
                         "hook_rate": None, "retencion": None, "ventana": ventana, "fiabilidad": fiab.nivel})
    escribir_atomico(ruta_producto(vault, p_id).parent / "trafico" / pais / "anuncios.json",
                     json.dumps(anuncios, ensure_ascii=False, indent=2) + "\n")
    if modo == "parte" and o.ventas_tienda is not None:
        from trovefy.caja.tests import actualizar_test

        try:
            actualizar_test(vault, o.campaign_id, ventas=o.ventas_tienda)
        except (KeyError, OSError, ValueError) as exc:
            print(f"aviso: no se actualizaron las ventas en config/caja.yaml ({exc})", file=sys.stderr)
    prop.guardar_memoria(vault, p_id, pais, memoria)
    anadir_log(vault, SKILL, f"{p_id} {pais}: {modo} ({len(depositadas)} propuesta(s), fiabilidad {fiab.nivel})",
               [rel_parte], ahora=ahora)
    print(texto)
    print(f"Parte: {ruta_p.relative_to(vault).as_posix()}")
    if args.rutina:
        from trovefy.rutinas import registrar_ejecucion

        registrar_ejecucion(vault, f"leer-{modo}-{pais.lower()}" if intradia else "leer-parte", ahora.date(),
                            f"{p_id} {pais}: {len(depositadas)} propuesta(s); fiabilidad {fiab.nivel}"
                            + (f"; no se depositó: {bloqueo}" if bloqueo else ""), ok=bloqueo is None, ahora=ahora)
    if bloqueo:
        print(f"No se depositó nada: {bloqueo}")
        return 1
    return 1 if depositadas else 0


def _parte(args) -> int:
    return _ronda(args, "parte")


def _intradia(args) -> int:
    return _ronda(args, "intradia")


def _base(args) -> int:
    return _ronda(args, "base")


def _estado(args) -> int:
    from trovefy.leer import estado as est
    from trovefy.leer import propuestas as prop

    vault, ahora, pais = _vault(), _reloj(args), args.pais.strip().upper()
    try:
        memoria = prop.cargar_memoria(vault, args.producto, pais)
        lineas = est.aplicar_resultados(vault, args.producto, pais, memoria, ahora)
        prop.guardar_memoria(vault, args.producto, pais, memoria)
        b = _bloque(vault, args.producto, pais)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error(exc)
    print(f"{args.producto} {pais}: estado {b.get('estado') or 'sin estado'}")
    lec = b.get("lectura") or {}
    if lec:
        print(f"  última lectura {lec.get('ultima', '—')} · fiabilidad {lec.get('fiabilidad', '—')} · "
              f"oferta {lec.get('estado_oferta', '—')}")
    pendientes = [p for p in memoria.get("propuestas", {}).values() if not p.get("aplicada")]
    print(f"  Pendiente: {len(pendientes)} propuesta(s) de /leer")
    for x in lineas:
        print(f"  {x}")
    return 0


def _economia(args) -> int:
    from trovefy.config.umbrales import UmbralFaltante
    from trovefy.leer import cargar_umbrales, num
    from trovefy.leer.economia import corte_oferta_usd, leer_economia

    vault, pais = _vault(), args.pais.strip().upper()
    try:
        e = leer_economia(vault, args.producto, pais)
        corte, fuente = corte_oferta_usd(cargar_umbrales(vault))
    except (OSError, ValueError, UmbralFaltante) as exc:
        return _error(exc)
    print(f"{args.producto} {pais}")
    print(f"  CPA_BE: {num(e.cpa_be_usd)} USD · AOV: {num(e.aov_usd)} USD")
    if e.medida:
        print(f"  Comisiones para el ROAS neto: {num(e.costes_pct * 100, 2)} % + {num(e.comision_fija_usd)} USD por cobro")
    else:
        print(f"  Comisiones: {e.motivo}")
    print(f"  Corte de oferta sin ventas: US$ {num(corte, 0)} ({fuente})")
    return 0 if e.medida else 1


def _completar(_args) -> int:
    from trovefy.config.umbrales import completar

    vault = _vault()
    try:
        lineas = completar(vault)
    except (OSError, ValueError) as exc:
        return _error(exc)
    print("\n".join(lineas) or "Nada que añadir: el vault ya tiene todos los umbrales de la plantilla.")
    return 0


_ACCIONES = {"preparar": _preparar, "importar": _importar, "parte": _parte, "intradia": _intradia, "base": _base,
             "estado": _estado, "economia": _economia, "completar": _completar}


def _ejecutar(args: argparse.Namespace) -> int:
    try:
        return _ACCIONES[args.accion](args)
    except ValueError as exc:  # --ahora mal escrito
        return _error(exc)


registrar("leer", _configurar, _ejecutar, "parte diario e intradía, cortes y surf propuestos al buzón (plan 23)")
