"""Subcomando `trovefy vigia`: salud del sistema, solo lectura."""
from __future__ import annotations

import argparse
from datetime import datetime

from trovefy.aprobaciones import fuentes
from trovefy.cli import registrar
from trovefy.rutinas import registrar_ejecucion
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.rutas import vault_root
from trovefy.vigia import comprobaciones as c


def _configurar(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rutina", action="store_true", help="deja el informe en rutinas/log/<día>/vigia.md; no pregunta")
    p.add_argument("--sin-alerta", action="store_true", help="solo informa: no deposita ninguna alerta")


def _ejecutar(args: argparse.Namespace) -> int:
    vault = vault_root()
    ahora = datetime.now(ZONA_NEGOCIO)
    res = c.vigilar(vault, ahora, c.fuentes_por_defecto())
    texto = c.informe(res)
    datos = None if args.sin_alerta else c.alerta(res)
    if datos is not None:
        try:
            fuentes.depositar(vault, datos, lambda: ahora)
            texto += "\nAlerta propuesta por el buzón.\n"
        except fuentes.BuzonNoDisponible as e:
            texto += f"\nno medido: aviso por Telegram ({e})\n"
    texto = fuentes.enmascarar_cuentas(texto)
    print(texto, end="")
    if args.rutina:
        registrar_ejecucion(vault, "vigia", ahora.date(), texto, ok=True, ahora=ahora)
    return 0


registrar("vigia", _configurar, _ejecutar, ayuda="salud del sistema, solo lectura")
