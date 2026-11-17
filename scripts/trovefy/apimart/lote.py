"""Lote de imágenes de APIMart: STOP, precio medido, ``flock``, tope, idempotencia y reanudar.

Orden de cada lote (plan 17, Tarea 5): STOP → precio medido → ``flock`` exclusivo sobre
``entregable/.apimart.lock`` durante todo el lote → por cada petición: omitir si ya está generada con el
mismo prompt, proporción y resolución; no reenviar si tiene una tarea ``pendiente``/``enviada``;
``comprobar_tope``; anotar ``enviando`` en ``costes.csv`` (y después el prompt en
``.apimart-intentos.jsonl``) **antes** del POST; ``enviada`` con su ``task_id``; sondear;
descargar sin clave y registrar el medio. El saldo de ``/v1/balance`` nunca se consulta: el tope manda.

STOP se mira otra vez dentro del cerrojo justo antes de cada llamada que cuesta (cada subida y cada POST),
en ``generar_imagenes`` y en ``reanudar``.

Una tarea enviada puede estar cobrada aunque no llegue respuesta: cuenta su estimado y nunca se reenvía;
``reanudar`` sondea el mismo ``task_id``. Un POST sin respuesta (última fila ``enviando``, sin ``task_id``)
bloquea esa imagen: no hay tarea que sondear y nunca se reenvía sola; solo ``descartar`` (``--descartar``)
la marca ``fallida`` conservando su estimado, y entonces otro lote puede reenviarla.

El ``prompt_sha256`` de cada intento se guarda en ``entregable/.apimart-intentos.jsonl`` (solo de
añadir) para que ``reanudar`` registre el medio con el prompt que se envió de verdad, no con el que haya
hoy en ``imagenes.yaml``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
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
from trovefy.apimart.subidas import MAX_SUBIDA, subir
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
MOTIVO_SIN_RESPUESTA = "sin respuesta del envío; revisa el panel de APIMart"
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
    avisos: tuple[str, ...] = ()  # «<imagen>: <motivo>» de las imágenes bloqueadas


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


def _bloqueo(filas: list[FilaCoste], pieza: str, imagen: str) -> str | None:
    """¿Por qué no se puede enviar esa imagen ahora? ``None`` si nada lo impide.

    ``"sin_respuesta"``: un intento cuya última fila es ``enviando`` (POST sin respuesta: pudo cobrarse y no
    hay ``task_id``). ``"en_vuelo"``: un intento enviado (con ``task_id``) y sin terminar. Ninguno se reenvía.
    """
    ultimas = [f for f in _ultimas(filas).values() if f.pieza == pieza and f.imagen == imagen]
    if any(f.estado == "enviando" for f in ultimas):
        return "sin_respuesta"
    if any(f.estado in ("enviada", "pendiente") and f.task_id for f in ultimas):
        return "en_vuelo"
    return None


def _stop(vault: Path) -> bool:
    return (vault / ".trovefy" / "STOP").exists()


def _sin_clave(texto: object, cred: Credenciales) -> str:
    """Texto apto para el resultado y el log: nunca la clave."""
    t = str(texto)
    return t.replace(cred.clave, "***") if cred.clave else t


def _ya_generada(manifiesto: dict, p: PeticionImagen) -> bool:
    previa = manifiesto.get(p.id) or {}
    return (previa.get("prompt_sha256") == _sha(p.prompt) and previa.get("proporcion") == p.proporcion
            and previa.get("resolucion") == p.resolucion)


def _leer_referencia(raiz: Path, entrada: dict) -> bytes:
    """Bytes de una referencia del manifiesto: sin seguir enlaces, archivo regular y mismo sha256."""
    ruta = raiz / CARPETA / entrada["archivo"]
    fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError(f"{CARPETA}/{entrada['archivo']} no es un archivo regular")
        datos = f.read(MAX_SUBIDA + 1)
    if hashlib.sha256(datos).hexdigest() != entrada["sha256"]:
        raise ValueError(f"el sha256 de {CARPETA}/{entrada['archivo']} no coincide con el manifiesto")
    return datos


@dataclass
class _Cuenta:
    generadas: list[str]
    omitidas: list[str]
    pendientes: list[str]
    fallidas: list[str]
    archivos: list[str]
    avisos: list[str]

    def resultado(self, detenido: str | None = None, alerta_id: str | None = None) -> ResultadoLote:
        return ResultadoLote(tuple(self.generadas), tuple(self.omitidas), tuple(self.pendientes),
                             tuple(self.fallidas), detenido, alerta_id, tuple(self.avisos))

    def bloqueada(self, imagen: str) -> None:
        self.pendientes.append(imagen)
        self.avisos.append(f"{imagen}: {MOTIVO_SIN_RESPUESTA}")


def _cuenta() -> _Cuenta:
    return _Cuenta([], [], [], [], [], [])


def _real_positivo(coste: Decimal | None) -> Decimal | None:
    """El coste real solo cuenta si es > 0; si no, manda el estimado (conservador)."""
    return coste if coste is not None and coste > 0 else None


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
                                          coste_real_usd=_real_positivo(estado.coste_real_usd), archivo=""))
        cuenta.pendientes.append(imagen)
        return
    raiz = rutas.pieza(vault, p_id, base.pieza).raiz
    archivo = f"{imagen}.{formato_imagen(datos)}"
    real = _real_positivo(estado.coste_real_usd)  # un coste real de 0 no se cree: cuenta el estimado
    sha = escribir_medio(raiz / CARPETA / archivo, datos, base=Path(vault))
    registrar_medio(raiz, imagen, archivo, sha, "apimart", task_id=estado.task_id, modelo=base.modelo,
                    prompt_sha256=prompt_sha256, proporcion=base.proporcion, resolucion=base.resolucion,
                    coste_usd=real if real is not None else base.coste_estimado_usd)
    rel = (raiz / CARPETA / archivo).relative_to(rutas.entregable(vault, p_id)).as_posix()
    anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="completada", coste_real_usd=real,
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
            if _ya_generada(manifiesto, p):
                cuenta.omitidas.append(p.id)
                continue
            filas = leer_costes(vault, p_id)
            bloqueo = _bloqueo(filas, p.pieza, p.id)
            if bloqueo == "sin_respuesta":
                cuenta.bloqueada(p.id)
                continue
            if bloqueo == "en_vuelo":
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
                faltan = 1 + sum(1 for q in peticiones[i + 1:] if _falta(vault, p_id, q, filas))
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
            urls: list[str] = []
            if p.referencias:
                try:
                    verificado = leer_manifiesto(raiz, verificar=True)
                    refs = [(verificado[r], _leer_referencia(raiz, verificado[r])) for r in p.referencias]
                except (KeyError, OSError, ValueError) as exc:
                    _log(vault, p_id, f"{p_id}: lote detenido: referencias que no cuadran con el manifiesto",
                         cuenta, ahora)
                    return cuenta.resultado(_sin_clave(f"las referencias de {p.id} no cuadran con el manifiesto "
                                                       f"({exc}); no se envió nada", cred))
                for entrada, datos_ref in refs:
                    if _stop(vault):
                        return _parar_por_stop(vault, p_id, cuenta, ahora)
                    try:
                        urls.append(subir(cred, raiz / CARPETA / entrada["archivo"], vault, abrir, ahora(),
                                          datos=datos_ref))
                    except (ErrorApimart, OSError, ValueError) as exc:
                        _log(vault, p_id, f"{p_id}: lote detenido al subir referencias", cuenta, ahora)
                        return cuenta.resultado(_sin_clave(f"no se pudieron subir las referencias de {p.id}: {exc}; "
                                                           "no se envió nada", cred))
            if _stop(vault):
                return _parar_por_stop(vault, p_id, cuenta, ahora)
            # Primero la fila del gasto y después la del prompt (ruling de la Tarea 13): un corte entre las dos
            # deja el gasto registrado; nunca una línea de intento sin su fila en costes.csv.
            anotar_coste(vault, p_id, base)
            _anotar_intento(vault, p_id, base.intento, prompt_sha)
            try:
                task_id = enviar(cred, cuerpo_envio(p, precio.modelo, urls), abrir)
            except (ErrorApimart, OSError) as exc:
                _log(vault, p_id, f"{p_id}: lote detenido: envío sin respuesta", cuenta, ahora)
                return cuenta.resultado(_sin_clave(
                    f"envío de {p.id}: {MOTIVO_SIN_RESPUESTA} ({exc}). Cuenta como gastado y no se reenvía solo; "
                    "si en el panel no hay tarea, descártala para reenviarla", cred))
            base = replace(base, task_id=task_id)
            anotar_coste(vault, p_id, replace(base, fecha=ahora(), estado="enviada"))
            estado = esperar(cred, task_id, abrir, dormir, reloj)
            _cerrar_tarea(vault, p_id, base, estado, prompt_sha, abrir_publico, ahora, cuenta)
        que = "simulación del lote de imágenes" if simular else "lote de imágenes de APIMart"
        _log(vault, p_id, f"{p_id}: {que} ({len(cuenta.generadas)} generadas, {len(cuenta.omitidas)} omitidas, "
                          f"{len(cuenta.pendientes)} pendientes, {len(cuenta.fallidas)} fallidas)", cuenta, ahora)
    return cuenta.resultado()


def _falta(vault: Path, p_id: str, p: PeticionImagen, filas: list[FilaCoste]) -> bool:
    """¿Esta petición se enviaría (no está generada ni bloqueada)? Para contar las que faltan."""
    if _ya_generada(leer_manifiesto(rutas.pieza(vault, p_id, p.pieza).raiz), p):
        return False
    return _bloqueo(filas, p.pieza, p.id) is None


def _parar_por_stop(vault: Path, p_id: str, cuenta: _Cuenta, ahora: Callable[[], datetime]) -> ResultadoLote:
    _log(vault, p_id, f"{p_id}: lote de imágenes detenido por STOP", cuenta, ahora)
    return cuenta.resultado(MOTIVO_STOP)


def reanudar(vault: Path, p_id: str, *, cred: Credenciales, abrir, abrir_publico, dormir=time.sleep,
             ahora: Callable[[], datetime], reloj=time.monotonic) -> ResultadoLote:
    """Sondea los intentos cuya última fila es ``pendiente`` o ``enviada`` con ``task_id`` y completa la
    descarga. Nunca reenvía. Los POST sin respuesta (``enviando``) salen como pendientes con su aviso.
    STOP se mira antes de cada sondeo."""
    vault = Path(vault)
    rutas.validar_p_id(p_id)
    cuenta = _cuenta()
    if _stop(vault):
        return cuenta.resultado(MOTIVO_STOP)
    with _cerrojo(vault, p_id):
        prompts = _intentos(vault, p_id)
        ultimas = list(_ultimas(leer_costes(vault, p_id)).values())
        for f in ultimas:
            if f.estado == "enviando":
                cuenta.bloqueada(f.imagen)
        abiertas = [f for f in ultimas if f.estado in ("pendiente", "enviada") and f.task_id]
        for f in abiertas:
            if _stop(vault):
                return _parar_por_stop(vault, p_id, cuenta, ahora)
            estado = esperar(cred, f.task_id, abrir, dormir, reloj)
            _cerrar_tarea(vault, p_id, f, estado, prompts.get(f.intento, ""), abrir_publico, ahora, cuenta)
        if abiertas:
            _log(vault, p_id, f"{p_id}: reanuda {len(abiertas)} tareas de APIMart ({len(cuenta.generadas)} generadas)",
                 cuenta, ahora)
    return cuenta.resultado()


def descartar(vault: Path, p_id: str, pieza: str, imagen: str, *, ahora: Callable[[], datetime]) -> int:
    """Descarta el POST sin respuesta de ``pieza``/``imagen`` (``--descartar``): lo marca ``fallida``.

    Conserva su estimado en el gasto (pudo cobrarse) y deja que otro lote la reenvíe. Devuelve cuántos
    intentos descarta; ``ValueError`` si la imagen no tiene ningún envío sin respuesta. No llama a APIMart.
    """
    vault = Path(vault)
    rutas.validar_p_id(p_id)
    with _cerrojo(vault, p_id):
        bloqueadas = [f for f in _ultimas(leer_costes(vault, p_id)).values()
                      if f.pieza == pieza and f.imagen == imagen and f.estado == "enviando"]
        if not bloqueadas:
            raise ValueError(f"{pieza}/{imagen}: no hay ningún envío sin respuesta que descartar")
        for f in bloqueadas:
            anotar_coste(vault, p_id, replace(f, fecha=ahora(), estado="fallida", coste_real_usd=None))
        anadir_log(vault, SKILL, f"{p_id}: descarta el envío sin respuesta de {pieza}/{imagen} "
                                 f"(su estimado sigue contando en el gasto)",
                   [f"productos/{p_id}/entregable/costes.csv"], ahora=ahora())
    return len(bloqueadas)
