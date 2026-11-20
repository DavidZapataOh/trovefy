"""Tests vivos en ``config/caja.yaml → tests`` sin perder los comentarios (plan 22, Tarea 9; resolución 11).

`abrir_test` (el 22, al registrar la activación), `actualizar_test` (el 22 suma las renovaciones; el 23 el surf, la
base y las ventas) y `cerrar_test` (el 23, al pasar a ``muerto``). Solo se reescribe el bloque ``tests:``; el resto del
archivo (y el comentario de la línea ``tests:``) queda byte a byte. Antes de sustituir se valida con
``trovefy.caja.config.cargar_caja``; si no valida, no se escribe nada. Idempotentes por ``campana_id``.
"""
from __future__ import annotations

import re
import tempfile
from decimal import Decimal
from pathlib import Path

import yaml

from trovefy.caja.config import cargar_caja
from trovefy.config.yaml_config import cargar_yaml
from trovefy.vault.escritura import escribir_atomico

_CLAVE = re.compile(r"^tests\s*:")
_ORDEN = ("producto", "pais", "campana_id", "estado", "prorroga", "ventas", "diario_usd")


def _ruta(vault: Path) -> Path:
    return Path(vault) / "config" / "caja.yaml"


def _numero(v: Decimal | int | str):
    d = Decimal(str(v))
    return int(d) if d == d.to_integral_value() else str(d)


def _bloque(lineas: list[str]) -> tuple[int, int]:
    """(inicio, fin) del bloque ``tests:`` (fin exclusivo)."""
    for i, ln in enumerate(lineas):
        if _CLAVE.match(ln):
            j = i + 1
            while j < len(lineas) and (lineas[j].startswith((" ", "\t", "-")) or not lineas[j].strip()):
                j += 1
            while j > i + 1 and not lineas[j - 1].strip():
                j -= 1
            return i, j
    raise ValueError("config/caja.yaml no tiene la clave tests:")


def _comentario(linea: str) -> str:
    m = re.search(r"\s#.*$", linea.split(":", 1)[1]) if ":" in linea else None
    return m.group(0) if m else ""


def _render(tests: list[dict], comentario: str) -> list[str]:
    if not tests:
        return [f"tests: []{comentario}\n"]
    salida = [f"tests:{comentario}\n"]
    for t in tests:
        ordenado = {k: t[k] for k in _ORDEN if k in t} | {k: v for k, v in t.items() if k not in _ORDEN}
        texto = yaml.safe_dump(ordenado, default_flow_style=True, sort_keys=False, allow_unicode=True, width=10_000)
        salida.append(f"  - {texto.strip()}\n")
    return salida


def _guardar(vault: Path, cambiar) -> bool:
    ruta = _ruta(vault)
    texto = ruta.read_text(encoding="utf-8")
    lineas = texto.splitlines(keepends=True)
    if lineas and not lineas[-1].endswith("\n"):
        lineas[-1] += "\n"
    raw = cargar_yaml(texto) or {}
    tests = [dict(t) for t in (raw.get("tests") or []) if isinstance(t, dict)]
    nuevos = cambiar(tests)
    if nuevos is None:
        return False
    i, j = _bloque(lineas)
    nuevo_texto = "".join(lineas[:i] + _render(nuevos, _comentario(lineas[i].rstrip("\n"))) + lineas[j:])
    with tempfile.TemporaryDirectory() as tmp:  # valida antes de sustituir
        (Path(tmp) / "config").mkdir()
        (Path(tmp) / "config" / "caja.yaml").write_text(nuevo_texto, encoding="utf-8")
        cargar_caja(Path(tmp))
    escribir_atomico(ruta, nuevo_texto)
    return True


def abrir_test(vault: Path, producto: str, pais: str, campana_id: str, diario_usd: Decimal | int) -> bool:
    """Añade el test vivo; ``False`` si ya estaba esa campaña."""

    def cambiar(tests: list[dict]):
        if any(str(t.get("campana_id")) == str(campana_id) for t in tests):
            return None
        return [*tests, {"producto": producto, "pais": pais, "campana_id": str(campana_id), "estado": "vivo",
                         "prorroga": False, "ventas": None, "diario_usd": _numero(diario_usd)}]

    return _guardar(vault, cambiar)


def actualizar_test(vault: Path, campana_id: str, *, diario_usd: Decimal | int | None = None,
                    ventas: int | None = None, prorroga: bool | None = None) -> bool:
    """Cambia ``diario_usd``, ``ventas`` o ``prorroga`` del test de esa campaña; ``False`` si no cambia nada.
    ``KeyError`` si la campaña no está en ``tests``."""

    def cambiar(tests: list[dict]):
        t = next((x for x in tests if str(x.get("campana_id")) == str(campana_id)), None)
        if t is None:
            raise KeyError(f"la campaña {campana_id} no está en config/caja.yaml → tests")
        antes = dict(t)
        if diario_usd is not None:
            t["diario_usd"] = _numero(diario_usd)
        if ventas is not None:
            t["ventas"] = ventas
        if prorroga is not None:
            t["prorroga"] = prorroga
        return None if t == antes else tests

    return _guardar(vault, cambiar)


def cerrar_test(vault: Path, campana_id: str) -> bool:
    def cambiar(tests: list[dict]):
        t = next((x for x in tests if str(x.get("campana_id")) == str(campana_id)), None)
        if t is None or t.get("estado") == "cerrado":
            return None
        t["estado"] = "cerrado"
        return tests

    return _guardar(vault, cambiar)


__all__ = ["abrir_test", "actualizar_test", "cerrar_test"]
