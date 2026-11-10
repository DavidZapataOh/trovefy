"""Consistencia entre config/umbrales.yaml y las páginas wiki/reglas/R-*.md."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from trovify.config.umbrales import cargar, cargar_texto
from trovify.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovify.vault.frontmatter import leer, renderizar

_INICIO = "<!-- REGLAS:INICIO -->"
_FIN = "<!-- REGLAS:FIN -->"
_ID = re.compile(r"R-(\d{3})")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_PAR = re.compile(r"`([a-z0-9_.]+)` \(([0-9][0-9.,]*)\)")  # `clave` (valor) en el texto de una regla


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


def _numero(texto: str) -> float | None:
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def valores_citados(vault: Path) -> list[tuple[str, str, str, float | None]]:
    """(página, clave, valor tal como se escribió, valor numérico) de cada `clave` (valor)
    en las reglas vigentes."""
    vault = Path(vault)
    pares = []
    for _rid, pagina, meta in _paginas(vault):
        if not _vigente(meta):
            continue
        rel = pagina.relative_to(vault).as_posix()
        for clave, texto in _PAR.findall(pagina.read_text(encoding="utf-8")):
            pares.append((rel, clave, texto, _numero(texto)))
    return pares


def valores_desactualizados(vault: Path) -> list[tuple[str, str]]:
    """(página, detalle) de cada valor citado que no coincide con config/umbrales.yaml."""
    umbrales = cargar(Path(vault) / "config" / "umbrales.yaml")
    problemas = []
    for rel, clave, texto, num in valores_citados(vault):
        if clave not in umbrales:
            problemas.append((rel, f"cita `{clave}` ({texto}), que no existe en umbrales.yaml"))
        elif num != float(umbrales[clave].valor):
            problemas.append((rel, f"cita `{clave}` ({texto}) pero umbrales.yaml dice {umbrales[clave].valor:g}"))
    return problemas


def formatear_valor_citado(nuevo: float, viejo: str) -> str:
    """El valor nuevo con el formato que usaba la página (coma decimal, decimales mínimos)."""
    sep = "," if "," in viejo else ("." if "." in viejo else None)
    dec_viejo = len(viejo.split(sep)[1]) if sep else 0
    dec_nuevo = len(f"{nuevo:.6f}".rstrip("0").split(".")[1])
    decimales = max(dec_viejo, dec_nuevo)
    texto = f"{nuevo:.{decimales}f}"
    return texto.replace(".", sep or ",") if decimales else texto


def _reescribir_citas(texto: str, nuevos: dict[str, float]) -> str:
    def cambia(m: re.Match) -> str:
        clave, viejo = m.group(1), m.group(2)
        return m.group(0) if clave not in nuevos else f"`{clave}` ({formatear_valor_citado(nuevos[clave], viejo)})"
    return _PAR.sub(cambia, texto)


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


@dataclass
class PlanRegla:
    """Todo lo que `nueva_regla` escribiría, ya calculado en memoria."""

    id: str
    ruta: Path
    vault: Path
    titulo: str
    escrituras: list[tuple[Path, str]] = field(default_factory=list)  # en orden de escritura
    lineas: list[str] = field(default_factory=list)

    def resumen(self) -> list[str]:
        return list(self.lineas)


def planear_regla(
    vault: Path,
    titulo: str,
    regla: str,
    porque: str,
    como: str,
    fuente: str,
    umbrales: dict[str, float] | None = None,
    reemplaza: list[str] | None = None,
    fecha: str | None = None,
) -> PlanRegla:
    """Valida todo y calcula los contenidos; no escribe nada."""
    vault = Path(vault)
    umbrales = dict(umbrales or {})
    reemplaza = list(reemplaza or [])
    fecha = fecha or datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d")
    if not _FECHA.fullmatch(fecha):
        raise ValueError(f"La fecha «{fecha}» no tiene el formato AAAA-MM-DD")
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise ValueError(f"La fecha «{fecha}» no existe en el calendario") from None
    if re.search(r"[\r\n]", titulo):
        raise ValueError("El título no puede tener saltos de línea")
    slug = _slug(titulo)
    if not slug:
        raise ValueError(f"El título «{titulo}» no genera un nombre de archivo válido")

    ruta_u = vault / "config" / "umbrales.yaml"
    claude = vault / "CLAUDE.md"
    indice = vault / "index.md"
    for archivo in (ruta_u, claude, indice):
        if not archivo.is_file():
            raise ValueError(f"Falta {archivo.relative_to(vault)} en el vault")
    texto_claude = claude.read_text(encoding="utf-8")
    if _INICIO not in texto_claude or _FIN not in texto_claude:
        raise ValueError("CLAUDE.md no tiene los marcadores de reglas (REGLAS:INICIO / REGLAS:FIN)")
    texto_indice = indice.read_text(encoding="utf-8")

    existentes = cargar(ruta_u)  # valida cada entrada
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
    nombre = f"{rid}-{slug}"
    ruta = vault / "wiki" / "reglas" / f"{nombre}.md"
    if ruta.exists():
        raise ValueError(f"Ya existe {ruta.relative_to(vault)}")
    heredados = [c for r in reemplaza for c in (paginas[r][1].get("umbrales") or [])
                 if c not in umbrales]
    heredados = list(dict.fromkeys(heredados))
    claves = list(dict.fromkeys([*umbrales, *heredados]))

    plan = PlanRegla(id=rid, ruta=ruta, vault=vault, titulo=titulo)
    rel = lambda p: str(p.relative_to(vault))

    # 1. página nueva
    meta = {"tipo": "regla", "id": rid, "titulo": titulo, "fecha": fecha, "fuente": fuente,
            "umbrales": claves, "estado": "vigente"}
    if reemplaza:
        meta["reemplaza"] = reemplaza
    cuerpo = (f"\n# {rid} · {titulo}\n\n## Regla\n\n{regla}\n\n## Por qué\n\n{porque}\n\n"
              f"## Cómo se aplica\n\n{como}\n\n## Fuente\n\n{fuente}\n")
    plan.escrituras.append((ruta, renderizar(meta, cuerpo)))

    # 2. páginas reemplazadas
    for viejo in reemplaza:
        pagina, m = paginas[viejo]
        _, texto = leer(pagina)
        m = {**m, "estado": "reemplazada", "reemplazada_por": rid}
        plan.escrituras.append((pagina, renderizar(m, texto)))

    # 2b. otras reglas vigentes que citan el valor de un umbral que cambia: se actualiza el número
    nuevos = {c: v for c, v in umbrales.items() if v != existentes[c].valor}
    actualizadas = []
    for otro, (pagina, m) in paginas.items():
        if otro in reemplaza or not _vigente(m):
            continue
        original = pagina.read_text(encoding="utf-8")
        cambiado = _reescribir_citas(original, nuevos)
        if cambiado != original:
            plan.escrituras.append((pagina, cambiado))
            actualizadas.append(otro)

    # 3. CLAUDE.md
    texto = texto_claude.replace(_FIN, f"- [[{nombre}]] {titulo}\n{_FIN}", 1)
    for viejo in reemplaza:
        texto = _marcar_reemplazada(texto, viejo, nombre)
    plan.escrituras.append((claude, texto))

    # 4. index.md
    lineas = texto_indice.split("\n")
    nueva = f"- [[wiki/reglas/{nombre}]] — {titulo}"
    ultimo = max((i for i, ln in enumerate(lineas) if ln.startswith("- [[wiki/reglas/")), default=None)
    if ultimo is None:
        lineas.append(nueva)
    else:
        lineas.insert(ultimo + 1, nueva)
    texto = "\n".join(lineas)
    for viejo in reemplaza:
        texto = _marcar_reemplazada(texto, viejo, f"wiki/reglas/{nombre}")
    plan.escrituras.append((indice, texto))

    # 5. umbrales.yaml (al final)
    if claves:
        crudo = ruta_u.read_text(encoding="utf-8")
        datos = yaml.safe_load(crudo) or {}
        for clave, valor in umbrales.items():
            previo = existentes[clave]
            cambio = {"valor": valor, "fuente": fuente, "fecha": fecha, "regla": rid}
            if valor != previo.valor:
                cambio["gana_sobre"] = f"{previo.regla}: {previo.valor:g}"
            datos[clave].update(cambio)
        for clave in heredados:
            datos[clave]["regla"] = rid
        cabecera = []
        for linea in crudo.splitlines():
            if not linea.startswith("#"):
                break
            cabecera.append(linea)
        cuerpo_u = yaml.safe_dump(datos, sort_keys=False, allow_unicode=True)
        nuevo_yaml = "".join(f"{c}\n" for c in cabecera) + cuerpo_u
        cargar_texto(nuevo_yaml)  # misma validación que el cargador: número finito, no bool
        plan.escrituras.append((ruta_u, nuevo_yaml))

    plan.lineas.append(f"Regla nueva: {rid} -> {rel(ruta)}")
    plan.lineas.append("Archivos que cambian: " + ", ".join(rel(p) for p, _ in plan.escrituras))
    for clave, valor in umbrales.items():
        plan.lineas.append(f"Umbral {clave}: {existentes[clave].valor} -> {valor}")
    if actualizadas:
        plan.lineas.append("Se actualiza el valor citado en " + ", ".join(actualizadas))
    for clave in heredados:
        plan.lineas.append(f"{rid} pasa a ser dueña de {clave} (valor sin cambios)")
    return plan


def aplicar_plan(plan: PlanRegla) -> Path:
    """Escribe el plan (cada archivo de forma atómica) y registra una línea en log.md."""
    for ruta, contenido in plan.escrituras:
        escribir_atomico(ruta, contenido)
    anadir_log(plan.vault, "recordar", f"regla {plan.id} «{plan.titulo}»",
               [str(p.relative_to(plan.vault)) for p, _ in plan.escrituras])
    return plan.ruta


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

    Valida y calcula todo antes de escribir. Las reglas reemplazadas pasan a
    `estado: reemplazada`; los umbrales que citaban y que la regla nueva no redefine pasan
    a ser suyos (solo cambia `regla` en umbrales.yaml, no el valor).
    """
    return aplicar_plan(planear_regla(vault, titulo, regla, porque, como, fuente,
                                      umbrales, reemplaza, fecha))
