"""Lint del vault: enlaces rotos, páginas huérfanas y frontmatter obligatorio.

Idea adaptada de ``wiki-lint`` de un repo de referencia
(MIT; ver avisos privados).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from trovify.vault.frontmatter import leer

EXCLUIDOS = {".trovify", ".claude", "raw", "sesiones"}
_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
_MDLINK = re.compile(r"(?<!\[)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CERCADO = re.compile(r"^(`{3,}|~{3,}).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_EN_LINEA = re.compile(r"`[^`\n]*`")
_ESQUEMA = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass
class Problema:
    tipo: Literal["enlace_roto", "huerfana", "frontmatter"]
    ruta: str
    detalle: str


def _paginas(vault: Path) -> list[Path]:
    return sorted(
        p for p in vault.rglob("*.md")
        if p.is_file() and not (set(p.relative_to(vault).parts[:-1]) & EXCLUIDOS)
    )


def _sin_codigo(texto: str) -> str:
    return _EN_LINEA.sub("", _CERCADO.sub("", texto))


def _existe(ruta: Path, vault: Path) -> Path | None:
    try:
        ruta = ruta.resolve()
        ruta.relative_to(vault)
    except (ValueError, OSError):
        return None
    return ruta if ruta.exists() else None


def _por_nombre(vault: Path) -> dict[str, list[Path]]:
    """Páginas por nombre sin carpeta: ``[[R-001-x]]`` al estilo Obsidian (CLAUDE.md lo usa)."""
    nombres: dict[str, list[Path]] = {}
    for p in _paginas(vault):
        nombres.setdefault(p.stem, []).append(p)
    return nombres


def _enlaces(
    texto: str, pagina: Path, vault: Path, nombres: dict[str, list[Path]]
) -> list[tuple[str, Path | None, str | None]]:
    """(destino tal como se escribió, ruta resuelta o None si no existe)."""
    resultado = []
    for m in _WIKILINK.finditer(texto):
        destino = re.split(r"[|#]", m.group(1), maxsplit=1)[0].strip().rstrip("\\").strip()
        if not destino:
            continue
        base = destino.lstrip("/")
        objetivo = vault / (base if base.endswith(".md") else base + ".md")
        resuelto = _existe(objetivo, vault)
        ambiguo = None
        if resuelto is None and "/" not in base:
            cand = nombres.get(base.removesuffix(".md"), [])
            if len(cand) == 1:
                resuelto = cand[0]
            elif len(cand) > 1:
                ambiguo = "ambiguo: " + ", ".join(c.relative_to(vault).as_posix() for c in cand)
        resultado.append((f"[[{m.group(1)}]]", resuelto, ambiguo))
    for m in _MDLINK.finditer(texto):
        destino = m.group(1).strip("<>")
        if not destino or destino.startswith("#") or _ESQUEMA.match(destino):
            continue
        limpio = re.split(r"[#?]", destino, maxsplit=1)[0]
        if not limpio:
            continue
        base = vault if limpio.startswith("/") else pagina.parent
        resultado.append((destino, _existe(base / limpio.lstrip("/"), vault), None))
    return resultado


def _revisar_frontmatter(pagina: Path, rel: str) -> Problema | None:
    try:
        meta, _ = leer(pagina)
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        return Problema("frontmatter", rel, f"frontmatter ilegible ({type(exc).__name__})")
    if not isinstance(meta, dict):
        return Problema("frontmatter", rel, "frontmatter ilegible (no es un mapa)")
    faltan = [c for c in ("tipo", "fecha") if meta.get(c) in (None, "")]
    if meta.get("fuente") in (None, "", []) and meta.get("fuentes") in (None, "", []):
        faltan.append("fuente o fuentes")
    return Problema("frontmatter", rel, "falta en el frontmatter: " + ", ".join(faltan)) if faltan else None


def lint(vault: Path) -> list[Problema]:
    vault = Path(vault).resolve()
    problemas: list[Problema] = []
    entrantes: set[Path] = set()
    paginas = _paginas(vault)
    nombres = _por_nombre(vault)
    for pagina in paginas:
        rel = pagina.relative_to(vault).as_posix()
        try:
            texto = pagina.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problemas.append(Problema("frontmatter", rel, f"no se pudo leer ({type(exc).__name__})"))
            continue
        for escrito, resuelto, ambiguo in _enlaces(_sin_codigo(texto), pagina, vault, nombres):
            if ambiguo:
                problemas.append(Problema("enlace_roto", rel, f"{escrito} {ambiguo}"))
            elif resuelto is None:
                problemas.append(Problema("enlace_roto", rel, f"{escrito} no existe"))
            elif resuelto != pagina:
                entrantes.add(resuelto)
        partes = rel.split("/")
        if partes[0] in ("wiki", "productos"):
            fallo = _revisar_frontmatter(pagina, rel)
            if fallo:
                problemas.append(fallo)
    for pagina in paginas:
        rel = pagina.relative_to(vault).as_posix()
        if rel.startswith("wiki/") and pagina not in entrantes:
            problemas.append(Problema("huerfana", rel, "ninguna página la enlaza (ni index.md)"))
    return problemas
