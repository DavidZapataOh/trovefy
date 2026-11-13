"""Funciones puras del instalador (plan 12, tarea 7). No ejecuta nada del sistema.

Uso desde el instalador (sin ``trovefy`` instalado, solo stdlib + PyYAML):

    python -I -m trovefy_ejecutor.instalacion cuenta <arranque.yaml>             -> "act moneda zona"
    python -I -m trovefy_ejecutor.instalacion limites <plantilla> <act> <moneda> <zona>  -> YAML
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .graph import OFFSETS_META
from .limites import cargar_limites

CUENTA_PLANTILLA = "act_0000000000000000"
_FALTA = "completa el paso 06 de /arranque (cuenta publicitaria)"


class OffsetDistinto(ValueError):
    """Meta confirma un offset distinto del ya instalado: no se toca nada."""


def cuenta_de_arranque(ruta: Path) -> tuple[str, str, str]:
    try:
        crudo = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        raise ValueError(_FALTA) from None
    pasos = crudo.get("pasos") if isinstance(crudo, dict) else None
    if not isinstance(pasos, list):
        raise ValueError(_FALTA)  # noqa: TRY004
    datos: object = None
    for p in pasos:
        if isinstance(p, dict) and str(p.get("id")) == "06":
            datos = p.get("datos")
            break
    if not isinstance(datos, dict):
        raise ValueError(_FALTA)  # noqa: TRY004
    act = str(datos.get("act_id") or "").strip()
    moneda = str(datos.get("moneda") or "").strip().upper()
    zona = str(datos.get("zona") or "").strip()
    act = act if act.startswith("act_") else f"act_{act}" if act else ""
    if not re.fullmatch(r"act_[0-9]+", act) or not re.fullmatch(r"[A-Z]{3}", moneda) or not zona:
        raise ValueError(_FALTA)
    try:
        ZoneInfo(zona)
    except Exception:  # noqa: BLE001 — zona desconocida o mal formada
        raise ValueError(_FALTA) from None
    return act, moneda, zona


def _linea_del_bloque(lineas: list[str], act_id: str, clave: str) -> int:
    """Índice de la línea ``clave:`` dentro de la sección ``cuentas.<act_id>``."""
    inicio = next((i for i, ln in enumerate(lineas) if re.fullmatch(rf"\s+{re.escape(act_id)}:\s*(#.*)?", ln)), None)
    if inicio is None:
        raise ValueError(f"limites.yaml: no se encuentra la sección de {act_id}")
    sangria = len(lineas[inicio]) - len(lineas[inicio].lstrip())
    for i in range(inicio + 1, len(lineas)):
        ln = lineas[i]
        if ln.strip() and not ln.lstrip().startswith("#") and len(ln) - len(ln.lstrip()) <= sangria:
            break
        if re.match(rf"\s+{clave}:", ln):
            return i
    raise ValueError(f"limites.yaml: falta «{clave}» en {act_id}")


def _poner(lineas: list[str], act_id: str, clave: str, valor: str) -> None:
    i = _linea_del_bloque(lineas, act_id, clave)
    sangria = lineas[i][: len(lineas[i]) - len(lineas[i].lstrip())]
    lineas[i] = f"{sangria}{clave}: {valor}"


def limites_para_cuenta(plantilla: str, act_id: str, moneda: str, zona: str) -> str:
    if not re.fullmatch(r"act_[0-9]+", act_id):
        raise ValueError("cuenta: debe ser act_<dígitos>")
    if not re.fullmatch(r"[A-Z]{3}", moneda):
        raise ValueError("moneda: código de tres letras mayúsculas")
    if moneda != "COP":
        # Los importes de la plantilla están en unidades mínimas de COP (offset 1); en otra moneda serían
        # otra cantidad de dinero. Mejor no generar nada que generar un tope equivocado.
        raise ValueError(f"la plantilla de límites está en COP; ajusta los importes a mano para {moneda} (P-21)")
    try:
        ZoneInfo(zona)
    except Exception:  # noqa: BLE001
        raise ValueError(f"zona horaria desconocida: {zona}") from None
    texto = plantilla.replace(CUENTA_PLANTILLA, act_id)
    lineas = texto.split("\n")
    _poner(lineas, act_id, "moneda", moneda)
    _poner(lineas, act_id, "zona_horaria", zona)
    # offset: null ya viene en la plantilla; se fuerza por si alguien la editó.
    i = _linea_del_bloque(lineas, act_id, "offset")
    sangria = lineas[i][: len(lineas[i]) - len(lineas[i].lstrip())]
    lineas[i] = f"{sangria}offset: null"
    return "\n".join(lineas)


def fijar_offset(limites_yaml: Path, meta: dict) -> int | None:
    """Escribe el offset confirmado por Meta si coincide la moneda. Devuelve el offset escrito o ``None``.

    No toca nada si la moneda no coincide, si el offset ya es ese, o si Meta no lo da. Si ya hay otro
    offset distinto, lanza ``OffsetDistinto`` (no se sobrescribe nunca)."""
    limites_yaml = Path(limites_yaml)
    lim = cargar_limites(limites_yaml, exigir_0600=False)
    act = meta.get("cuenta")
    if not isinstance(act, str):
        if len(lim.cuentas_permitidas) != 1:
            return None
        act = next(iter(lim.cuentas_permitidas))
    cuenta = lim.cuentas.get(act)
    moneda, offset = meta.get("currency"), meta.get("offset")
    if cuenta is None or type(offset) is not int or moneda != cuenta.moneda_codigo:
        return None
    if OFFSETS_META.get(moneda) != offset:
        return None
    if cuenta.offset == offset:
        return None
    if cuenta.offset is not None:
        raise OffsetDistinto("offset distinto del instalado: revisa (P-21)")
    lineas = limites_yaml.read_text(encoding="utf-8").split("\n")
    i = _linea_del_bloque(lineas, act, "offset")
    sangria = lineas[i][: len(lineas[i]) - len(lineas[i].lstrip())]
    lineas[i] = f"{sangria}offset: {offset}"
    tmp = limites_yaml.with_name(f".{limites_yaml.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas))
            f.flush()
            os.fsync(f.fileno())
        if cargar_limites(tmp, exigir_0600=False).cuentas[act].offset != offset:
            raise ValueError("limites.yaml: el offset escrito no se lee de vuelta")
        os.replace(tmp, limites_yaml)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return offset


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == "cuenta":
            print(" ".join(cuenta_de_arranque(Path(args[1]))))
            return 0
        if len(args) == 5 and args[0] == "limites":
            sys.stdout.write(limites_para_cuenta(Path(args[1]).read_text(encoding="utf-8"), *args[2:]))
            return 0
    except (ValueError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print("uso: instalacion cuenta <arranque.yaml> | limites <plantilla> <act> <moneda> <zona>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
