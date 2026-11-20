"""QA de idioma con Whisper (plan 21, Tarea 9): «Whisper contra el texto, 0,925 de similitud» (C1 51:00).

Se re-transcribe cada vídeo con el WhisperX local que ya instaló ``/ver-anuncios`` (``trovefy.referencia.watch``;
sin red ni clave) y se compara con el guion de voz. Todos los vídeos llevan voz. Sin WhisperX el resultado es
«no medido» con los pasos para instalarlo (los ejecuta el usuario; Claude no usa sudo) y la tanda no cierra.
Con ``corregir`` se re-voza una vez con el texto ajustado (L1 59:55); si sigue por debajo con APIMart, la voz pasa
a ElevenLabs (S1 8:30, con su coste aprobado); si tampoco llega, se para y se avisa al usuario.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from trovefy.creativos import registro
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.guion import GuionVideo
from trovefy.referencia import watch

_PUNTUACION = re.compile(r"[^\w\s€$£]", re.UNICODE)


@dataclass(frozen=True)
class ResultadoWhisper:
    ad: str
    estado: Literal["ok", "corregir", "no_medido"]
    similitud: Decimal | None
    transcripcion: str | None
    motivo: str | None


def normalizar(texto: str, idioma: str) -> list[str]:
    """Minúsculas, sin puntuación, ``ё``→``е`` y comillas unificadas; números y monedas tal cual (si el guion dice
    el precio en palabras y Whisper devuelve cifras, la similitud baja: es lo que hay que ver, L1 59:55)."""
    t = unicodedata.normalize("NFC", texto or "").lower().replace("ё", "е")
    t = re.sub(r"[«»“”„\"'’`]", " ", t)
    t = re.sub(r"(?<=\d)[,.](?=\d)", "§", t)  # 13,90 se queda como un solo número
    t = _PUNTUACION.sub(" ", t).replace("§", ",")
    return t.split()


def similitud(guion: str, transcripcion: str, idioma: str) -> Decimal:
    a, b = normalizar(guion, idioma), normalizar(transcripcion, idioma)
    if not a and not b:
        return Decimal("1.000")
    r = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return Decimal(str(r)).quantize(Decimal("0.001"))


def revisar_voz(guion: GuionVideo, video: Path, idioma: str, cfg: ConfigCreativos, trabajo: Path, *,
                entorno: watch.Entorno | None = None, ejecutar=None) -> ResultadoWhisper:
    if not guion.texto_voz.strip():
        return ResultadoWhisper(guion.ad, "corregir", None, None, "un vídeo sin voz es un fallo (L2 15:25)")
    entorno = entorno or watch.comprobar_entorno()
    if not entorno.whisperx:
        pasos = "; ".join(watch.pasos_instalacion(entorno)) or "instala WhisperX con /ver-anuncios"
        return ResultadoWhisper(guion.ad, "no_medido", None, None,
                                f"no medido: falta WhisperX local ({entorno.whisperx_detalle}). Pasos para el usuario: "
                                f"{pasos}")
    kw = {"ejecutar": ejecutar} if ejecutar else {}
    inf = watch.ejecutar_watch(Path(video), Path(trabajo), idioma, entorno, **kw)
    if inf.transcripcion is None:
        return ResultadoWhisper(guion.ad, "no_medido", None, None, inf.motivo or "no medido: sin transcripción")
    s = similitud(guion.texto_voz, inf.transcripcion, idioma)
    estado = "ok" if s >= cfg.whisper_similitud_min else "corregir"
    return ResultadoWhisper(guion.ad, estado, s, inf.transcripcion, None)


def anotar(carpeta: Path, r: ResultadoWhisper, cfg: ConfigCreativos, proveedor: str, ahora: datetime) -> Path:
    video = registro.archivo_pieza(carpeta, r.ad, "video")
    datos = {"ad": r.ad, "sha256": registro.sha_archivo(video) or "falta", "estado": r.estado,
             "similitud": str(r.similitud) if r.similitud is not None else "no medido",
             "umbral": str(cfg.whisper_similitud_min), "proveedor": proveedor}
    if r.motivo:
        datos["motivo"] = r.motivo
    return registro.anotar(carpeta, "whisper", datos, f"Transcripción: {r.transcripcion or '—'}", ahora)


def siguiente_paso(carpeta: Path, ad: str) -> Literal["nada", "revozar", "elevenlabs", "parar"]:
    """Tras un ``corregir``: re-vozar una vez con APIMart, luego ElevenLabs, luego parar y avisar al usuario."""
    hist = [s for s in registro.leer(carpeta) if s.tipo == "whisper" and s.datos.get("ad") == ad]
    if not hist or hist[-1].datos.get("estado") != "corregir":
        return "nada"
    malos_apimart = sum(1 for s in hist if s.datos.get("estado") == "corregir" and s.datos.get("proveedor") == "apimart")
    if hist[-1].datos.get("proveedor") == "elevenlabs":
        return "parar"
    return "revozar" if malos_apimart < 2 else "elevenlabs"
