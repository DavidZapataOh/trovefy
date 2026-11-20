"""Subcomando `trovefy montar` (plan 22): la tanda aprobada → campaña de test ABO en PAUSED por el ejecutor.

Orden de §4.14: ``preparar`` (precondiciones, tanda, importes, estructura y resumen en seco; no deposita nada) →
``validar`` (la misma estructura con ``solo_validar``: ``validate_only`` de Meta, sin crear nada) → ``depositar`` (todo
en PAUSED; el ejecutor valida cada objeto antes de crearlo, relee y genera «Activar campaña» con Aceptar en Telegram).
``registrar`` recoge lo que copió el ejecutor; ``activar`` vuelve a proponer «Activar» si caducó; ``estado`` lo
resume; ``excepcion`` registra tu palabra para activar con una excepción de /listo; ``renovacion`` monta las piezas
nuevas de una renovación en la misma ABO (T3 18:55, T3 19:55).

Claude nunca escribe en Meta: solo deposita propuestas por ``trovefy.aprobaciones.fuentes.depositar``.
Códigos de salida: 0 bien · 1 bloqueado (precondiciones, resultado pendiente) · 2 error de uso o de datos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trovefy.cli import registrar
from trovefy.vault.escritura import ZONA_NEGOCIO


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _reloj() -> datetime:
    return getattr(sys.modules.get(__name__), "_ahora", _ahora)()


def _mod(nombre: str):
    return getattr(sys.modules.get(__name__), nombre)


def _evaluar_listo(vault, p_id, pais, ahora, fuentes):
    from trovefy.listo import veredicto

    return veredicto.evaluar(vault, p_id, pais, ahora, fuentes)


def _fuentes(vault: Path):
    from trovefy.listo import veredicto

    return veredicto.fuentes_por_defecto(vault)


def _trm(vault: Path, dia):
    from trovefy import trm

    return trm.trm_del_dia(vault, dia)


def _error(msg: object, codigo: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return codigo


def _comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--producto", required=True, help="p-id del producto (p-0001-…)")
    p.add_argument("--pais", required=True, help="código del país (BG…)")


def _configurar(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="accion", required=True, metavar="<acción>")
    for nombre, ayuda in (("preparar", "precondiciones, tanda, importes y resumen en seco (no deposita nada)"),
                          ("validar", "deposita la estructura con solo_validar (validate_only de Meta)"),
                          ("depositar", "deposita el montaje en PAUSED (tras una validación ejecutada)")):
        p = sub.add_parser(nombre, help=ayuda)
        _comunes(p)
        p.add_argument("--tanda", required=True, help="t1, t2…")
        if nombre == "preparar":
            p.add_argument("--anuncios", help="ADnn separados por comas (solo entre las filas de la tanda)")
    r = sub.add_parser("registrar", help="recoge lo que copió el ejecutor (histórico, estado, caja, veto)")
    grupo = r.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pendientes", action="store_true", help="todos los productos-país con algo sin cerrar")
    grupo.add_argument("--producto")
    r.add_argument("--pais")
    a = sub.add_parser("activar", help="vuelve a proponer «Activar campaña» si la del ejecutor caducó")
    _comunes(a)
    e = sub.add_parser("estado", help="resumen del montaje de un producto-país")
    _comunes(e)
    x = sub.add_parser("excepcion", help="tu palabra para activar con una excepción aprobada de /listo")
    _comunes(x)
    x.add_argument("--gate", required=True, help="reembolso, utm_checkout, dominio o dataset")
    x.add_argument("--cita", required=True, help="tus palabras literales: un mensaje tuyo entero")
    x.add_argument("--motivo", required=True, help="por qué, en una frase")
    n = sub.add_parser("renovacion", help="monta una renovación en la misma ABO (preparar, validar o depositar)")
    _comunes(n)
    n.add_argument("--tanda", required=True, help="la tanda de renovación (t2, t3…)")
    n.add_argument("--paso", choices=("preparar", "validar", "depositar"), default="preparar")


# --- ayudantes ---------------------------------------------------------------------------------------------------


def _vault() -> Path:
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _ruta_json(vault: Path, p_id: str, pais: str, tanda: str) -> Path:
    from trovefy.vault.producto import ruta_producto

    return ruta_producto(vault, p_id).parent / "trafico" / pais / f"MONTAJE-{tanda}.json"


def _guardar_json(ruta: Path, datos: dict) -> None:
    from trovefy.vault.escritura import escribir_atomico

    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _cargar_json(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"no existe {ruta.name}: ejecuta antes `trovefy montar preparar`") from None
    except ValueError:
        raise ValueError(f"{ruta.name} ilegible: vuelve a preparar") from None


def _trafico(vault: Path, p_id: str, pais: str) -> tuple[str | None, dict]:
    from trovefy.montar.tanda import bloque_pais

    b = bloque_pais(vault, p_id, pais)
    t = b.get("trafico")
    return b.get("estado"), dict(t) if isinstance(t, dict) else {}


def _imprimir_pre(pre) -> None:
    print("Precondiciones:")
    print("\n".join(f"  {x}" for x in pre.lineas))


def _usd_vivos(vault: Path) -> Decimal:
    from trovefy.caja.config import cargar_caja

    return sum((Decimal(t.presupuesto_diario) / 100 for t in cargar_caja(vault).tests if t.estado == "vivo"),
               Decimal(0))


def _gastado_usd(vault: Path, p_id: str, pais: str) -> Decimal | None:
    from trovefy.caja.config import cargar_caja
    from trovefy.caja.gasto import gastos_de_tests

    try:
        for g in gastos_de_tests(vault, cargar_caja(vault), lambda d: _mod("_trm")(vault, d)):
            if g.producto == p_id and g.pais == pais and g.usd_centavos is not None:
                return Decimal(g.usd_centavos) / 100
    except (OSError, ValueError):
        return None
    return None


def _comprobar_medios(vault: Path, estructura: dict) -> str | None:
    for m in estructura.get("medios") or []:
        try:
            sha = hashlib.sha256((vault / m["ruta"]).read_bytes()).hexdigest()
        except OSError:
            return f"falta {m['ruta']}"
        if sha != m["sha256"]:
            return f"{m['ruta']} cambió"
    return None


def _comprobar_guardado(vault: Path, datos: dict, ahora: datetime) -> str | None:
    from trovefy.montar.estructura import huella

    est = datos.get("estructura") or {}
    cambio = _comprobar_medios(vault, est)
    if cambio:
        return f"la tanda cambió ({cambio}): vuelve a preparar"
    if huella(est) != datos.get("huella"):
        return "el montaje preparado cambió a mano: vuelve a preparar"
    inicio = datetime.fromisoformat((est.get("conjuntos") or [{}])[0].get("inicio", ahora.isoformat()))
    if inicio <= ahora + timedelta(minutes=10):
        return "la hora de salida ya pasó o está a menos de 10 minutos: vuelve a preparar"
    return None


# --- preparar / validar / depositar -----------------------------------------------------------------------------


def _preparar(args, modo: str = "montar") -> int:
    from trovefy.aprobaciones.fuentes import leer_estado
    from trovefy.config.umbrales import valor
    from trovefy.montar import MontajeInvalido, NoMedido, TandaInvalida
    from trovefy.montar.estructura import (
        cargar_contexto,
        construir,
        huella,
        resumen_en_seco,
    )
    from trovefy.montar.importes import calcular
    from trovefy.montar.precondiciones import comprobar
    from trovefy.montar.tanda import elegir, leer_tanda
    from trovefy.vault.escritura import anadir_log, escribir_atomico

    vault, ahora, pais = _vault(), _reloj(), args.pais.strip().upper()
    renov = modo == "renovacion"
    try:
        pre = comprobar(vault, args.producto, pais, ahora, _mod("_fuentes")(vault), evaluar=_mod("_evaluar_listo"),
                        modo=modo)
        _imprimir_pre(pre)
        if not pre.ok:
            print("No se prepara el montaje: arregla lo marcado con ✗.")
            return 1
        tanda = leer_tanda(vault, args.producto, pais, args.tanda)
        if not tanda.aprobada:
            print(f"La tanda {args.tanda} no está aprobada: {tanda.motivo}")
            return 1
        conjuntos = int(valor(vault, "test.conjuntos"))
        ids = [x.strip() for x in (getattr(args, "anuncios", None) or "").split(",") if x.strip()] or None
        piezas = elegir(tanda.piezas, uso="renovacion" if renov else "test", ids=ids,
                        n=None if (ids or renov) else conjuntos)
        usd_conjunto = Decimal(str(valor(vault, "test.presupuesto_conjunto_usd")))
        usd_tope = Decimal(str(valor(vault, "test.spend_cap_usd")))
        ctx = cargar_contexto(vault, args.producto, pais)
        campana_existente = None
        avisos: list[str] = []
        if renov:
            _, trafico = _trafico(vault, args.producto, pais)
            campana_existente = str((trafico.get("campana") or {}).get("id") or "")
            if not campana_existente:
                print("No hay campaña del test registrada: `trovefy montar registrar` primero.")
                return 1
            t0s = [datetime.fromisoformat(x) for x in (trafico.get("activado"), trafico.get("inicio")) if x]
            if not t0s:
                print("El test aún no está activado: no hay reloj del test (t0).")
                return 1
            plazo = int((trafico.get("plazo") or {}).get("dias") or ctx.cfg.plazo_dias)
            if ahora > max(t0s) + timedelta(days=plazo):
                print(f"El plazo del test ({plazo} días, C1 0:18:10) ya venció: no se renueva.")
                return 1
            gastado = _gastado_usd(vault, args.producto, pais)
            if gastado is None:
                avisos.append("no medido: gasto del test (sin ledger/gasto); Meta para igual en el techo")
            elif gastado >= usd_tope:
                print(f"El techo del test (US$ {usd_tope}) ya se gastó (US$ {gastado}): no se renueva.")
                return 1
        importes = calcular(ctx.cuenta, leer_estado("meta", cuenta=ctx.cuenta), leer_estado("limites"),
                            _mod("_trm")(vault, ahora.astimezone(ZONA_NEGOCIO).date()),
                            ahora.astimezone(ZONA_NEGOCIO).date(), conjuntos=len(piezas), usd_conjunto=usd_conjunto,
                            usd_tope=usd_tope, usd_vivos=_usd_vivos(vault))
        est = construir(ctx, piezas, importes, tanda.grupo, ahora, campana_existente=campana_existente)
    except (NoMedido, TandaInvalida, MontajeInvalido) as exc:
        print(f"No se prepara el montaje: {exc}")
        return 1
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error(exc)
    h = huella(est)
    ruta = _ruta_json(vault, args.producto, pais, args.tanda)
    previo = {}
    if ruta.is_file():
        try:
            previo = json.loads(ruta.read_text(encoding="utf-8"))
        except ValueError:
            previo = {}
    datos = {"tipo": modo if renov else "test", "tanda": args.tanda, "grupo": tanda.grupo, "estructura": est,
             "huella": h, "importes": importes.a_dict(), "plazo_dias": ctx.cfg.plazo_dias,
             "fecha": ahora.isoformat(timespec="seconds"),
             "piezas": [{"id": p.id, "nombre": p.nombre, "angulo": p.angulo, "tipo": p.tipo, "ruta": p.ruta,
                         "miniatura": p.miniatura} for p in piezas]}
    for clave in ("validacion", "montaje"):
        if isinstance(previo.get(clave), dict) and previo[clave].get("huella") == h:
            datos[clave] = previo[clave]
    _guardar_json(ruta, datos)
    resumen = resumen_en_seco(est, importes, piezas, ctx, avisos)
    escribir_atomico(ruta.with_suffix(".md"), f"# Montaje {args.tanda} (en seco)\n\n```\n{resumen}\n```\n")
    rel = ruta.relative_to(vault).as_posix()
    anadir_log(vault, "/montar", f"{args.producto} {pais} {args.tanda}: montaje preparado (huella {h[:12]})",
               [rel, ruta.with_suffix(".md").relative_to(vault).as_posix()], ahora=ahora)
    print()
    print(resumen)
    print()
    print(f"Preparado: {rel}. Siguiente: `trovefy montar {'renovacion --paso validar' if renov else 'validar'} "
          f"--producto {args.producto} --pais {pais} --tanda {args.tanda}`.")
    return 0


def _depositar_dict(vault: Path, datos: dict, ahora: datetime) -> str:
    from trovefy.aprobaciones.fuentes import depositar

    return depositar(vault, datos, lambda: ahora)


def _validar(args, modo: str = "montar") -> int:
    from trovefy.aprobaciones.fuentes import BuzonNoDisponible

    vault, ahora, pais = _vault(), _reloj(), args.pais.strip().upper()
    ruta = _ruta_json(vault, args.producto, pais, args.tanda)
    try:
        datos = _cargar_json(ruta)
    except ValueError as exc:
        return _error(exc)
    problema = _comprobar_guardado(vault, datos, ahora)
    if problema:
        return _error(problema)
    previa = datos.get("validacion")
    if isinstance(previa, dict) and previa.get("huella") == datos["huella"]:
        print(f"ya depositada la validación: {previa['id']}")
        return 0
    try:
        id_ = _depositar_dict(vault, {**datos["estructura"], "solo_validar": True}, ahora)
    except BuzonNoDisponible as exc:
        return _error(exc, 1)
    datos["validacion"] = {"id": id_, "huella": datos["huella"]}
    _guardar_json(ruta, datos)
    print(f"Validación depositada: {id_} (validate_only de Meta, no crea nada). Mira el resultado con "
          f"`trovefy montar registrar --producto {args.producto} --pais {pais}` o `trovefy montar estado`.")
    return 0


def _texto_spend_cap(detalle: str) -> bool:
    return "spend_cap" in detalle.lower()


def _depositar(args, modo: str = "montar") -> int:
    from trovefy.aprobaciones.fuentes import BuzonNoDisponible
    from trovefy.montar.precondiciones import comprobar, vetado
    from trovefy.montar.registro import leer_resultado
    from trovefy.vault.producto import sustituir_clave_pais

    vault, ahora, pais = _vault(), _reloj(), args.pais.strip().upper()
    renov = modo == "renovacion"
    ruta = _ruta_json(vault, args.producto, pais, args.tanda)
    try:
        datos = _cargar_json(ruta)
    except ValueError as exc:
        return _error(exc)
    previo = datos.get("montaje")
    if isinstance(previo, dict) and previo.get("huella") == datos.get("huella"):
        print(f"ya depositado: {previo['id']}")
        return 0
    problema = _comprobar_guardado(vault, datos, ahora)
    if problema:
        return _error(problema)
    val = datos.get("validacion")
    if not isinstance(val, dict) or val.get("huella") != datos["huella"]:
        return _error("falta la validación de este montaje: `trovefy montar validar` primero")
    r = leer_resultado(vault, val["id"])
    if r is None or r.estado not in ("ejecutada", "fallida", "discrepancia", "rechazada", "caducada", "obsoleta"):
        print(f"La validación {val['id']} aún no tiene resultado del ejecutor: espera y vuelve a intentarlo.")
        return 1
    if r.estado != "ejecutada":
        print(f"La validación {val['id']} quedó {r.estado}: {r.detalle}")
        if _texto_spend_cap(r.detalle):
            print("Si Meta pide un spend_cap de campaña mínimo mayor que US$ 100: apunta el mínimo que dijo Meta y "
                  "sigue el desvío D1 (techo como límite de la cuenta, Tarea 11 del plan 22); no se monta así.")
        return 1
    try:
        pre = comprobar(vault, args.producto, pais, ahora, _mod("_fuentes")(vault), evaluar=_mod("_evaluar_listo"),
                        modo=modo)
    except (OSError, ValueError) as exc:
        return _error(exc)
    _imprimir_pre(pre)
    if not pre.ok:
        print("No se deposita: arregla lo marcado con ✗.")
        return 1
    _, trafico = _trafico(vault, args.producto, pais)
    if not renov and trafico.get("montaje"):
        if trafico.get("montaje_estado") in ("fallida", "discrepancia") and trafico.get("historico"):
            print(f"El montaje anterior ({trafico['montaje']}) dejó algo creado (estado parcial): no se vuelve a "
                  "montar sin tu palabra. Revisa el histórico en Ads Manager y dímelo.")
            return 1
        if not (vetado(trafico, vault) or trafico.get("montaje_estado") in ("fallida", "discrepancia")):
            print(f"Ya hay un montaje ({trafico['montaje']}): no se deposita otro.")
            return 1
    try:
        id_ = _depositar_dict(vault, dict(datos["estructura"]), ahora)
    except BuzonNoDisponible as exc:
        return _error(exc, 1)
    datos["montaje"] = {"id": id_, "huella": datos["huella"]}
    _guardar_json(ruta, datos)
    if renov:
        renovs = [*(trafico.get("renovaciones") or []),
                  {"tanda": args.tanda, "validacion": val["id"], "montaje": id_,
                   "fecha": ahora.isoformat(timespec="seconds")}]
        nuevo = {**trafico, "renovaciones": renovs}
    else:
        anteriores = list(trafico.get("anteriores") or [])
        if trafico.get("montaje"):
            anteriores.append({k: v for k, v in trafico.items() if k != "anteriores"})
        nuevo = {"tanda": args.tanda, "validacion": val["id"], "montaje": id_}
        if anteriores:
            nuevo["anteriores"] = anteriores
    sustituir_clave_pais(vault, args.producto, pais, "trafico", nuevo, "/montar", ahora,
                         archivos_log=[ruta.relative_to(vault).as_posix()])
    print(f"Montaje depositado: {id_}. El ejecutor lo crea todo en PAUSED, lo relee y te manda «Activar campaña» "
          "con las miniaturas a Telegram (caduca en 24 h). Después: `trovefy montar registrar`.")
    return 0


# --- registrar / activar / estado / excepcion ---------------------------------------------------------------------


def _registrar(args) -> int:
    from trovefy.montar.registro import pendientes, registrar

    vault, ahora = _vault(), _reloj()
    if args.pendientes:
        pares = pendientes(vault)
        if not pares:
            print("Nada pendiente de registrar.")
            return 0
    else:
        if not args.pais:
            return _error("falta --pais")
        pares = [(args.producto, args.pais.strip().upper())]
    codigo = 0
    for p, pais in pares:
        try:
            print("\n".join(registrar(vault, p, pais, ahora)))
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"Error en {p} {pais}: {exc}", file=sys.stderr)
            codigo = 2
    return codigo


def propuesta_activar(trafico: dict, montaje: dict, producto: str, pais: str) -> dict:
    """«Activar campaña» de Claude (``origen: /montar``) con la campaña, los conjuntos y los anuncios del histórico."""
    from trovefy_ejecutor.dinero import Moneda, formatear

    est = montaje.get("estructura") or {}
    ops = [{"entidad": "campaign", "id": str(trafico["campana"]["id"]), "campo": "status", "de_esperado": "PAUSED",
            "a": "ACTIVE"}]
    ops += [{"entidad": "adset", "id": str(i), "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
            for i in (trafico.get("conjuntos") or {}).values()]
    ops += [{"entidad": "ad", "id": str(a["id"]), "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
            for a in (trafico.get("anuncios") or {}).values()]
    anuncios = []
    for c in est.get("conjuntos") or []:
        for a in c.get("anuncios") or []:
            anuncios.append({"nombre": a["nombre"], "texto": a["texto"][:125], "titulo": a["titulo"][:40],
                             "vista_previa": None, "miniatura": a.get("miniatura"), "miniatura_url": None})
    imp = montaje.get("importes") or {}
    mon = Moneda(imp.get("moneda", "COP"), int(imp.get("offset", 1)))
    motivo = (f"Activar campaña {trafico['campana'].get('nombre')}: {len(trafico.get('conjuntos') or {})} × "
              f"{formatear(int(imp.get('diario_conjunto', 0)), mon)}/día, techo "
              f"{formatear(int(imp.get('spend_cap', 0)), mon)}; creada en PAUSED (montaje {trafico.get('montaje')}); "
              "la del ejecutor caducó")[:1000]
    return {"tipo": "activar", "origen": "/montar", "cuenta": trafico.get("cuenta") or est.get("cuenta"),
            "producto": producto, "pais": pais, "operaciones": ops, "motivo": motivo,
            "evidencia": {"montaje": trafico.get("montaje"), "medios": [m["ruta"] for m in est.get("medios") or []],
                          "anuncios": anuncios[:10]},
            "reinicia_aprendizaje": False}


def _activar(args) -> int:
    from trovefy.aprobaciones.fuentes import BuzonNoDisponible
    from trovefy.montar.precondiciones import comprobar
    from trovefy.montar.registro import leer_montaje_json
    from trovefy.vault.producto import sustituir_clave_pais

    vault, ahora, pais = _vault(), _reloj(), args.pais.strip().upper()
    try:
        _, trafico = _trafico(vault, args.producto, pais)
    except (FileNotFoundError, ValueError) as exc:
        return _error(exc)
    if trafico.get("activar_estado") != "caducada":
        print("Solo se vuelve a proponer «Activar» si la anterior caducó (`trovefy montar registrar` lo dice).")
        return 1
    pre = comprobar(vault, args.producto, pais, ahora, _mod("_fuentes")(vault), evaluar=_mod("_evaluar_listo"),
                    modo="activar")
    _imprimir_pre(pre)
    if not pre.ok:
        return 1
    datos = propuesta_activar(trafico, leer_montaje_json(vault, args.producto, pais, trafico.get("tanda", "")),
                              args.producto, pais)
    try:
        id_ = _depositar_dict(vault, datos, ahora)
    except BuzonNoDisponible as exc:
        return _error(exc, 1)
    sustituir_clave_pais(vault, args.producto, pais, "trafico",
                         {**trafico, "activar": id_, "activar_estado": None}, "/montar", ahora)
    print(f"«Activar campaña» depositada: {id_}. Te llega a Telegram con Aceptar y Rechazar.")
    return 0


def _estado(args) -> int:
    from trovefy.montar.registro import leer_resultado

    vault, pais = _vault(), args.pais.strip().upper()
    try:
        estado, t = _trafico(vault, args.producto, pais)
    except (FileNotFoundError, ValueError) as exc:
        return _error(exc)
    print(f"{args.producto} {pais}: estado {estado or 'sin estado'}")
    if not t:
        print("Sin montaje.")
        return 0
    for clave in ("validacion", "montaje", "activar"):
        if t.get(clave):
            r = leer_resultado(vault, t[clave])
            print(f"  {clave}: {t[clave]} · {r.estado if r else 'sin resultado del ejecutor'}")
    camp = t.get("campana") or {}
    if camp.get("id"):
        print(f"  campaña: {camp.get('nombre')} (…{str(camp['id'])[-4:]}) · {len(t.get('conjuntos') or {})} conjuntos")
    print(f"  tanda: {t.get('tanda')} · salida: {t.get('inicio') or '—'} · activado: {t.get('activado') or '—'}")
    for x in t.get("renovaciones") or []:
        print(f"  renovación {x.get('tanda')}: montaje {x.get('montaje')} · activado {x.get('activado') or '—'}")
    carpeta = vault / "ledger" / "auditoria"
    ids = [t[c] for c in ("validacion", "montaje", "activar") if t.get(c)]
    vistos = set()
    for f in carpeta.glob("*.jsonl") if carpeta.is_dir() else ():
        texto = f.read_text(encoding="utf-8", errors="replace")
        vistos |= {i for i in ids if i in texto}
    for i in ids:
        print(f"  auditoría: {i} {'anotado' if i in vistos else 'aún no copiado al vault'}")
    return 0


def _hay_terminal() -> bool:
    from trovefy.checkout.mcp_cli import hay_terminal

    return hay_terminal()


def _excepcion(args) -> int:
    from trovefy.checkout.mensajes import es_mensaje_del_usuario
    from trovefy.montar.precondiciones import registrar_excepcion_activar

    vault, ahora, pais = _vault(), _reloj(), args.pais.strip().upper()
    if not _mod("_hay_terminal")() and not es_mensaje_del_usuario(args.cita or "",
                                                                  desde=ahora.timestamp() - 24 * 3600):
        return _error("esas palabras no son un mensaje tuyo de las últimas 24 h: activar con una excepción lo decide "
                      "el usuario, no Claude. Escribe tu aprobación en un mensaje aparte y pásalo entero con --cita")
    try:
        ruta = registrar_excepcion_activar(vault, args.producto, pais, args.gate, args.cita, args.motivo, ahora)
    except (ValueError, OSError) as exc:
        return _error(exc)
    print(f"Registrado con tus palabras: {ruta.relative_to(vault).as_posix()} (no cuenta como verde).")
    return 0


def _renovacion(args) -> int:
    return {"preparar": _preparar, "validar": _validar, "depositar": _depositar}[args.paso](args, "renovacion")


_ACCIONES = {"preparar": _preparar, "validar": _validar, "depositar": _depositar, "registrar": _registrar,
             "activar": _activar, "estado": _estado, "excepcion": _excepcion, "renovacion": _renovacion}


def _ejecutar(args: argparse.Namespace) -> int:
    return _ACCIONES[args.accion](args)


registrar("montar", _configurar, _ejecutar, "monta el test en PAUSED por el ejecutor y registra la activación (plan 22)")
