"""Hook PreToolUse: APIMart solo se llama con ``trovefy producto`` (tiene tope de gasto, contrato 7).

Deniega un ``Bash`` con algún segmento que mencione ``apimart.ai`` o ``APIMART_API_KEY`` y no empiece
por ``trovefy `` ni ``uv run trovefy ``, también dentro de ``$(…)`` o comillas invertidas, y un
``WebFetch`` a ``apimart.ai`` o a un subdominio. Lo demás pasa. Solo biblioteca estándar; falla cerrado.
Idea tomada del ``guard.mjs`` de LordVayron/video-factory (MIT, commit 8afd1b2e).
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from _comun import _SEGMENTOS, ejecutar_guardia, herramienta

MOTIVO = "APIMart solo se llama con `trovefy producto`: tiene tope de gasto"
_MENCION = re.compile(r"apimart\.ai|APIMART_API_KEY", re.IGNORECASE)
_PERMITIDO = re.compile(r"(?:uv\s+run\s+)?trovefy\s")
_SUBCOMANDO = re.compile(r"\$\(|`")


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _bash_denegado(comando: str) -> bool:
    for segmento in _SEGMENTOS.split(comando):
        if not _MENCION.search(segmento):
            continue
        limpio = segmento.strip()
        if not _PERMITIDO.match(limpio) or _SUBCOMANDO.search(limpio):
            return True
    return False


def decidir(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    nombre = nombre.lower()
    if nombre == "bash":
        comando = datos.get("command", "")
        if not isinstance(comando, str):
            return "deny", MOTIVO
        if _bash_denegado(comando) or _bash_denegado(unquote(comando)):
            return "deny", MOTIVO
    elif nombre == "webfetch":
        url = str(datos.get("url", ""))
        host = _host(url) or _host(unquote(url))
        if host == "apimart.ai" or host.endswith(".apimart.ai"):
            return "deny", MOTIVO
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(decidir)
