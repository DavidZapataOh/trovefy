"""Fábrica del vault de prueba de /landing (plan 18): producto y países ficticios.

``vault_demo(tmp_path, estado="producido", secciones=15)`` escribe ``PRODUCTO.md`` (con el PDF vigente
en ``entregable.bg.principal``, resolución 14), ``OFERTA.md`` (``core`` y ``estructura_landing``,
resoluciones 4 y 5), ``ESCALERA.md`` (``paises.ZZ.pasos.front.precio``, resolución 6), ``BRANDBOOK.md``
(``nombre_local`` y ``tokens_css``, resolución 7), ``config/mercados.yaml`` con ``ZZ``/``ZY`` (y su
``tienda``, resolución 24), ``config/arranque.yaml`` con el paso 07 y su dominio, el PDF fijo de 3
páginas y una imagen propia en ``entregable/medios/`` con su manifiesto (resolución 15).
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from trovefy.landing import entrada
from trovefy.producto.medios import escribir_medio, registrar_medio
from trovefy.vault import frontmatter

P = "p-0099-demo"
RAIZ = Path(__file__).resolve().parents[2]
PDF_FIJO = RAIZ / "fixtures" / "landing" / "demo-bg-v1.pdf"
TIENDA = "https://tienda.demo.test"
DOMINIO = "ejemplo-demo.test"

# 15 secciones: (tipo, palabras, cta). La «prueba_social» de la referencia se sustituye sin reseñas.
ESTRUCTURA = [
    ("hero", 60, True), ("problema", 90, False), ("villano", 70, False), ("mecanismo", 90, False),
    ("que_incluye", 80, False), ("formato", 30, False), ("prueba_social", 40, False), ("bonos", 70, False),
    ("para_quien", 50, False), ("no_es_para", 40, False), ("comparativa", 60, False), ("garantia", 40, False),
    ("precio", 30, True), ("faq", 150, False), ("cta_final", 40, True),
]
EXTRA = [("autor", 50, False), ("faq", 60, False)]

MERCADOS = f"""\
ZZ: {{idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo, tienda: "{TIENDA}"}}
ZY: {{idioma: ro, moneda: EUR, zona: Europe/Bucharest, banda_eur: [9, 19], estado: activo, tienda: null}}
"""


class Ejecutar:
    """`subprocess.run` falso: registra cada orden y crea el archivo de salida que pediría. ``pdfinfo``
    contesta ``paginas`` (3, las del PDF fijo y de PRODUCTO.md)."""

    def __init__(self, paginas: int = 3):
        self.paginas = paginas
        self.ordenes: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, orden, **kw):
        assert isinstance(orden, list)
        self.ordenes.append(orden)
        self.kwargs.append(kw)
        if orden[0] == "pdfinfo":
            return subprocess.CompletedProcess(orden, 0, f"Pages:          {self.paginas}\n", "")
        if orden[0] == "pdftoppm":
            Path(orden[-1] + ".png").write_bytes(b"\x89PNG falso " + " ".join(orden).encode())
        elif orden[0] == "ffmpeg":
            Path(orden[-1]).write_bytes(b"RIFF webp falso " + " ".join(orden).encode())
        return subprocess.CompletedProcess(orden, 0, "", "")


def cargar(v: Path, pais: str = "ZZ", **kw):
    """``cargar_datos`` con ``pdfinfo`` falso (los unitarios nunca llaman al binario real)."""
    kw.setdefault("correr", Ejecutar())
    return entrada.cargar_datos(v, P, pais, **kw)


@pytest.fixture(autouse=True)
def _home_de_prueba(tmp_path, monkeypatch):
    """Nunca el HOME real: las confirmaciones de pantalla viven en el directorio de configuración de trovefy."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


class _Tty(io.StringIO):
    def __init__(self, fd: int):
        super().__init__()
        self.fd = fd

    def fileno(self):
        return self.fd


def con_terminal(monkeypatch, stdin: bool = True, stdout: bool = True) -> None:
    """stdin/stdout que `trovefy.tienda.confirmacion.hay_terminal` ve como terminal (o no)."""
    import types

    from trovefy.tienda import confirmacion

    monkeypatch.setattr(confirmacion, "sys", types.SimpleNamespace(stdin=_Tty(100), stdout=_Tty(101)))
    monkeypatch.setattr(confirmacion.os, "isatty", lambda fd: {100: stdin, 101: stdout}.get(fd, False))


@pytest.fixture(autouse=True)
def _sin_binarios_reales(monkeypatch):
    """Un unitario que llegue a ``pdfinfo``/``pdftoppm``/``ffmpeg`` reales falla: hay que inyectarlos."""
    real = subprocess.run

    def guardia(orden, *a, **kw):
        if isinstance(orden, (list, tuple)) and orden and orden[0] in ("pdfinfo", "pdftoppm", "ffmpeg"):
            raise AssertionError(f"unitario con {orden[0]} real: inyecta correr/ejecutar")
        return real(orden, *a, **kw)

    monkeypatch.setattr(subprocess, "run", guardia)


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (31, 78, 95)).save(buf, format="PNG")
    return buf.getvalue()


def estructura(n: int) -> list[dict]:
    base = (ESTRUCTURA + EXTRA)[:n] if n > len(ESTRUCTURA) else ESTRUCTURA[:n]
    return [{"orden": i, "tipo": t, "palabras": w, "cta": c} for i, (t, w, c) in enumerate(base, 1)]


def escribir_md(ruta: Path, meta: dict, cuerpo: str = "Ficticio.\n") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    frontmatter.escribir(ruta, meta, cuerpo)


def editar_md(v: Path, nombre: str, cambio) -> None:
    ruta = v / "productos" / P / f"{nombre}.md"
    meta, cuerpo = frontmatter.leer(ruta)
    cambio(meta)
    frontmatter.escribir(ruta, meta, cuerpo)


def vault_demo(tmp_path: Path, estado: str = "producido", secciones: int = 15) -> Path:
    v = tmp_path / "v"
    prod = v / "productos" / P
    (v / "config").mkdir(parents=True)
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    arranque = {"pasos": [
        {"id": "06", "nombre": "Otro paso", "estado": "hecho", "evidencia": [], "datos": {}},
        {"id": "07", "nombre": "Dominio", "estado": "verificado", "evidencia": ["config/evidencia/x.json"],
         "datos": {"dominio": DOMINIO}},
    ]}
    (v / "config" / "arranque.yaml").write_text(yaml.safe_dump(arranque, allow_unicode=True), encoding="utf-8")
    escribir_md(prod / "PRODUCTO.md", {
        "tipo": "producto", "producto": P,
        "paises": {"ZZ": {"estado": estado, "historial": []}, "ZY": {"estado": "modelado", "historial": []}},
        "entregable": {"bg": {"principal": {"version": 1, "pdf": "entregable/demo-bg-v1.pdf", "paginas": 3,
                                            "fecha": "2026-11-16"}}},
    }, "# Producto p-0099-demo\n\nFicticio.\n")
    escribir_md(prod / "OFERTA.md", {
        "tipo": "oferta", "producto": P, "pais": "ZZ", "aprobacion": "aprobada",
        "core": {"promesa_h1": "Спокойно тяло за 14 дни", "garantia_dias": 30,
                 "garantia_como": "Връщане на парите с имейл", "formato": "PDF за четене на телефона",
                 "angulo": "Десет минути вечер вместо хапчета"},
        "estructura_landing": estructura(secciones),
    })
    escribir_md(prod / "ESCALERA.md", {
        "tipo": "escalera", "producto": P,
        "paises": {"ZZ": {"moneda": "EUR", "pasos": {"front": {"precio": "14.90", "activo": True}}},
                   "ZY": {"moneda": "EUR", "pasos": {"front": {"precio": "12.90", "activo": True}}}},
    })
    escribir_md(prod / "BRANDBOOK.md", {
        "tipo": "brandbook", "producto": P, "nombre_local": "Somatix", "idioma": "bg",
        "tipografias": [{"familia": "DejaVu Serif", "uso": "titulos"}, {"familia": "DejaVu Sans", "uso": "texto"}],
        "tokens_css": {"--color-primario": "#1F4E5F", "--color-fondo": "#FAF7F2",
                       "--fuente-titulos": "'DejaVu Serif', serif", "--fuente-texto": "'DejaVu Sans', sans-serif"},
    })
    ent = prod / "entregable"
    ent.mkdir(parents=True)
    shutil.copyfile(PDF_FIJO, ent / "demo-bg-v1.pdf")
    sha = escribir_medio(ent / "medios" / "portada.png", _png(), base=v)
    registrar_medio(ent, "portada", "portada.png", sha, "propio", base=v)
    return v


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Vault demo con TROVEFY_VAULT y HOME en tmp_path (para la CLI), con órdenes externas falsas."""
    from trovefy import landing_cli

    v = vault_demo(tmp_path)
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return v
