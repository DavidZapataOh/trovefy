"""Comprobaciones de salud de /vigia: solo lectura, sin red salvo el saldo de APIMart.

Lo que no se puede medir hoy es ``no_medido`` con su motivo; nunca alerta, nunca es 0.
La clave de APIMart se lee de ``claude.env`` y no sale en ningún texto.
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

from trovefy.aprobaciones.fuentes import (
    Lectura,
    enmascarar_cuentas,
    leer_estado,
    ruta_spool,
)
from trovefy.arranque.verificadores.apimart import BASE_POR_DEFECTO, consultar_saldo
from trovefy.caja.config import cargar_caja
from trovefy.referencia import cache as cache_referencia_mod
from trovefy.rutinas import TIMER_CAZA, directorio_unidades
from trovefy.secretos import RUTA_CLAUDE_ENV, leer_env
from trovefy.vault.escritura import ZONA_NEGOCIO

Nivel = Literal["ok", "info", "aviso", "urgente", "no_medido"]

LATIDO_AVISO = timedelta(minutes=10)
LATIDO_URGENTE = timedelta(hours=2)
DISCO_MIN_LIBRE_PCT = 10  # umbral técnico
DISCO_MIN_LIBRE_BYTES = 2 << 30  # umbral técnico: 2 GiB
TOKEN_AVISO = timedelta(days=7)
META_VIEJA = timedelta(hours=48)
HORA_CAZA = 7
MOTIVO_MCP = "no medido: requiere el MCP oficial de Meta (paso 14) o la lectura del ejecutor (Fase 3)"
_SECCION = re.compile(r"^## .* · (.+?)\s*$", re.MULTILINE)
_ICONO = {"ok": "OK", "info": "INFO", "aviso": "AVISO", "urgente": "URGENTE", "no_medido": "NO MEDIDO"}


@dataclass(frozen=True)
class Comprobacion:
    nombre: str
    nivel: Nivel
    texto: str


@dataclass(frozen=True)
class Fuentes:
    spool: Path
    unidades: Path
    ruta_env: Path
    abrir_apimart: Callable | None = None
    uso_disco: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage
    cache_referencia: Path = field(default_factory=cache_referencia_mod.base_cache)


def fuentes_por_defecto() -> Fuentes:
    return Fuentes(spool=ruta_spool(), unidades=directorio_unidades(), ruta_env=RUTA_CLAUDE_ENV)


def _nm(nombre: str, motivo: str) -> Comprobacion:
    return Comprobacion(nombre, "no_medido", motivo if motivo.startswith("no medido") else f"no medido: {motivo}")


def _fecha(valor: object) -> datetime | None:
    if not isinstance(valor, str):
        return None
    try:
        f = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return f if f.tzinfo else None


def _duracion(d: timedelta) -> str:
    s = int(d.total_seconds())
    if s < 3600:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} días"


def latido(ahora: datetime, lectura: Lectura) -> Comprobacion:
    if lectura.datos is None:
        return _nm("latido", lectura.motivo or "sin latido")
    f = _fecha(lectura.datos.get("fecha"))
    if f is None:
        return _nm("latido", "latido.json sin fecha legible")
    edad = ahora - f
    if edad > LATIDO_URGENTE:
        return Comprobacion("latido", "urgente", f"el ejecutor no late desde hace {_duracion(edad)}")
    if edad > LATIDO_AVISO:
        return Comprobacion("latido", "aviso", f"el último latido del ejecutor fue hace {_duracion(edad)}")
    return Comprobacion("latido", "ok", f"el ejecutor late (hace {_duracion(max(edad, timedelta(0)))})")


def avisos_ejecutor(lectura: Lectura) -> list[Comprobacion]:
    d = lectura.datos
    if d is None:
        return []
    res: list[Comprobacion] = []
    avisos = d.get("avisos")
    for a in avisos if isinstance(avisos, list) else []:
        if isinstance(a, str) and a:
            res.append(Comprobacion("ejecutor", "aviso", f"El ejecutor avisa: {a[:300]}"))
    if d.get("telegram") == "sin red":
        res.append(Comprobacion("telegram", "aviso", "El ejecutor no tiene red para Telegram"))
    if d.get("vault") == "no escribible":
        res.append(Comprobacion("vault", "aviso", "El ejecutor no puede escribir en el vault"))
    return res


def rutinas(vault: Path, ahora: datetime, unidades: Path) -> Comprobacion:
    hoy = ahora.astimezone(ZONA_NEGOCIO)
    if not (Path(unidades) / TIMER_CAZA).exists():
        return _nm("rutinas", "la rutina de caza no está instalada")
    if hoy.weekday() == 6:
        return Comprobacion("rutinas", "ok", "hoy es domingo: no se espera la caza")
    if hoy.hour < HORA_CAZA:
        return Comprobacion("rutinas", "ok", f"aún no son las {HORA_CAZA:02d}:00: la caza de hoy no se exige todavía")
    log = Path(vault) / "rutinas" / "log" / hoy.date().isoformat() / "caza.md"
    try:
        secciones = _SECCION.findall(log.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Comprobacion("rutinas", "aviso", "la caza de hoy no dejó su log")
    except (OSError, UnicodeDecodeError):
        return _nm("rutinas", "no se pudo leer el log de la caza de hoy")
    if not secciones or secciones[-1] != "ok":
        return Comprobacion("rutinas", "aviso", f"la caza de hoy terminó «{secciones[-1] if secciones else 'sin estado'}»")
    return Comprobacion("rutinas", "ok", "la caza de hoy terminó bien")


def _coma(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01'), ROUND_HALF_UP):.2f}".replace(".", ",")


def apimart(ruta_env: Path, aviso_centavos: int | None, abrir: Callable | None = None) -> Comprobacion:
    try:
        env = leer_env(ruta_env)
    except FileNotFoundError:
        return _nm("apimart", "falta claude.env")
    except Exception:  # noqa: BLE001 - permisos, symlink, ilegible: nunca se muestra el contenido
        return _nm("apimart", "claude.env no se puede leer con seguridad")
    clave = env.get("APIMART_API_KEY", "")
    if not clave:
        return _nm("apimart", "falta APIMART_API_KEY en claude.env")
    try:
        r = consultar_saldo(env.get("APIMART_BASE_URL") or BASE_POR_DEFECTO, clave, abrir)
    except Exception:  # noqa: BLE001 - red, JSON, clave rechazada: sin detalles que puedan arrastrar la clave
        return _nm("apimart", "no se pudo consultar el saldo de APIMart")
    saldo = r["saldo"]
    if saldo == "ilimitado":
        return Comprobacion("apimart", "ok", "APIMart sin límite de saldo")
    d = Decimal(str(saldo))
    if aviso_centavos is None:
        return Comprobacion("apimart", "info", f"Quedan {_coma(d)} USD (sin umbral: falta config/caja.yaml)")
    umbral = Decimal(aviso_centavos) / 100
    if d < umbral:
        return Comprobacion("apimart", "aviso", f"Quedan {_coma(d)} USD (aviso por debajo de {_coma(umbral)})")
    return Comprobacion("apimart", "ok", f"Quedan {_coma(d)} USD")


def disco(vault: Path, uso: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage) -> Comprobacion:
    try:
        total, _, libre = uso(Path(vault))
    except OSError:
        return _nm("disco", "no se pudo leer el espacio en disco")
    if total <= 0:
        return _nm("disco", "el disco informa tamaño 0")
    pct = libre * 100 / total
    texto = f"{libre / (1 << 30):.1f} GiB libres ({pct:.0f} %)"
    if pct < DISCO_MIN_LIBRE_PCT or libre < DISCO_MIN_LIBRE_BYTES:
        return Comprobacion("disco", "aviso", f"poco espacio: {texto}")
    return Comprobacion("disco", "ok", texto)


def tokens(ahora: datetime, meta: Lectura) -> Comprobacion:
    if meta.datos is None:
        return _nm("tokens", meta.motivo or "sin meta.json")
    vo = meta.datos.get("validate_only")
    if isinstance(vo, dict) and vo.get("ok") is False:
        motivo = str(vo.get("motivo") or "")[:200]
        if "token" in motivo.lower():
            return Comprobacion("tokens", "urgente", f"el token de Meta falla: {motivo}")
        return Comprobacion("tokens", "aviso", f"la validación de prueba de Meta falló: {motivo or 'sin motivo'}")
    caduca = _fecha(meta.datos.get("token_caduca"))
    if caduca is None:
        return _nm("tokens", "el ejecutor no informa la caducidad del token")
    resto = caduca - ahora
    if resto < timedelta(0):
        return Comprobacion("tokens", "urgente", f"el token de Meta caducó el {caduca:%Y-%m-%d}")
    if resto <= TOKEN_AVISO:
        return Comprobacion("tokens", "aviso", f"el token de Meta caduca el {caduca:%Y-%m-%d}")
    return Comprobacion("tokens", "ok", f"el token de Meta caduca el {caduca:%Y-%m-%d}")


def stop(vault: Path, lectura: Lectura) -> Comprobacion:
    cerebro = (Path(vault) / ".trovefy" / "STOP").exists()
    ejecutor = lectura.datos is not None and lectura.datos.get("activo") is True
    if lectura.datos is None and not cerebro:
        return _nm("stop", lectura.motivo or "sin stop.json")
    if not ejecutor and not cerebro:
        return Comprobacion("stop", "ok", "sin STOP")
    partes = []
    if ejecutor:
        motivo = lectura.datos.get("motivo")  # type: ignore[union-attr]
        partes.append("STOP del ejecutor activo" + (f" ({str(motivo)[:200]})" if motivo else ""))
    if cerebro:
        partes.append("STOP del cerebro activo")
    if lectura.datos is None:
        partes.append("el STOP del ejecutor no se pudo leer")
    return Comprobacion("stop", "info", "; ".join(partes))


def cuenta_meta(meta: Lectura, ahora: datetime | None = None) -> Comprobacion:
    if meta.datos is None:
        return _nm("cuenta", meta.motivo or "sin meta.json")
    estado = meta.datos.get("account_status")
    if isinstance(estado, bool) or not isinstance(estado, int):
        return _nm("cuenta", "meta.json no trae el estado de la cuenta")
    if estado != 1:
        return Comprobacion("cuenta", "urgente", f"la cuenta publicitaria no está activa (account_status {estado})")
    f = _fecha(meta.datos.get("fecha"))
    if ahora is not None and f is not None and ahora - f > META_VIEJA:
        return Comprobacion("cuenta", "info", f"cuenta activa, dato del {f:%Y-%m-%d}")
    return Comprobacion("cuenta", "ok", "cuenta publicitaria activa")


def impultienda(vault: Path) -> Comprobacion:
    ev = Path(vault) / "config" / "evidencia"
    ficheros = sorted(ev.glob("09-*.json")) if ev.is_dir() else []
    if not ficheros:
        return _nm("impultienda", "requiere navegador (pídelo con /arranque 09)")
    m = re.search(r"(\d{4}-\d{2}-\d{2})\.json$", ficheros[-1].name)
    cuando = m.group(1) if m else "fecha desconocida"
    return Comprobacion("impultienda", "info", f"última comprobación de ImpulTienda el {cuando} (no se revisa en vivo)")


def _retencion_referencia(vault: Path) -> int:
    try:
        from trovefy.referencia.config import cargar_umbrales_referencia

        return cargar_umbrales_referencia(vault).retencion_dias
    except (OSError, ValueError, KeyError, TypeError):  # umbrales ilegibles: la vigía no cae, usa el valor por defecto
        return cache_referencia_mod.RETENCION_DIAS


def referencia_cache(ahora: datetime, base: Path, retencion_dias: int = cache_referencia_mod.RETENCION_DIAS) -> Comprobacion:
    base = Path(base)
    if not base.is_dir():
        return Comprobacion("referencia", "ok", "sin medios de referencia")
    try:
        n = len(cache_referencia_mod.vencidos(ahora, base, retencion_dias))
    except OSError as e:
        return Comprobacion(
            "referencia", "aviso", f"no se pudo leer la caché de medios de referencia ({type(e).__name__})")
    if n:
        return Comprobacion(
            "referencia", "aviso",
            f"{n} carpetas o lotes de referencia pasaron sus {retencion_dias} días: `trovefy ver-anuncios limpiar`")
    return Comprobacion("referencia", "ok", "medios de referencia dentro de plazo")


def no_medidas() -> list[Comprobacion]:
    return [Comprobacion(n, "no_medido", MOTIVO_MCP) for n in
            ("anuncios rechazados", "eventos del dataset en 24 h", "restricciones del Business",
             "spend_cap de campañas vivas")]


def vigilar(vault: Path, ahora: datetime, fuentes: Fuentes) -> list[Comprobacion]:
    vault = Path(vault)
    try:
        caja = cargar_caja(vault)
        cuenta, aviso = caja.cuenta.id, caja.apimart_aviso
    except Exception:  # noqa: BLE001 - sin caja no hay cuenta ni umbral; no es alarma
        cuenta, aviso = None, None
    lat = leer_estado("latido", fuentes.spool)
    meta = leer_estado("meta", fuentes.spool, cuenta)
    res = [latido(ahora, lat), *avisos_ejecutor(lat),
           stop(vault, leer_estado("stop", fuentes.spool)),
           tokens(ahora, meta), cuenta_meta(meta, ahora),
           apimart(fuentes.ruta_env, aviso, fuentes.abrir_apimart),
           disco(vault, fuentes.uso_disco),
           rutinas(vault, ahora, fuentes.unidades),
           impultienda(vault), referencia_cache(ahora, fuentes.cache_referencia, _retencion_referencia(vault)), *no_medidas()]
    return res


def alerta(comprobaciones: list[Comprobacion]) -> dict | None:
    malas = [x for x in comprobaciones if x.nivel in ("aviso", "urgente")]
    if not malas:
        return None
    nivel = "urgente" if any(x.nivel == "urgente" for x in malas) else "aviso"
    return {"tipo": "alerta", "origen": "/vigia", "nivel": nivel, "titulo": f"Vigía: {len(malas)} avisos",
            "texto": enmascarar_cuentas("\n".join(f"{x.nombre}: {x.texto}" for x in malas))[:3000]}


def informe(comprobaciones: list[Comprobacion]) -> str:
    return enmascarar_cuentas("\n".join(f"- {_ICONO[x.nivel]} · {x.nombre}: {x.texto}" for x in comprobaciones)) + "\n"
