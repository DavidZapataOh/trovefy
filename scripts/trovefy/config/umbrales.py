"""Umbrales de negocio con fuente, fecha y regla; nunca hay valores por defecto."""

import math
import re
from dataclasses import dataclass
from pathlib import Path

from trovefy.config.yaml_config import cargar_yaml

_CAMPOS = ("valor", "fuente", "fecha", "gana_sobre", "regla")
_REGLA = re.compile(r"R-\d{3}")


class UmbralInvalido(ValueError):
    def __init__(self, clave: str, motivo: str):
        self.clave = clave
        self.motivo = motivo
        super().__init__(f"Umbral «{clave}» inválido: {motivo}")


class UmbralFaltante(KeyError):
    def __init__(self, clave: str):
        self.clave = clave
        super().__init__(f"Umbral «{clave}» no existe en config/umbrales.yaml")

    def __str__(self) -> str:
        return self.args[0]


@dataclass(frozen=True)
class Umbral:
    clave: str
    valor: float
    fuente: str
    fecha: str
    gana_sobre: str
    regla: str


def cargar(ruta: Path) -> dict[str, Umbral]:
    return cargar_texto(Path(ruta).read_text(encoding="utf-8"))


def cargar_texto(texto: str) -> dict[str, Umbral]:
    """Valida el contenido de un umbrales.yaml con las mismas reglas que `cargar`."""
    datos = cargar_yaml(texto) or {}
    umbrales: dict[str, Umbral] = {}
    for clave, entrada in datos.items():
        if not isinstance(entrada, dict):
            raise UmbralInvalido(clave, "la entrada no es un mapa")
        for campo in _CAMPOS:
            if campo not in entrada or entrada[campo] is None or entrada[campo] == "":
                raise UmbralInvalido(clave, f"falta el campo «{campo}»")
        v = entrada["valor"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise UmbralInvalido(clave, f"«valor» no es numérico: {v!r}")
        if not math.isfinite(v):
            raise UmbralInvalido(clave, f"«valor» no es finito: {v!r}")
        for campo in ("fuente", "fecha", "gana_sobre", "regla"):
            entrada[campo] = str(entrada[campo])
        if not _REGLA.fullmatch(entrada["regla"]):
            raise UmbralInvalido(clave, f"«regla» no tiene el formato R-NNN: {entrada['regla']!r}")
        umbrales[clave] = Umbral(clave=clave, **{c: entrada[c] for c in _CAMPOS})
    return umbrales


def valor(vault: Path, clave: str) -> float:
    umbrales = cargar(Path(vault) / "config" / "umbrales.yaml")
    if clave not in umbrales:
        raise UmbralFaltante(clave)
    return umbrales[clave].valor


PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "umbrales.yaml"
_BLOQUE = re.compile(r"^([a-z0-9_.]+):\n(?:[ \t]+.*\n?)+", re.MULTILINE)


def _bloques(texto: str) -> dict[str, str]:
    return {m.group(1): m.group(0).rstrip("\n") + "\n" for m in _BLOQUE.finditer(texto)}


def completar(vault: Path, plantilla: Path | None = None) -> list[str]:
    """Añade al ``config/umbrales.yaml`` del vault las claves de la plantilla que le faltan, con su bloque literal
    (valor, fuente, fecha, gana_sobre y regla), y copia la página de la regla si el vault no la tiene y su número está
    libre. **Nunca cambia un valor existente** ni borra claves: los valores del vault cambian con el «sí» del usuario
    (`/recordar`). Devuelve una línea por cambio (vacía si no hay nada que añadir). Idempotente."""
    from trovefy.vault.escritura import escribir_atomico
    from trovefy.vault.frontmatter import leer

    vault = Path(vault)
    plantilla = Path(plantilla) if plantilla is not None else PLANTILLA
    ruta = vault / "config" / "umbrales.yaml"
    original = ruta.read_text(encoding="utf-8")
    existentes = cargar_texto(original)
    nuevos = cargar_texto(plantilla.read_text(encoding="utf-8"))
    bloques = _bloques(plantilla.read_text(encoding="utf-8"))
    reglas_vault = Path(vault) / "wiki" / "reglas"
    reglas_plantilla = plantilla.parent.parent / "wiki" / "reglas"
    titulos = {}
    for pagina in sorted(reglas_vault.glob("R-*.md")) if reglas_vault.is_dir() else ():
        meta, _ = leer(pagina)
        titulos[str(meta.get("id") or pagina.name[:5])] = pagina.name
    lineas: list[str] = []
    anadir: list[str] = []
    copiar: dict[str, Path] = {}
    for clave, u in nuevos.items():
        if clave in existentes:
            continue
        origen = next(iter(sorted(reglas_plantilla.glob(f"{u.regla}-*.md"))), None)
        if u.regla in titulos:
            if origen is not None and titulos[u.regla] != origen.name:
                lineas.append(f"pendiente: {clave} es de {u.regla} en la plantilla, pero tu {u.regla} es otra regla "
                              f"({titulos[u.regla]}): añádela con /recordar")
                continue
        elif origen is not None:
            copiar[u.regla] = origen
        else:
            lineas.append(f"pendiente: {clave} cita {u.regla}, que no tiene página")
            continue
        anadir.append(clave)
    if not anadir:
        return lineas
    texto = original if original.endswith("\n") else original + "\n"
    texto += "".join("\n" + bloques[c] for c in anadir)
    cargar_texto(texto)  # valida antes de escribir
    for origen in copiar.values():
        destino = reglas_vault / origen.name
        escribir_atomico(destino, origen.read_text(encoding="utf-8"))
        nombre = origen.stem
        meta, _ = leer(origen)
        titulo = str(meta.get("titulo") or nombre)
        claude = vault / "CLAUDE.md"
        if claude.is_file():
            t = claude.read_text(encoding="utf-8")
            if f"[[{nombre}]]" not in t and "<!-- REGLAS:FIN -->" in t:
                escribir_atomico(claude, t.replace("<!-- REGLAS:FIN -->", f"- [[{nombre}]] {titulo}\n<!-- REGLAS:FIN -->", 1))
        indice = vault / "index.md"
        if indice.is_file():
            t = indice.read_text(encoding="utf-8")
            if f"[[wiki/reglas/{nombre}]]" not in t:
                ls = t.split("\n")
                ultimo = max((i for i, ln in enumerate(ls) if ln.startswith("- [[wiki/reglas/")), default=len(ls) - 1)
                ls.insert(ultimo + 1, f"- [[wiki/reglas/{nombre}]] — {titulo}")
                escribir_atomico(indice, "\n".join(ls))
        lineas.append(f"regla copiada de la plantilla: {origen.name}")
    escribir_atomico(ruta, texto)
    lineas.append(f"umbrales añadidos a config/umbrales.yaml: {', '.join(anadir)}")
    return lineas
