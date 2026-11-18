"""Hook PreToolUse: Claude nunca cambia límites ni estado del ejecutor (§5.1, §5.6; M7 de la revisión T6–10).

``limites.yaml`` y el estado del ejecutor solo los cambia el usuario, en una terminal aparte: Claude le da los
comandos (``trovefy tracking ejecutor``) pero no los ejecuta. Se deniega en Bash:

- cualquier cosa que corra como ``trovefy-exec`` (``sudo -u trovefy-exec``, ``sudo --user=…``, ``su``,
  ``runuser``, ``doas``, ``pkexec``, ``machinectl``);
- ``trovefy-ejecutor`` (o ``python -m trovefy_ejecutor[.cli]``) con un subcomando que cambia límites o estado:
  ``permitir``, ``reanudar``, ``emparejar``, ``servir``, ``auditoria``, ``comprobar-meta``, ``comprobar-dataset``.

Pasan las lecturas (``estado``, ``limites``), ``simular`` (carpeta temporal) y ``stop`` (solo frena). Solo
biblioteca estándar; falla cerrado.
"""
from __future__ import annotations

import re

from _comun import ejecutar_guardia, herramienta

MOTIVO = ("el ejecutor (límites y estado) solo lo cambias tú, en una terminal aparte: Claude te da el comando, "
          "no lo ejecuta")
_CAMBIAN = ("permitir", "reanudar", "emparejar", "servir", "auditoria", "comprobar-meta", "comprobar-dataset")
_COMO_EJECUTOR = re.compile(
    r"\b(?:sudo|su|runuser|doas|pkexec|machinectl|setpriv)\b[^;&|\n]*?(?<![\w-])trovefy-exec(?![\w-])")
_INVOCACION = re.compile(
    r"(?:(?<![\w.-])trovefy-ejecutor|-m\s+trovefy_ejecutor(?:\.cli)?)(?![\w-])"
    r"(?:\s+--?[\w-]+(?:=\S+)?)*\s+(?P<orden>[\w-]+)")


def _limpio(comando: str) -> str:
    return re.sub(r"[\"'\\]", "", comando)


def clasificar(tool_name: str, tool_input: dict) -> tuple[str, str]:
    if tool_name != "Bash":
        return "allow", ""
    comando = tool_input.get("command")
    if not isinstance(comando, str):
        return "deny", MOTIVO
    limpio = _limpio(comando)
    if _COMO_EJECUTOR.search(limpio):
        return "deny", MOTIVO
    for m in _INVOCACION.finditer(limpio):
        if m.group("orden") in _CAMBIAN:
            return "deny", MOTIVO
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(lambda e: clasificar(*herramienta(e)))
