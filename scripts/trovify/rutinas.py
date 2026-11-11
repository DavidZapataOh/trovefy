"""Rutinas programadas con timers de systemd de usuario (§3.6 [D-06]).

Cada rutina lanza ``claude -p "/trovify:<skill> --rutina"`` con su lista ``--allowedTools``; nunca
con ``--dangerously-skip-permissions``. Cada ejecución deja ``rutinas/log/AAAA-MM-DD/<rutina>.md`` y,
si terminó sin parada, un archivo ``ok`` (lo mira /vigia).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from trovify.vault.escritura import ZONA_NEGOCIO, escribir_atomico

PLANTILLAS = Path(__file__).resolve().parents[2] / "templates" / "systemd"
SERVICIO_CAZA = "trovify-caza.service"
TIMER_CAZA = "trovify-caza.timer"


def _rellenar(texto: str, **valores: str) -> str:
    for clave, valor in valores.items():
        texto = texto.replace("{" + clave + "}", valor)
    return texto


def unidad_caza(vault: Path, claude: str, path: str | None = None) -> tuple[str, str]:
    """Texto del ``.service`` y del ``.timer`` de la caza diaria (lunes a sábado, 06:30 COT).

    ``path`` es el PATH del servicio; por defecto la carpeta de ``claude``, ``~/.local/bin`` (``%h``
    de systemd: ahí instala ``uv tool`` el comando ``trovify``) y las rutas del sistema."""
    if path is None:
        path = ":".join(dict.fromkeys([os.path.dirname(claude) or "/usr/bin", "%h/.local/bin",
                                       "/usr/local/bin", "/usr/bin", "/bin"]))
    for valor in (str(vault), claude, path):
        if any(ch in valor for ch in '"\\\n'):
            raise ValueError(f"ruta no admitida en una unidad de systemd: {valor!r}")
    # «%» es un especificador de systemd: en rutas propias se escribe «%%» (el PATH usa %h a propósito).
    servicio = _rellenar((PLANTILLAS / SERVICIO_CAZA).read_text(encoding="utf-8"),
                         vault=str(vault).replace("%", "%%"), claude=claude.replace("%", "%%"), path=path)
    timer = (PLANTILLAS / TIMER_CAZA).read_text(encoding="utf-8")
    if "dangerously" in servicio:  # nunca: §3.6, [D-30]
        raise ValueError("la unidad de la rutina no puede saltarse los permisos")
    return servicio, timer


def _systemctl(comando: list[str]) -> None:
    subprocess.run(comando, check=True)


def directorio_unidades() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def instalar_caza(vault: Path, claude: str, ejecutar: Callable[[list[str]], None] | None = None) -> list[Path]:
    """Escribe las unidades en ``~/.config/systemd/user/`` y activa el timer."""
    ejecutar = ejecutar or _systemctl
    servicio, timer = unidad_caza(Path(vault), claude)
    carpeta = directorio_unidades()
    rutas = [carpeta / SERVICIO_CAZA, carpeta / TIMER_CAZA]
    for ruta, texto in zip(rutas, (servicio, timer), strict=True):
        escribir_atomico(ruta, texto)
    ejecutar(["systemctl", "--user", "daemon-reload"])
    ejecutar(["systemctl", "--user", "enable", "--now", TIMER_CAZA])
    return rutas


def buscar_claude() -> str | None:
    return shutil.which("claude")


def registrar_ejecucion(vault: Path, rutina: str, dia: date, texto: str, ok: bool,
                        ahora: datetime | None = None) -> Path:
    """Añade el resumen a ``rutinas/log/<dia>/<rutina>.md``; deja ``ok`` solo si no hubo parada."""
    carpeta = Path(vault) / "rutinas" / "log" / dia.isoformat()
    ruta = carpeta / f"{rutina}.md"
    previo = ruta.read_text(encoding="utf-8") if ruta.exists() else f"# Rutina {rutina} · {dia.isoformat()}\n"
    hora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    estado = "ok" if ok else "parada"
    escribir_atomico(ruta, f"{previo.rstrip()}\n\n## {hora:%H:%M} COT · {estado}\n\n{texto.rstrip()}\n")
    marca = carpeta / "ok"
    if ok:
        escribir_atomico(marca, f"{hora.isoformat()}\n")
    elif marca.exists():
        marca.unlink()
    return ruta
