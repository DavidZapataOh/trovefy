"""CLI ``trovefy-ejecutor`` (plan 12, tarea 7).

Códigos de salida: 0 ok · 1 error interno · 2 secretos o límites ilegibles · 3 otra instancia · 4 sin emparejar.
(``servir`` añade 5: auditoría corrupta; se repara con ``trovefy-ejecutor auditoria reparar``.)
Ninguna salida lleva tokens, ids de chat/usuario ni el contenido de ``secretos.env``: todo texto pasa por
``_limpio`` (quita los tokens conocidos y aplica ``auditoria.redactar``).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .auditoria import (
    EV_LIMITE_CAMBIADO,
    EV_STOP,
    Auditoria,
    AuditoriaCorrupta,
    redactar,
    reparar,
)
from .buzon import Buzon
from .candado import MENSAJE_OTRO, OtroEjecutorActivo, candado
from .comprobar_meta import comprobar_meta, informe_a_dict
from .config import RutasEjecutor, rutas_por_defecto
from .dinero import formatear
from .emparejar import ejecutar_emparejamiento
from .estado import Almacen
from .graph import ClienteGraph
from .instalacion import OffsetDistinto, fijar_offset
from .limites import Limites, LimitesInvalidos, cargar_limites, limites_a_dict
from .secretos import Secretos, SecretosInseguros, borrar_secretos, cargar_secretos
from .servicio import servir
from .simulado import simulacro
from .stop import activar_stop, quitar_stop, stop_activo
from .telegram import ClienteTelegram, ErrorRedTelegram, ErrorTelegram

_ESTADOS = ("recibida", "enviada", "aceptada", "ejecutando", "ejecutada", "fallida", "discrepancia",
            "rechazada", "caducada", "obsoleta")


def _limpio(texto: object, secretos: Secretos | None = None) -> str:
    t = str(texto)
    if secretos is not None:
        for s in (secretos.meta_token, secretos.telegram_bot_token):
            if s:
                t = t.replace(s, "***")
    return redactar(t)


def _salida(texto: object, secretos: Secretos | None = None, *, err: bool = False) -> None:
    print(_limpio(texto, secretos), file=sys.stderr if err else sys.stdout)


def _leer_secretos(rutas: RutasEjecutor) -> Secretos | None:
    try:
        return cargar_secretos(rutas.secretos)
    except SecretosInseguros as e:
        _salida(f"Secretos inseguros: {e}", err=True)
    except FileNotFoundError:
        _salida("No existe secretos.env: ejecuta el instalador", err=True)
    except (OSError, ValueError) as e:
        _salida(f"No se pueden leer los secretos ({type(e).__name__})", err=True)
    return None


def _leer_limites(rutas: RutasEjecutor) -> Limites | None:
    try:
        return cargar_limites(rutas.limites)
    except LimitesInvalidos as e:
        _salida(f"limites.yaml no válido: {e}", err=True)
    except Exception as e:  # noqa: BLE001
        _salida(f"limites.yaml ilegible ({type(e).__name__})", err=True)
    return None


def _ahora() -> datetime:
    return datetime.now(UTC)


# -- emparejar ---------------------------------------------------------------------------------------
def _cmd_emparejar(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    rutas.base.parent.mkdir(parents=True, exist_ok=True)
    try:
        with candado(rutas.base.with_suffix(".lock")):
            return _emparejar_con_candado(a, rutas)
    except OtroEjecutorActivo:
        print(MENSAJE_OTRO)
        return 3


def _emparejar_con_candado(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    secretos = _leer_secretos(rutas)
    if secretos is None:
        return 2
    if not secretos.telegram_bot_token:
        _salida("Falta TELEGRAM_BOT_TOKEN en secretos.env", err=True)
        return 2
    if a.reiniciar:
        try:
            borrar_secretos(rutas.secretos, ("TELEGRAM_USER_ID", "TELEGRAM_CHAT_ID"))
        except (OSError, ValueError) as e:
            _salida(f"No se pudo reiniciar el emparejamiento ({type(e).__name__})", secretos, err=True)
            return 2
    try:
        cliente = ClienteTelegram(secretos.telegram_bot_token)
    except ValueError:
        _salida("TELEGRAM_BOT_TOKEN con formato inválido", err=True)
        return 2
    almacen = None
    try:
        almacen = Almacen(rutas.base)
        auditoria = Auditoria(rutas.auditoria)
        buzon = Buzon(rutas.spool)
        r = ejecutar_emparejamiento(cliente, almacen, rutas.secretos, lambda t: _salida(t, secretos),
                                    auditoria=auditoria, buzon=buzon, ahora=_ahora)
    except ValueError as e:  # «ya emparejado», «emparejamiento a medias»
        _salida(f"{e}. Para volver a emparejar: trovefy-ejecutor emparejar --reiniciar", secretos, err=True)
        return 2
    except (ErrorTelegram, ErrorRedTelegram) as e:
        _salida(f"Telegram no responde ({type(e).__name__}): {e}", secretos, err=True)
        return 1
    finally:
        if almacen is not None:
            almacen.cerrar()
    if r is None:
        _salida("No se emparejó (código caducado o demasiados intentos). Si enviaste el código bien y se "
                "ignoró por «antiguo», sincroniza el reloj: sudo hwclock -s", secretos, err=True)
        return 1
    print("Emparejado.")
    return 0


# -- comprobar-meta ----------------------------------------------------------------------------------
def _cmd_comprobar_meta(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    secretos = _leer_secretos(rutas)
    lim = _leer_limites(rutas)
    if secretos is None or lim is None:
        return 2
    if not secretos.meta_token:
        _salida("Falta META_TOKEN en secretos.env (paso 13 de /arranque)", err=True)
        return 2
    act = a.cuenta
    if act is None:
        if len(lim.cuentas_permitidas) != 1:
            _salida("Hay varias cuentas permitidas: indica --cuenta act_…", err=True)
            return 2
        act = next(iter(lim.cuentas_permitidas))
    if act not in lim.cuentas_permitidas:
        _salida("Esa cuenta no está en cuentas_permitidas de limites.yaml", err=True)
        return 2
    informe = comprobar_meta(ClienteGraph(secretos.meta_token), act)
    d = informe_a_dict(informe)
    Buzon(rutas.spool).escribir_estado("meta", d)
    _salida(json.dumps(d, ensure_ascii=False, indent=2), secretos)
    for p in informe.problemas:
        _salida(f"- {p}", secretos)
    codigo = 0 if informe.ok else 1
    try:
        nuevo = fijar_offset(rutas.limites, d) if informe.cuenta is not None else None
    except OffsetDistinto:
        _salida("offset distinto del instalado: revisa (P-21)", err=True)
        return 1
    except (LimitesInvalidos, OSError, ValueError) as e:
        _salida(f"No se pudo fijar el offset ({type(e).__name__})", secretos, err=True)
        return 2
    if nuevo is not None:
        Auditoria(rutas.auditoria).anotar(EV_LIMITE_CAMBIADO, clave="offset", de=None, a=nuevo)
        _salida(f"offset fijado en limites.yaml: {nuevo}", secretos)
    return codigo


# -- estado ------------------------------------------------------------------------------------------
def _edad_latido(rutas: RutasEjecutor) -> str:
    try:
        d = json.loads((rutas.spool / "estado" / "latido.json").read_text(encoding="utf-8"))
        fecha = datetime.fromisoformat(d["fecha"])
        s = int((_ahora() - fecha).total_seconds())
    except (OSError, ValueError, KeyError, TypeError):
        return "sin latido"
    return f"hace {s} s" + (" (el servicio no late)" if s > 120 else "")


def _cmd_estado(_a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    print(f"STOP: {'ACTIVO' if stop_activo(rutas) else 'no'}")
    if rutas.base.exists():
        almacen = Almacen(rutas.base)
        try:
            for e in _ESTADOS:
                n = len(almacen.en_estado(e))  # type: ignore[arg-type]
                if n:
                    print(f"propuestas {e}: {n}")
        finally:
            almacen.cerrar()
    else:
        print("propuestas: sin base de datos")
    print(f"latido: {_edad_latido(rutas)}")
    try:
        ok = Auditoria(rutas.auditoria).verificar() if rutas.auditoria.exists() else True
    except Exception as e:  # noqa: BLE001
        _salida(f"auditoría: ilegible ({type(e).__name__})")
        return 1
    print(f"auditoría: {'íntegra' if ok else 'ROTA (para el servicio y ejecuta: trovefy-ejecutor auditoria reparar)'}")
    return 0 if ok else 1


# -- stop / reanudar (respaldo si Telegram no responde) ----------------------------------------------
def _anotar_stop(rutas: RutasEjecutor, activo: bool, motivo: str) -> bool:
    try:
        Auditoria(rutas.auditoria).anotar(EV_STOP, activo=activo, motivo=motivo)
    except Exception as e:  # noqa: BLE001 — el interruptor ya cambió: se avisa, no se deshace
        _salida(f"Aviso: no se pudo anotar en la auditoría ({type(e).__name__})", err=True)
        return False
    return True


def _cmd_stop(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    """``stop [motivo]``: inmediato, sin candado (funciona con el servicio en marcha). No pausa campañas."""
    if stop_activo(rutas):
        print("STOP ya estaba activo")
        return 0
    motivo = "CLI: " + _limpio(" ".join(a.motivo)).strip()[:200] if a.motivo else "CLI stop"
    activar_stop(rutas, motivo, _ahora())
    print("STOP activo: no se escribe nada en Meta. No pausa campañas. Para quitarlo: trovefy-ejecutor reanudar")
    return 0 if _anotar_stop(rutas, True, motivo) else 1


def _cmd_reanudar(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    if not stop_activo(rutas):
        print("STOP no estaba activo")
        return 0
    if not a.si:
        try:
            resp = input("Quitar el STOP permite volver a escribir en Meta. Escribe «sí» para seguir: ")
        except EOFError:
            resp = ""
        if resp.strip().lower() not in ("sí", "si"):
            print("No se quitó el STOP.")
            return 1
    quitar_stop(rutas)
    print("STOP quitado.")
    return 0 if _anotar_stop(rutas, False, "CLI reanudar") else 1


# -- auditoria reparar ------------------------------------------------------------------------------
def _cmd_auditoria(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    """``auditoria reparar``: aparta el archivo roto (``.roto-<fecha>``, nunca se borra) y abre una cadena
    nueva con ``cadena_reanudada``. Exige el servicio parado (mismo candado que ``servir``)."""
    rutas.base.parent.mkdir(parents=True, exist_ok=True)
    try:
        with candado(rutas.base.with_suffix(".lock")):
            return _reparar_con_candado(rutas)
    except OtroEjecutorActivo:
        print(MENSAJE_OTRO)
        return 3


def _reparar_con_candado(rutas: RutasEjecutor) -> int:
    if not rutas.auditoria.exists() and not rutas.auditoria.with_name(rutas.auditoria.name + ".cabeza").exists():
        print("auditoría: no existe; no hay nada que reparar")
        return 0
    try:
        Auditoria(rutas.auditoria)
        integra = Auditoria(rutas.auditoria).verificar()
    except AuditoriaCorrupta:
        integra = False
    if integra:
        print("auditoría: íntegra; no hay nada que reparar")
        return 0
    roto = reparar(rutas.auditoria)
    print(f"auditoría reparada: el archivo roto se guardó como {roto.name} (no lo borres: es la prueba)")
    print("Arranca de nuevo el servicio: sudo systemctl start trovefy-ejecutor")
    return 0


# -- simular / limites / servir -----------------------------------------------------------------------
def _cmd_simular(a: argparse.Namespace, _rutas: RutasEjecutor) -> int:
    if a.raiz:
        pasos = simulacro(Path(a.raiz))
    else:
        with tempfile.TemporaryDirectory(prefix="trovefy-simulacro-") as d:
            pasos = simulacro(Path(d))
    return 0 if pasos and all(ok for _, ok in pasos) else 1


def _cmd_limites(_a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    lim = _leer_limites(rutas)
    if lim is None:
        return 2
    for cid in sorted(lim.cuentas_permitidas):
        c = lim.cuentas[cid]
        print(f"{cid} ({c.moneda_codigo}, zona {c.zona_horaria})")
        if c.offset is None:
            print("  sin configurar (P-21)")
            continue
        m = c.moneda()
        for nombre in ("tope_gasto_diario_total", "max_presupuesto_conjunto", "max_presupuesto_campana_cbo",
                       "spend_cap_test", "spend_cap_test_prorroga"):
            print(f"  {nombre}: {formatear(getattr(c, nombre), m)}")
    Buzon(rutas.spool).escribir_estado("limites", limites_a_dict(lim))
    print("Los cambios se piden por /limites en Telegram.")
    return 0


def _cmd_servir(a: argparse.Namespace, rutas: RutasEjecutor) -> int:
    return servir(rutas, graph_simulado=a.graph_simulado)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trovefy-ejecutor", description="Ejecutor de Trovefy (aprobador y caja).")
    sub = p.add_subparsers(dest="orden", required=True)
    e = sub.add_parser("emparejar", help="empareja el bot con tu chat privado")
    e.add_argument("--reiniciar", action="store_true", help="olvida el emparejamiento actual")
    c = sub.add_parser("comprobar-meta", help="comprueba la cuenta de Meta")
    c.add_argument("--cuenta", help="act_… (por defecto, la única de cuentas_permitidas)")
    s = sub.add_parser("servir", help="arranca el servicio")
    s.add_argument("--graph-simulado", action="store_true", help="sin tocar Meta")
    sub.add_parser("estado", help="STOP, propuestas, latido y auditoría")
    si = sub.add_parser("simular", help="recorre el ejecutor con Telegram y Meta simulados")
    si.add_argument("--raiz", help="carpeta de trabajo (por defecto, temporal)")
    sub.add_parser("limites", help="muestra los límites por cuenta")
    st = sub.add_parser("stop", help="STOP inmediato sin Telegram (no pausa campañas)")
    st.add_argument("motivo", nargs="*", help="motivo (queda en la auditoría)")
    re_ = sub.add_parser("reanudar", help="quita el STOP (pide escribir «sí»)")
    re_.add_argument("--si", action="store_true", help="no preguntar")
    au = sub.add_parser("auditoria", help="mantenimiento de la auditoría (con el servicio parado)")
    au_sub = au.add_subparsers(dest="accion", required=True)
    au_sub.add_parser("reparar", help="aparta el archivo roto y empieza una cadena nueva")
    return p


_ORDENES = {"emparejar": _cmd_emparejar, "comprobar-meta": _cmd_comprobar_meta, "servir": _cmd_servir,
            "estado": _cmd_estado, "simular": _cmd_simular, "limites": _cmd_limites,
            "auditoria": _cmd_auditoria, "stop": _cmd_stop, "reanudar": _cmd_reanudar}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _ORDENES[args.orden](args, rutas_por_defecto())
    except Exception as e:  # noqa: BLE001 — nunca traza ni texto sin limpiar
        _salida(f"Error interno ({type(e).__name__})", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
