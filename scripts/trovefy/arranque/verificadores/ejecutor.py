"""Pasos 12 (emparejamiento de Telegram) y 13 (cuenta de Meta vía ``meta.json``).

Solo LEEN ``estado/*.json`` del spool del ejecutor (a través de ``trovefy.aprobaciones.fuentes``): sin sudo, sin
secretos, sin red ni navegador. Dato ausente = «no medido: motivo».
"""

import json
import re
from datetime import datetime
from pathlib import Path

import yaml
from trovefy_ejecutor.dinero import OFFSETS_OFICIALES

from trovefy.aprobaciones import fuentes
from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import guardar_evidencia
from trovefy.secretos import RevisionSecretosNoDisponible, buscar_secreto

EJECUTOR = "/home/trovefy-exec/.local/bin/trovefy-ejecutor"
ARREGLO_EMPAREJAR = f"sudo -u trovefy-exec {EJECUTOR} emparejar"
ARREGLO_META = f"sudo -u trovefy-exec {EJECUTOR} comprobar-meta"
ARREGLO_ARRANQUE = "sudo systemctl start trovefy-ejecutor"
ARREGLO_REINICIO = "sudo systemctl restart trovefy-ejecutor"
LATIDO_MAX_S = 600
D37 = "Moneda COP y hora America/Bogota por decisión del usuario (D-37); los límites del ejecutor van en COP"


class EstadoNoDisponible(Exception):
    def __init__(self, motivo: str, arreglos: list[str] | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.arreglos = arreglos or []


def raiz_spool() -> Path:
    return fuentes.ruta_spool()


def _quitar_prefijo(motivo: str) -> str:
    return motivo.removeprefix("no medido: ")


def _leer(nombre: str, raiz: Path | None, cuenta: str | None = None) -> dict | None:
    """Datos del estado, None si el archivo falta, o ``EstadoNoDisponible`` (nunca muestra su contenido)."""
    lectura = fuentes.leer_estado(nombre, raiz, cuenta=cuenta)
    if lectura.datos is None:
        motivo = _quitar_prefijo(lectura.motivo or "")
        if motivo.startswith("el ejecutor no ha escrito"):
            return None
        if "sin permiso" in motivo:
            motivo = "tu usuario no está en el grupo trovefy (cierra y abre la terminal y Claude Code tras instalar)"
            raise EstadoNoDisponible(motivo, ["añade tu usuario al grupo trovefy y abre una terminal nueva"])
        if "aún no está instalado" in motivo:
            motivo = "el ejecutor no está instalado (no existe su carpeta de estado)"
        raise EstadoNoDisponible(fuentes.enmascarar_cuentas(motivo))
    try:
        secreto = buscar_secreto(json.dumps(lectura.datos, ensure_ascii=False))
    except RevisionSecretosNoDisponible:
        raise EstadoNoDisponible("no se pudo revisar si el estado lleva secretos; no se lee") from None
    if secreto:
        raise EstadoNoDisponible("el estado del ejecutor lleva algo que parece un secreto; no se lee")
    return lectura.datos


def leer_estado(nombre: str, raiz: Path | None = None) -> dict | None:
    return _leer(nombre, raiz)


def _no_medido(e: EstadoNoDisponible) -> ResultadoVerificacion:
    return ResultadoVerificacion(None, [], f"no medido: {e.motivo}", e.arreglos)


def _latido(raiz: Path | None) -> str:
    """«late», «viejo» (hubo latido pero de hace más de 10 min) o «ausente» (el servicio aún no ha arrancado)."""
    try:
        d = _leer("latido", raiz)
    except EstadoNoDisponible:
        return "ausente"
    if d is None:
        return "ausente"
    try:
        fecha = datetime.fromisoformat(d["fecha"])
        edad = (datetime.now(fecha.tzinfo) - fecha).total_seconds()
    except (KeyError, ValueError, TypeError):
        return "viejo"
    return "late" if edad <= LATIDO_MAX_S else "viejo"


@verificador("12")
def verificar_bot(vault: Path, raiz: Path | None = None) -> ResultadoVerificacion:
    try:
        datos = _leer("emparejamiento", raiz)
    except EstadoNoDisponible as e:
        return _no_medido(e)
    if not datos or datos.get("emparejado") is not True:
        return ResultadoVerificacion(
            False, [], "el bot de Telegram aún no está emparejado contigo", [ARREGLO_EMPAREJAR],
            lineas=["escribe al bot desde tu Telegram cuando el comando lo pida"],
        )
    ev = guardar_evidencia(vault, "12", "emparejamiento", {"emparejado": True, "fecha": datos.get("fecha")})
    arreglos: list[str] = []
    lineas = ["✓ el bot de Telegram está emparejado"]
    latido = _latido(raiz)
    if latido == "ausente":  # sin META_TOKEN, `servir` sale con 2: se arranca en el 13, con los dos tokens
        lineas.append("el servicio arranca en el paso 13")
    elif latido == "viejo":
        arreglos.append(ARREGLO_REINICIO)
        lineas.append("el servicio del ejecutor no late (latido de hace más de 10 min o ilegible)")
    return ResultadoVerificacion(True, [ev], "bot de Telegram emparejado", arreglos, lineas=lineas)


def _cuenta_y_decision(vault: Path) -> tuple[str | None, str | None, str | None]:
    p = next((p for p in cargar(vault) if p.id == "06"), None)
    d = p.datos if p else {}
    act = d.get("act_id")
    if not (act and re.fullmatch(r"\d+", act)):
        try:
            cfg = yaml.safe_load((Path(vault) / "config" / "caja.yaml").read_text(encoding="utf-8")) or {}
            act = str(cfg["cuenta"]["id"]).removeprefix("act_")
        except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError):
            act = None
    return (f"act_{act}" if act else None), d.get("moneda"), d.get("zona")


def _fallo(motivo: str) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, [], motivo, [ARREGLO_META])


OFFSET_SIN_FIJAR = "no medido: el offset aún no está fijado en limites.yaml (repite comprobar-meta)"


def _offset_de_limites(raiz: Path | None, cuenta: str) -> object:
    """``estado/limites.json`` → ``cuentas[cuenta].offset`` (lo fija ``comprobar-meta``); None si falta."""
    try:
        lim = _leer("limites", raiz) or {}
    except EstadoNoDisponible:
        return None
    cuentas = lim.get("cuentas")
    c = cuentas.get(cuenta) if isinstance(cuentas, dict) else None
    off = c.get("offset") if isinstance(c, dict) else None
    return off if isinstance(off, int) and not isinstance(off, bool) else None


@verificador("13")
def verificar_meta(vault: Path, raiz: Path | None = None) -> ResultadoVerificacion:
    cuenta, moneda_06, zona_06 = _cuenta_y_decision(vault)
    if cuenta is None:
        return ResultadoVerificacion(
            None, [], "no medido: falta la cuenta del paso 06", ["completa y verifica el paso 06"]
        )
    try:
        m = _leer("meta", raiz, cuenta=cuenta)
    except EstadoNoDisponible as e:
        return _no_medido(e)
    if m is None:
        return _fallo("el ejecutor aún no ha comprobado la cuenta de Meta (falta meta.json)")
    moneda, offset, zona = m.get("currency"), m.get("offset"), m.get("timezone_name")
    valida = m.get("validate_only") if isinstance(m.get("validate_only"), dict) else {}
    if m.get("account_status") != 1:
        return _fallo("la cuenta no está activa en Meta")
    if moneda_06 and moneda != moneda_06:
        return _fallo(f"la moneda de Meta ({moneda}) no coincide con la del paso 06 ({moneda_06})")
    if zona_06 and zona != zona_06:
        return _fallo(f"la zona horaria de Meta ({zona}) no coincide con la del paso 06 ({zona_06})")
    if offset is None or isinstance(offset, bool) or not isinstance(offset, int):
        return _fallo("offset sin confirmar (P-21)")
    if moneda not in OFFSETS_OFICIALES:
        return ResultadoVerificacion(
            None, [], "no medido: moneda sin offset oficial confirmado (P-21)", [ARREGLO_META]
        )
    if offset != OFFSETS_OFICIALES[moneda]:
        return _fallo(f"el offset {offset} no es el oficial de {moneda} ({OFFSETS_OFICIALES[moneda]})")
    if valida.get("ok") is not True:
        return _fallo(f"validate_only falló: {valida.get('motivo') or 'sin motivo'}")
    if _offset_de_limites(raiz, cuenta) != offset:
        arreglos = [ARREGLO_META] + ([ARREGLO_ARRANQUE] if _latido(raiz) == "ausente" else [])
        return ResultadoVerificacion(None, [], OFFSET_SIN_FIJAR, arreglos)  # limites.json lo escribe el servicio
    campos = {
        "cuenta": cuenta, "moneda": moneda, "offset": str(offset), "zona": zona,
        "spend_cap": str(m.get("spend_cap")), "amount_spent": str(m.get("amount_spent")),
    }
    ev = guardar_evidencia(vault, "13", "meta", {**campos, "validate_only": {"ok": True}})
    lineas = [fuentes.enmascarar_cuentas(f"✓ cuenta {cuenta}"), f"✓ moneda {moneda}, offset {offset}, hora {zona}"]
    if moneda == "COP" and zona == "America/Bogota":
        lineas.append(D37)
    return ResultadoVerificacion(
        True, [ev], f"cuenta de Meta en {moneda}, offset oficial {offset}",
        [], {**campos, "cuenta": fuentes.enmascarar_cuentas(cuenta)}, lineas,
    )
