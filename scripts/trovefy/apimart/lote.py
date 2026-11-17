"""Lote de imágenes de APIMart: STOP, precio medido, ``flock``, tope, idempotencia y reanudar.

Orden de cada lote (plan 17, Tarea 5): STOP → precio medido → ``flock`` exclusivo sobre
``entregable/.apimart.lock`` durante todo el lote → por cada petición: omitir si ya está generada con el
mismo prompt, proporción y resolución; no reenviar si tiene una tarea ``pendiente``/``enviada``;
``comprobar_tope``; anotar ``enviando`` **antes** del POST; ``enviada`` con su ``task_id``; sondear;
descargar sin clave y registrar el medio. El saldo de ``/v1/balance`` nunca se consulta: el tope manda.

Una tarea enviada puede estar cobrada aunque no llegue respuesta: cuenta su estimado y nunca se reenvía;
``reanudar`` sondea el mismo ``task_id``. El ``prompt_sha256`` de cada intento se guarda en
``entregable/.apimart-intentos.jsonl`` (solo de añadir) para que ``reanudar`` registre el medio con el
prompt que se envió de verdad, no con el que haya hoy en ``imagenes.yaml``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from trovefy.apimart.cliente import (
    EstadoTarea,
    PeticionImagen,
    PeticionInvalida,
    cuerpo_envio,
    descargar,
    enviar,
    esperar,
    formato_imagen,
    validar,
)
from trovefy.apimart.gasto import (
    FilaCoste,
    TopeSuperado,
    anotar_coste,
    avisar_tope,
    comprobar_tope,
    gastado_usd,
    leer_costes,
)
from trovefy.apimart.http import Credenciales, ErrorApimart
from trovefy.apimart.precios import Precio
from trovefy.apimart.subidas import subir
from trovefy.aprobaciones import fuentes
from trovefy.config.yaml_config import cargar_yaml
from trovefy.producto import rutas
from trovefy.producto.config import ConfigProducto, tope_de
from trovefy.producto.medios import (
    CARPETA,
    escribir_medio,
    leer_manifiesto,
    registrar_medio,
)
from trovefy.vault.escritura import anadir_log

SKILL = "/producto"
CERROJO = ".apimart.lock"
INTENTOS = ".apimart-intentos.jsonl"
PETICIONES = "imagenes.yaml"
MOTIVO_STOP = "STOP del cerebro activo: no se genera nada"
MOTIVO_SIN_PRECIO = "no medido: precio de APIMart; no se genera nada"
_CLAVES = {"id", "pieza", "prompt", "proporcion", "resolucion", "referencias"}
_OBLIGATORIAS = _CLAVES - {"referencias"}


@dataclass(frozen=True)
class ResultadoLote:
    generadas: tuple[str, ...]
    omitidas: tuple[str, ...]
    pendientes: tuple[str, ...]
    fallidas: tuple[str, ...]
    detenido: str | None
    alerta_id: str | None


def leer_peticiones(vault: Path, p_id: str) -> list[PeticionImagen]:
    """Lee ``entregable/imagenes.yaml`` (lista de ``{id, pieza, prompt, proporcion, resolucion, referencias}``).

    ``FileNotFoundError`` si falta; ``PeticionInvalida`` si la forma no cuadra o hay ids repetidos.
    """
    ruta = rutas.entregable(vault, p_id) / PETICIONES
    if not ruta.is_file():
        raise FileNotFoundError(f"falta productos/{p_id}/entregable/{PETICIONES}")
    try:
        datos = cargar_yaml(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PeticionInvalida(f"{PETICIONES} no se puede leer: {exc}") from None
    if not isinstance(datos, list):
        raise PeticionInvalida(f"{PETICIONES} debe ser una lista de imágenes")
    salida, vistos = [], set()
    for n, d in enumerate(datos, start=1):
        if not isinstance(d, dict) or not _OBLIGATORIAS <= set(d) or not set(d) <= _CLAVES:
            raise PeticionInvalida(f"{PETICIONES}, imagen {n}: usa solo {', '.join(sorted(_CLAVES))}")
        refs = d.get("referencias") or []
        textos = [d[k] for k in sorted(_OBLIGATORIAS)]
        if not all(isinstance(x, str) for x in textos) or not isinstance(refs, list) \
                or not all(isinstance(r, str) for r in refs):
            raise PeticionInvalida(f"{PETICIONES}, imagen {n}: los campos son textos y referencias una lista")
        if d["id"] in vistos:
            raise PeticionInvalida(f"{PETICIONES}: el id «{d['id']}» está repetido")
        vistos.add(d["id"])
        salida.append(PeticionImagen(d["id"], d["pieza"], d["prompt"], d["proporcion"], d["resolucion"],
                                     tuple(refs)))
    return salida


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@contextmanager
def _cerrojo(vault: Path, p_id: str) -> Iterator[None]:
    ruta = rutas.entregable(vault, p_id) / CERROJO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ruta, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # cerrar suelta el flock


def _anotar_intento(vault: Path, p_id: str, intento: str, prompt_sha256: str) -> None:
    ruta = rutas.entregable(vault, p_id) / INTENTOS
    linea = json.dumps({"intento": intento, "prompt_sha256": prompt_sha256}, sort_keys=True) + "\n"
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(linea)
        f.flush()
        os.fsync(f.fileno())


def _intentos(vault: Path, p_id: str) -> dict[str, str]:
    ruta = rutas.entregable(vault, p_id) / INTENTOS
    if not ruta.is_file():
        return {}
    salida = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("intento"), str) and isinstance(d.get("prompt_sha256"), str):
            salida[d["intento"]] = d["prompt_sha256"]
    return salida


def _ultimas(filas: list[FilaCoste]) -> dict[str, FilaCoste]:
    ultima: dict[str, FilaCoste] = {}
    for f in filas:
        ultima[f.intento] = f
    return ultima


def _en_vuelo(filas: list[FilaCoste], pieza: str, imagen: str) -> bool:
    """¿Hay un intento de esa imagen enviado (con ``task_id``) y sin terminar? Entonces no se reenvía."""
    return any(f.pieza == pieza and f.imagen == imagen and f.estado in ("enviada", "pendiente") and f.task_id
               for f in _ultimas(filas).values())


@dataclass
class _Cuenta:
    generadas: list[str]
    omitidas: list[str]
    pendientes: list[str]
    fallidas: list[str]
    archivos: list[str]

    def resultado(self, detenido: str | None = None, alerta_id: str | None = None) -> ResultadoLote:
        return ResultadoLote(tuple(self.generadas), tuple(self.omitidas), tuple(self.pendientes),
                             tuple(self.fallidas), detenido, alerta_id)


def _cuenta() -> _Cuenta:
    return _Cuenta([], [], [], [], [])


def _cerrar_tarea(vault: Path, p_id: str, base: FilaCoste, estado: EstadoTarea, prompt_sha256: str,
                  abrir_publico, ahora: Callable[[], datetime], cuenta: _Cuenta) -> None:
    """Anota el final de una tarea sondeada: descarga y registro si está completada."""
    imagen = base.imagen
    if estado.estado == "fallida":
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="fallida", coste_real_usd=estado.coste_real_usd,
                                          archivo=""))
        cuenta.fallidas.append(imagen)
        return
    if estado.estado == "pendiente":
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="pendiente", archivo=""))
        cuenta.pendientes.append(imagen)
        return
    try:
        datos = descargar(estado.url, abrir_publico)
    except ErrorApimart:
        # Completada en APIMart pero sin descargar: se reintenta con --reanudar (mismo task_id).
        anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="pendiente",
                                          coste_real_usd=estado.coste_real_usd, archivo=""))
        cuenta.pendientes.append(imagen)
        return
    raiz = rutas.pieza(vault, p_id, base.pieza).raiz
    archivo = f"{imagen}.{formato_imagen(datos)}"
    sha = escribir_medio(raiz / CARPETA / archivo, datos, base=Path(vault))
    registrar_medio(raiz, imagen, archivo, sha, "apimart", task_id=estado.task_id, modelo=base.modelo,
                    prompt_sha256=prompt_sha256, proporcion=base.proporcion, resolucion=base.resolucion,
                    coste_usd=estado.coste_real_usd if estado.coste_real_usd is not None else base.coste_estimado_usd)
    rel = (raiz / CARPETA / archivo).relative_to(rutas.entregable(vault, p_id)).as_posix()
    anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="completada", coste_real_usd=estado.coste_real_usd,
                                      sha256=sha, archivo=rel))
    cuenta.generadas.append(imagen)
    cuenta.archivos.append(rel)


def _log(vault: Path, p_id: str, que: str, cuenta: _Cuenta, ahora: Callable[[], datetime]) -> None:
    archivos = [f"productos/{p_id}/entregable/costes.csv", *(f"productos/{p_id}/entregable/{a}" for a in cuenta.archivos)]
    anadir_log(vault, SKILL, que, archivos, ahora=ahora())


def generar_imagenes(vault: Path, p_id: str, peticiones: list[PeticionImagen], *, cred: Credenciales,
                     cfg: ConfigProducto, precio: Precio | None, abrir, abrir_publico, dormir=time.sleep,
                     ahora: Callable[[], datetime], simular: bool = False, depositar=fuentes.depositar,
                     reloj=time.monotonic) -> ResultadoLote:
    """Genera las imágenes de ``peticiones`` dentro del tope del producto. Ver el orden en el módulo.

    ``PeticionInvalida`` (antes de tocar nada) si una petición no vale o su resolución no es la del precio.
    """
    vault = Path(vault)
    rutas.validar_p_id(p_id)
    cuenta = _cuenta()
    if (vault / ".trovefy" / "STOP").exists():
        return cuenta.resultado(MOTIVO_STOP)
    if precio is None:
        return cuenta.resultado(MOTIVO_SIN_PRECIO)
    ids = [p.id for p in peticiones]
    if len(set(ids)) != len(ids):
        raise PeticionInvalida("hay ids de imagen repetidos en el lote")
    for p in peticiones:
        validar(p, leer_manifiesto(rutas.pieza(vault, p_id, p.pieza).raiz) if rutas.PIEZA.fullmatch(p.pieza) else {})
        if p.resolucion != precio.resolucion:
            raise PeticionInvalida(f"{p.id}: el precio medido es de {precio.resolucion}, no de {p.resolucion}")
    estimado = precio.usd_por_imagen
    with _cerrojo(vault, p_id):
        tope = tope_de(vault, p_id, cfg)
        simulado = Decimal(0)
        for i, p in enumerate(peticiones):
            raiz = rutas.pieza(vault, p_id, p.pieza).raiz
            manifiesto = leer_manifiesto(raiz)
            prompt_sha = _sha(p.prompt)
            previa = manifiesto.get(p.id) or {}
            if (previa.get("prompt_sha256") == prompt_sha and previa.get("proporcion") == p.proporcion
                    and previa.get("resolucion") == p.resolucion):
                cuenta.omitidas.append(p.id)
                continue
            filas = leer_costes(vault, p_id)
            if _en_vuelo(filas, p.pieza, p.id):
                cuenta.pendientes.append(p.id)
                continue
            base = FilaCoste(fecha=ahora(), producto=p_id, pieza=p.pieza, imagen=p.id, intento=str(uuid.uuid4()),
                             task_id="", modelo=precio.modelo, resolucion=p.resolucion, proporcion=p.proporcion,
                             estado="enviando", coste_estimado_usd=estimado, coste_real_usd=None,
                             fuente_precio=precio.fuente, sha256="", archivo="")
            gastado = gastado_usd(filas) + simulado
            try:
                comprobar_tope(gastado, estimado, tope)
            except TopeSuperado as exc:
                faltan = len(peticiones) - i
                motivo = (f"tope: gastado {exc.gastado} USD + {exc.estimado} USD superaría el tope de {exc.tope} USD; "
                          f"faltan {faltan} imágenes")
                if simular:
                    return cuenta.resultado(motivo)
                alerta = avisar_tope(vault, p_id, gastado, tope, faltan, estimado * faltan, ahora(), depositar,
                                     pieza=p.pieza, imagen=p.id, modelo=precio.modelo, resolucion=p.resolucion,
                                     proporcion=p.proporcion, fuente_precio=precio.fuente)
                _log(vault, p_id, f"{p_id}: lote de imágenes detenido por el tope de APIMart", cuenta, ahora)
                return cuenta.resultado(motivo, alerta)
            if simular:
                anotar_coste(vault, p_id, replace(base, estado="simulada"))
                simulado += estimado
                continue
            try:
                urls = [subir(cred, raiz / CARPETA / manifiesto[r]["archivo"], vault, abrir, ahora())
                        for r in p.referencias]
            except (ErrorApimart, OSError, ValueError) as exc:
                _log(vault, p_id, f"{p_id}: lote detenido al subir referencias", cuenta, ahora)
                return cuenta.resultado(f"no se pudieron subir las referencias de {p.id}: {exc}; no se envió nada")
            _anotar_intento(vault, p_id, base.intento, prompt_sha)
            anotar_coste(vault, p_id, base)
            try:
                task_id = enviar(cred, cuerpo_envio(p, precio.modelo, urls), abrir)
            except (ErrorApimart, OSError) as exc:
                _log(vault, p_id, f"{p_id}: lote detenido: envío sin respuesta", cuenta, ahora)
                return cuenta.resultado(f"envío de {p.id} sin respuesta ({exc}); cuenta como gastado "
                                        "y no se reenvía solo")
            base = replace(base, task_id=task_id)
            anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="enviada"))
            estado = esperar(cred, task_id, abrir, dormir, reloj)
            _cerrar_tarea(vault, p_id, base, estado, prompt_sha, abrir_publico, ahora, cuenta)
        que = "simulación del lote de imágenes" if simular else "lote de imágenes de APIMart"
        _log(vault, p_id, f"{p_id}: {que} ({len(cuenta.generadas)} generadas, {len(cuenta.omitidas)} omitidas, "
                          f"{len(cuenta.pendientes)} pendientes, {len(cuenta.fallidas)} fallidas)", cuenta, ahora)
    return cuenta.resultado()


def reanudar(vault: Path, p_id: str, *, cred: Credenciales, abrir, abrir_publico, dormir=time.sleep,
             ahora: Callable[[], datetime], reloj=time.monotonic) -> ResultadoLote:
    """Sondea los intentos cuya última fila es ``pendiente`` o ``enviada`` con ``task_id`` y completa la
    descarga. Nunca reenvía."""
    vault = Path(vault)
    rutas.validar_p_id(p_id)
    cuenta = _cuenta()
    if (vault / ".trovefy" / "STOP").exists():
        return cuenta.resultado(MOTIVO_STOP)
    with _cerrojo(vault, p_id):
        prompts = _intentos(vault, p_id)
        abiertas = [f for f in _ultimas(leer_costes(vault, p_id)).values()
                    if f.estado in ("pendiente", "enviada") and f.task_id]
        for f in abiertas:
            estado = esperar(cred, f.task_id, abrir, dormir, reloj)
            _cerrar_tarea(vault, p_id, f, estado, prompts.get(f.intento, ""), abrir_publico, ahora, cuenta)
        if abiertas:
            _log(vault, p_id, f"{p_id}: reanuda {len(abiertas)} tareas de APIMart ({len(cuenta.generadas)} generadas)",
                 cuenta, ahora)
    return cuenta.resultado()
