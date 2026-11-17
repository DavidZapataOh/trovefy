import hashlib
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fixtures.pdf.fuente_latina import crear_fuente_latina
from trovefy.pdf.render import (
    PdfNoDisponible,
    desbordes,
    fetcher_local,
    nombre_pdf,
    paginas_pdfinfo,
    producir_pdf,
    renderizar,
    siguiente_version,
)
from trovefy.producto.config import ConfigProducto
from trovefy.producto.ficha import Ficha, PiezaFicha
from trovefy.producto.medios import escribir_medio, registrar_medio
from trovefy.producto.rutas import pieza
from trovefy.vault import frontmatter

TESTS = Path(__file__).resolve().parents[2]
RESPIRA = TESTS / "fixtures" / "pdf" / "respira"
PRODUCTO = TESTS / "fixtures" / "producto" / "p-0042-respira"
AHORA = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
CFG = ConfigProducto(
    tope_usd=Decimal("2.00"), modelos_imagen=("gpt-image-2",), resolucion="1k", palabras_por_pagina=350,
    paginas_min={"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}, seccion_palabras_min=60,
    puntuacion_min=85,
)


def _hay_weasyprint() -> str | None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:
        return f"WeasyPrint no disponible ({exc}): sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0"
    return None


_SIN_WEASY = _hay_weasyprint()
necesita_pdf = pytest.mark.skipif(_SIN_WEASY is not None or shutil.which("pdfinfo") is None
                                  or shutil.which("fc-match") is None,
                                  reason=_SIN_WEASY or "falta pdfinfo o fc-match (poppler-utils, fontconfig)")


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (60, 90), (31, 78, 95)).save(buf, format="PNG")
    return buf.getvalue()


def _vault(tmp_path: Path, p_id: str, pais: str, idioma: str, slug: str) -> Path:
    v = tmp_path / "v"
    shutil.copytree(PRODUCTO, v / "productos" / p_id)
    p = pieza(v, p_id, "principal")
    shutil.copytree(RESPIRA / "fuente", p.raiz / "fuente")
    ficha = Ficha(p_id=p_id, pais=pais, idioma=idioma, slug=slug, unidad_venta="plan de 21 días",
                  promesa="Duerme mejor", avatar="Adulto que duerme mal", exigencia="sanitario", tipo="ebook",
                  piezas=(PiezaFicha("principal", "Respira y duerme", "ebook", 4),))
    meta = {"tipo_documento": "ficha", "fecha": "2026-11-16", **asdict(ficha)}
    meta["piezas"] = [asdict(x) for x in ficha.piezas]
    frontmatter.escribir(p.raiz / "FICHA.md", meta, "# Ficha\n")
    datos = _png()
    sha = escribir_medio(p.raiz / "medios" / "portada.png", datos)
    registrar_medio(p.raiz, "portada", "portada.png", sha, "apimart", task_id="t-0001")
    return v


@pytest.fixture
def vault_respira(tmp_path):
    return _vault(tmp_path, "p-0042-respira", "ZZ", "es", "respira")


@pytest.fixture
def vault_dishai(tmp_path):
    v = _vault(tmp_path, "p-0043-dishai", "ZY", "bg", "dishai")
    s = pieza(v, "p-0043-dishai", "principal").raiz / "fuente" / "secciones" / "01-por-que-te-cuesta.html"
    s.write_text(s.read_text(encoding="utf-8").replace("Por qué te cuesta dormir", "Дишай спокойно"),
                 encoding="utf-8")
    return v


def _pdfinfo_texto(pdf: Path) -> str:
    return subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout


def _sin(programa: str):
    """``correr`` real salvo ``programa``, que no está instalado."""

    def correr(args, **kw):
        if args[0] == programa:
            raise FileNotFoundError(programa)
        return subprocess.run(args, **kw)  # noqa: PLW1510 - check lo pasa el llamador

    return correr


# --- funciones puras --------------------------------------------------------------------------------


def test_siguiente_version(tmp_path):
    assert siguiente_version(tmp_path, "respira", "es") == 1
    (tmp_path / "respira-es-v1.pdf").write_bytes(b"x")
    (tmp_path / "respira-es-v3.pdf").write_bytes(b"x")
    (tmp_path / "respira-bono-1-es-v9.pdf").write_bytes(b"x")
    (tmp_path / "respira-es-vx.pdf").write_bytes(b"x")
    assert siguiente_version(tmp_path, "respira", "es") == 4
    (tmp_path / "fuente").mkdir()
    (tmp_path / "fuente" / "respira-es-v7.html").write_text("x")
    assert siguiente_version(tmp_path, "respira", "es") == 8
    assert siguiente_version(tmp_path, "respira-bono-1", "es") == 10


def test_nombre_pdf():
    ficha = Ficha(p_id="p-0042-respira", pais="ZZ", idioma="es", slug="respira", unidad_venta="u", promesa="p",
                  avatar="a", exigencia="normal", tipo="ebook", piezas=())
    assert nombre_pdf(ficha, "principal", 1) == "respira-es-v1.pdf"
    assert nombre_pdf(ficha, "bono-1", 1) == "respira-bono-1-es-v1.pdf"
    assert nombre_pdf(ficha, "u1", 2) == "respira-u1-es-v2.pdf"
    with pytest.raises(ValueError):
        nombre_pdf(ficha, "../x", 1)
    with pytest.raises(ValueError):
        nombre_pdf(ficha, "principal", 0)


def test_desbordes():
    anclas = {"ini-portada": 0, "fin-portada": 0, "ini-diario": 5, "fin-diario": 6, "ini-mapa": 7, "s-01": 2}
    assert desbordes(anclas) == ("diario", "mapa")
    assert desbordes({"ini-a": 1, "fin-a": 1}) == ()


def test_paginas_pdfinfo_lee_pages(tmp_path):
    def correr(args, **kw):
        assert args == ["pdfinfo", str(tmp_path / "a.pdf")]
        return subprocess.CompletedProcess(args, 0, stdout="Title: x\nPages:          7\nEncrypted: no\n")

    assert paginas_pdfinfo(tmp_path / "a.pdf", correr=correr) == 7


def test_paginas_pdfinfo_sin_programa(tmp_path):
    assert paginas_pdfinfo(tmp_path / "a.pdf", correr=_sin("pdfinfo")) is None


def test_recurso_remoto_no_se_carga(tmp_path, monkeypatch):
    def red(*a, **k):
        raise AssertionError("nada sale a la red")

    monkeypatch.setattr("urllib.request.urlopen", red)
    monkeypatch.setattr("socket.create_connection", red)
    f = fetcher_local(tmp_path)
    for url in ("https://x/a.png", "http://x/a.png", "//x/a.png", "data:image/png;base64,AAAA",
                "ftp://x/a.png", f"file://{tmp_path.parent}/fuera.png", f"file://{tmp_path}/../fuera.png"):
        with pytest.raises(ValueError):
            f(url)


def test_fetcher_sirve_archivos_de_la_pieza(tmp_path):
    if _SIN_WEASY:
        pytest.skip(_SIN_WEASY)
    (tmp_path / "medios").mkdir()
    (tmp_path / "medios" / "a.png").write_bytes(b"png")
    r = fetcher_local(tmp_path)(f"file://{tmp_path}/medios/a.png")
    assert r.read() == b"png"
    r.close()


def test_fetcher_no_sigue_enlaces_fuera(tmp_path):
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "enlace.png").symlink_to(fuera)
    with pytest.raises(ValueError):
        fetcher_local(raiz)(f"file://{raiz}/enlace.png")


def test_sin_weasyprint_mensaje_guiado(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(PdfNoDisponible) as exc:
        renderizar("<p>x</p>", tmp_path, tmp_path / "x.pdf")
    assert "libpango" in str(exc.value) and "paso 00" in str(exc.value)
    assert not (tmp_path / "x.pdf").exists()


# --- PDF real ---------------------------------------------------------------------------------------


@necesita_pdf
def test_pdf_a4_y_paginas(vault_respira):
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.informe.pasa and r.problemas == () and r.desbordes == ()
    assert r.apto and r.pdf.name == "respira-es-v1.pdf" and r.paginas == r.paginas_pdfinfo
    assert r.version == 1 and r.html.name == "respira-es-v1.html" and r.html.parent.name == "fuente"
    assert stat.S_IMODE(r.pdf.stat().st_mode) == 0o640
    assert re.search(r"^Page size:\s+595\.276 x 841\.89 pts \(A4\)$", _pdfinfo_texto(r.pdf), re.MULTILINE)
    log = (vault_respira / "log.md").read_text(encoding="utf-8")
    assert "respira-es-v1.pdf" in log and "producto" in log


@necesita_pdf
def test_version_no_sobrescribe(vault_respira):
    r1 = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    sha1 = hashlib.sha256(r1.pdf.read_bytes()).hexdigest()
    r2 = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r2.version == 2 and r2.pdf.name == "respira-es-v2.pdf"
    assert hashlib.sha256(r1.pdf.read_bytes()).hexdigest() == sha1


def test_sin_gates_no_hay_pdf(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    s = raiz / "fuente" / "secciones" / "02-respiracion-lenta.html"
    s.write_text(s.read_text(encoding="utf-8").replace("No hace falta más.", "TODO: ampliar."), encoding="utf-8")
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.pdf is None and not r.apto and not r.informe.pasa
    assert "QG-01" in {h.gate for h in r.informe.hallazgos}
    assert r.html.is_file()
    assert list(raiz.glob("*.pdf")) == []


@necesita_pdf
def test_pagina_fija_desbordada_se_detecta(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    diario = raiz / "fuente" / "fichas" / "diario.yaml"
    diario.write_text(diario.read_text(encoding="utf-8").replace("filas: 7", "filas: 80"), encoding="utf-8")
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.desbordes == ("diario",) and not r.apto
    assert r.pdf is not None


@necesita_pdf
def test_sin_pdfinfo_no_medido(vault_respira):
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, correr=_sin("pdfinfo"), ahora=AHORA)
    assert r.paginas_pdfinfo is None and not r.apto
    assert "no medido: falta pdfinfo (sudo apt install -y poppler-utils)" in r.problemas


def test_bulgaro_sin_glifos_no_renderiza(vault_dishai, tmp_path):
    latina = crear_fuente_latina(tmp_path / "latin-only.ttf")

    def correr(args, **kw):
        if args[0] == "fc-match":
            return subprocess.CompletedProcess(args, 0, stdout=f"{args[-1]}\n{latina}", stderr="")
        raise AssertionError(f"no debe llegar a {args[0]}")

    r = producir_pdf(vault_dishai, "p-0043-dishai", "principal", CFG, correr=correr, ahora=AHORA)
    assert r.informe.pasa
    assert r.pdf is None and not r.apto
    assert any("Д" in p and "no tiene" in p for p in r.problemas)
    assert list(pieza(vault_dishai, "p-0043-dishai", "principal").raiz.glob("*.pdf")) == []


def test_pieza_que_no_esta_en_la_ficha(vault_respira):
    with pytest.raises(ValueError, match="bono-3"):
        producir_pdf(vault_respira, "p-0042-respira", "bono-3", CFG, ahora=AHORA)
