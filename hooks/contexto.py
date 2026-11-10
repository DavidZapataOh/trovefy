"""Hook SessionStart: resumen corto del vault como contexto de la sesión.

Informativo: nunca bloquea ni rompe la sesión. Ante cualquier fallo sale con
código 0 sin imprimir nada. Solo biblioteca estándar.

Formato (docs de Claude Code, SessionStart): se imprime por stdout
``{"hookSpecificOutput": {"hookEventName": "SessionStart",
"additionalContext": "..."}}`` y se sale con código 0.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

LINEAS_INDICE = 40
MAX_INDICE = 1800
MAX_TOTAL = 4000
MAX_ITEMS = 15
MAX_ITEM_CHARS = 120
MAX_LINEAS_FM = 200
MAX_ARCHIVOS = 200
MAX_BYTES_INDICE = 8192
MAX_ENTRADAS_SESIONES = 1000
PRESUPUESTO_PRODUCTOS = 1300
PRESUPUESTO_TRASPASO = 200
PRESUPUESTO_PROPUESTAS = 800
ESTADOS_VIVOS = {"TEST", "CANDIDATO", "PRE_ESCALA", "ESCALA"}


def _estados(ruta: pathlib.Path) -> list[str]:
    """Valores de ``estado:`` (de cualquier nivel) entre los dos primeros ``---``.

    Lee de forma incremental: se detiene en el ``---`` de cierre o tras
    ``MAX_LINEAS_FM`` líneas.
    """
    valores = []
    with ruta.open(encoding="utf-8", errors="replace") as f:
        primera = f.readline(1024)
        if primera.strip() != "---":
            return []
        for _ in range(MAX_LINEAS_FM):
            linea = f.readline(4096)
            if not linea or linea.strip() == "---":
                break
            clave, sep, valor = linea.strip().partition(":")
            if sep and clave == "estado":
                valores.append(valor.strip().strip("\"'"))
    return valores


def _archivos(patron_dir: pathlib.Path, patron: str) -> list[pathlib.Path]:
    return sorted(patron_dir.glob(patron))[:MAX_ARCHIVOS]


def _lista(titulo: str, items: list[str]) -> str | None:
    if not items:
        return None
    items = sorted(items)
    extra = len(items) - MAX_ITEMS
    cuerpo = [f"- {i[:MAX_ITEM_CHARS]}" for i in items[:MAX_ITEMS]]
    if extra > 0:
        cuerpo.append(f"- … y {extra} más")
    return f"## {titulo}\n" + "\n".join(cuerpo)


def _seguro(f, *args):
    try:
        return f(*args)
    except Exception:  # noqa: BLE001 - una sección rota no tumba las demás
        return None


def _indice(vault: pathlib.Path) -> str | None:
    with (vault / "index.md").open(encoding="utf-8", errors="replace") as f:
        texto = f.read(MAX_BYTES_INDICE)
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
    pend = [p.name for p in _archivos(vault / "propuestas", "*.md") if "pendiente" in _estados(p)]
    return _lista("Propuestas pendientes", pend)


def _productos(vault: pathlib.Path) -> str | None:
    vivos = [
        p.parent.name
        for p in _archivos(vault / "productos", "*/PRODUCTO.md")
        if ESTADOS_VIVOS & set(_estados(p))
    ]
    return _lista("Productos en marcha", vivos)


def _traspaso(vault: pathlib.Path) -> str | None:
    entradas = itertools.islice((vault / "sesiones").iterdir(), MAX_ENTRADAS_SESIONES)
    archivos = sorted(p.name for p in entradas if p.name.endswith(".md"))
    return f"## Último traspaso\nsesiones/{archivos[-1][:MAX_ITEM_CHARS]}" if archivos else None


def _recortar(seccion: str | None, limite: int) -> str | None:
    """Corta la sección en un salto de línea para que no pase de ``limite``."""
    if not seccion or limite <= 0:
        return None
    if len(seccion) <= limite:
        return seccion
    corte = seccion[: limite - 1]
    if "\n" in corte:
        corte = corte[: corte.rindex("\n")]
    return corte + "…"


def armar_contexto(vault: pathlib.Path) -> str | None:
    """Orden de salida: índice, STOP, propuestas, productos, traspaso.

    STOP, productos y traspaso se construyen primero y reservan su espacio;
    propuestas e índice se reparten lo que queda, así el total es <= MAX_TOTAL.
    """
    if not vault.is_dir():
        return None
    stop = _recortar(_seguro(_stop, vault), 200)
    prod = _recortar(_seguro(_productos, vault), PRESUPUESTO_PRODUCTOS)
    tras = _recortar(_seguro(_traspaso, vault), PRESUPUESTO_TRASPASO)
    reservado = [x for x in (stop, prod, tras) if x]
    libre = MAX_TOTAL - sum(len(x) for x in reservado) - 2 * (len(reservado) + 2)
    prop = _recortar(_seguro(_propuestas, vault), min(PRESUPUESTO_PROPUESTAS, libre // 3))
    libre -= len(prop) if prop else 0
    ind = _recortar(_seguro(_indice, vault), min(MAX_INDICE, libre))
    partes = [ind, stop, prop, prod, tras]
    texto = "\n\n".join(x for x in partes if x)
    return texto[:MAX_TOTAL] or None


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
