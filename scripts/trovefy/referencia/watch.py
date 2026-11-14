"""Motor /watch local (ffmpeg + WhisperX) sobre vendor/claude-video.

Siempre en local: ningún servicio de vídeo ni clave de API. Claude no usa sudo:
si falta algo se devuelven pasos para que el usuario los ejecute.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import trovefy

RAIZ_VENDOR = (
    Path(trovefy.__file__).resolve().parents[2]
    / "vendor/claude-video/skills/watch/scripts"
)
_RAIZ_CV = Path(trovefy.__file__).resolve().parents[2] / "vendor/claude-video"
TIMEOUT_S = 1800
_NO_VENDOR = "no medido: falta vendor/claude-video"


@dataclass(frozen=True)
class Entorno:
    ffmpeg: str | None
    ffprobe: str | None
    vendor_ok: bool
    whisperx: bool
    whisperx_detalle: str


@dataclass(frozen=True)
class InformeWatch:
    duracion_s: Decimal | None
    fotogramas: tuple[Path, ...]
    transcripcion: str | None
    fuente_transcripcion: str | None
    motivo: str | None


def _vendor_ok() -> bool:
    try:
        lineas = (_RAIZ_CV / "MANIFEST.sha256").read_text().splitlines()
        for linea in lineas:
            suma, rel = linea.split(maxsplit=1)
            if hashlib.sha256((_RAIZ_CV / rel).read_bytes()).hexdigest() != suma:
                return False
        return bool(lineas) and (RAIZ_VENDOR / "watch.py").is_file()
    except (OSError, ValueError):
        return False


def _env_base() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C.UTF-8",
    }


def _ejecutar_grupo(
    cmd, *, timeout, env=None, capture_output=True, text=True, check=False
):
    """Como subprocess.run, pero en su propio grupo: al vencer el plazo mata todo el grupo."""
    p = subprocess.Popen(
        cmd, env=env, text=text, start_new_session=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
    )  # fmt: skip
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:
        for sen, gracia in ((signal.SIGTERM, 3), (signal.SIGKILL, None)):
            try:
                os.killpg(p.pid, sen)
            except (ProcessLookupError, PermissionError):
                break
            try:
                p.wait(timeout=gracia) if gracia else p.wait()
                break
            except subprocess.TimeoutExpired:
                continue
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _limpiar(trabajo: Path) -> None:
    """Borra lo parcial dentro de `trabajo` (nunca fuera, nunca siguiendo enlaces)."""
    try:
        hijos = list(trabajo.iterdir())
    except OSError:
        return
    for h in hijos:
        try:
            if h.is_symlink() or h.is_file():
                h.unlink()
            else:
                shutil.rmtree(h, ignore_errors=True)
        except OSError:
            pass


def comprobar_entorno(which=shutil.which, ejecutar=subprocess.run) -> Entorno:
    vendor = _vendor_ok()
    whisperx, detalle = False, ""
    if vendor:
        try:
            p = ejecutar(
                [sys.executable, "-s", "-E", str(RAIZ_VENDOR / "setup.py"), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=_env_base(),
            )
            if p.returncode != 0:
                detalle = f"setup.py terminó con código {p.returncode}"
            else:
                whisperx = bool(json.loads(p.stdout).get("whisperx_ready"))
                detalle = "listo" if whisperx else "WhisperX no instalado"
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as e:
            detalle = f"no se pudo leer el estado de WhisperX ({type(e).__name__})"
    else:
        detalle = "vendor/claude-video no cuadra con su MANIFEST"
    return Entorno(which("ffmpeg"), which("ffprobe"), vendor, whisperx, detalle)


def pasos_instalacion(e: Entorno) -> list[str]:
    pasos: list[str] = []
    if not e.vendor_ok:
        pasos.append("vendor/claude-video no cuadra con su MANIFEST: no se usa; avisa.")
    if not e.ffmpeg or not e.ffprobe:
        pasos.append(
            "Ejecuta tú: `sudo apt install ffmpeg` (pide tu contraseña; Claude no usa sudo)."
        )
    if e.vendor_ok and not e.whisperx:
        pasos += [
            (
                "WhisperX local: unos 1 GB de paquetes más el modelo small (464 MB), en "
                "`~/.cache/watch/whisperx-venv`; pide 3 GB libres y 8 GB de RAM. Sin sudo."
            ),
            f"Ejecuta tú: `{shlex.quote(sys.executable)} -s -E {shlex.quote(str(RAIZ_VENDOR / 'setup.py'))} --install-whisperx`",
            "Después: `trovefy ver-anuncios comprobar`.",
        ]
    return pasos


def comando_watch(
    video: Path, trabajo: Path, whisperx: bool, max_fotogramas: int = 30
) -> list[str]:
    return [
        sys.executable, "-s", "-E", str(RAIZ_VENDOR / "watch.py"), str(Path(video).resolve()),
        "--engine", "local", "--detail", "efficient",
        "--max-frames", str(max_fotogramas), "--out-dir", str(trabajo),
        *(["--whisper", "whisperx"] if whisperx else ["--no-whisper"]),
    ]  # fmt: skip


def entorno_hijo(idioma: str | None, whisperx: bool) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C.UTF-8",
        "WATCH_ENGINE": "local",
        "WATCH_WHISPER_BACKEND": "whisperx" if whisperx else "none",
    }
    if idioma and re.fullmatch(r"[a-z]{2}", idioma):
        env["WATCH_WHISPERX_LANGUAGE"] = idioma
    return env


_SECCION_TRANSCRIPT = r"^## Transcript\n(.*?)(?=^## |^---$|\Z)"
_MARCA_TIEMPO = re.compile(r"^\[\d+:\d{2}(?::\d{2})?\]\s*")


def texto_transcripcion(texto: str) -> str | None:
    """Solo el texto hablado del bloque ``## Transcript`` de watch.md, sin marcas ``[MM:SS]``."""
    sec = re.search(_SECCION_TRANSCRIPT, texto, re.DOTALL | re.MULTILINE)
    b = re.search(r"```\n(.*?)\n```", sec.group(1), re.DOTALL) if sec else None
    if not b:
        return None
    lineas = [_MARCA_TIEMPO.sub("", ln).strip() for ln in b.group(1).splitlines()]
    unido = " ".join(ln for ln in lineas if ln)
    return unido or None


def leer_informe(texto: str, trabajo: Path) -> InformeWatch:
    m = re.search(r"- \*\*Duration:\*\* \S+ \(([\d.]+)s\)", texto)
    duracion = Decimal(m.group(1)) if m else None

    raiz = trabajo.resolve()
    fotos: list[Path] = []
    sec = re.search(r"^## Frames\n(.*?)(?=^## |\Z)", texto, re.DOTALL | re.MULTILINE)
    for ruta in re.findall(
        r"^- `([^`]+)` \(t=", sec.group(1) if sec else "", re.MULTILINE
    ):
        p = Path(ruta).resolve()
        if not p.is_relative_to(raiz):
            raise ValueError("fotograma fuera del directorio de trabajo")
        fotos.append(p)

    transcripcion = fuente = None
    sec = re.search(_SECCION_TRANSCRIPT, texto, re.DOTALL | re.MULTILINE)
    if sec:
        b = re.search(r"```\n(.*?)\n```", sec.group(1), re.DOTALL)
        if b and b.group(1).strip():
            transcripcion = b.group(1)
            f = re.search(r"_Source: ([^.\n_]+)", sec.group(1))
            fuente = f.group(1).strip() if f else None
    motivo = None
    if transcripcion is None:
        est = re.search(r"- \*\*Transcript:\*\* (.+)", texto)
        motivo = f"no medido: {est.group(1).strip() if est else 'sin transcripción'}"
    return InformeWatch(duracion, tuple(fotos), transcripcion, fuente, motivo)


def _vacio(motivo: str) -> InformeWatch:
    return InformeWatch(None, (), None, None, motivo)


def ejecutar_watch(
    video: Path,
    trabajo: Path,
    idioma: str | None,
    entorno: Entorno,
    ejecutar=_ejecutar_grupo,
) -> InformeWatch:
    if not entorno.vendor_ok:
        return _vacio(_NO_VENDOR)
    if not entorno.ffmpeg or not entorno.ffprobe:
        return _vacio("no medido: falta ffmpeg (trovefy ver-anuncios comprobar)")
    trabajo.mkdir(parents=True, exist_ok=True)
    fallo = "no medido: /watch no dio evidencia"
    try:
        p = ejecutar(
            comando_watch(video, trabajo, entorno.whisperx),
            capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
            env=entorno_hijo(idioma, entorno.whisperx),
        )  # fmt: skip
        if p.returncode != 0:
            _limpiar(trabajo)
            return _vacio(fallo)
        (trabajo / "watch.md").write_text(p.stdout, encoding="utf-8")
        r = leer_informe(p.stdout, trabajo)
    except (OSError, subprocess.SubprocessError, ValueError):
        _limpiar(trabajo)
        return _vacio(fallo)
    if not entorno.whisperx and r.transcripcion is None:
        r = InformeWatch(
            r.duracion_s, r.fotogramas, None, None,
            "no medido: whisper local no instalado (trovefy ver-anuncios comprobar)",
        )  # fmt: skip
    return r
