"""Montaje de ``crear_estructura_pausada`` en Meta (§5.2, §5.10, §7; resoluciones 13 y 19).

Orden: preparación sin escribir (forma, importes, ubicaciones, medios con sha256 dentro del vault,
cuenta y moneda, idiomas) → ``validate_only`` de la campaña (con ``solo_validar`` se acaba aquí) →
subida de medios → campaña → conjuntos → creativo y anuncio por anuncio → relectura.

Reglas: ``status`` siempre ``"PAUSED"`` lo fija este módulo (la entrada no lo trae y nunca se usa);
``_crear`` es el único sitio que llama a ``graph.crear``: siempre ``validate_only`` y luego **una**
creación real, que nunca se reenvía. Nada se borra nunca: lo creado queda en PAUSED y se lista en
``ids_creados``. Desde la primera escritura real (subida incluida), ninguna excepción escapa: todo
acaba en un ``Resultado`` con lo ya creado y su ``ejecucion`` final en la auditoría.

Diferencias con el texto del plan (anotadas en el informe de la Tarea 6): la ``validate_only`` de la
campaña se hace también antes de subir medios (es la de ``solo_validar`` y comprueba que la auditoría
funciona antes de la primera escritura); ``_crear`` la repite justo antes de la creación real.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from trovefy_ejecutor.auditoria import EV_EJECUCION, Auditoria, redactar
from trovefy_ejecutor.ejecutar import Resultado, siguiente_id
from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.graph import DetenidoPorStop, ErrorGraph, ErrorRed, clasificar
from trovefy_ejecutor.modelo import Estructura, Propuesta

TIPO = "crear_estructura_pausada"
PLATAFORMAS = ("facebook", "instagram", "messenger", "audience_network", "threads")
ORIGEN = "trovefy-ejecutor"
INTERVALO_VIDEO = 10
MAX_LECTURAS_VIDEO = 30
MAX_VIDEO = 100 * 1024 * 1024  # igual que ClienteGraph.subir_video (subida simple, sin partes)
EXT_IMAGEN = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
EXT_VIDEO = frozenset({".mp4", ".mov", ".m4v"})
_ID_META = re.compile(r"[0-9]{1,20}")
_SIN_NUMERO = "sin número libre 800–899 hoy: crea la propuesta a mano"
_REVISA = "puede haberse creado: revísalo en Ads Manager antes de volver a montar"


def _ahora() -> datetime:
    return datetime.now(UTC)


class _Fallo(Exception):
    """Fallo de la preparación (nada escrito) o corte del montaje (``estado``/``error``)."""

    def __init__(self, detalle: str, error: str = "otro", estado: str = "fallida"):
        self.detalle = detalle
        self.error = error
        self.estado = estado
        super().__init__(detalle)


def _texto_error(e: BaseException) -> str:
    if isinstance(e, ErrorGraph):
        return str(e)
    if isinstance(e, ErrorRed):
        return f"red: {e.motivo}"
    return type(e).__name__


def _importe(v: object) -> bool:
    return type(v) is int and v > 0


@dataclass(frozen=True)
class _Archivo:
    ref: str
    ruta: str  # relativa al vault, como viene en la propuesta
    real: Path
    video: bool
    contenido: bytes | None  # bytes verificados (solo imágenes)
    sha256: str


@dataclass
class _Preparado:
    archivos: dict[str, _Archivo]
    locales: dict[str, int]


@dataclass
class _Ids:
    campana: str | None = None
    conjuntos: dict[str, str] = field(default_factory=dict)
    anuncios: dict[str, str] = field(default_factory=dict)
    creativos: dict[str, str] = field(default_factory=dict)
    medios: dict[str, str] = field(default_factory=dict)

    def algo(self) -> bool:
        return bool(self.campana or self.conjuntos or self.anuncios or self.creativos or self.medios)

    def a_dict(self) -> dict:
        return {"campana": self.campana, "conjuntos": dict(self.conjuntos), "anuncios": dict(self.anuncios),
                "creativos": dict(self.creativos), "medios": dict(self.medios)}

    def resumen(self) -> str:
        partes = [f"campaña {self.campana}"] if self.campana else []
        partes += [f"conjunto {n} {i}" for n, i in self.conjuntos.items()]
        partes += [f"creativo {n} {i}" for n, i in self.creativos.items()]
        partes += [f"anuncio {n} {i}" for n, i in self.anuncios.items()]
        partes += [f"medio {r} {i}" for r, i in self.medios.items()]
        return "creado (queda en PAUSED, no se borra nada): " + ", ".join(partes) if partes else "nada creado"


# -- preparación (sin escribir) ---------------------------------------------------------------
def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _resolver(vault: Path, ruta: str) -> Path:
    if not isinstance(ruta, str) or not ruta or Path(ruta).is_absolute() or "\0" in ruta or "\\" in ruta:
        raise _Fallo(f"ruta fuera del vault: {ruta!r}")
    if ".." in Path(ruta).parts:
        raise _Fallo(f"ruta fuera del vault: {ruta!r}")
    try:
        base = vault.resolve(strict=True)
        real = (base / ruta).resolve(strict=True)
    except (OSError, RuntimeError):
        raise _Fallo(f"el medio no existe: {ruta}") from None
    if not real.is_relative_to(base):
        raise _Fallo(f"ruta fuera del vault: {ruta!r}")
    if not real.is_file():
        raise _Fallo(f"el medio no es un archivo: {ruta}")
    return real


def _preparar_medios(e: Estructura, vault: Path) -> dict[str, _Archivo]:
    archivos: dict[str, _Archivo] = {}
    for m in e.medios:
        if m.ref in archivos:
            raise _Fallo(f"ref de medio repetida: {m.ref}")
        real = _resolver(vault, m.ruta)
        ext = real.suffix.lower()
        if ext in EXT_IMAGEN:
            contenido = real.read_bytes()  # se lee una vez: se verifica y se suben estos mismos bytes
            sha = hashlib.sha256(contenido).hexdigest()
            video = False
        elif ext in EXT_VIDEO:
            if real.stat().st_size > MAX_VIDEO:
                raise _Fallo(f"vídeo > 100 MB (subida por partes no soportada): {m.ruta}")
            contenido, sha, video = None, _sha256_archivo(real), True
        else:
            raise _Fallo(f"tipo de medio no soportado ({ext or 'sin extensión'}): {m.ruta}")
        if sha != m.sha256:
            raise _Fallo(f"sha256 distinto en {m.ruta}: el archivo no es el aprobado")
        archivos[m.ref] = _Archivo(m.ref, m.ruta, real, video, contenido, sha)
    return archivos


def _preparar_forma(p: Propuesta) -> None:
    e = p.estructura
    if e is None:
        raise _Fallo("la propuesta no trae estructura")
    if e.unidad != "minima":
        raise _Fallo('unidad debe ser "minima"')
    c = e.campana
    if c.tipo_presupuesto not in ("ABO", "CBO"):
        raise _Fallo("tipo_presupuesto debe ser ABO o CBO")
    if not _importe(c.spend_cap):
        raise _Fallo("spend_cap de la campaña debe ser un entero > 0")
    if c.tipo_presupuesto == "CBO":
        if not _importe(c.daily_budget):
            raise _Fallo("CBO: daily_budget de la campaña debe ser un entero > 0")
        if any(cj.daily_budget is not None for cj in e.conjuntos):
            raise _Fallo("CBO: los conjuntos no llevan daily_budget")
    else:
        if c.daily_budget is not None:
            raise _Fallo("ABO: la campaña no lleva daily_budget")
        for cj in e.conjuntos:
            if not _importe(cj.daily_budget):
                raise _Fallo(f"ABO: daily_budget del conjunto {cj.nombre} debe ser un entero > 0")
    if not e.conjuntos:
        raise _Fallo("la estructura no tiene conjuntos")
    refs = {m.ref for m in e.medios}
    conjuntos: set[str] = set()
    anuncios: set[str] = set()
    for cj in e.conjuntos:
        if cj.nombre in conjuntos:
            raise _Fallo(f"nombre de conjunto repetido: {cj.nombre}")
        conjuntos.add(cj.nombre)
        _plataformas(cj.ubicaciones_excluidas, cj.nombre)
        if not cj.anuncios or not cj.paises or not cj.idiomas:
            raise _Fallo(f"conjunto {cj.nombre}: faltan anuncios, países o idiomas")
        for a in cj.anuncios:
            if a.nombre in anuncios:
                raise _Fallo(f"nombre de anuncio repetido: {a.nombre}")
            anuncios.add(a.nombre)
            if a.medio not in refs:
                raise _Fallo(f"anuncio {a.nombre}: el medio {a.medio} no está en medios")


def _plataformas(excluidas: tuple[str, ...], nombre: str) -> list[str] | None:
    """``None`` = ubicaciones automáticas de Meta (sin ``publisher_platforms``)."""
    if not excluidas:
        return None
    ajenas = [x for x in excluidas if x not in PLATAFORMAS]
    if ajenas:
        raise _Fallo(f"conjunto {nombre}: ubicación desconocida {ajenas[0]!r}")
    quedan = [x for x in PLATAFORMAS if x not in excluidas]
    if not quedan:
        raise _Fallo(f"conjunto {nombre}: no queda ninguna plataforma")
    return quedan


def _preparar_meta(p: Propuesta, graph) -> dict[str, int]:
    e = p.estructura
    info = graph.cuenta(p.cuenta)
    if info.offset is None:
        raise _Fallo(f"moneda sin offset confirmado (P-21): {info.currency or '?'}", error="moneda")
    if info.currency != e.moneda:
        raise _Fallo(f"moneda {e.moneda} distinta de la de la cuenta ({info.currency})", error="moneda")
    locales: dict[str, int] = {}
    for cj in e.conjuntos:
        for codigo in cj.idiomas:
            if codigo in locales:
                continue
            filas = graph.buscar("adlocale", codigo, ["key", "name"])
            claves = {str(f.get("key")) for f in filas if isinstance(f, dict) and f.get("key") is not None}
            if len(filas) != 1 or len(claves) != 1:
                raise _Fallo(f"idioma sin resolver: {codigo}")
            (clave,) = claves
            if not _ID_META.fullmatch(clave):
                raise _Fallo(f"idioma sin resolver: {codigo}")
            locales[codigo] = int(clave)
    return locales


# -- datos que se envían (status siempre PAUSED) ------------------------------------------------
def _datos_campana(e: Estructura) -> dict:
    c = e.campana
    datos: dict = {"name": c.nombre, "objective": c.objetivo, "special_ad_categories": [],
                   "spend_cap": c.spend_cap, "status": "PAUSED"}
    if c.tipo_presupuesto == "CBO":
        datos.update(daily_budget=c.daily_budget, bid_strategy=c.bid_strategy)
    else:
        datos["is_adset_budget_sharing_enabled"] = False
    return datos


def _datos_conjunto(e: Estructura, cj, campana_id: str, locales: dict[str, int]) -> dict:
    targeting: dict = {"geo_locations": {"countries": list(cj.paises)},
                       "locales": [locales[x] for x in cj.idiomas]}
    plataformas = _plataformas(cj.ubicaciones_excluidas, cj.nombre)
    if plataformas is not None:
        targeting["publisher_platforms"] = plataformas
    datos: dict = {"campaign_id": campana_id, "name": cj.nombre, "billing_event": "IMPRESSIONS",
                   "optimization_goal": "OFFSITE_CONVERSIONS",
                   "promoted_object": {"pixel_id": e.dataset_id, "custom_event_type": cj.evento},
                   "targeting": targeting, "status": "PAUSED"}
    if e.campana.tipo_presupuesto == "ABO":
        datos.update(daily_budget=cj.daily_budget, bid_strategy=e.campana.bid_strategy)
    return datos


def _datos_creativo(e: Estructura, a, medio: str, video: bool, miniatura: str | None) -> dict:
    cta = {"type": a.cta, "value": {"link": a.url}}
    if video:
        spec = {"page_id": e.pagina_id,
                "video_data": {"video_id": medio, "image_url": miniatura, "message": a.texto, "title": a.titulo,
                               "link_description": a.descripcion, "call_to_action": cta}}
    else:
        spec = {"page_id": e.pagina_id,
                "link_data": {"image_hash": medio, "link": a.url, "message": a.texto, "name": a.titulo,
                              "description": a.descripcion, "call_to_action": cta}}
    return {"name": a.nombre, "object_story_spec": spec}


# -- el montaje ----------------------------------------------------------------------------------
class _Montaje:
    def __init__(self, p: Propuesta, graph, almacen: Almacen, auditoria: Auditoria,
                 ahora: Callable[[], datetime], esperar: Callable[[float], None]):
        self.p, self.e, self.graph = p, p.estructura, graph
        self.almacen, self.auditoria, self.ahora, self.esperar = almacen, auditoria, ahora, esperar
        self.ids = _Ids()
        self.notas: list[str] = []

    def anotar(self, validate_only: bool, ok: bool, detalle: str) -> bool:
        try:
            self.auditoria.anotar(EV_EJECUCION, id=self.p.id, tipo=TIPO, validate_only=validate_only, ok=ok,
                                  detalle=redactar(detalle))
            return True
        except Exception:  # noqa: BLE001 — la auditoría rota no debe tumbar un montaje ya empezado
            return False

    # Validación: nunca crea. Corta (sin crear) ante cualquier fallo o si la auditoría no anota.
    def validar(self, padre: str, arista: str, datos: dict, desc: str) -> None:
        try:
            self.graph.crear(padre, arista, datos, validate_only=True)
        except DetenidoPorStop:
            raise _Fallo(f"{desc}: STOP, no se intentó", error="stop") from None
        except ErrorGraph as ex:
            self.anotar(True, False, f"{desc}; {_texto_error(ex)}")
            raise _Fallo(f"{desc}: validate_only rechazado: {_texto_error(ex)}", error=clasificar(ex)) from None
        except Exception as ex:  # noqa: BLE001 — falla cerrado sin crear
            self.anotar(True, False, f"{desc}; {_texto_error(ex)}")
            raise _Fallo(f"{desc}: validate_only sin respuesta ({_texto_error(ex)}): no se creó",
                         error="red" if isinstance(ex, ErrorRed) else "otro") from None
        if not self.anotar(True, True, f"{desc}; validate_only ok"):
            raise _Fallo(f"{desc}: auditoría no disponible: no se crea")

    def _crear(self, padre: str, arista: str, datos: dict, desc: str) -> str:
        """Único sitio que llama a ``graph.crear``: ``validate_only`` y después exactamente una creación."""
        self.validar(padre, arista, datos, desc)
        try:
            r = self.graph.crear(padre, arista, datos)
        except DetenidoPorStop:
            raise _Fallo(f"{desc}: STOP, no se intentó", error="stop") from None
        except ErrorGraph as ex:
            self.anotar(False, False, f"{desc}; {_texto_error(ex)}")
            raise _Fallo(f"{desc}: Meta lo rechazó: {_texto_error(ex)}", error=clasificar(ex)) from None
        except Exception as ex:  # noqa: BLE001 — no se sabe si salió: nunca se reenvía
            self.anotar(False, False, f"{desc}; sin respuesta tras enviar ({_texto_error(ex)})")
            raise _Fallo(f"{desc}: estado desconocido tras enviar ({_texto_error(ex)}); {_REVISA}",
                         error="red" if isinstance(ex, ErrorRed) else "otro", estado="discrepancia") from None
        nuevo = r.get("id") if isinstance(r, dict) else None
        if not isinstance(nuevo, str) or not _ID_META.fullmatch(nuevo):
            self.anotar(False, False, f"{desc}; respuesta sin id")
            raise _Fallo(f"{desc}: Meta respondió sin id legible; {_REVISA}", estado="discrepancia")
        self.anotar(False, True, f"{desc}; creado {nuevo}")
        return nuevo

    def _cadencia(self, entidad: str) -> None:
        try:
            self.almacen.registrar_cambio(entidad, "estructura", self.ahora())
        except Exception:  # noqa: BLE001 — ya creado; no se pierde el resultado
            self.notas.append(f"no se pudo registrar la cadencia de {entidad}")

    def _subir(self, a: _Archivo) -> str:
        desc = f"medio {a.ref} ({a.ruta})"
        try:
            if a.video:
                # subir_video toma la ruta: se vuelve a verificar el sha256 justo antes (ventana mínima).
                if _sha256_archivo(a.real) != a.sha256:
                    raise _Fallo(f"sha256 distinto en {a.ruta}: el archivo cambió tras verificarlo")
                medio = self.graph.subir_video(self.p.cuenta, a.real)
            else:
                medio = self.graph.subir_imagen(self.p.cuenta, a.contenido, a.real.name)
        except _Fallo:
            raise
        except DetenidoPorStop:
            raise _Fallo(f"{desc}: STOP, no se intentó", error="stop") from None
        except ErrorGraph as ex:
            self.anotar(False, False, f"{desc}; {_texto_error(ex)}")
            raise _Fallo(f"{desc}: Meta rechazó la subida: {_texto_error(ex)}", error=clasificar(ex)) from None
        except Exception as ex:  # noqa: BLE001 — subida en duda: no se reintenta
            self.anotar(False, False, f"{desc}; sin respuesta tras enviar ({_texto_error(ex)})")
            raise _Fallo(f"{desc}: subida en estado desconocido ({_texto_error(ex)}); revísalo en la biblioteca "
                         "de medios", error="red" if isinstance(ex, ErrorRed) else "otro") from None
        if not isinstance(medio, str) or not medio:
            raise _Fallo(f"{desc}: Meta respondió sin identificador", estado="discrepancia")
        self.ids.medios[a.ref] = medio
        self.anotar(False, True, f"{desc}; subido {medio}")
        return medio

    def _esperar_video(self, ref: str, vid: str) -> str:
        for n in range(MAX_LECTURAS_VIDEO):
            if n:
                self.esperar(INTERVALO_VIDEO)
            try:
                r = self.graph.leer(vid, ["status"])
            except Exception as ex:  # noqa: BLE001
                raise _Fallo(f"vídeo {ref} {vid}: no se pudo leer su estado ({_texto_error(ex)})",
                             error="red" if isinstance(ex, ErrorRed) else "otro") from None
            st = r.get("status") if isinstance(r, dict) else None
            estado = st.get("video_status") if isinstance(st, dict) else None
            if estado == "ready":
                break
            if estado == "error":
                raise _Fallo(f"vídeo {ref} {vid}: Meta no pudo procesarlo (error)")
        else:
            raise _Fallo(f"vídeo {ref} {vid}: no quedó listo tras {MAX_LECTURAS_VIDEO} lecturas")
        try:
            r = self.graph.leer(vid, ["thumbnails{uri,is_preferred}"])
        except Exception as ex:  # noqa: BLE001
            raise _Fallo(f"vídeo {ref} {vid}: no se pudo leer la miniatura ({_texto_error(ex)})") from None
        th = r.get("thumbnails") if isinstance(r, dict) else None
        filas = [x for x in (th.get("data") if isinstance(th, dict) else None) or []
                 if isinstance(x, dict) and isinstance(x.get("uri"), str) and x["uri"].startswith("https://")]
        if not filas:
            raise _Fallo(f"vídeo {ref} {vid}: sin miniatura")
        preferida = next((x for x in filas if x.get("is_preferred") is True), filas[0])
        return preferida["uri"]

    def montar(self, prep: _Preparado) -> None:
        e, cuenta = self.e, self.p.cuenta
        medios: dict[str, str] = {}
        miniaturas: dict[str, str] = {}
        for ref, a in prep.archivos.items():
            medios[ref] = self._subir(a)
            if a.video:
                miniaturas[ref] = self._esperar_video(ref, medios[ref])
        campana = self._crear(cuenta, "campaigns", _datos_campana(e), f"campaña {e.campana.nombre}")
        self.ids.campana = campana
        self._cadencia(campana)
        for cj in e.conjuntos:
            sid = self._crear(cuenta, "adsets", _datos_conjunto(e, cj, campana, prep.locales),
                              f"conjunto {cj.nombre}")
            self.ids.conjuntos[cj.nombre] = sid
            self._cadencia(sid)
            for a in cj.anuncios:
                video = prep.archivos[a.medio].video
                creativo = self._crear(cuenta, "adcreatives",
                                       _datos_creativo(e, a, medios[a.medio], video, miniaturas.get(a.medio)),
                                       f"creativo {a.nombre}")
                self.ids.creativos[a.nombre] = creativo
                anuncio = self._crear(cuenta, "ads", {"name": a.nombre, "adset_id": sid,
                                                      "creative": {"creative_id": creativo}, "status": "PAUSED"},
                                      f"anuncio {a.nombre}")
                self.ids.anuncios[a.nombre] = anuncio

    def releer(self) -> tuple[list[str], list[str]]:
        """Devuelve (no PAUSED, otras discrepancias). Cualquier duda cuenta como discrepancia."""
        e = self.e
        cbo = e.campana.tipo_presupuesto == "CBO"
        objetos: list[tuple[str, str, dict]] = []
        importes_c = {"spend_cap": e.campana.spend_cap} | ({"daily_budget": e.campana.daily_budget} if cbo else {})
        objetos.append((f"campaña {self.ids.campana}", self.ids.campana, importes_c))
        for cj in e.conjuntos:
            objetos.append((f"conjunto {cj.nombre} {self.ids.conjuntos[cj.nombre]}", self.ids.conjuntos[cj.nombre],
                            {} if cbo else {"daily_budget": cj.daily_budget}))
            for a in cj.anuncios:
                objetos.append((f"anuncio {a.nombre} {self.ids.anuncios[a.nombre]}", self.ids.anuncios[a.nombre], {}))
        no_paused: list[str] = []
        otras: list[str] = []
        for desc, oid, importes in objetos:
            try:
                r = self.graph.leer(oid, ["status", "effective_status", *importes])
            except Exception as ex:  # noqa: BLE001
                otras.append(f"{desc}: no se pudo releer ({_texto_error(ex)}): estado desconocido")
                continue
            status = r.get("status") if isinstance(r, dict) else None
            efectivo = r.get("effective_status") if isinstance(r, dict) else None
            if status != "PAUSED" or not isinstance(efectivo, str) or efectivo == "ACTIVE":
                no_paused.append(f"{desc}: status {status}, effective_status {efectivo}")
            for campo, pedido in importes.items():
                leido = r.get(campo) if isinstance(r, dict) else None
                if str(leido) != str(pedido):
                    otras.append(f"{desc}: {campo} {leido}, pedido {pedido}")
        return no_paused, otras

    def activar(self) -> tuple[dict | None, str | None]:
        momento = self.ahora()
        nuevo_id = siguiente_id(self.almacen, momento)
        if nuevo_id is None:
            return None, _SIN_NUMERO
        ops = [{"entidad": "campaign", "id": self.ids.campana, "campo": "status", "de_esperado": "PAUSED",
                "a": "ACTIVE"}]
        ops += [{"entidad": "adset", "id": i, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
                for i in self.ids.conjuntos.values()]
        ops += [{"entidad": "ad", "id": i, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}
                for i in self.ids.anuncios.values()]
        datos: dict = {"version": 1, "id": nuevo_id, "tipo": "activar", "creada": momento.isoformat(),
                       "origen": ORIGEN, "cuenta": self.p.cuenta, "operaciones": ops,
                       "motivo": f"activar el montaje {self.p.id} (creado en PAUSED)",
                       "evidencia": {"montaje": self.p.id, "medios": [m.ruta for m in self.e.medios]}}
        if self.p.producto is not None:
            datos["producto"] = self.p.producto
        if self.p.pais is not None:
            datos["pais"] = self.p.pais
        try:
            cargar_propuesta(datos)
        except PropuestaInvalida as ex:
            return None, f"no se pudo preparar la propuesta activar ({ex.motivo}): crea la propuesta a mano"
        return datos, None

    def cerrar(self, estado: str, detalle: str, error: str | None = None) -> Resultado:
        partes = [detalle, self.ids.resumen(), *self.notas]
        texto = " | ".join(x for x in partes if x)
        algo = self.ids.algo()
        parcial = estado != "ejecutada" and algo
        r = Resultado(estado, redactar(texto), parcial=parcial, error=error, ids_creados=self.ids.a_dict())
        self.anotar(False, estado == "ejecutada", f"{estado}: {texto}")
        return r


def _rechazo(p: Propuesta, auditoria: Auditoria, detalle: str, error: str = "otro") -> Resultado:
    """Nada escrito en Meta: un único ``ejecucion`` con validate_only=False, ok=False."""
    try:
        auditoria.anotar(EV_EJECUCION, id=p.id, tipo=TIPO, validate_only=False, ok=False, detalle=redactar(detalle))
    except Exception:  # noqa: BLE001, S110
        pass
    return Resultado("fallida", redactar(detalle), error=error)


def montar(p: Propuesta, graph, almacen: Almacen, auditoria: Auditoria, vault: Path, *,
           ahora: Callable[[], datetime] = _ahora, esperar: Callable[[float], None] = time.sleep) -> Resultado:
    """Monta ``p`` (``crear_estructura_pausada``) en PAUSED. Siempre devuelve un ``Resultado``."""
    if p.tipo != TIPO or p.estructura is None or not isinstance(p.cuenta, str):
        return _rechazo(p, auditoria, f"montar solo ejecuta {TIPO} con estructura y cuenta")
    e = p.estructura
    # 1) preparación: primero lo local (nada sale a Meta si un medio no es el aprobado), luego lecturas.
    try:
        _preparar_forma(p)
        archivos = _preparar_medios(e, vault)
        locales = _preparar_meta(p, graph)
    except _Fallo as f:
        return _rechazo(p, auditoria, f.detalle, f.error)
    except ErrorGraph as ex:
        return _rechazo(p, auditoria, f"no se pudo leer Meta: {_texto_error(ex)}", clasificar(ex))
    except ErrorRed as ex:
        return _rechazo(p, auditoria, f"no se pudo leer Meta ({ex.motivo})", "red")
    except DetenidoPorStop:
        return _rechazo(p, auditoria, "STOP: no se intentó", "stop")
    except Exception as ex:  # noqa: BLE001 — toda salida es un Resultado
        return _rechazo(p, auditoria, f"preparación fallida: {_texto_error(ex)}")

    m = _Montaje(p, graph, almacen, auditoria, ahora, esperar)
    # 2) validate_only de la campaña (sin crear nada; con solo_validar se acaba aquí).
    try:
        m.validar(p.cuenta, "campaigns", _datos_campana(e), f"campaña {e.campana.nombre}")
    except _Fallo as f:
        m.anotar(e.solo_validar, False, f"fallida: {f.detalle}; no se subió ni se creó nada")
        return Resultado("fallida", redactar(f.detalle), error=f.error)
    except Exception as ex:  # noqa: BLE001
        return _rechazo(p, auditoria, f"validate_only falló: {_texto_error(ex)}")
    if e.solo_validar:
        detalle = ("solo validar: la campaña pasa validate_only; los conjuntos y anuncios no se pueden validar "
                   "sin crear sus padres, así que no se validaron; no se subió ni se creó nada")
        m.anotar(True, True, f"ejecutada: {detalle}")
        return Resultado("ejecutada", detalle)

    # 3) escrituras reales: desde aquí nada escapa.
    try:
        m.montar(_Preparado(archivos, locales))
    except _Fallo as f:
        return m.cerrar(f.estado, f.detalle, f.error)
    except Exception as ex:  # noqa: BLE001
        return m.cerrar("discrepancia", f"error inesperado durante el montaje ({_texto_error(ex)}); {_REVISA}",
                        "otro")
    try:
        no_paused, otras = m.releer()
    except Exception as ex:  # noqa: BLE001
        return m.cerrar("discrepancia", f"no se pudo releer lo creado ({_texto_error(ex)})")
    if no_paused:
        return m.cerrar("discrepancia", "URGENTE: objetos creados que no están en PAUSED: " + "; ".join(
            no_paused + otras) + "; no se propone activar")
    if otras:
        return m.cerrar("discrepancia", "lo releído no es lo pedido: " + "; ".join(otras))
    detalle = "montaje en PAUSED completado; la relectura confirma"
    nueva: dict | None = None
    if p.origen == "/montar":
        try:
            nueva, aviso = m.activar()
        except Exception as ex:  # noqa: BLE001 — nada tras crear puede escapar
            nueva = None
            aviso = f"no se pudo preparar la propuesta activar ({_texto_error(ex)}): crea la propuesta a mano"
        if aviso:
            detalle = f"{detalle} | {aviso}"
    r = m.cerrar("ejecutada", detalle)
    return Resultado(r.estado, r.detalle, ids_creados=r.ids_creados, nueva_propuesta=nueva)
