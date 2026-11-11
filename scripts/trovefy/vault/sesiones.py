"""Traspasos de sesión: el contexto de una sesión no se pierde si se corta."""

import re
from datetime import datetime
from pathlib import Path

from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.frontmatter import escribir

_NOMBRE = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{4})(?:-(\d+))?\.md$")


def _seccion(titulo: str, items: list[str]) -> str:
    cuerpo = "\n".join(f"- {i}" for i in items) if items else "- nada"
    return f"## {titulo}\n\n{cuerpo}\n"


def escribir_traspaso(
    vault: Path,
    hecho: list[str],
    pendiente: list[str],
    decisiones: list[str],
    archivos: list[str],
    ahora: datetime | None = None,
) -> Path:
    """Escribe ``sesiones/AAAA-MM-DD-HHMM.md`` (hora COT) y devuelve su ruta."""
    ahora = (ahora or datetime.now(ZONA_NEGOCIO)).astimezone(ZONA_NEGOCIO)
    base = f"{ahora:%Y-%m-%d-%H%M}"
    ruta = Path(vault) / "sesiones" / f"{base}.md"
    n = 1
    while ruta.exists():  # dos cierres en el mismo minuto: nunca se pisa el primero
        n += 1
        ruta = ruta.with_name(f"{base}-{n}.md")
    meta = {
        "tipo": "traspaso",
        "fecha": f"{ahora:%Y-%m-%d}",
        "hora": f"{ahora:%H:%M} COT",
        "fuente": "sesión de trabajo con Claude",
    }
    cuerpo = "\n# Traspaso de sesión\n\n" + "\n".join(
        [
            _seccion("Hecho", hecho),
            _seccion("Pendiente", pendiente),
            _seccion("Decisiones del usuario", decisiones),
            _seccion("Archivos tocados", archivos),
        ]
    )
    escribir(ruta, meta, cuerpo)
    return ruta


def ultimo_traspaso(vault: Path) -> Path | None:
    carpeta = Path(vault) / "sesiones"
    if not carpeta.is_dir():
        return None
    candidatos = []
    for p in carpeta.iterdir():
        m = _NOMBRE.match(p.name)
        if m:
            candidatos.append(((m.group(1), int(m.group(2) or 1)), p.name))
    return carpeta / max(candidatos)[1] if candidatos else None
