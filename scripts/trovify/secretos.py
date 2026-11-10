"""Lectura de secretos desde ~/.config/trovify/*.env (modo 0600) y detección de secretos en texto.

Nunca registra valores.
"""

import errno
import importlib.util
import os
import stat
import sys
from pathlib import Path

RUTA_CLAUDE_ENV = Path.home() / ".config/trovify/claude.env"


class PermisosInseguros(Exception):
    """El archivo de secretos no tiene modo 0600."""

    def __init__(self, ruta: Path, modo: int) -> None:
        super().__init__(ruta, modo)
        self.ruta = Path(ruta)
        self.modo = modo

    def __str__(self) -> str:
        return f"{self.ruta} tiene permisos {self.modo:o}; deben ser 600"


class EnvNoSeguro(Exception):
    """El archivo de secretos es un enlace simbólico, no es regular o no es del usuario."""


def leer_env(ruta: Path) -> dict[str, str]:
    """Lee líneas CLAVE=VALOR (ignora vacías y comentarios, quita comillas envolventes).

    Lanza FileNotFoundError si falta y PermisosInseguros si el modo no es 0600
    (se comprueba antes de leer el contenido).
    """
    ruta = Path(ruta)
    try:
        fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # NONBLOCK: una FIFO no debe colgar
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise EnvNoSeguro("es un enlace simbólico") from None
        raise
    with os.fdopen(fd, "r", encoding="utf-8") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise EnvNoSeguro("no es un archivo regular")
        if info.st_uid != os.getuid():
            raise EnvNoSeguro("no pertenece a tu usuario")
        modo = stat.S_IMODE(info.st_mode)
        if modo != 0o600:
            raise PermisosInseguros(ruta, modo)
        texto = f.read()
    valores: dict[str, str] = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[clave.strip().removeprefix("export ").strip()] = valor
    return valores


class RevisionSecretosNoDisponible(FileNotFoundError):
    """No se encuentra hooks/secretos.py: no se puede revisar si un texto lleva secretos."""

    def __str__(self) -> str:
        return (
            "no encuentro hooks/secretos.py (la instalación de Trovify está incompleta); "
            "no se puede revisar si hay secretos, así que no se guarda nada"
        )


def _candidatos_hooks() -> list[Path]:
    return [padre / "hooks" for padre in Path(__file__).resolve().parents]


def buscar_secreto(texto: str) -> str | None:
    """Nombre del patrón de secreto que aparece en `texto` (o None).

    Usa los patrones de hooks/secretos.py (una sola fuente), sin la mención `access_token=`.
    Lanza `RevisionSecretosNoDisponible` si no encuentra los hooks.
    """
    hooks = next((h for h in _candidatos_hooks() if (h / "secretos.py").is_file() and (h / "_comun.py").is_file()), None)
    if hooks is None:
        raise RevisionSecretosNoDisponible()
    sys.path.insert(0, str(hooks))
    try:
        spec = importlib.util.spec_from_file_location("_trovify_hook_secretos", hooks / "secretos.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(hooks))
    return mod.buscar_secreto(texto, mod.PATRONES_TOKEN)
