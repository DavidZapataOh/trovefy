"""Fixtures de /listo (plan 20): un vault de prueba con el producto-país ``p-9001-prueba``/``ZZ`` en verde.

Nunca la red, el HOME real, /var/spool ni el vault real.
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.listo.ficha import leer_ficha
from trovefy.vault import frontmatter

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "listo" / "PRODUCTO-verde.md"
PLANTILLA_CAJA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "caja.yaml"
P = "p-9001-prueba"
PAIS = "ZZ"
AHORA = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
EVIDENCIAS = (
    "landing/ZZ/qa/movil-0123456789ab-publicada.png",
    "landing/ZZ/qa/utm.png",
    "checkout/ZZ/compra/pedido.json",
    "checkout/ZZ/compra/events-manager.json",
    "checkout/ZZ/compra/entrega.md",
    "checkout/ZZ/compra/reembolso.json",
)


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool-inexistente"))
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path / "vault-inexistente"))


def escribir_tracking(vault: Path, estado: str = "verificado", motivos: list[str] | None = None,
                      dataset: str = "123456789012345") -> None:
    meta = {"tipo": "tracking", "producto": P, "pais": PAIS, "dataset_nombre": "PRUEBA ZZ", "dataset_id": dataset,
            "emisores": dict.fromkeys(("PageView", "ViewContent", "InitiateCheckout", "Purchase"), "impultienda"),
            "pixel_publico": "ok", "pixel_config": None, "capi": "visto_en_meta",
            "eventos": {"PageView": 3, "ViewContent": 0, "InitiateCheckout": 1, "Purchase": 1},
            "fuente_eventos": "mcp", "estado": estado, "evidencia": [], "motivos": motivos or [], "ejecutor": None}
    frontmatter.escribir(vault / "productos" / P / "checkout" / PAIS / "TRACKING.md", meta, "# Tracking\n")


def preparar_vault(base: Path) -> Path:
    vault = base / "vault"
    carpeta = vault / "productos" / P
    carpeta.mkdir(parents=True)
    shutil.copy(FIXTURE, carpeta / "PRODUCTO.md")
    for rel in EVIDENCIAS:
        (carpeta / rel).parent.mkdir(parents=True, exist_ok=True)
        (carpeta / rel).write_bytes(b"")
    escribir_tracking(vault)
    return vault


@pytest.fixture
def ficha_verde(tmp_path):
    vault = preparar_vault(tmp_path)
    return vault, leer_ficha(vault, P, PAIS)


def romper(ficha, ruta: str, valor):
    """Copia de la ficha con ``ruta`` (``a.b.c``) cambiada; ``valor=None`` la quita."""
    import copy
    from dataclasses import replace

    datos = copy.deepcopy(ficha.datos)
    partes = ruta.split(".")
    d = datos
    for p in partes[:-1]:
        d = d.setdefault(p, {})
    if valor is None:
        d.pop(partes[-1], None)
    else:
        d[partes[-1]] = valor
    return replace(ficha, datos=datos)


# --- lo del instante: TRM, caja, spool, landing ---------------------------------------------------------------------


def trm_fijo(dia: date):
    from trovefy.trm import Trm

    return Trm(Decimal(4000), dia, dia)


def vault_con_caja(vault: Path) -> Path:
    (vault / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(PLANTILLA_CAJA, vault / "config" / "caja.yaml")
    return vault


def spool_con(base: Path, estados: dict) -> Path:
    carpeta = base / "spool" / "estado"
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, datos in estados.items():
        (carpeta / f"{nombre}.json").write_text(json.dumps(datos))
    return base / "spool"


def spool_sano(base: Path, ahora: datetime = AHORA) -> Path:
    return spool_con(base, {"latido": {"fecha": (ahora - timedelta(minutes=1)).isoformat()},
                            "stop": {"activo": False}})


class _Cabeceras(dict):
    def get(self, clave, defecto=None):
        return super().get(clave.lower(), defecto)


class _Resp:
    def __init__(self, codigo: int, cuerpo: bytes, url: str, tipo: str):
        self.status = codigo
        self._cuerpo = cuerpo
        self._url = url
        self.headers = _Cabeceras({"content-type": tipo})

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._cuerpo if n < 0 else self._cuerpo[:n]

    def close(self):
        pass


def abrir_landing_falso(codigo: int = 200, cuerpo: bytes = b"<html>ok</html>", final: str | None = None,
                        tipo: str = "text/html; charset=utf-8", error: Exception | None = None):
    peticiones: list = []

    def abrir(req, timeout=None):
        peticiones.append((req, timeout))
        if error is not None:
            raise error
        if codigo >= 400:
            import io
            import urllib.error

            raise urllib.error.HTTPError(req.full_url, codigo, "error", {}, io.BytesIO(b""))
        return _Resp(codigo, cuerpo, final or req.full_url, tipo)

    abrir.peticiones = peticiones
    return abrir


def marcar_dominio(vault: Path, estado08: str = "verificado") -> None:
    from trovefy.arranque.estado import (
        ResultadoVerificacion,
        aplicar_verificacion,
        marcar_hecho,
    )

    marcar_hecho(vault, "07", datos={"dominio": "tienda-prueba.example"})
    if estado08 == "verificado":
        aplicar_verificacion(vault, "08", ResultadoVerificacion(True, ["config/evidencia/08.png"], "verificado", []))
    elif estado08 == "hecho":
        marcar_hecho(vault, "08")


@pytest.fixture
def todo_verde(tmp_path):
    """El vault de la fixture con dominio, caja y un spool sano; devuelve (vault, FuentesListo)."""
    from trovefy.listo.veredicto import FuentesListo

    vault = preparar_vault(tmp_path)
    marcar_dominio(vault)
    vault_con_caja(vault)
    fuentes = FuentesListo(spool=spool_sano(tmp_path), abrir_landing=abrir_landing_falso(), trm_de=trm_fijo)
    return vault, fuentes
