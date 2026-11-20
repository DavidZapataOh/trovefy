"""Whisper real sobre un audio de prueba en búlgaro (plan 21, Tarea 9).

El audio (``tests/fixtures/creativos/voz-bg.mp4`` y su guion ``voz-bg.txt``) se genera una vez con la primera voz
aprobada de la tanda real y se guarda como fixture propio; hasta entonces este test se salta (generarlo cuesta).
"""

from pathlib import Path

import pytest
from trovefy.creativos import whisper
from trovefy.creativos.config import cargar_plantilla
from trovefy.referencia import watch

pytestmark = pytest.mark.integracion
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "creativos"


def test_whisper_real_bg(tmp_path):
    video, guion = FIX / "voz-bg.mp4", FIX / "voz-bg.txt"
    if not video.is_file() or not guion.is_file():
        pytest.skip("falta el audio de prueba en búlgaro (se guarda con la primera tanda real)")
    entorno = watch.comprobar_entorno()
    if not entorno.whisperx:
        pytest.skip("WhisperX local no instalado")
    inf = watch.ejecutar_watch(video, tmp_path, "bg", entorno)
    texto = guion.read_text(encoding="utf-8")
    assert whisper.similitud(texto, inf.transcripcion or "", "bg") >= cargar_plantilla().whisper_similitud_min
