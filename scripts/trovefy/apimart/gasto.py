"""Gasto de APIMart: ``entregable/costes.csv`` solo de añadir, tope por producto, alerta y subir el tope.

``costes.csv`` es uno por producto (suma principal, bonos y upsells: contrato 7) y solo crece: cada cambio
de estado de un intento es una fila nueva, añadida bajo ``flock``. Una fila mala lanza
``CostesCorruptos`` y nunca se «arregla»: sin un gasto legible no se envía nada (falla cerrado).
Importes en ``Decimal`` escritos con ``str(Decimal)``; fechas ISO 8601 con zona.

Rebase del tope (ruling L4): el tope se comprueba con el **precio medido** antes de cada envío. Si APIMart
cobra por esa imagen más de lo medido, el tope puede superarse como mucho en esa diferencia de una imagen
(nunca en una imagen más: la siguiente ya ve el gasto real y se para).
"""

from __future__ import annotations

import csv
import fcntl
import io
import os
import uuid
from collections.abc import Callable
from dataclasses import astuple, dataclass, fields, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.aprobaciones import fuentes
from trovefy.aprobaciones.fuentes import BuzonNoDisponible
from trovefy.producto.config import (
    ConfigInvalida,
    cargar_config,
    importe_usd,
    tope_de,
    ultima_decision,
)
from trovefy.producto.rutas import entregable, validar_p_id
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import actualizar_producto, ruta_producto, secreto_en

CABECERA = ["fecha", "producto", "pieza", "imagen", "intento", "task_id", "modelo", "resolucion", "proporcion",
            "estado", "coste_estimado_usd", "coste_real_usd", "fuente_precio", "sha256", "archivo"]
ESTADOS = ("enviando", "enviada", "completada", "fallida", "pendiente", "tope", "simulada")
ESTADOS_QUE_GASTAN = ("enviando", "enviada", "completada", "fallida", "pendiente")
ARCHIVO = "costes.csv"
INTENTOS = ".apimart-intentos.jsonl"  # el mismo nombre que ``trovefy.apimart.lote.INTENTOS`` (lote importa gasto)
SKILL = "/producto"


AYUDA_CORRUPTOS = ("No se genera nada con APIMart. No lo edites a mano (es el registro del gasto real): "
                   "pide ayuda para revisarlo")


class CostesCorruptos(ValueError):
    """``costes.csv`` no se puede leer; nunca se reescribe para «arreglarlo». El mensaje pide ayuda."""

    def __init__(self, motivo: str) -> None:
        super().__init__(f"{motivo}. {AYUDA_CORRUPTOS}")
        self.motivo = motivo


class TopeSuperado(Exception):
    def __init__(self, gastado: Decimal, tope: Decimal, estimado: Decimal) -> None:
        super().__init__(f"gastado {gastado} + estimado {estimado} USD supera el tope de {tope} USD")
        self.gastado, self.tope, self.estimado = gastado, tope, estimado


@dataclass(frozen=True)
class FilaCoste:
    fecha: datetime
    producto: str
    pieza: str
    imagen: str
    intento: str
    task_id: str
    modelo: str
    resolucion: str
    proporcion: str
    estado: str
    coste_estimado_usd: Decimal | None
    coste_real_usd: Decimal | None
    fuente_precio: str
    sha256: str
    archivo: str


assert [f.name for f in fields(FilaCoste)] == CABECERA


def ruta_costes(vault: Path, p_id: str, raiz: Path | None = None) -> Path:
    """El libro del entregable o, con ``raiz`` (el destino de una tanda de creativos), el de esa carpeta."""
    validar_p_id(p_id)
    return (entregable(vault, p_id) if raiz is None else Path(raiz)) / ARCHIVO


def _con_zona(ahora: datetime) -> datetime:
    if not isinstance(ahora, datetime) or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError(f"fecha sin zona horaria: {ahora!r}")
    return ahora


def _a_texto(fila: FilaCoste) -> list[str]:
    out = []
    for nombre, v in zip(CABECERA, astuple(fila), strict=True):
        if nombre == "fecha":
            out.append(_con_zona(v).isoformat())
        elif nombre.endswith("_usd"):
            if v is not None and (not isinstance(v, Decimal) or not v.is_finite() or v < 0):
                raise ValueError(f"{nombre}: importe no válido ({v!r}); usa Decimal ≥ 0")
            out.append("" if v is None else str(v))
        else:
            if not isinstance(v, str) or "\n" in v or "\r" in v:
                raise ValueError(f"{nombre}: debe ser texto de una línea ({v!r})")
            out.append(v)
    return out


def _desde_texto(celdas: list[str], n: int) -> FilaCoste:
    donde = f"{ARCHIVO} línea {n}"
    if len(celdas) != len(CABECERA):
        raise CostesCorruptos(f"{donde}: tiene {len(celdas)} columnas y deben ser {len(CABECERA)}")
    d = dict(zip(CABECERA, celdas, strict=True))
    try:
        fecha = datetime.fromisoformat(d["fecha"])
    except ValueError:
        raise CostesCorruptos(f"{donde}: fecha ilegible") from None
    if fecha.tzinfo is None:
        raise CostesCorruptos(f"{donde}: fecha sin zona horaria")
    if d["estado"] not in ESTADOS:
        raise CostesCorruptos(f"{donde}: estado desconocido «{d['estado']}»")
    if not d["intento"]:
        raise CostesCorruptos(f"{donde}: falta el intento")
    importes: dict[str, Decimal | None] = {}
    for k in ("coste_estimado_usd", "coste_real_usd"):
        if d[k] == "":
            importes[k] = None
            continue
        try:
            v = Decimal(d[k])
        except InvalidOperation:
            raise CostesCorruptos(f"{donde}: {k} ilegible") from None
        if not v.is_finite() or v < 0:
            raise CostesCorruptos(f"{donde}: {k} no válido")
        importes[k] = v
    return FilaCoste(**{**d, "fecha": fecha, **importes})


def _leer(texto: str) -> list[FilaCoste]:
    filas = list(csv.reader(io.StringIO(texto, newline="")))
    if not filas:
        return []
    if filas[0] != CABECERA:
        raise CostesCorruptos(f"{ARCHIVO}: la cabecera no es la esperada")
    return [_desde_texto(celdas, n) for n, celdas in enumerate(filas[1:], start=2)]


def leer_costes(vault: Path, p_id: str, raiz: Path | None = None) -> list[FilaCoste]:
    """Filas de ``costes.csv`` (``[]`` si el producto aún no gastó nada).

    Falla cerrado: si existe ``.apimart-intentos.jsonl`` (ya hubo envíos) y ``costes.csv`` falta o está
    vacío, el registro del gasto se perdió o se vació: ``CostesCorruptos``, nunca «cero gastado».
    """
    ruta = ruta_costes(vault, p_id, raiz)
    intentos = (ruta.parent / INTENTOS).exists()
    if not ruta.is_file():
        if intentos:
            raise CostesCorruptos(f"falta {ARCHIVO} pero existe {INTENTOS}: hubo envíos a APIMart y su gasto "
                                  "no está registrado")
        return []
    try:
        texto = ruta.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise CostesCorruptos(f"{ARCHIVO}: no es UTF-8") from None
    if intentos and not texto.strip():
        raise CostesCorruptos(f"{ARCHIVO} está vacío pero existe {INTENTOS}: hubo envíos a APIMart y su gasto "
                              "no está registrado")
    return _leer(texto)


def anotar_coste(vault: Path, p_id: str, fila: FilaCoste, raiz: Path | None = None) -> None:
    """Añade ``fila`` al final de ``costes.csv`` (con la cabecera si está vacío), bajo ``flock``.

    Antes de escribir relee el archivo entero: si está corrupto lanza ``CostesCorruptos`` y no toca nada.
    """
    validar_p_id(p_id)
    if fila.producto != p_id:
        raise ValueError(f"la fila es de {fila.producto}, no de {p_id}")
    if fila.estado not in ESTADOS:
        raise ValueError(f"estado de coste desconocido: «{fila.estado}»")
    celdas = _a_texto(fila)
    nombre = secreto_en(celdas)
    if nombre:
        raise ValueError(f"la fila de costes trae algo con forma de secreto ({nombre}); no se guarda")
    salida = io.StringIO()
    csv.writer(salida, lineterminator="\n").writerow(celdas)
    ruta = ruta_costes(vault, p_id, raiz)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ruta, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "r+", encoding="utf-8", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                actual = f.read()
            except UnicodeDecodeError:
                raise CostesCorruptos(f"{ARCHIVO}: no es UTF-8") from None
            _leer(actual)
            if actual and not actual.endswith("\n"):
                raise CostesCorruptos(f"{ARCHIVO}: la última línea está cortada")
            if not actual:
                csv.writer(f, lineterminator="\n").writerow(CABECERA)
            f.write(salida.getvalue())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def gastado_usd(filas: list[FilaCoste]) -> Decimal:
    """Suma de la **última fila de cada intento**: real si existe y, si no, el estimado (conservador).

    ``tope`` y ``simulada`` suman 0. Una fallida sin coste real cuenta su estimado.
    """
    ultima: dict[str, FilaCoste] = {}
    for f in filas:
        ultima[f.intento] = f
    total = Decimal(0)
    for f in ultima.values():
        if f.estado not in ESTADOS_QUE_GASTAN:
            continue
        importe = f.coste_real_usd if f.coste_real_usd is not None else f.coste_estimado_usd
        total += importe or Decimal(0)
    return total


def comprobar_tope(gastado: Decimal, estimado: Decimal, tope: Decimal) -> None:
    """``TopeSuperado`` si ``gastado + estimado > tope`` (llegar justo al tope está permitido).

    ``estimado`` es el precio medido. Rebase aceptado (ruling L4): si el coste real de la imagen sale mayor
    que el medido, el tope puede superarse como mucho en esa diferencia de una sola imagen.
    """
    if gastado + estimado > tope:
        raise TopeSuperado(gastado, tope, estimado)


def _coma(v: Decimal, decimales: str) -> str:
    return str(Decimal(v).quantize(Decimal(decimales))).replace(".", ",")


def alerta_tope(p_id: str, gastado: Decimal, tope: Decimal, faltan: int, estimado: Decimal, *,
                origen: str = SKILL, quien: str | None = None) -> dict:
    """Alerta del buzón (§5.2): ``estimado`` es lo que costarían las ``faltan`` imágenes que no se generan."""
    imagenes = "imagen" if faltan == 1 else "imágenes"
    if origen != SKILL:
        imagenes = "pieza" if faltan == 1 else "piezas"
    texto = (f"{quien or p_id}: gastado {_coma(gastado, '0.0001')} USD de {_coma(tope, '0.01')}. "
             f"Faltan {faltan} {imagenes} (≈ {_coma(estimado, '0.0001')} USD). "
             "No se generó nada más. Subir el tope es decisión tuya.")
    return {"tipo": "alerta", "origen": origen, "nivel": "aviso", "titulo": "Tope de APIMart alcanzado",
            "texto": texto}


def _dia(fecha: datetime):
    return fecha.astimezone(ZONA_NEGOCIO).date()


ALERTA_DEPOSITANDO = "alerta (depositando)"
ALERTA_NO_DEPOSITADA = "alerta no depositada"


def avisar_tope(vault: Path, p_id: str, gastado: Decimal, tope: Decimal, faltan: int, estimado: Decimal,
                ahora: datetime, depositar: Callable = fuentes.depositar, *, pieza: str = "", imagen: str = "",
                modelo: str = "", resolucion: str = "", proporcion: str = "", fuente_precio: str = "",
                raiz: Path | None = None, origen: str = SKILL, quien: str | None = None) -> str | None:
    """Deposita la alerta de tope (una por producto y día) y la deja anotada en filas ``tope``; devuelve su id.

    La marca (fila ``tope`` «alerta (depositando)») se escribe **antes** de depositar: si algo falla
    después, otra llamada del mismo día no repite la alerta. Con el id va otra fila del mismo intento.
    ``BuzonNoDisponible`` (no se depositó nada) cierra el intento como «alerta no depositada» y da ``None``:
    más tarde, ese mismo día, se puede volver a avisar. El aviso es secundario; la parada del lote, no.
    """
    ahora = _con_zona(ahora)
    hoy = _dia(ahora)
    ultimas: dict[str, FilaCoste] = {}
    for f in leer_costes(vault, p_id, raiz):
        if f.estado == "tope":
            ultimas[f.intento] = f
    if any(_dia(f.fecha) == hoy and f.archivo != ALERTA_NO_DEPOSITADA for f in ultimas.values()):
        return None
    marca = FilaCoste(
        fecha=ahora, producto=p_id, pieza=pieza, imagen=imagen, intento=str(uuid.uuid4()), task_id="",
        modelo=modelo, resolucion=resolucion, proporcion=proporcion, estado="tope",
        coste_estimado_usd=estimado, coste_real_usd=None, fuente_precio=fuente_precio, sha256="",
        archivo=ALERTA_DEPOSITANDO)
    anotar_coste(vault, p_id, marca, raiz)
    try:
        id_ = depositar(Path(vault), alerta_tope(p_id, gastado, tope, faltan, estimado, origen=origen, quien=quien),
                        lambda: ahora)
    except BuzonNoDisponible:
        anotar_coste(vault, p_id, replace(marca, archivo=ALERTA_NO_DEPOSITADA), raiz)
        return None
    anotar_coste(vault, p_id, replace(marca, archivo=f"alerta {id_}"), raiz)
    return id_


def _cita_md(cita: str) -> str:
    return "\n".join(f"> {x}" if x else ">" for x in cita.split("\n"))


def subir_tope(vault: Path, p_id: str, usd: Decimal, cita: str, ahora: datetime) -> Path:
    """Sube el tope de APIMart del producto con la cita literal del usuario.

    Escribe primero ``productos/<p>/decisiones/AAAA-MM-DD-HHMMSS-tope-apimart.md`` (hora local de ``ahora``,
    la misma que su ``registrada``) y después ``PRODUCTO.md`` → ``apimart_tope_usd`` (fusión con
    ``actualizar_producto``: conserva el resto y el cuerpo).
    ``ValueError`` si falta la cita, trae un secreto o el tope nuevo no es mayor que el actual.

    Recuperación tras un corte: si el proceso muere después de escribir la decisión y antes de
    ``PRODUCTO.md``, ``tope_de`` falla cerrado (``ConfigInvalida``: no coinciden) y no se genera nada.
    Para terminar, repite ``subir_tope`` con el mismo importe y la cita del usuario: al ver que la última
    decisión ya es ese importe, solo escribe ``PRODUCTO.md`` (no crea otra decisión) y devuelve la ruta de
    esa decisión. Con otro importe sigue fallando: hay que terminar antes la subida cortada.
    """
    vault, ahora = Path(vault), _con_zona(ahora)
    validar_p_id(p_id)
    if not isinstance(cita, str) or not cita.strip():
        raise ValueError("hace falta la cita literal del usuario para subir el tope")
    if any(0x80 <= ord(c) <= 0x9F for c in cita):
        raise ValueError("la cita lleva caracteres de control que no se ven: escríbela de nuevo")
    if buscar_secreto(cita):
        raise ValueError("la cita trae algo con forma de secreto; no se guarda")
    nuevo = importe_usd(str(usd) if isinstance(usd, Decimal) else usd, "tope nuevo")
    try:
        anterior = tope_de(vault, p_id, cargar_config(vault))
    except ConfigInvalida:
        pendiente = ultima_decision(ruta_producto(vault, p_id).parent, p_id, ahora)
        if pendiente is None or pendiente[0] != nuevo:
            raise
        rel = pendiente[1].relative_to(vault).as_posix()
        anadir_log(vault, SKILL, f"{p_id}: termina la subida del tope de APIMart a {nuevo} USD que se cortó", [rel],
                   ahora=ahora)
        actualizar_producto(vault, p_id, {"apimart_tope_usd": str(nuevo)}, [], SKILL, ahora)
        return pendiente[1]
    if nuevo <= anterior:
        raise ValueError(f"el tope nuevo ({nuevo} USD) debe ser mayor que el actual ({anterior} USD)")
    meta = {"tipo": "decision", "fecha": ahora.date().isoformat(), "registrada": ahora.isoformat(timespec="seconds"),
            "fuente": "usuario", "producto": p_id, "decision": "tope_apimart",
            "tope_anterior_usd": str(anterior), "tope_nuevo_usd": str(nuevo), "cita": cita}
    lineas = [f"# Tope de APIMart · {p_id} ({ahora.date().isoformat()})", "",
              f"De {anterior} USD a {nuevo} USD por producto (suma principal, bonos y upsells).", "",
              "Palabras del usuario (cita literal):", "", _cita_md(cita), "",
              f"Producto: [[productos/{p_id}/PRODUCTO]]", ""]
    texto = frontmatter.renderizar(meta, "\n".join(lineas))
    if secreto_en(meta) or buscar_secreto(texto):
        raise ValueError("la decisión trae algo con forma de secreto; no se guarda")
    if not ruta_producto(vault, p_id).is_file():
        raise FileNotFoundError(f"no existe productos/{p_id}/PRODUCTO.md")
    destino = ruta_producto(vault, p_id).parent / "decisiones" / f"{ahora:%Y-%m-%d-%H%M%S}-tope-apimart.md"
    if destino.exists():
        raise FileExistsError(f"ya existe {destino.name}: espera un segundo y repite")
    escribir_atomico(destino, texto)
    rel = destino.relative_to(vault).as_posix()
    anadir_log(vault, SKILL, f"{p_id}: tope de APIMart {anterior} → {nuevo} USD con la cita del usuario", [rel],
               ahora=ahora)
    actualizar_producto(vault, p_id, {"apimart_tope_usd": str(nuevo)}, [], SKILL,
                        ahora)
    return destino
