"""Paso 00: comprobación del entorno (Python, uv, Node, git, ffmpeg, poppler, WeasyPrint, Playwright, systemd, Obsidian)."""

import glob
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import base, verificador
from trovify.vault.rutas import vault_root

_OBSIDIAN = "/mnt/c/Users/*/AppData/Local/Programs/Obsidian/Obsidian.exe"
_NODE_MINIMO = 20


@dataclass
class Elemento:
    nombre: str
    ok: bool
    detalle: str
    arreglo: str | None


def _primera_linea(salida: str) -> str:
    return salida.splitlines()[0] if salida else ""


def _herramienta(correr: Callable, nombre: str, cmd: list[str], arreglo: str, timeout: float = 10) -> Elemento:
    codigo, salida = correr(cmd, timeout=timeout)
    if codigo == 0:
        return Elemento(nombre, True, _primera_linea(salida) or "disponible", None)
    detalle = salida if codigo is None else f"falló (código {codigo}): {_primera_linea(salida)}"
    return Elemento(nombre, False, detalle, arreglo)


def comprobar_entorno(
    correr: Callable = base.correr, home: Path | None = None, obsidian: list[Path] | None = None
) -> list[Elemento]:
    home = Path.home() if home is None else Path(home)
    elementos = [
        _herramienta(correr, "python", ["uv", "python", "find", "3.12"], "! uv python install 3.12"),
        _herramienta(
            correr, "uv", ["uv", "--version"],
            "instala uv con una versión fijada (por ejemplo `! pipx install uv==<versión>`); no uses `curl | bash`",
        ),
    ]
    codigo, salida = correr(["node", "--version"], timeout=10)
    m = re.match(r"v?(\d+)", salida) if codigo == 0 else None
    if m and int(m.group(1)) >= _NODE_MINIMO:
        elementos.append(Elemento("node", True, salida, None))
    else:
        detalle = salida if codigo is None else f"versión {salida or 'desconocida'}: se necesita Node {_NODE_MINIMO} o superior"
        elementos.append(Elemento("node", False, detalle, f"instala Node LTS ({_NODE_MINIMO} o superior) con una versión fijada y vuelve a verificar"))
    elementos += [
        _herramienta(correr, "git", ["git", "--version"], "! sudo apt install -y git"),
        # el ffmpeg de snap se cuelga en WSL: por eso el límite de 10 s y el arreglo con apt
        _herramienta(correr, "ffmpeg", ["ffmpeg", "-version"], "! sudo apt install -y ffmpeg"),
        _herramienta(correr, "poppler", ["pdfinfo", "-v"], "! sudo apt install -y poppler-utils"),
    ]
    codigo, salida = correr(["ldconfig", "-p"], timeout=10)
    if codigo == 0 and "libpango-1.0" in salida:
        elementos.append(Elemento("weasyprint", True, "libpango-1.0 presente", None))
    else:
        detalle = salida if codigo is None else "falta libpango-1.0"
        elementos.append(Elemento("weasyprint", False, detalle, "! sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0"))
    navegadores = sorted(glob.glob(str(home / ".cache" / "ms-playwright" / "chromium-*")))
    if navegadores:
        elementos.append(Elemento("playwright", True, Path(navegadores[0]).name, None))
    else:
        elementos.append(Elemento(
            "playwright", False, "no hay navegador de Playwright en ~/.cache/ms-playwright",
            "Playwright para Python se instala en el plan 05; después: ! uv run playwright install chromium",
        ))
    codigo, salida = correr(["systemctl", "is-system-running"], timeout=10)
    estado = _primera_linea(salida)
    if estado in ("running", "degraded"):
        elementos.append(Elemento("systemd", True, estado, None))
    else:
        detalle = salida if codigo is None else (estado or "sin respuesta")
        elementos.append(Elemento(
            "systemd", False, detalle,
            "edita /etc/wsl.conf (! sudo nano /etc/wsl.conf) y añade `[boot]` y `systemd=true`; "
            "luego ejecuta `wsl --shutdown` desde PowerShell de Windows y reabre la terminal",
        ))
    candidatos = [Path(p) for p in sorted(glob.glob(_OBSIDIAN))] if obsidian is None else [Path(p) for p in obsidian]
    encontrado = next((p for p in candidatos if p.exists()), None)
    if encontrado:
        elementos.append(Elemento("obsidian", True, str(encontrado), None))
    else:
        elementos.append(Elemento(
            "obsidian", False, "no se encontró Obsidian.exe en Windows",
            "instala Obsidian en Windows desde https://obsidian.md (lo haces tú) y vuelve a verificar",
        ))
    return elementos


@verificador("00")
def verificar_entorno(vault: Path | None = None) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    elementos = comprobar_entorno()
    ruta = base.guardar_evidencia(vault, "00", "entorno", {"elementos": [asdict(e) for e in elementos]})
    fallan = [e for e in elementos if not e.ok]
    lineas = [f"{'✓' if e.ok else '✗'} {e.nombre} — {e.detalle}" for e in elementos]
    if not fallan:
        return ResultadoVerificacion(True, [ruta], "entorno completo", [], {}, lineas)
    motivo = "faltan: " + ", ".join(e.nombre for e in fallan)
    return ResultadoVerificacion(False, [ruta], motivo, [f"{e.nombre}: {e.arreglo}" for e in fallan if e.arreglo], {}, lineas)
