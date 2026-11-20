"""Un envío de pago de la tanda (voz, clip, música) con la misma disciplina que el lote de imágenes (plan 21).

Orden: STOP → coste aprobado por el usuario (``Destino.permiso``) → cerrojo de la tanda → no reenviar lo que tenga
un envío sin respuesta o una tarea en vuelo → tope (si se supera: alerta al buzón y nada sale) → fila ``enviando``
en el libro **antes** del POST → POST → ``enviada`` con su ``task_id`` (las tareas) → sondeo → descarga sin clave →
medio registrado y fila ``completada``. Un POST sin respuesta queda ``enviando``: pudo cobrarse, cuenta su estimado
y nunca se reenvía solo.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trovefy.apimart.cliente import EstadoTarea
from trovefy.apimart.gasto import (
    FilaCoste,
    TopeSuperado,
    anotar_coste,
    avisar_tope,
    comprobar_tope,
    gastado_usd,
    leer_costes,
)
from trovefy.apimart.lote import (
    MOTIVO_SIN_RESPUESTA,
    MOTIVO_STOP,
    Destino,
    _anotar_intento,
    _bloqueo,
    _cerrojo,
    _ultimas,
)
from trovefy.aprobaciones import fuentes


@dataclass(frozen=True)
class Envio:
    id: str
    estado: str  # completada | fallida | pendiente | simulada | detenido
    archivo: Path | None = None
    motivo: str | None = None
    alerta_id: str | None = None
    coste_usd: Decimal | None = None


def _stop(vault: Path) -> bool:
    return (Path(vault) / ".trovefy" / "STOP").exists()


def _preparar(vault: Path, p_id: str, d: Destino, pieza: str, id_: str, modelo: str, estimado: Decimal, fuente: str,
              ahora: Callable[[], datetime], simular: bool, depositar) -> FilaCoste | Envio:
    filas = leer_costes(vault, p_id, d.raiz_libro)
    bloqueo = _bloqueo(filas, pieza, id_)
    if bloqueo == "sin_respuesta":
        return Envio(id_, "pendiente", motivo=MOTIVO_SIN_RESPUESTA)
    if bloqueo == "en_vuelo":
        return Envio(id_, "pendiente", motivo="tarea en vuelo: --reanudar")
    base = FilaCoste(fecha=ahora(), producto=p_id, pieza=pieza, imagen=id_, intento=str(uuid.uuid4()), task_id="",
                     modelo=modelo, resolucion="", proporcion="", estado="enviando", coste_estimado_usd=estimado,
                     coste_real_usd=None, fuente_precio=fuente, sha256="", archivo="")
    simuladas = sum((f.coste_estimado_usd or Decimal(0)) for f in _ultimas(filas).values()
                    if f.estado == "simulada" and simular)
    gastado = gastado_usd(filas)
    tope = d.tope()
    try:
        comprobar_tope(gastado + simuladas, estimado, tope)
    except TopeSuperado as exc:
        motivo = (f"tope: gastado {exc.gastado} USD + {exc.estimado} USD superaría el tope de {exc.tope} USD; "
                  f"no se envía {id_}")
        if simular:
            return Envio(id_, "detenido", motivo=motivo)
        alerta = avisar_tope(vault, p_id, gastado, tope, 1, estimado, ahora(), depositar, pieza=pieza, imagen=id_,
                             modelo=modelo, fuente_precio=fuente, raiz=d.raiz_libro, origen=d.skill, quien=d.quien)
        return Envio(id_, "detenido", motivo=motivo, alerta_id=alerta)
    return base


def enviar(vault: Path, p_id: str, d: Destino, *, pieza: str, id_: str, modelo: str, estimado: Decimal, fuente: str,
           prompt_sha: str, llamar: Callable[[], bytes | str], guardar: Callable[[bytes, EstadoTarea | None], Path],
           ahora: Callable[[], datetime], simular: bool = False, depositar=fuentes.depositar,
           esperar: Callable[[str], EstadoTarea] | None = None,
           descargar: Callable[[str], bytes] | None = None) -> Envio:
    """Un envío. Síncrono (``llamar`` devuelve los bytes) o asíncrono (``llamar`` devuelve el ``task_id`` y hacen
    falta ``esperar`` y ``descargar``). ``guardar(bytes, estado)`` escribe el medio y devuelve su ruta."""
    vault = Path(vault)
    if _stop(vault):
        return Envio(id_, "detenido", motivo=MOTIVO_STOP)
    if not simular and (sin_permiso := d.permiso()):
        return Envio(id_, "detenido", motivo=sin_permiso)
    with _cerrojo(d):
        base = _preparar(vault, p_id, d, pieza, id_, modelo, estimado, fuente, ahora, simular, depositar)
        if isinstance(base, Envio):
            return base
        if simular:
            anotar_coste(vault, p_id, replace(base, estado="simulada"), d.raiz_libro)
            return Envio(id_, "simulada", coste_usd=estimado)
        if _stop(vault):
            return Envio(id_, "detenido", motivo=MOTIVO_STOP)
        anotar_coste(vault, p_id, base, d.raiz_libro)
        _anotar_intento(d, base.intento, prompt_sha)
        try:
            respuesta = llamar()
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del POST: pudo cobrarse, no se reenvía solo
            return Envio(id_, "pendiente", motivo=f"{MOTIVO_SIN_RESPUESTA} ({type(exc).__name__}: {str(exc)[:120]})")
        if isinstance(respuesta, bytes):
            return _cerrar(vault, p_id, d, base, respuesta, None, guardar, ahora)
        base = replace(base, task_id=respuesta)
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="enviada"), d.raiz_libro)
        if esperar is None or descargar is None:
            return Envio(id_, "pendiente", motivo="tarea enviada: --reanudar")
        return _sondear(vault, p_id, d, base, esperar, descargar, guardar, ahora)


def _cerrar(vault: Path, p_id: str, d: Destino, base: FilaCoste, datos: bytes, estado: EstadoTarea | None,
            guardar, ahora) -> Envio:
    ruta = guardar(datos, estado)
    real = estado.coste_real_usd if estado and estado.coste_real_usd and estado.coste_real_usd > 0 else None
    anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="completada", coste_real_usd=real,
                                      sha256=hashlib.sha256(datos).hexdigest(),
                                      archivo=Path(ruta).relative_to(d.raiz_libro).as_posix()), d.raiz_libro)
    return Envio(base.imagen, "completada", archivo=Path(ruta), coste_usd=real or base.coste_estimado_usd)


def _sondear(vault, p_id, d, base: FilaCoste, esperar, descargar, guardar, ahora) -> Envio:
    estado = esperar(base.task_id)
    if estado.estado == "fallida":
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="fallida", coste_real_usd=estado.coste_real_usd),
                     d.raiz_libro)
        return Envio(base.imagen, "fallida", motivo=estado.motivo)
    if estado.estado == "pendiente":
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="pendiente"), d.raiz_libro)
        return Envio(base.imagen, "pendiente", motivo=estado.motivo or "sin terminar: --reanudar")
    try:
        datos = descargar(estado.url)
    except Exception as exc:  # noqa: BLE001 - completada pero sin descargar: se reanuda con el mismo task_id
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="pendiente"), d.raiz_libro)
        return Envio(base.imagen, "pendiente", motivo=f"sin descargar ({type(exc).__name__}): --reanudar")
    return _cerrar(vault, p_id, d, base, datos, estado, guardar, ahora)


def reanudar(vault: Path, p_id: str, d: Destino, pieza: str, *, esperar: Callable[[str], EstadoTarea],
             descargar: Callable[[str], bytes], guardar_de: Callable[[str], Callable],
             ahora: Callable[[], datetime]) -> list[Envio]:
    """Sondea las tareas de ``pieza`` que quedaron ``enviada``/``pendiente`` con ``task_id``. Nunca reenvía."""
    vault = Path(vault)
    if _stop(vault):
        return [Envio("*", "detenido", motivo=MOTIVO_STOP)]
    salida = []
    with _cerrojo(d):
        for f in _ultimas(leer_costes(vault, p_id, d.raiz_libro)).values():
            if f.pieza != pieza:
                continue
            if f.estado == "enviando":
                salida.append(Envio(f.imagen, "pendiente", motivo=MOTIVO_SIN_RESPUESTA))
            elif f.estado in ("enviada", "pendiente") and f.task_id:
                salida.append(_sondear(vault, p_id, d, f, esperar, descargar, guardar_de(f.imagen), ahora))
    return salida


def ya_hecho(manifiesto: dict, id_: str, prompt_sha: str) -> bool:
    previa = manifiesto.get(id_) or {}
    return previa.get("prompt_sha256") == prompt_sha
