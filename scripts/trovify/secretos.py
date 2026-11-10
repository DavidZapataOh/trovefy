"""Lectura de secretos desde ~/.config/trovify/*.env (modo 0600). Nunca registra valores."""

import stat
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


def leer_env(ruta: Path) -> dict[str, str]:
    """Lee líneas CLAVE=VALOR (ignora vacías y comentarios, quita comillas envolventes).

    Lanza FileNotFoundError si falta y PermisosInseguros si el modo no es 0600
    (se comprueba antes de leer el contenido).
    """
    ruta = Path(ruta)
    modo = stat.S_IMODE(ruta.stat().st_mode)
    if modo != 0o600:
        raise PermisosInseguros(ruta, modo)
    valores: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[clave.strip().removeprefix("export ").strip()] = valor
    return valores
