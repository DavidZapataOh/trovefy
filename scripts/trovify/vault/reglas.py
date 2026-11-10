"""Consistencia entre config/umbrales.yaml y las páginas wiki/reglas/R-*.md."""

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

from trovify.config.umbrales import cargar
from trovify.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovify.vault.frontmatter import escribir, leer

_INICIO = "<!-- REGLAS:INICIO -->"
_FIN = "<!-- REGLAS:FIN -->"
_ID = re.compile(r"R-(\d{3})")


class ConflictoDeReglas(Exception):
    def __init__(self, ids: list[str]):
        self.ids = ids
        super().__init__(f"La regla nueva choca con: {', '.join(ids)}")


def _paginas(vault: Path):
    """(id, ruta, meta) de cada R-*.md, ordenadas."""
    for pagina in sorted((Path(vault) / "wiki" / "reglas").glob("R-*.md")):
        meta, _ = leer(pagina)
        yield str(meta.get("id") or pagina.name[:5]), pagina, meta


def _vigente(meta: dict) -> bool:
    return meta.get("estado", "vigente") == "vigente"


def consistencia(vault: Path) -> list[str]:
    """Problemas entre los umbrales y las reglas que los citan (vacío = todo bien)."""
    vault = Path(vault)
    umbrales = cargar(vault / "config" / "umbrales.yaml")
    problemas: list[str] = []
    citados: set[str] = set()
    ids: set[str] = set()
    for rid, _pagina, meta in _paginas(vault):
        ids.add(rid)
        if not _vigente(meta):
            continue
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


def conflictos(vault: Path, claves: list[str]) -> list[str]:
    """Ids de reglas vigentes que citan alguna de esas claves de umbral."""
    pedidas = set(claves)
    return [rid for rid, _p, meta in _paginas(vault)
            if _vigente(meta) and pedidas & set(meta.get("umbrales") or [])]


def _slug(titulo: str) -> str:
    base = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")


def _marcar_reemplazada(texto: str, viejo: str, nuevo_enlace: str) -> str:
    """Añade « (reemplazada por [[…]])» a las líneas de lista que enlazan a la regla vieja."""
    lineas = texto.split("\n")
    for i, linea in enumerate(lineas):
        enlaza = f"[[{viejo}-" in linea or f"[[wiki/reglas/{viejo}-" in linea
        if linea.startswith("- ") and enlaza and "(reemplazada por" not in linea:
            lineas[i] = f"{linea} (reemplazada por [[{nuevo_enlace}]])"
    return "\n".join(lineas)


def nueva_regla(
    vault: Path,
    titulo: str,
    regla: str,
    porque: str,
    como: str,
    fuente: str,
    umbrales: dict[str, float] | None = None,
    reemplaza: list[str] | None = None,
    fecha: str | None = None,
) -> Path:
    """Crea la regla R-nnn siguiente, la indexa y actualiza umbrales.yaml.

    Las reglas reemplazadas pasan a `estado: reemplazada`; los umbrales que citaban y que
    la regla nueva no redefine pasan a ser suyos (solo cambia `regla`, no el valor).
    """
    vault = Path(vault)
    umbrales = dict(umbrales or {})
    reemplaza = list(reemplaza or [])
    fecha = fecha or datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d")
    ruta_u = vault / "config" / "umbrales.yaml"
    existentes = cargar(ruta_u)
    desconocidas = [c for c in umbrales if c not in existentes]
    if desconocidas:
        raise ValueError(f"Umbral(es) que no existen en umbrales.yaml: {', '.join(desconocidas)}")

    paginas = {rid: (p, m) for rid, p, m in _paginas(vault)}
    for rid in reemplaza:
        if rid not in paginas or not _vigente(paginas[rid][1]):
            raise ValueError(f"No se puede reemplazar {rid}: no existe o no está vigente")

    choques = [i for i in conflictos(vault, list(umbrales)) if i not in reemplaza]
    if choques:
        raise ConflictoDeReglas(choques)

    numeros = [int(m.group(1)) for rid in paginas if (m := _ID.fullmatch(rid))]
    rid = f"R-{max(numeros, default=0) + 1:03d}"
    nombre = f"{rid}-{_slug(titulo)}"
    heredados = [c for r in reemplaza for c in (paginas[r][1].get("umbrales") or [])
                 if c not in umbrales]
    claves = list(dict.fromkeys([*umbrales, *heredados]))

    # Todo validado: a partir de aquí se escribe.
    datos = yaml.safe_load(ruta_u.read_text(encoding="utf-8")) or {}
    for clave, valor in umbrales.items():
        datos[clave].update({"valor": valor, "fuente": fuente, "fecha": fecha, "regla": rid})
    for clave in heredados:
        datos[clave]["regla"] = rid
    if claves:
        cabecera = []
        for linea in ruta_u.read_text(encoding="utf-8").splitlines():
            if not linea.startswith("#"):
                break
            cabecera.append(linea)
        cuerpo_u = yaml.safe_dump(datos, sort_keys=False, allow_unicode=True)
        escribir_atomico(ruta_u, "".join(f"{c}\n" for c in cabecera) + cuerpo_u)

    meta = {"tipo": "regla", "id": rid, "titulo": titulo, "fecha": fecha, "fuente": fuente,
            "umbrales": claves, "estado": "vigente"}
    if reemplaza:
        meta["reemplaza"] = reemplaza
    cuerpo = (f"\n# {rid} · {titulo}\n\n## Regla\n\n{regla}\n\n## Por qué\n\n{porque}\n\n"
              f"## Cómo se aplica\n\n{como}\n\n## Fuente\n\n{fuente}\n")
    ruta = vault / "wiki" / "reglas" / f"{nombre}.md"
    escribir(ruta, meta, cuerpo)

    for viejo in reemplaza:
        pagina, m = paginas[viejo]
        _, texto = leer(pagina)
        m = {**m, "estado": "reemplazada", "reemplazada_por": rid}
        escribir(pagina, m, texto)

    claude = vault / "CLAUDE.md"
    texto = claude.read_text(encoding="utf-8")
    if _FIN not in texto:
        raise ValueError("CLAUDE.md no tiene el marcador de reglas")
    texto = texto.replace(_FIN, f"- [[{nombre}]] {titulo}\n{_FIN}", 1)
    for viejo in reemplaza:
        texto = _marcar_reemplazada(texto, viejo, nombre)
    escribir_atomico(claude, texto)

    indice = vault / "index.md"
    lineas = indice.read_text(encoding="utf-8").split("\n")
    nueva = f"- [[wiki/reglas/{nombre}]] — {titulo}"
    ultimo = max((i for i, l in enumerate(lineas) if l.startswith("- [[wiki/reglas/")), default=None)
    if ultimo is None:
        lineas += [nueva]
    else:
        lineas.insert(ultimo + 1, nueva)
    texto = "\n".join(lineas)
    for viejo in reemplaza:
        texto = _marcar_reemplazada(texto, viejo, f"wiki/reglas/{nombre}")
    escribir_atomico(indice, texto)

    anadir_log(vault, "recordar", f"regla {rid} «{titulo}»", [f"wiki/reglas/{nombre}.md"])
    return ruta
