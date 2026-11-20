"""Carga y validación de ``config/creativos.yaml`` (plan 21, Tarea 1). Cada hoja es ``{valor, fuente, fecha}``.

Mismo formato que ``config/producto.yaml`` (resolución 12). Los importes salen en ``Decimal`` y se escriben
entre comillas: un ``float`` es ``ConfigInvalida("importe sin comillas")``. Un precio en ``null`` es «no medido»:
esa pieza no se envía hasta que se mida (P-11), pero la configuración carga.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.economia.config import EconomiaInvalida, es_hoja, revisar_hojas
from trovefy.vault.escritura import escribir_atomico

PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "creativos.yaml"
RELATIVA = Path("config") / "creativos.yaml"
PLANTILLAS_VIDEO = ("broll_voz", "ugc", "claymation", "3d")
_MODELO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", re.ASCII)
_CTA = re.compile(r"[A-Z][A-Z0-9_]{0,59}")


class ConfigInvalida(ValueError):
    """``config/creativos.yaml`` no cumple el formato."""


@dataclass(frozen=True)
class Plantilla:
    nombre: str
    descripcion: str
    coste_tanda_usd: Decimal


@dataclass(frozen=True)
class ElevenLabs:
    plan: str | None
    coste_mensual_usd: Decimal | None
    caracteres_mes: int | None
    modelo: str | None
    voz_id: str | None

    @property
    def usd_por_caracter(self) -> Decimal | None:
        if self.coste_mensual_usd is None or not self.caracteres_mes:
            return None
        return self.coste_mensual_usd / Decimal(self.caracteres_mes)


@dataclass(frozen=True)
class ConfigCreativos:
    piezas: int
    videos_sin_mezcla: int
    imagenes_sin_mezcla: int
    al_test: int
    reserva: int
    briefs_candidatos: int
    seguir_referencia: bool
    plantillas: dict[str, Plantilla]
    formatos_extra_video: tuple[str, ...]
    reparto_por_defecto: tuple[str, ...]
    formatos_estaticos: tuple[str, ...]
    hooks: tuple[str, ...]
    principal_visible: int
    principal_max: int
    titulo_max: int
    descripcion_max: int
    cta_por_defecto: str
    imagen_ancho: int
    imagen_alto: int
    video_ancho: int
    video_alto: int
    duracion_s: tuple[int, int]
    fps: int
    gancho_s: int
    prueba_gancho_s: int
    corte_broll_s: Decimal
    zona_segura_arriba_pct: int
    zona_segura_abajo_pct: int
    musica_db: int
    voz: str
    musica: str
    clip_gancho: bool
    whisper_similitud_min: Decimal
    idiomas_candidatos: tuple[str, ...]
    expresiones_riesgo: dict[str, tuple[str, ...]]
    tope_tanda_usd: Decimal
    tope_renovacion_usd: Decimal
    modelos_imagen: tuple[str, ...]
    resolucion: str
    modelo_tts: str | None
    voz_tts: str | None
    precio_tts_usd_1000: Decimal | None
    modelo_video: str | None
    resolucion_video: str
    precio_video_usd_segundo: Decimal | None
    modelo_musica: str | None
    version_musica: str | None
    precio_musica_usd_pista: Decimal | None
    licencia_musica_comercial: bool | None
    elevenlabs: ElevenLabs

    @property
    def formatos_video(self) -> tuple[str, ...]:
        return (*self.plantillas, *self.formatos_extra_video)

    def mezcla(self, imagenes_pct: int | None) -> tuple[int, int]:
        """(imágenes, vídeos) de la tanda: la del competidor si está medida (L1 46:54), si no 3/7 (C2 6:50)."""
        if imagenes_pct is None or not self.seguir_referencia:
            return self.imagenes_sin_mezcla, self.videos_sin_mezcla
        imagenes = int((Decimal(imagenes_pct) * self.piezas / 100).to_integral_value(rounding="ROUND_HALF_DOWN"))  # 85 % → 8 (L1 56:40)
        imagenes = min(max(imagenes, 0), self.piezas - 1)  # al menos un vídeo
        return imagenes, self.piezas - imagenes


def _nodo(datos: dict, clave: str) -> dict:
    actual: Any = datos
    for parte in clave.split("."):
        if not isinstance(actual, dict) or es_hoja(actual) or parte not in actual:
            raise ConfigInvalida(f"falta {clave} en config/creativos.yaml")
        actual = actual[parte]
    if not es_hoja(actual):
        raise ConfigInvalida(f"{clave}: no es una hoja {{valor, fuente, fecha}}")
    return actual


def _valor(datos: dict, clave: str, *, nulo: bool = False) -> Any:
    v = _nodo(datos, clave)["valor"]
    if v is None and not nulo:
        raise ConfigInvalida(f"no medido: falta {clave} en config/creativos.yaml")
    return v


def _entero(datos: dict, clave: str, *, minimo: int = 1, nulo: bool = False) -> int | None:
    v = _valor(datos, clave, nulo=nulo)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimo:
        raise ConfigInvalida(f"{clave}: debe ser un entero ≥ {minimo} ({v!r})")
    return v


def _importe(datos: dict, clave: str, *, nulo: bool = False, positivo: bool = True) -> Decimal | None:
    v = _valor(datos, clave, nulo=nulo)
    if v is None:
        return None
    if isinstance(v, float):
        raise ConfigInvalida(f"{clave}: importe sin comillas ({v!r}); escríbelo entre comillas, p. ej. \"6.00\"")
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise ConfigInvalida(f"{clave}: importe ilegible ({v!r})")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise ConfigInvalida(f"{clave}: importe ilegible ({v!r})") from None
    if not d.is_finite() or (d <= 0 if positivo else d < 0):
        raise ConfigInvalida(f"{clave}: importe no válido ({v!r})")
    return d


def _lista(datos: dict, clave: str, *, vacia: bool = False) -> tuple[str, ...]:
    v = _valor(datos, clave, nulo=vacia)
    v = [] if v is None else v
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v) or (not v and not vacia):
        raise ConfigInvalida(f"{clave}: debe ser una lista de textos{'' if vacia else ' no vacía'}")
    return tuple(x.strip() for x in v)


def _texto(datos: dict, clave: str, *, nulo: bool = False) -> str | None:
    v = _valor(datos, clave, nulo=nulo)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ConfigInvalida(f"{clave}: debe ser un texto ({v!r})")
    return v.strip()


def _modelo(datos: dict, clave: str) -> str | None:
    v = _texto(datos, clave, nulo=True)
    if v is not None and not _MODELO.fullmatch(v):
        raise ConfigInvalida(f"{clave}: nombre de modelo mal escrito ({v!r})")
    return v


def _construir(datos: Any) -> ConfigCreativos:
    if not isinstance(datos, dict):
        raise ConfigInvalida("config/creativos.yaml no es un mapa")
    try:
        revisar_hojas(datos, "")
    except EconomiaInvalida as exc:
        raise ConfigInvalida(f"config/creativos.yaml: {exc}") from None

    piezas = _entero(datos, "tanda.piezas")
    al_test, reserva = _entero(datos, "tanda.al_test"), _entero(datos, "tanda.reserva")
    if al_test + reserva != piezas:
        raise ConfigInvalida(f"tanda.al_test ({al_test}) + tanda.reserva ({reserva}) debe ser tanda.piezas ({piezas})")
    videos, imagenes = _entero(datos, "tanda.videos_sin_mezcla", minimo=0), _entero(datos, "tanda.imagenes_sin_mezcla",
                                                                                      minimo=0)
    if videos + imagenes != piezas:
        raise ConfigInvalida("tanda.videos_sin_mezcla + tanda.imagenes_sin_mezcla debe ser tanda.piezas")
    candidatos = _entero(datos, "tanda.briefs_candidatos")
    if candidatos < piezas:
        raise ConfigInvalida("tanda.briefs_candidatos no puede ser menor que tanda.piezas")

    bloque = datos.get("plantillas")
    if not isinstance(bloque, dict) or set(bloque) != set(PLANTILLAS_VIDEO):
        raise ConfigInvalida(f"plantillas: deben ser exactamente {', '.join(PLANTILLAS_VIDEO)} (L2 16:01)")
    plantillas = {n: Plantilla(n, _texto(datos, f"plantillas.{n}.descripcion"),
                               _importe(datos, f"plantillas.{n}.coste_tanda_usd")) for n in PLANTILLAS_VIDEO}

    riesgo = _valor(datos, "qa.expresiones_riesgo", nulo=True) or {}
    if not isinstance(riesgo, dict) or not all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)
            for k, v in riesgo.items()):
        raise ConfigInvalida("qa.expresiones_riesgo: un mapa idioma → lista de expresiones")

    cta = _texto(datos, "cta_por_defecto")
    if not _CTA.fullmatch(cta):
        raise ConfigInvalida(f"cta_por_defecto: código de Meta mal escrito ({cta!r}), p. ej. LEARN_MORE")
    sim = _importe(datos, "qa.whisper_similitud_min")
    if sim > 1:
        raise ConfigInvalida("qa.whisper_similitud_min: entre 0 y 1")
    dmin, dmax = _entero(datos, "video.duracion_min_s"), _entero(datos, "video.duracion_max_s")
    if dmin > dmax:
        raise ConfigInvalida("video.duracion_min_s no puede ser mayor que video.duracion_max_s")
    musica_db = _valor(datos, "video.musica_db")
    if isinstance(musica_db, bool) or not isinstance(musica_db, int) or musica_db >= 0:
        raise ConfigInvalida("video.musica_db: un entero negativo (dB por debajo de la voz)")
    licencia = _valor(datos, "apimart.licencia_musica_comercial", nulo=True)
    if licencia is not None and not isinstance(licencia, bool):
        raise ConfigInvalida("apimart.licencia_musica_comercial: true, false o null (no medido)")
    resolucion = _texto(datos, "apimart.resolucion")
    if resolucion not in ("1k", "2k", "4k"):
        raise ConfigInvalida(f"apimart.resolucion: {resolucion!r} no es 1k, 2k ni 4k")
    seguir = _valor(datos, "mezcla.seguir_referencia")
    clip = _valor(datos, "video.clip_gancho")
    if not isinstance(seguir, bool) or not isinstance(clip, bool):
        raise ConfigInvalida("mezcla.seguir_referencia y video.clip_gancho son true o false")
    voz, musica = _texto(datos, "video.voz"), _texto(datos, "video.musica")
    if voz != "siempre" or musica != "siempre":
        raise ConfigInvalida("video.voz y video.musica son «siempre»: todos los vídeos llevan voz y música (L2 15:25)")
    hooks = _lista(datos, "hooks")
    extra = _lista(datos, "formatos_extra_video")
    por_defecto = _lista(datos, "reparto_videos.por_defecto")
    if not set(por_defecto) <= set(extra):
        raise ConfigInvalida("reparto_videos.por_defecto: solo formatos de formatos_extra_video")

    return ConfigCreativos(
        piezas=piezas, videos_sin_mezcla=videos, imagenes_sin_mezcla=imagenes, al_test=al_test, reserva=reserva,
        briefs_candidatos=candidatos, seguir_referencia=seguir, plantillas=plantillas,
        formatos_extra_video=extra, reparto_por_defecto=por_defecto,
        formatos_estaticos=_lista(datos, "formatos_estaticos"), hooks=hooks,
        principal_visible=_entero(datos, "texto.principal_visible"), principal_max=_entero(datos, "texto.principal_max"),
        titulo_max=_entero(datos, "texto.titulo_max"), descripcion_max=_entero(datos, "texto.descripcion_max"),
        cta_por_defecto=cta,
        imagen_ancho=_entero(datos, "imagen.ancho"), imagen_alto=_entero(datos, "imagen.alto"),
        video_ancho=_entero(datos, "video.ancho"), video_alto=_entero(datos, "video.alto"),
        duracion_s=(dmin, dmax), fps=_entero(datos, "video.fps"), gancho_s=_entero(datos, "video.gancho_s"),
        prueba_gancho_s=_entero(datos, "video.prueba_gancho_s"), corte_broll_s=_importe(datos, "video.corte_broll_s"),
        zona_segura_arriba_pct=_entero(datos, "video.zona_segura_arriba_pct", minimo=0),
        zona_segura_abajo_pct=_entero(datos, "video.zona_segura_abajo_pct", minimo=0),
        musica_db=musica_db, voz=voz, musica=musica, clip_gancho=clip,
        whisper_similitud_min=sim, idiomas_candidatos=_lista(datos, "qa.idiomas_candidatos"),
        expresiones_riesgo={k: tuple(v) for k, v in riesgo.items()},
        tope_tanda_usd=_importe(datos, "gasto.tope_tanda_usd"),
        tope_renovacion_usd=_importe(datos, "gasto.tope_renovacion_usd"),
        modelos_imagen=_lista(datos, "apimart.modelos_imagen"), resolucion=resolucion,
        modelo_tts=_modelo(datos, "apimart.modelo_tts"), voz_tts=_texto(datos, "apimart.voz_tts", nulo=True),
        precio_tts_usd_1000=_importe(datos, "apimart.precio_tts_usd_1000_caracteres", nulo=True),
        modelo_video=_modelo(datos, "apimart.modelo_video"),
        resolucion_video=_texto(datos, "apimart.resolucion_video"),
        precio_video_usd_segundo=_importe(datos, "apimart.precio_video_usd_segundo", nulo=True),
        modelo_musica=_modelo(datos, "apimart.modelo_musica"),
        version_musica=_texto(datos, "apimart.version_musica", nulo=True),
        precio_musica_usd_pista=_importe(datos, "apimart.precio_musica_usd_pista", nulo=True),
        licencia_musica_comercial=licencia,
        elevenlabs=ElevenLabs(
            plan=_texto(datos, "elevenlabs.plan", nulo=True),
            coste_mensual_usd=_importe(datos, "elevenlabs.coste_mensual_usd", nulo=True),
            caracteres_mes=_entero(datos, "elevenlabs.caracteres_mes", nulo=True),
            modelo=_modelo(datos, "elevenlabs.modelo"),
            voz_id=_texto(datos, "elevenlabs.voz_id", nulo=True)),
    )


def fuente_de(vault: Path, clave: str) -> str | None:
    """La ``fuente`` de una hoja de ``config/creativos.yaml`` (para decir de dónde sale un precio)."""
    try:
        datos = cargar_yaml((Path(vault) / RELATIVA).read_text(encoding="utf-8"))
        return _nodo(datos, clave)["fuente"]
    except (OSError, yaml.YAMLError, ConfigInvalida):
        return None


def cargar_config(vault: Path) -> ConfigCreativos:
    ruta = Path(vault) / RELATIVA
    if not ruta.is_file():
        raise FileNotFoundError("falta config/creativos.yaml: ejecuta `trovefy creativos iniciar`")
    return cargar_texto(ruta.read_text(encoding="utf-8"))


def cargar_texto(texto: str) -> ConfigCreativos:
    try:
        datos = cargar_yaml(texto)
    except yaml.YAMLError as exc:
        raise ConfigInvalida(f"config/creativos.yaml no se puede leer: {exc}") from None
    return _construir(datos)


def cargar_plantilla() -> ConfigCreativos:
    return cargar_texto(PLANTILLA.read_text(encoding="utf-8"))


def iniciar_config(vault: Path) -> Path:
    """Copia la plantilla a ``config/creativos.yaml``; nunca sobrescribe."""
    ruta = Path(vault) / RELATIVA
    if ruta.exists():
        raise FileExistsError(f"ya existe {RELATIVA}: no se sobrescribe")
    escribir_atomico(ruta, PLANTILLA.read_text(encoding="utf-8"))
    return ruta
