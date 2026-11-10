"""Hook SessionStart: resumen corto del vault como contexto de la sesión.

Informativo: nunca bloquea ni rompe la sesión. Ante cualquier fallo sale con
código 0 sin imprimir nada. Solo biblioteca estándar.

Formato (docs de Claude Code, SessionStart): se imprime por stdout
``{"hookSpecificOutput": {"hookEventName": "SessionStart",
"additionalContext": "..."}}`` y se sale con código 0.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

LINEAS_INDICE = 40
MAX_INDICE = 1800
MAX_TOTAL = 4000
MAX_ITEMS = 15
ESTADOS_VIVOS = {"TEST", "CANDIDATO", "PRE_ESCALA", "ESCALA"}


def _estados(ruta: pathlib.Path) -> list[str]:
    """Valores de ``estado:`` (de cualquier nivel) entre los dos primeros ``---``."""
    lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lineas or lineas[0].strip() != "---":
        return []
    valores = []
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        clave, sep, valor = linea.strip().partition(":")
        if sep and clave == "estado":
            valores.append(valor.strip().strip("\"'"))
    return valores


def _lista(titulo: str, items: list[str]) -> str | None:
    if not items:
        return None
    items = sorted(items)
    extra = len(items) - MAX_ITEMS
    cuerpo = [f"- {i}" for i in items[:MAX_ITEMS]]
    if extra > 0:
        cuerpo.append(f"- … y {extra} más")
    return f"## {titulo}\n" + "\n".join(cuerpo)


def _seguro(f, *args):
    try:
        return f(*args)
    except Exception:  # noqa: BLE001 - una sección rota no tumba las demás
        return None


def _indice(vault: pathlib.Path) -> str | None:
    texto = (vault / "index.md").read_text(encoding="utf-8", errors="replace")
    cab = "\n".join(texto.splitlines()[:LINEAS_INDICE])
    if len(cab) > MAX_INDICE:
        cab = cab[:MAX_INDICE] + "…"
    return "## Índice (cabecera)\n" + cab if cab.strip() else None


def _stop(vault: pathlib.Path) -> str | None:
    from _comun import stop_activo

    if stop_activo(vault):
        return "## STOP activo\nExiste .trovify/STOP: no se debe escribir ni ejecutar acciones hasta retirarlo."
    return None


def _propuestas(vault: pathlib.Path) -> str | None:
    pend = [p.name for p in (vault / "propuestas").glob("*.md") if "pendiente" in _estados(p)]
    return _lista("Propuestas pendientes", pend)


def _productos(vault: pathlib.Path) -> str | None:
    vivos = [
        p.parent.name
        for p in (vault / "productos").glob("*/PRODUCTO.md")
        if ESTADOS_VIVOS & set(_estados(p))
    ]
    return _lista("Productos en marcha", vivos)


def _traspaso(vault: pathlib.Path) -> str | None:
    archivos = sorted(p.name for p in (vault / "sesiones").glob("*.md"))
    return f"## Último traspaso\nsesiones/{archivos[-1]}" if archivos else None


def armar_contexto(vault: pathlib.Path) -> str | None:
    if not vault.is_dir():
        return None
    secciones = [
        _seguro(f, vault) for f in (_indice, _stop, _propuestas, _productos, _traspaso)
    ]
    texto = "\n\n".join(s for s in secciones if s)
    if len(texto) > MAX_TOTAL:
        texto = texto[: MAX_TOTAL - 1] + "…"
    return texto or None


def main() -> None:
    try:
        from _comun import vault_root

        contexto = armar_contexto(vault_root())
        if contexto:
            sys.stdout.write(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": contexto,
                        }
                    }
                )
            )
            sys.stdout.flush()
    except BaseException:  # noqa: BLE001, S110 - informativo: jamás rompe la sesión
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
