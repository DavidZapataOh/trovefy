"""Hook Stop: recuerda cerrar la sesión si hubo trabajo hoy y no hay traspaso.

Informativo: nunca bloquea (siempre sale con 0) y ante cualquier fallo calla.
Solo biblioteca estándar; lee solo la cola de log.md.

Formato (docs de Claude Code, Stop): con código 0, el campo común
``systemMessage`` del JSON de stdout se muestra al usuario sin detener a
Claude (a diferencia del código 2 o de ``decision: "block"``, que sí lo
harían seguir). Lo que sale por stderr con código 0 Claude no lo ve.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

COLA_LOG = 64 * 1024
MAX_ENTRADAS_SESIONES = 2000
ENFRIAMIENTO = 3600
MENSAJE = (
    "Hoy se trabajó en el cerebro y aún no hay traspaso de sesión. "
    "Si vas a parar, ejecuta /trovify:cerrar para no perder el contexto."
)


def _hoy() -> str:
    return datetime.datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")


def _hubo_trabajo(vault: pathlib.Path, hoy: str) -> bool:
    ruta = vault / "log.md"
    with ruta.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - COLA_LOG))
        cola = f.read(COLA_LOG).decode("utf-8", errors="replace")
    return re.search(rf"^- {re.escape(hoy)}\b", cola, re.MULTILINE) is not None


def _hay_traspaso(vault: pathlib.Path, hoy: str) -> bool:
    carpeta = vault / "sesiones"
    if not carpeta.is_dir():
        return False
    for i, p in enumerate(carpeta.iterdir()):
        if i >= MAX_ENTRADAS_SESIONES:
            break
        if p.name.startswith(hoy + "-") and p.name.endswith(".md"):
            return True
    return False


def recordatorio(vault: pathlib.Path) -> str | None:
    hoy = _hoy()
    if _hubo_trabajo(vault, hoy) and not _hay_traspaso(vault, hoy):
        return MENSAJE
    return None


def _en_vault(entrada: dict, vault: pathlib.Path) -> bool:
    cwd = entrada.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False
    try:
        pathlib.Path(cwd).expanduser().resolve().relative_to(vault.resolve())
    except (ValueError, OSError):
        return False
    return True


def _enfriado(vault: pathlib.Path) -> bool:
    """True si ya se avisó hace menos de una hora (mtime del marcador)."""
    try:
        return time.time() - (vault / ".trovify" / "cierre-aviso").stat().st_mtime < ENFRIAMIENTO
    except OSError:
        return False


def _marcar(vault: pathlib.Path) -> None:
    try:
        marca = vault / ".trovify" / "cierre-aviso"
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.touch()
    except OSError:
        pass


def main() -> None:
    try:
        from _comun import leer_entrada, vault_root

        vault = vault_root()
        if not _en_vault(leer_entrada(), vault) or _enfriado(vault):
            sys.exit(0)
        mensaje = recordatorio(vault)
        if mensaje:
            _marcar(vault)
            sys.stdout.write(json.dumps({"systemMessage": mensaje}))
            sys.stdout.flush()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001, S110 - informativo: jamás rompe la sesión
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
