"""Andamio del vault: copia la plantilla sin sobrescribir nada."""

from pathlib import Path

from trovefy.vault.escritura import escribir_atomico

PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro"
_MARCADOR = ".gitkeep"


def crear_vault(destino: Path, plantilla: Path | None = None) -> list[Path]:
    """Crea el vault desde la plantilla y devuelve lo creado; nunca sobrescribe.

    Las carpetas vacías de la plantilla llevan `.gitkeep`: se crea la carpeta, no el marcador.
    """
    destino = Path(destino)
    plantilla = Path(plantilla) if plantilla is not None else PLANTILLA
    if not plantilla.is_dir():
        raise FileNotFoundError(f"No existe la plantilla del vault: {plantilla}")
    creados: list[Path] = []
    destino.mkdir(parents=True, exist_ok=True)
    for origen in sorted(plantilla.rglob("*")):
        objetivo = destino / origen.relative_to(plantilla)
        if origen.is_dir():
            objetivo.mkdir(parents=True, exist_ok=True)
        elif origen.name == _MARCADOR:
            objetivo.parent.mkdir(parents=True, exist_ok=True)
        elif not objetivo.exists():
            escribir_atomico(objetivo, origen.read_text(encoding="utf-8"))
            creados.append(objetivo)
    return creados
