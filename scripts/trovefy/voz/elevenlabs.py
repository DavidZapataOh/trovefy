"""Voz de ElevenLabs (plan 21, Tarea 6; S1 8:30), solo si APIMart no da precio medible o su voz no pasa Whisper.

``POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128`` con la cabecera
``xi-api-key`` y ``{"text", "model_id"}``; responde MP3 binario. La clave la guarda el usuario en
``~/.config/trovefy/elevenlabs.env`` (``ELEVENLABS_API_KEY``, modo 0600); Claude nunca la ve. El coste por carácter
sale del plan que el usuario contrató (``config/creativos.yaml → elevenlabs``) y se aprueba antes de gastar.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from trovefy.secretos import leer_env

BASE = "https://api.elevenlabs.io"
RUTA_ENV = Path.home() / ".config/trovefy/elevenlabs.env"
MAX_TEXTO = 5000
MAX_AUDIO = 50 * 2**20
_VOZ = re.compile(r"[A-Za-z0-9]{8,64}")
_CLAVE = re.compile(r"[A-Za-z0-9_-]{20,200}")


class ErrorElevenLabs(Exception):
    pass


class SinClaveElevenLabs(ErrorElevenLabs):
    pass


@dataclass(frozen=True)
class CredElevenLabs:
    clave: str

    def __repr__(self) -> str:
        return "CredElevenLabs(clave=***)"


def leer_credenciales(ruta: Path = RUTA_ENV) -> CredElevenLabs:
    if not Path(ruta).is_file():
        raise SinClaveElevenLabs(f"falta {ruta}: el usuario guarda ahí ELEVENLABS_API_KEY (modo 0600)")
    clave = leer_env(ruta).get("ELEVENLABS_API_KEY", "")
    if not _CLAVE.fullmatch(clave):
        raise SinClaveElevenLabs("ELEVENLABS_API_KEY falta o tiene una forma rara")
    return CredElevenLabs(clave)


def cuerpo(texto: str, modelo: str) -> dict:
    if not isinstance(texto, str) or not texto.strip() or len(texto) > MAX_TEXTO:
        raise ValueError(f"el texto de la voz debe tener de 1 a {MAX_TEXTO} caracteres")
    return {"text": texto, "model_id": modelo}


def generar(cred: CredElevenLabs, voz_id: str, datos: dict, abrir=urllib.request.urlopen, timeout: float = 120) -> bytes:
    """Bytes MP3 de la voz. Ningún mensaje lleva la clave."""
    if not isinstance(voz_id, str) or not _VOZ.fullmatch(voz_id):
        raise ValueError("voz de ElevenLabs mal escrita")
    url = f"{BASE}/v1/text-to-speech/{quote(voz_id, safe='')}?output_format=mp3_44100_128"
    req = urllib.request.Request(url, data=json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                                 headers={"xi-api-key": cred.clave, "Content-Type": "application/json",
                                          "Accept": "audio/mpeg", "User-Agent": "trovefy"}, method="POST")
    try:
        with abrir(req, timeout=timeout) as resp:
            codigo, audio = resp.status, resp.read(MAX_AUDIO + 1)
    except urllib.error.HTTPError as exc:
        raise ErrorElevenLabs(f"ElevenLabs respondió HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise ErrorElevenLabs("sin red: ElevenLabs no responde") from None
    if codigo != 200 or len(audio) > MAX_AUDIO:
        raise ErrorElevenLabs(f"ElevenLabs respondió HTTP {codigo}")
    if not (audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)):
        raise ErrorElevenLabs("ElevenLabs no devolvió MP3")
    return audio
