"""Subcomando `trovefy caja`: sobres, huecos de test, mover, anotar herramientas y proponer límites.

Salidas: 0 bien · 1 sin depositar (buzón no disponible) · 2 error de uso o ``caja.yaml`` ausente/inválido.
Claude nunca escribe en Meta: ``proponer-limites`` solo deposita propuestas para que las apruebe el usuario.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy import trm as trm_mod
from trovefy.aprobaciones import fuentes
from trovefy.caja import config as cfg_mod
from trovefy.caja.bloqueos import usd
from trovefy.caja.calculo import EstadoCaja, calcular
from trovefy.caja.config import SOBRES, CajaInvalida, ConfigCaja, cargar_caja
from trovefy.caja.gasto import GastoCorrupto, gastos_de_tests
from trovefy.caja.limites import propuestas_de_limites, recomendar
from trovefy.caja.mover import MovimientoInvalido, anotar_herramienta, mover
from trovefy.caja.movimientos import MovimientosCorruptos, leer_movimientos
from trovefy.caja.salida import escribir_caja, linea_informe
from trovefy.cli import registrar
from trovefy.trm import Trm
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log


class _Salida(Exception):
    def __init__(self, codigo: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def _ahora() -> datetime:
    return datetime.now(ZONA_NEGOCIO)


def _vault() -> Path:
    from trovefy.vault.rutas import vault_root

    return vault_root()


def _configurar(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="accion", metavar="<accion>", required=True)
    ini = sub.add_parser("iniciar", help="crea config/caja.yaml con la cuenta del paso 06")
    ini.add_argument("--moneda", help="moneda de la cuenta, ya confirmada por el usuario (p. ej. COP)")
    sub.add_parser("ver", help="calcula la caja, escribe wiki/analisis/caja.md y la resume")
    mv = sub.add_parser("mover", help="mueve USD entre sobres (decisión del usuario, con su cita)")
    mv.add_argument("--de", required=True, help="sobre de origen")
    mv.add_argument("--a", required=True, help="sobre de destino")
    mv.add_argument("--importe", required=True, help="USD, p. ej. 50 o 12.50")
    mv.add_argument("--cita", required=True, help="las palabras literales del usuario")
    an = sub.add_parser("anotar", help="anota un gasto de herramientas")
    an.add_argument("--importe", required=True)
    an.add_argument("--moneda", required=True, choices=["USD", "COP"])
    an.add_argument("--nota", required=True)
    sub.add_parser("proponer-limites", help="deposita las propuestas de límites para aprobación")


def _decimal(texto: str, campo: str) -> Decimal:
    try:
        d = Decimal(texto.strip())
    except InvalidOperation:
        raise _Salida(2, f"{campo}: importe ilegible ({texto!r})") from None
    if not d.is_finite():
        raise _Salida(2, f"{campo}: importe ilegible ({texto!r})")
    return d


def _trm(vault: Path, dia: date) -> Trm | None:
    return trm_mod.trm_del_dia(vault, dia, abrir=trm_mod._abrir_seguro)


def _cargar(vault: Path) -> ConfigCaja:
    try:
        return cargar_caja(vault)
    except FileNotFoundError:
        raise _Salida(2, "falta config/caja.yaml: ejecuta `trovefy caja iniciar`") from None
    except CajaInvalida as e:
        raise _Salida(2, str(e)) from None


def _estado(vault: Path, cfg: ConfigCaja) -> EstadoCaja:
    try:
        gastos = gastos_de_tests(vault, cfg, lambda d: _trm(vault, d))
        return calcular(cfg, leer_movimientos(vault), gastos)
    except (GastoCorrupto, MovimientosCorruptos) as e:
        raise _Salida(2, str(e)) from None


def _log(vault: Path, que: str, archivos: list[str], ahora: datetime) -> None:
    anadir_log(vault, "caja", que, archivos, ahora=ahora)


def _iniciar(args: argparse.Namespace, vault: Path, ahora: datetime) -> int:
    from trovefy.arranque.verificadores.cuenta import act_guardado

    moneda = args.moneda.strip().upper() if args.moneda else None
    if moneda is not None and (len(moneda) != 3 or not moneda.isalpha()):
        raise _Salida(2, f"--moneda: se esperaba un código de 3 letras ({args.moneda!r})")
    digitos = act_guardado(vault)
    act = f"act_{digitos}" if digitos else None
    try:
        ruta = cfg_mod.iniciar_caja(vault, act, moneda)
    except (FileExistsError, CajaInvalida) as e:
        raise _Salida(2, str(e)) from None
    _log(vault, "iniciar caja", ["config/caja.yaml"], ahora)
    print(f"Creado {ruta.relative_to(vault)}.")
    print("Cuenta: " + ("la del paso 06." if act else "sin cuenta guardada (paso 06 pendiente)."))
    print("Moneda: " + (moneda if moneda else "sin confirmar; repite con --moneda cuando el usuario la confirme."))
    return 0


def _limites(vault: Path, cfg: ConfigCaja, estado: EstadoCaja, ahora: datetime):
    dia = ahora.astimezone(ZONA_NEGOCIO).date()
    trm = _trm(vault, dia)
    rec = recomendar(estado, cfg)
    props, nm = propuestas_de_limites(
        rec, cfg, trm, dia,
        fuentes.leer_estado("limites"),
        fuentes.leer_estado("meta", cuenta=cfg.cuenta.id),
        ahora=ahora,
    )  # fmt: skip
    return trm, rec, props, list(dict.fromkeys(nm))


def _ver(_args: argparse.Namespace, vault: Path, ahora: datetime) -> int:
    cfg = _cargar(vault)
    estado = _estado(vault, cfg)
    trm, rec, props, _nm = _limites(vault, cfg, estado, ahora)
    ruta = escribir_caja(vault, estado, cfg, rec, trm, ahora)
    _log(vault, "ver caja", [str(ruta.relative_to(vault))], ahora)
    for s in SOBRES:
        r = estado.restante[s]
        print(f"{s}: asignado {usd(estado.asignado[s])} · restante {'no medido' if r is None else usd(r)}")
    print("Huecos de test: " + ("no medido" if estado.huecos is None else str(estado.huecos)))
    print(linea_informe(estado))
    print("Tope diario recomendado: " + ("no medido" if rec.tope_diario is None else f"{usd(rec.tope_diario)} USD"))
    print(
        "Límite de cuenta recomendado: "
        + ("no medido" if rec.limite_cuenta_restante is None else f"{usd(rec.limite_cuenta_restante)} USD")
    )
    for m in dict.fromkeys(rec.motivos):
        print(f"  {m}")
    if props:
        print(f"Propuestas de límites por depositar: {len(props)} (`trovefy caja proponer-limites`)")
    else:
        print("Propuestas de límites por depositar: ninguna")
    print(f"Escrito {ruta.relative_to(vault)}")
    return 0


def _mover(args: argparse.Namespace, vault: Path, ahora: datetime) -> int:
    cfg = _cargar(vault)
    estado = _estado(vault, cfg)
    importe = _decimal(args.importe, "--importe")
    centavos = importe * 100
    if centavos != centavos.to_integral_value():
        raise _Salida(2, f"--importe: máximo 2 decimales ({args.importe!r})")
    try:
        ruta, m = mover(vault, args.de, args.a, int(centavos), args.cita, estado, ahora)
    except MovimientoInvalido as e:
        raise _Salida(2, str(e)) from None
    rel = str(ruta.relative_to(vault))
    _log(vault, f"mover {usd(m.usd_centavos)} USD de {m.origen} a {m.destino}", [rel, "ledger/caja/movimientos.csv"], ahora)
    print(f"Movido {usd(m.usd_centavos)} USD de {m.origen} a {m.destino}. Decisión: {rel}")
    return 0


def _anotar(args: argparse.Namespace, vault: Path, ahora: datetime) -> int:
    cfg = _cargar(vault)
    importe = _decimal(args.importe, "--importe")
    trm = _trm(vault, ahora.astimezone(ZONA_NEGOCIO).date()) if args.moneda == "COP" else None
    try:
        m = anotar_herramienta(vault, importe, args.moneda, args.nota, trm, ahora)
    except MovimientoInvalido as e:
        raise _Salida(2, str(e)) from None
    _log(vault, f"anotar herramienta {usd(m.usd_centavos)} USD", ["ledger/caja/movimientos.csv"], ahora)
    print(f"Anotado {usd(m.usd_centavos)} USD en herramientas.")
    r = _estado(vault, cfg).restante["herramientas"]
    if r is not None and r < 0:
        print("Aviso: sobre Herramientas agotado: para y avisa")
    return 0


def _proponer(_args: argparse.Namespace, vault: Path, ahora: datetime) -> int:
    cfg = _cargar(vault)
    estado = _estado(vault, cfg)
    _, _, props, nm = _limites(vault, cfg, estado, ahora)
    ids: list[str] = []
    try:
        for p in props:
            ids.append(fuentes.depositar(vault, p, lambda: ahora))
    except fuentes.BuzonNoDisponible as e:
        for i in ids:
            print(f"Depositada: {i}")
        print(f"No se pudo depositar: {e}", file=sys.stderr)
        return 1
    finally:
        if ids:
            _log(vault, "proponer límites: " + ", ".join(ids), [], ahora)
    for i in ids:
        print(f"Depositada: {i}")
    for m in nm:
        print(m)
    if not ids and not nm:
        print("Nada que proponer: los límites vivos ya coinciden con la recomendación.")
    return 0


def _ejecutar(args: argparse.Namespace) -> int:
    vault, ahora = _vault(), _ahora()
    accion = {
        "iniciar": _iniciar, "ver": _ver, "mover": _mover,
        "anotar": _anotar, "proponer-limites": _proponer,
    }[args.accion]  # fmt: skip
    try:
        return accion(args, vault, ahora)
    except _Salida as e:
        print(f"Error: {e}", file=sys.stderr)
        return e.codigo


registrar("caja", _configurar, _ejecutar, ayuda="sobres, huecos de test y límites propuestos")
