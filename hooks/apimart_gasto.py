"""Hook PreToolUse: APIMart solo se llama con ``trovefy producto`` (tiene tope de gasto, contrato 7).

Bash (el comando se normaliza antes: sin comillas ni barras invertidas, y también decodificado ``%xx``):

- Si el comando menciona APIMart (``apimart.ai``, ``APIMART…``, ``trovefy.apimart``, ``claude.env`` o
  ``apimart_tope_usd``), se deniega con ``$(…)``, comillas invertidas, ``<(…)``, ``>(…)`` o un ``&`` suelto
  (segundo plano), y si algún segmento empieza por un intérprete (``sh``, ``python``, ``xargs``, ``env``…).
- Cada segmento que lo menciona debe empezar por ``trovefy producto`` (o ``uv run trovefy producto``) o
  ser de solo lectura/desarrollo: ``uv run pytest``, ``uv run ruff``, ``ruff``, ``rg``, ``grep``,
  ``git log|diff|show|commit`` (sin ``--pre``, ``--output`` ni ``--ext-diff``). ``claude.env`` (la clave)
  solo bajo ``trovefy producto``.
- Un comando destructivo (``rm``, ``mv``, ``cp``, ``truncate``, ``>``, ``>>``, ``tee``, ``sed -i``…) o un
  intérprete sobre ``costes.csv``, ``.apimart-intentos.jsonl``, ``.apimart.lock`` o ``config/producto.yaml``.

Write/Edit/MultiEdit/NotebookEdit dentro del vault: deniega ``productos/*/entregable/**/costes.csv``,
``.apimart-intentos.jsonl`` y ``.apimart.lock`` (el registro del gasto), ``config/producto.yaml``,
``productos/*/decisiones/*-tope-apimart.md`` y todo cambio de ``apimart_tope_usd`` en
``productos/*/PRODUCTO.md`` (el tope solo lo sube ``trovefy producto`` con la cita del usuario).

Read/Grep: deniega ``claude.env``. WebFetch: deniega ``apimart.ai`` y sus subdominios salvo
``docs.apimart.ai`` (documentación, sin coste; ruling R-D). Solo biblioteca estándar; falla cerrado.
Idea tomada del ``guard.mjs`` de LordVayron/video-factory (MIT, commit 8afd1b2e).
"""
from __future__ import annotations

import pathlib
import re
from urllib.parse import unquote, urlsplit

from _comun import (
    _SEGMENTOS,
    bash_destructivo,
    ejecutar_guardia,
    herramienta,
    resolver,
    vault_root,
)

MOTIVO = "APIMart solo se llama con `trovefy producto`: tiene tope de gasto"
MOTIVO_CLAVE = "claude.env guarda la clave de APIMart: solo la lee `trovefy producto`"
MOTIVO_TOPE = "el tope de APIMart solo lo sube `trovefy producto` con la cita literal del usuario"
MOTIVO_CONFIG = "config/producto.yaml no se edita desde Claude: sus valores los decide el usuario"
MOTIVO_GASTO = ("costes.csv, .apimart-intentos.jsonl y .apimart.lock son el registro del gasto: solo los escribe "
                "`trovefy producto`; no se editan ni se borran (si algo falla, pide ayuda)")

_MENCION = re.compile(
    r"(?i:apimart\.ai|trovefy\.apimart|from\s+trovefy\s+import\s+apimart|claude\.env|apimart_tope_usd)|APIMART")
_CLAUDE_ENV = re.compile(r"claude\.env", re.IGNORECASE)
_TOPE = re.compile(r"apimart_tope_usd", re.IGNORECASE)
_TROVEFY = re.compile(r"(?:uv\s+run\s+)?trovefy\s+producto(?:\s|$)")
_LECTURA = re.compile(r"(?:uv\s+run\s+(?:pytest|ruff)|ruff|rg|grep|git\s+(?:log|diff|show|commit))(?:\s|$)")
_OPCION_PELIGROSA = re.compile(r"--(?:pre|pre-glob|output|ext-diff|textconv|exec)\b")
_SUBCOMANDO = re.compile(r"\$\(|`|<\(|>\(")
_REDIRECCION_FD = re.compile(r"\d*>&\d*-?|&>>?|\d?>\s*/dev/null")
_INTERPRETE = re.compile(
    r"(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|fish|python[\d.]*|perl|ruby|node|deno|bun|php|xargs|eval|source|\.|exec"
    r"|env|printenv|nohup|timeout|parallel|busybox|uv\s+run\s+python[\d.]*)(?:\s|$)")
_GASTO = re.compile(r"costes\.csv|\.apimart-intentos\.jsonl|\.apimart\.lock", re.IGNORECASE)
_CONFIG = re.compile(r"config/producto\.yaml", re.IGNORECASE)
_ARCHIVOS_GASTO = (".apimart-intentos.jsonl", ".apimart.lock")
_TOPE_YAML = re.compile(r"^\s*apimart_tope_usd\s*:(.*)$", re.MULTILINE)


def _normalizar(comando: str) -> str:
    return re.sub(r"[\"'\\]", "", comando)


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _fondo(comando: str) -> bool:
    """¿Hay un ``&`` suelto (segundo plano), sin contar ``&&`` ni las redirecciones ``2>&1``/``&>``?"""
    return "&" in _REDIRECCION_FD.sub(" ", comando).replace("&&", " ")


def _escribe(comando: str) -> bool:
    limpio = re.sub(r"\d?>\s*/dev/null", " ", comando)
    return bash_destructivo(limpio) or ">>" in limpio or bool(re.search(r"\bdd\b|\bshred\b|\bunlink\b", limpio))


def _segmentos(comando: str) -> list[str]:
    return [s.strip() for s in _SEGMENTOS.split(comando) if s.strip()]


def _bash(comando: str) -> tuple[str, str]:
    for variante in dict.fromkeys((comando, unquote(comando))):
        c = _normalizar(variante)
        segmentos = _segmentos(c)
        if _GASTO.search(c) and (_escribe(c) or any(_INTERPRETE.match(s) for s in segmentos)):
            return "deny", MOTIVO_GASTO
        if _CONFIG.search(c) and (_escribe(c) or any(_INTERPRETE.match(s) for s in segmentos)):
            return "deny", MOTIVO_CONFIG
        if not _MENCION.search(c):
            continue
        if _SUBCOMANDO.search(c) or _fondo(c):
            return "deny", MOTIVO
        for seg in segmentos:
            if not _MENCION.search(seg):
                if _INTERPRETE.match(seg):  # p. ej. `rg -o 'curl …apimart.ai…' x | sh`
                    return "deny", MOTIVO
                continue
            if _TROVEFY.match(seg):
                continue
            if _CLAUDE_ENV.search(seg):
                return "deny", MOTIVO_CLAVE
            if _LECTURA.match(seg) and not _OPCION_PELIGROSA.search(seg) and not _escribe(seg):
                continue
            return "deny", MOTIVO_TOPE if _TOPE.search(seg) else MOTIVO
    return "allow", ""


def _relativa(ruta: str, cwd: str | None) -> tuple[str, ...] | None:
    """Partes de ``ruta`` (resuelta, enlaces incluidos) relativas al vault; ``None`` si está fuera."""
    try:
        destino = resolver(ruta, cwd)
        return destino.relative_to(vault_root().resolve(strict=False)).parts
    except (ValueError, OSError):
        return None


def _topes(texto: str) -> list[str]:
    return [v.strip() for v in _TOPE_YAML.findall(texto)]


def _tras_editar(actual: str, ediciones: object) -> str | None:
    if not isinstance(ediciones, list) or not ediciones:
        return None
    for e in ediciones:
        if not isinstance(e, dict):
            return None
        viejo, nuevo = e.get("old_string"), e.get("new_string")
        if not isinstance(viejo, str) or not isinstance(nuevo, str) or not viejo or viejo not in actual:
            return None
        actual = actual.replace(viejo, nuevo) if e.get("replace_all") else actual.replace(viejo, nuevo, 1)
    return actual


def _cambia_tope(nombre: str, datos: dict, destino: pathlib.Path) -> bool:
    try:
        actual = destino.read_text(encoding="utf-8") if destino.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return True
    if nombre == "write":
        nuevo = datos.get("content")
        return not isinstance(nuevo, str) or _topes(nuevo) != _topes(actual)
    ediciones = [datos] if nombre == "edit" else datos.get("edits")
    nuevo = _tras_editar(actual, ediciones)
    if nuevo is None:  # no se sabe cómo queda: se deniega si la edición nombra el tope
        return any(isinstance(e, dict) and _TOPE.search(f"{e.get('old_string')}{e.get('new_string')}")
                   for e in (ediciones if isinstance(ediciones, list) else [datos]))
    return _topes(nuevo) != _topes(actual)


def _escritura(nombre: str, datos: dict, cwd: str | None) -> tuple[str, str]:
    ruta = datos.get("notebook_path" if nombre == "notebookedit" else "file_path")
    if not isinstance(ruta, str) or not ruta:
        return "allow", ""
    partes = _relativa(ruta, cwd)
    if partes is None:
        return "allow", ""
    if partes == ("config", "producto.yaml"):
        return "deny", MOTIVO_CONFIG
    if len(partes) < 3 or partes[0] != "productos":
        return "allow", ""
    if partes[2] == "entregable" and (partes[-1] == "costes.csv" or partes[-1] in _ARCHIVOS_GASTO):
        return "deny", MOTIVO_GASTO
    if len(partes) == 4 and partes[2] == "decisiones" and partes[3].endswith("-tope-apimart.md"):
        return "deny", MOTIVO_TOPE
    if len(partes) == 3 and partes[2] == "PRODUCTO.md" and (
            nombre == "notebookedit" or _cambia_tope(nombre, datos, resolver(ruta, cwd))):
        return "deny", MOTIVO_TOPE
    return "allow", ""


def decidir(entrada: dict) -> tuple[str, str]:
    nombre, datos = herramienta(entrada)
    nombre = nombre.lower()
    cwd = entrada.get("cwd") if isinstance(entrada.get("cwd"), str) else None
    if nombre == "bash":
        comando = datos.get("command", "")
        if not isinstance(comando, str):
            return "deny", MOTIVO
        return _bash(comando)
    if nombre == "webfetch":
        url = str(datos.get("url", ""))
        hosts = {_host(url), _host(unquote(url))}
        if any(h == "apimart.ai" or (h.endswith(".apimart.ai") and h != "docs.apimart.ai") for h in hosts):
            return "deny", MOTIVO
        return "allow", ""
    if nombre in ("read", "grep"):
        ruta = datos.get("file_path" if nombre == "read" else "path")
        if isinstance(ruta, str) and _CLAUDE_ENV.search(_normalizar(unquote(ruta))):
            return "deny", MOTIVO_CLAVE
        return "allow", ""
    if nombre in ("write", "edit", "multiedit", "notebookedit"):
        return _escritura(nombre, datos, cwd)
    return "allow", ""


if __name__ == "__main__":
    ejecutar_guardia(decidir)
