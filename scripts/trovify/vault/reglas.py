"""Consistencia entre config/umbrales.yaml y las páginas wiki/reglas/R-*.md."""

from pathlib import Path

from trovify.config.umbrales import cargar
from trovify.vault.frontmatter import leer


def consistencia(vault: Path) -> list[str]:
    """Problemas entre los umbrales y las reglas que los citan (vacío = todo bien)."""
    vault = Path(vault)
    umbrales = cargar(vault / "config" / "umbrales.yaml")
    problemas: list[str] = []
    citados: set[str] = set()
    ids: set[str] = set()
    for pagina in sorted((vault / "wiki" / "reglas").glob("R-*.md")):
        meta, _ = leer(pagina)
        rid = str(meta.get("id") or pagina.name[:5])
        ids.add(rid)
        for clave in meta.get("umbrales") or []:
            citados.add(clave)
            if clave not in umbrales:
                problemas.append(f"{rid}: cita el umbral «{clave}», que no existe en umbrales.yaml")
            elif umbrales[clave].regla != rid:
                problemas.append(
                    f"{rid}: cita el umbral «{clave}», cuya regla en umbrales.yaml es {umbrales[clave].regla}"
                )
    for clave, u in umbrales.items():
        if u.regla not in ids:
            problemas.append(f"{u.regla}: no tiene página en wiki/reglas/ (umbral «{clave}»)")
        if clave not in citados:
            problemas.append(f"umbral «{clave}» ({u.regla}): ninguna regla lo cita")
    return problemas
