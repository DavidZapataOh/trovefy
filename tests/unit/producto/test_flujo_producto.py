"""Flujo completo de `/producto` por la CLI (plan 17, Tarea 13), en un vault temporal.

ficha → plan → gates → imágenes (APIMart falso) → maquetar cada pieza (WeasyPrint y poppler reales) →
anotar-qc revisor y nativo (veredictos falsos de los agentes) → cerrar → `producido`.
"""

import io
import shutil
import stat
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from fixtures.pdf.herramientas import faltan, requerir
from trovefy import cli, producto_cli
from trovefy.apimart.gasto import gastado_usd, leer_costes
from trovefy.producto.config import PLANTILLA
from trovefy.producto.rutas import pieza
from trovefy.vault import frontmatter

from .apimart_falso import CLAVE, APIMartFalso, escribir_env, publico

P = "p-0042-respira"
TESTS = Path(__file__).resolve().parents[2]
FIXTURE = TESTS / "fixtures" / "producto" / P
FUENTE = TESTS / "fixtures" / "pdf" / "respira" / "fuente"
GOLDEN = TESTS / "golden" / "producto" / "PRODUCTO-flujo.md"
COT = ZoneInfo("America/Bogota")
AHORA = datetime(2026, 11, 16, 10, 0, tzinfo=COT)
MERCADOS = "ZZ: {idioma: es, moneda: EUR, zona: Europe/Madrid, banda_eur: [9, 19], estado: activo}\n"
PIEZAS = ("principal", "bono-1", "bono-2", "bump", "u1")
PLAN = "| sección | palabras | fichas |\n|---|---|---|\n| s-01 | 450 | 1 |\n| s-02 | 350 | 0 |\n| s-03 | 350 | 0 |\n"
IMAGENES = [{"id": "portada", "pieza": "principal", "prompt": "portada de un cuaderno de respiración, azul",
             "proporcion": "2:3", "resolucion": "1k"},
            {"id": "mockup", "pieza": "principal", "prompt": "mockup del cuaderno abierto sobre una mesa",
             "proporcion": "3:2", "resolucion": "1k"},
            {"id": "il-01", "pieza": "principal", "prompt": "ilustración de una persona respirando despacio",
             "proporcion": "1:1", "resolucion": "1k"}]
REVISOR = "Revisé las 6 páginas de la hoja: sin desbordes ni páginas en blanco.\n\nVEREDICTO: ok\n"
NATIVO = "Se lee natural en español de ZZ.\n\nVEREDICTO: ok\n"


def _config(v: Path) -> None:
    """La plantilla con los mínimos de páginas y de palabras de la fixture (3 páginas, secciones de 60)."""
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    for tipo in datos["plan"]["paginas_min"]:
        datos["plan"]["paginas_min"][tipo]["valor"] = 3
    datos["plan"]["seccion_palabras_min"]["valor"] = 60
    (v / "config" / "producto.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    requerir(faltan("pdfinfo", "pdftoppm", "fc-match", weasyprint=True))
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / ".trovefy").mkdir()
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    _config(v)
    shutil.copytree(FIXTURE, v / "productos" / P)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(producto_cli, "RUTA_ENV", escribir_env(tmp_path / "home" / ".config" / "trovefy"))
    monkeypatch.setattr(producto_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(producto_cli, "_dormir", lambda s: None)
    monkeypatch.setattr(producto_cli, "_abrir", APIMartFalso())
    monkeypatch.setattr(producto_cli, "_abrir_publico", publico)
    return v


def _cli(capsys, monkeypatch, *args, stdin=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    codigo = cli.main(["producto", *args])
    salida = capsys.readouterr()
    texto = salida.out + salida.err
    assert CLAVE not in texto and "sk-prueba" not in texto
    return codigo, texto


def _lineas_log(v: Path) -> list[str]:
    return [x for x in (v / "log.md").read_text(encoding="utf-8").splitlines() if "producto" in x]


def test_flujo_producto(vault, capsys, monkeypatch):
    v = vault

    def paso(*args, stdin=None, codigo=0):
        antes = len(_lineas_log(v)) if (v / "log.md").is_file() else 0
        c, texto = _cli(capsys, monkeypatch, *args, stdin=stdin)
        assert c == codigo, f"{args}: {texto}"
        return texto, antes

    texto, _ = paso("ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    assert all(p in texto for p in PIEZAS)
    assert len(_lineas_log(v)) >= 1

    # Claude escribe el plan y los fragmentos de cada pieza (aquí, los de la fixture).
    for pid in PIEZAS:
        raiz = pieza(v, P, pid).raiz
        raiz.mkdir(parents=True, exist_ok=True)
        (raiz / "PLAN.md").write_text(PLAN, encoding="utf-8")
        shutil.copytree(FUENTE, raiz / "fuente")
        paso("plan", P, "--pieza", pid)
        paso("gates", P, "--pieza", pid)

    (v / "productos" / P / "entregable" / "imagenes.yaml").write_text(
        yaml.safe_dump(IMAGENES, allow_unicode=True), encoding="utf-8")
    paso("imagenes", P, "--simular")
    texto, antes = paso("imagenes", P)
    assert "generadas: portada, mockup, il-01" in texto
    filas = leer_costes(v, P)
    assert sum(1 for f in filas if f.estado == "completada") == 3
    assert gastado_usd(filas) <= Decimal("2.00")
    assert len(_lineas_log(v)) > antes

    for pid in PIEZAS:
        texto, antes = paso("maquetar", P, "--pieza", pid)
        assert "Apto." in texto and "hoja de contactos" in texto
        assert len(_lineas_log(v)) >= antes + 2  # el PDF y el QC con la hoja
        for agente, respuesta in (("revisor", REVISOR), ("nativo", NATIVO)):
            _, antes = paso("anotar-qc", P, "--pieza", pid, "--version", "1", "--agente", agente, stdin=respuesta)
            assert len(_lineas_log(v)) == antes + 1
    texto, _ = paso("qc", P, "--pieza", "principal", "--paginas", "1,2")
    assert "contactos-v1-r1.png" in texto

    texto, antes = paso("cerrar", P, "--pais", "ZZ")
    assert "ZZ: modelado → producido" in texto
    assert len(_lineas_log(v)) > antes
    meta, _ = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    assert meta["paises"]["ZZ"]["estado"] == "producido"
    assert (v / "productos" / P / "PRODUCTO.md").read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")

    entregable = v / "productos" / P / "entregable"
    medios = [f for f in entregable.rglob("*") if f.suffix in (".png", ".pdf")]
    assert len([f for f in medios if f.suffix == ".pdf"]) == len(PIEZAS)
    assert len([f for f in medios if f.parent.name == "medios"]) == 3
    for f in medios:
        assert stat.S_IMODE(f.stat().st_mode) == 0o640, f

    texto, _ = paso("estado", P)
    assert texto.count(" apta") == len(PIEZAS)
