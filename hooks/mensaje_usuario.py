"""Hook UserPromptSubmit: anota la huella de cada mensaje del usuario (plan 19, Tarea 11).

`trovefy checkout aprobar --cita "…"` solo acepta como aprobación de un plan del MCP de Impultienda un mensaje que
el usuario escribió de verdad (ver `trovefy.checkout.mensajes`). Se guarda solo la huella y la hora, nunca el texto.

Informativo: nunca bloquea ni imprime nada (sale siempre con 0) y ante cualquier fallo calla.
Solo biblioteca estándar.
"""
from __future__ import annotations

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    try:
        entrada = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        prompt = entrada.get("prompt") if isinstance(entrada, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            return
        scripts = str(RAIZ / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from trovefy.checkout.mensajes import registrar_mensaje

        registrar_mensaje(prompt)
    except Exception:  # noqa: BLE001 - un hook informativo nunca molesta al usuario
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
