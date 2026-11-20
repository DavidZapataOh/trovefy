"""QA de idioma con Whisper local (plan 21, Tarea 9). Sin WhisperX real: entorno y ejecutor falsos."""

import subprocess
from decimal import Decimal

from trovefy.creativos import registro, whisper
from trovefy.creativos.config import cargar_plantilla
from trovefy.creativos.guion import validar_video
from trovefy.referencia.watch import Entorno

from .ejemplos import AHORA, guion_video

CFG = cargar_plantilla()
LISTO = Entorno("/usr/bin/ffmpeg", "/usr/bin/ffprobe", True, True, "listo")
SIN = Entorno("/usr/bin/ffmpeg", "/usr/bin/ffprobe", True, False, "WhisperX no instalado", "/usr/bin/yt-dlp")


def _g(**kw):
    return validar_video("AD09", guion_video("claymation", **kw), CFG)


def _ejecutar(texto):
    def correr(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 0, f"## Transcripción\n\n{texto}\n", "")
    return correr


def test_similitud_identica_1():
    assert whisper.similitud("Здравей, свят!", "здравей свят", "bg") == Decimal("1.000")


def test_precio_en_cifras_baja_similitud():
    s = whisper.similitud("Само тринадесет евро и деветдесет цента", "Само 13,90 евро", "bg")
    assert s < Decimal("0.925")


def test_video_sin_voz_es_fallo(tmp_path):
    g = _g()
    from dataclasses import replace
    mudo = replace(g, partes=tuple(replace(p, texto_voz="") for p in g.partes))
    r = whisper.revisar_voz(mudo, tmp_path / "AD09.mp4", "bg", CFG, tmp_path / "w", entorno=LISTO)
    assert r.estado == "corregir"


def test_sin_whisperx_no_medido_con_pasos(tmp_path):
    r = whisper.revisar_voz(_g(), tmp_path / "AD09.mp4", "bg", CFG, tmp_path / "w", entorno=SIN)
    assert r.estado == "no_medido" and "Ejecuta tú" in r.motivo


def test_ok_sobre_umbral(tmp_path, monkeypatch):
    g = _g()
    monkeypatch.setattr(whisper.watch, "leer_informe",
                        lambda texto, trabajo: whisper.watch.InformeWatch(None, (), g.texto_voz, "whisperx", None))
    r = whisper.revisar_voz(g, tmp_path / "AD09.mp4", "bg", CFG, tmp_path / "w", entorno=LISTO,
                            ejecutar=_ejecutar(g.texto_voz))
    assert r.estado == "ok" and r.similitud == Decimal("1.000")


def test_transcripcion_en_qa(tmp_path):
    (tmp_path / "AD09.mp4").write_bytes(b"x")
    r = whisper.ResultadoWhisper("AD09", "corregir", Decimal("0.800"), "Само 13,90 евро", None)
    whisper.anotar(tmp_path, r, CFG, "apimart", AHORA)
    texto = (tmp_path / "QA.md").read_text(encoding="utf-8")
    assert "> Transcripción: Само 13,90 евро" in texto and "- similitud: 0.800" in texto
    s = registro.ultima(registro.leer(tmp_path), "whisper", ad="AD09")
    assert s.datos["sha256"] == registro.sha_archivo(tmp_path / "AD09.mp4")


def test_corregir_dos_veces_pasa_a_elevenlabs(tmp_path):
    (tmp_path / "AD09.mp4").write_bytes(b"x")
    mal = whisper.ResultadoWhisper("AD09", "corregir", Decimal("0.8"), "x", None)
    whisper.anotar(tmp_path, mal, CFG, "apimart", AHORA)
    assert whisper.siguiente_paso(tmp_path, "AD09") == "revozar"
    whisper.anotar(tmp_path, mal, CFG, "apimart", AHORA)
    assert whisper.siguiente_paso(tmp_path, "AD09") == "elevenlabs"
    whisper.anotar(tmp_path, mal, CFG, "elevenlabs", AHORA)
    assert whisper.siguiente_paso(tmp_path, "AD09") == "parar"
    whisper.anotar(tmp_path, whisper.ResultadoWhisper("AD09", "ok", Decimal("0.95"), "x", None), CFG, "elevenlabs",
                   AHORA)
    assert whisper.siguiente_paso(tmp_path, "AD09") == "nada"
