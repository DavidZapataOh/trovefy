import subprocess

import pytest
from trovefy.referencia.watch import comprobar_entorno, ejecutar_watch


@pytest.mark.vivo
def test_watch_vivo(tmp_path):
    video = tmp_path / "prueba.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=3",
            "-shortest",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    e = comprobar_entorno()
    r = ejecutar_watch(video, tmp_path / "trabajo", None, e)
    assert len(r.fotogramas) >= 1
    if e.whisperx:
        assert r.fuente_transcripcion is not None or "no instalado" not in (
            r.motivo or ""
        )
