"""TTS de APIMart (plan 21, Tarea 6) y subida de audio.

Forma leída en ``docs.apimart.ai/en/api-reference/audios/tts`` (2026-11-20): ``POST /v1/audio/speech`` con
``model`` (``gpt-4o-mini-tts``), ``input`` (≤ 4096 caracteres), ``voice`` (alloy, echo, fable, onyx, nova, shimmer),
``response_format`` (wav, opus, aac, flac, pcm) y ``speed`` (0,25–4); responde **audio binario** (síncrono, sin
tarea). La documentación no da precio: ``precio_tts`` sale de ``config/creativos.yaml`` y, sin él, ``None``
(«no medido»: no se envía nada, P-11).

Subida de audio (``docs.apimart.ai/en/api-reference/uploads/audios``): ``POST /v1/uploads/audios?retention_days=3``,
multipart con el campo ``file``; MP3, WAV o M4A, 15 MB; la URL va en la raíz (``url``). Sirve para el UGC con
labios sincronizados (``audio_urls`` del vídeo).
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal

from trovefy.apimart.http import (
    Credenciales,
    RespuestaInesperada,
    SinRed,
    _lanzar,
    _leer_json,
    abrir_sin_redireccion,
    clave_valida,
    pedir,
    validar_base,
)

RUTA_TTS = "/v1/audio/speech"
MAX_TEXTO = 4096
VOCES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
FORMATO = "wav"
MAX_AUDIO = 50 * 2**20
MAX_SUBIDA_AUDIO = 15 * 2**20
_TIPOS_AUDIO = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4"}


@dataclass(frozen=True)
class PrecioVoz:
    proveedor: str  # apimart | elevenlabs
    modelo: str
    usd_por_caracter: Decimal
    fuente: str

    def estimado(self, texto: str) -> Decimal:
        return (self.usd_por_caracter * len(texto)).quantize(Decimal("0.000001"))


def precio_tts(modelo: str | None, usd_1000: Decimal | None, fuente: str | None) -> PrecioVoz | None:
    """Precio del TTS de APIMart desde ``config/creativos.yaml``; ``None`` (no medido) ante cualquier hueco."""
    if not modelo or usd_1000 is None or not usd_1000.is_finite() or usd_1000 <= 0 or usd_1000 > 1:
        return None
    return PrecioVoz("apimart", modelo, usd_1000 / 1000, fuente or "config/creativos.yaml")


def cuerpo_tts(modelo: str, texto: str, voz: str, velocidad: Decimal | None = None) -> dict:
    if not isinstance(texto, str) or not texto.strip() or len(texto) > MAX_TEXTO:
        raise ValueError(f"el texto de la voz debe tener de 1 a {MAX_TEXTO} caracteres")
    if voz not in VOCES:
        raise ValueError(f"voz «{voz}» no es una de {', '.join(VOCES)}")
    cuerpo = {"model": modelo, "input": texto, "voice": voz, "response_format": FORMATO}
    if velocidad is not None:
        cuerpo["speed"] = float(velocidad)
    return cuerpo


def es_audio(datos: bytes) -> str | None:
    """Extensión del audio por su cabecera (wav, mp3, m4a, flac, ogg) o ``None``."""
    if datos[:4] == b"RIFF" and datos[8:12] == b"WAVE":
        return "wav"
    if datos[:3] == b"ID3" or (len(datos) > 1 and datos[0] == 0xFF and datos[1] & 0xE0 == 0xE0):
        return "mp3"
    if datos[4:8] == b"ftyp":
        return "m4a"
    if datos[:4] == b"fLaC":
        return "flac"
    if datos[:4] == b"OggS":
        return "ogg"
    return None


def pedir_audio(cred: Credenciales, cuerpo: dict, abrir=abrir_sin_redireccion, timeout: float = 120) -> bytes:
    """``POST /v1/audio/speech`` → bytes del audio. Errores JSON con nombre, como ``pedir``."""
    raiz = cred.base.rstrip("/")
    validar_base(raiz)
    if not clave_valida(cred.clave):
        raise RespuestaInesperada("la clave tiene caracteres raros")
    req = urllib.request.Request(raiz + RUTA_TTS, data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "audio/*",
                                          "User-Agent": "trovefy", "Authorization": f"Bearer {cred.clave}"},
                                 method="POST")
    try:
        with abrir(req, timeout=timeout) as resp:
            codigo, datos = resp.status, resp.read(MAX_AUDIO + 1)
    except urllib.error.HTTPError as exc:
        try:
            datos = exc.read(1 << 20) if exc.fp is not None else b""
        except Exception:  # noqa: BLE001
            datos = b""
        _lanzar(exc.code, _leer_json(datos), cred.clave)
        raise
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise SinRed("sin red: APIMart no responde") from None
    if codigo >= 400:
        _lanzar(codigo, _leer_json(datos), cred.clave)
    if len(datos) > MAX_AUDIO:
        raise RespuestaInesperada("el audio de APIMart pasa de 50 MB")
    if es_audio(datos) is None:
        raise RespuestaInesperada("APIMart no devolvió audio")
    return datos


def subir_audio(cred: Credenciales, nombre: str, datos: bytes, abrir=abrir_sin_redireccion) -> str:
    """URL pública (https) del audio subido a APIMart (72 h)."""
    ext = es_audio(datos)
    if ext not in _TIPOS_AUDIO:
        raise ValueError("APIMart solo admite MP3, WAV o M4A como audio de referencia")
    if len(datos) > MAX_SUBIDA_AUDIO:
        raise ValueError("el audio pasa de 15 MB; APIMart no lo admite")
    frontera = f"trovefy-{uuid.uuid4().hex}"
    limpio = re.sub(r"[^A-Za-z0-9_-]", "-", nombre)[:60] or "voz"
    cuerpo = (f'--{frontera}\r\nContent-Disposition: form-data; name="file"; filename="{limpio}.{ext}"\r\n'
              f"Content-Type: {_TIPOS_AUDIO[ext]}\r\n\r\n").encode() + datos + f"\r\n--{frontera}--\r\n".encode()
    resp = pedir(cred, "POST", "/v1/uploads/audios?retention_days=3", cuerpo,
                 f"multipart/form-data; boundary={frontera}", abrir, timeout=120)
    url = resp.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RespuestaInesperada("APIMart no devolvió una URL https de la subida")
    return url
