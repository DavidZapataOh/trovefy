import hashlib
import os
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
import yaml
from fixtures.pdf.fuente_latina import crear_fuente_latina
from fixtures.pdf.herramientas import falta_weasyprint, faltan, requerir
from trovefy.pdf import render
from trovefy.pdf.render import (
    MARGEN_INFERIOR_MM,
    NO_PDFINFO,
    ORDEN_PANGO,
    Ancla,
    PdfinfoNoMedido,
    PdfNoDisponible,
    desbordes,
    escribir_exclusivo,
    fetcher_local,
    fijas_esperadas,
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


_SIN_WEASY = falta_weasyprint()
_SIN_PDF = faltan("pdfinfo", "fc-match", weasyprint=True)


@pytest.fixture
def _herramientas_pdf():
    requerir(_SIN_PDF)  # con CI definido, falla en vez de saltar (ruling L7)


necesita_pdf = pytest.mark.usefixtures("_herramientas_pdf")


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (60, 90), (31, 78, 95)).save(buf, format="PNG")
    return buf.getvalue()


def _vault(tmp_path: Path, p_id: str, pais: str, idioma: str, slug: str,
           titulo: str = "Respira y duerme") -> Path:
    v = tmp_path / "v"
    shutil.copytree(PRODUCTO, v / "productos" / p_id)
    p = pieza(v, p_id, "principal")
    shutil.copytree(RESPIRA / "fuente", p.raiz / "fuente")
    ficha = Ficha(p_id=p_id, pais=pais, idioma=idioma, slug=slug, unidad_venta="plan de 21 días",
                  promesa="Duerme mejor", avatar="Adulto que duerme mal", exigencia="sanitario", tipo="ebook",
                  piezas=(PiezaFicha("principal", titulo, "ebook", 4),))
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


def _a(pagina: int, y: float = 500.0, limite: float = 1046.0) -> Ancla:
    return Ancla(pagina, y, limite)


def test_desbordes():
    anclas = {"ini-portada": _a(0), "fin-portada": _a(0), "ini-diario": _a(5), "fin-diario": _a(6),
              "ini-mapa": _a(7), "s-01": _a(2)}
    assert desbordes(anclas) == ("diario", "mapa")
    assert desbordes({"ini-a": _a(1), "fin-a": _a(1)}) == ()


def test_desbordes_fin_por_debajo_del_margen():
    """El contenido que se sale por abajo de la página fija (recortado al pintar) deja ``fin-X`` fuera."""
    assert desbordes({"ini-a": _a(0, 75), "fin-a": _a(0, 1046.4, 1046.0)}) == ()
    assert desbordes({"ini-a": _a(0, 75), "fin-a": _a(0, 1097.7, 1046.0)}) == ("a",)


def test_desbordes_falla_cerrado_si_faltan_anclas():
    anclas = {"ini-portada": _a(0), "fin-portada": _a(0), "fin-diario": _a(3)}
    assert desbordes(anclas, ("portada", "diario", "mapa")) == ("diario", "mapa")
    assert desbordes({}, ("portada",)) == ("portada",)


def test_fijas_esperadas():
    html = ('<div class="page portada"><span id="ini-portada"></span><h1>T</h1></div>'
            '<div class="page ficha"><span id="ini-diario"></span><span id="fin-diario"></span></div>'
            '<div class="page ficha"><h2>Sin anclas</h2><span class="push" id="fin-mapa"></span></div>'
            '<section id="s-01"><h2 id="x">a</h2></section>')
    assert fijas_esperadas(html) == ("diario", "mapa", "portada")
    assert fijas_esperadas("<p>nada</p>") == ("portada",)


def test_margen_inferior_es_el_de_base_css():
    from trovefy.pdf.maqueta import BASE_CSS

    css = BASE_CSS.read_text(encoding="utf-8")
    regla = re.search(r"\.page\{([^}]*)\}", css).group(1)
    assert f"padding:{MARGEN_INFERIOR_MM}mm " in regla


def test_orden_pango_lleva_harfbuzz_subset():
    assert "libharfbuzz-subset0" in ORDEN_PANGO.split()


def test_paginas_pdfinfo_lee_pages(tmp_path):
    def correr(args, **kw):
        assert args == ["pdfinfo", str(tmp_path / "a.pdf")]
        return subprocess.CompletedProcess(args, 0, stdout="Title: x\nPages:          7\nEncrypted: no\n")

    assert paginas_pdfinfo(tmp_path / "a.pdf", correr=correr) == 7


def test_paginas_pdfinfo_sin_programa(tmp_path):
    with pytest.raises(PdfinfoNoMedido) as exc:
        paginas_pdfinfo(tmp_path / "a.pdf", correr=_sin("pdfinfo"))
    assert str(exc.value) == NO_PDFINFO


@pytest.mark.parametrize(("codigo", "salida", "error", "detalle"), [
    (1, "", "Syntax Warning: May not be a PDF file", "código 1: Syntax Warning: May not be a PDF file"),
    (0, "Title: x\nEncrypted: no\n", "", "salida sin «Pages:»"),
    (0, "Pages: muchas\n", "", "salida sin «Pages:»"),
])
def test_paginas_pdfinfo_falla(tmp_path, codigo, salida, error, detalle):
    def correr(args, **kw):
        return subprocess.CompletedProcess(args, codigo, stdout=salida, stderr=error)

    with pytest.raises(PdfinfoNoMedido) as exc:
        paginas_pdfinfo(tmp_path / "a.pdf", correr=correr)
    assert str(exc.value) == f"no medido: pdfinfo falló ({detalle})"


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
    requerir(_SIN_WEASY)
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
        renderizar("<p>x</p>", tmp_path, tmp_path / "x.pdf", base=tmp_path)
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


@necesita_pdf
def test_pdfinfo_que_falla_no_es_que_falte(vault_respira):
    def correr(args, **kw):
        if args[0] == "pdfinfo":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="I/O Error: Couldn't open file")
        return subprocess.run(args, **kw)  # noqa: PLW1510 - check lo pasa el llamador

    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, correr=correr, ahora=AHORA)
    assert r.paginas_pdfinfo is None and not r.apto
    assert r.problemas == ("no medido: pdfinfo falló (código 1: I/O Error: Couldn't open file)",)


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


# --- revisión: desbordes dentro de un hijo flex (H1) ------------------------------------------------


def _ficha_yaml(raiz: Path, spec: dict) -> None:
    (raiz / "fuente" / "fichas" / "diario.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True),
                                                             encoding="utf-8")


@necesita_pdf
def test_instrucciones_largas_en_la_ficha_se_detectan(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    instrucciones = " ".join(["Anota cada mañana a qué hora te acostaste y cuánto tardaste."] * 150)
    assert len(instrucciones.split()) >= 1500
    _ficha_yaml(raiz, {"id": "diario", "titulo": "Diario de sueño", "instrucciones": instrucciones,
                       "tipo": "lineas", "filas": 3})
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.pdf is not None and "diario" in r.desbordes and not r.apto


@necesita_pdf
def test_casillas_largas_en_bulgaro_se_detectan(vault_dishai):
    raiz = pieza(vault_dishai, "p-0043-dishai", "principal").raiz
    frase = "Отбележи всеки ден колко минути дишаш бавно преди сън"
    etiquetas = [f"{i}. " + " ".join([frase] * 3) for i in range(1, 26)]
    assert all(28 <= len(e.split()) <= 32 for e in etiquetas)
    _ficha_yaml(raiz, {"id": "diario", "titulo": "Дневник", "instrucciones": "Отбележи всяка сутрин.",
                       "tipo": "casillas", "filas": etiquetas})
    r = producir_pdf(vault_dishai, "p-0043-dishai", "principal", CFG, ahora=AHORA)
    assert r.pdf is not None and "diario" in r.desbordes and not r.apto


@necesita_pdf
def test_titulo_de_portada_largo_se_detecta(tmp_path):
    titulo = " ".join(["Respira despacio y duerme mejor cada noche"] * 22)
    v = _vault(tmp_path, "p-0042-respira", "ZZ", "es", "respira", titulo=titulo)
    r = producir_pdf(v, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.pdf is not None and "portada" in r.desbordes and not r.apto


@necesita_pdf
def test_ancla_que_falta_en_el_html_es_desborde(tmp_path):
    html = ('<html><head><style>@page{size:A4;margin:0}div{break-after:page}</style></head><body>'
            '<div class="page portada"><h1>Sin anclas</h1></div>'
            '<div class="page ficha"><span id="ini-mapa"></span><p>a</p></div></body></html>')
    anclas = renderizar(html, tmp_path, tmp_path / "x.pdf", base=tmp_path)
    assert anclas["ini-mapa"].pagina == 1 and anclas["ini-mapa"].limite > anclas["ini-mapa"].y
    assert desbordes(anclas, fijas_esperadas(html)) == ("mapa", "portada")


# --- 17b: fichas ilustradas -------------------------------------------------------------------------


def _png_grande(ancho: int = 1024, alto: int = 1536) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (ancho, alto), (200, 170, 120)).save(buf, format="PNG")
    return buf.getvalue()


@necesita_pdf
@pytest.mark.parametrize("tamano", [(1024, 1536), (1536, 1024), (60, 90)])
def test_ficha_ilustrada_es_apta(vault_respira, tamano):
    """Una ilustración de 1k (más alta que la página a 96 ppp) cabe en la ficha con su tabla: la CSS la
    acota a ~115 mm sin recortar nada, y las anclas siguen detectando desbordes."""
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    sha = escribir_medio(raiz / "medios" / "f-01.png", _png_grande(*tamano))
    registrar_medio(raiz, "f-01", "f-01.png", sha, "apimart", task_id="t-0002")
    diario = raiz / "fuente" / "fichas" / "diario.yaml"
    diario.write_text(diario.read_text(encoding="utf-8") + "imagen: f-01\n", encoding="utf-8")
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert 'src="medios/f-01.png"' in r.html.read_text(encoding="utf-8")
    assert r.informe.pasa and r.desbordes == () and r.problemas == ()
    assert r.apto


@necesita_pdf
def test_ficha_ilustrada_desbordada_se_detecta(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    sha = escribir_medio(raiz / "medios" / "f-01.png", _png_grande())
    registrar_medio(raiz, "f-01", "f-01.png", sha, "apimart", task_id="t-0002")
    diario = raiz / "fuente" / "fichas" / "diario.yaml"
    texto = diario.read_text(encoding="utf-8").replace("filas: 7", "filas: 17")
    diario.write_text(texto + "imagen: f-01\n", encoding="utf-8")
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.pdf is not None and "diario" in r.desbordes and not r.apto


# --- revisión: escrituras sin seguir enlaces (M3) ---------------------------------------------------


def _archivos(carpeta: Path) -> dict[str, bytes]:
    return {p.relative_to(carpeta).as_posix(): p.read_bytes() for p in sorted(carpeta.rglob("*")) if p.is_file()}


def test_carpeta_de_bonos_enlazada_no_escribe_fuera(tmp_path):
    v = _vault(tmp_path, "p-0042-respira", "ZZ", "es", "respira")
    raiz = pieza(v, "p-0042-respira", "principal").raiz
    fuera = tmp_path / "fuera"
    shutil.copytree(RESPIRA / "fuente", fuera / "bono-1" / "fuente")
    (raiz / "bonos").symlink_to(fuera, target_is_directory=True)
    meta, cuerpo = frontmatter.leer(raiz / "FICHA.md")
    meta["piezas"].append({"id": "bono-1", "titulo": "Bono", "tipo": "bono", "paginas_objetivo": 4})
    frontmatter.escribir(raiz / "FICHA.md", meta, cuerpo)
    antes = _archivos(fuera)
    with pytest.raises(ValueError, match="enlace simbólico"):
        producir_pdf(v, "p-0042-respira", "bono-1", CFG, ahora=AHORA)
    assert _archivos(fuera) == antes


def test_renderizar_no_escribe_por_un_enlace(tmp_path):
    requerir(_SIN_WEASY)
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "entregable").symlink_to(fuera, target_is_directory=True)
    with pytest.raises(ValueError, match="enlace simbólico"):
        renderizar("<p>x</p>", tmp_path / "v" / "entregable", tmp_path / "v" / "entregable" / "x.pdf",
                   base=tmp_path / "v")
    assert list(fuera.iterdir()) == []


def test_escribir_exclusivo(tmp_path):
    destino = tmp_path / "a" / "b.html"
    escribir_exclusivo(destino, b"uno", base=tmp_path)
    assert destino.read_bytes() == b"uno" and stat.S_IMODE(destino.stat().st_mode) == 0o640
    with pytest.raises(FileExistsError):
        escribir_exclusivo(destino, b"dos", base=tmp_path)
    assert destino.read_bytes() == b"uno"
    assert sorted(p.name for p in destino.parent.iterdir()) == ["b.html"]  # sin temporales


def test_escribir_exclusivo_no_sigue_un_enlace_final(tmp_path):
    fuera = tmp_path / "fuera.html"
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "b.html").symlink_to(fuera)
    with pytest.raises(FileExistsError):
        escribir_exclusivo(tmp_path / "v" / "b.html", b"x", base=tmp_path / "v")
    assert not fuera.exists()


# --- revisión: versión reservada de forma atómica (M4) ----------------------------------------------


@necesita_pdf
def test_dos_ejecuciones_a_la_vez_dan_versiones_distintas(vault_respira, monkeypatch):
    """Las dos eligen la versión a la vez (barrera tras ``siguiente_version``): la reserva con
    ``O_EXCL`` hace que una se quede la v1 y la otra pase a la v2."""
    import threading

    barrera = threading.Barrier(2, timeout=30)
    original = render.siguiente_version
    primeras = threading.local()

    def a_la_vez(*a, **k):
        n = original(*a, **k)
        if not getattr(primeras, "hecha", False):  # solo la primera elección de cada hilo espera a la otra
            primeras.hecha = True
            barrera.wait()
        return n

    monkeypatch.setattr(render, "siguiente_version", a_la_vez)
    resultados, errores = [], []

    def correr():
        try:
            resultados.append(producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA))
        except Exception as exc:  # noqa: BLE001 - se comprueba abajo
            errores.append(exc)

    hilos = [threading.Thread(target=correr) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(120)
    assert errores == []
    assert sorted(r.version for r in resultados) == [1, 2]
    assert sorted(r.pdf.name for r in resultados) == ["respira-es-v1.pdf", "respira-es-v2.pdf"]
    assert all(r.apto for r in resultados)
    for r in resultados:
        assert r.html.name == r.pdf.name.replace(".pdf", ".html")


# --- revisión: PdfNoDisponible deja rastro en el log (L4) -------------------------------------------


def test_pdf_no_disponible_tras_el_html_queda_en_el_log(vault_respira, monkeypatch):
    def sin_weasy():
        raise PdfNoDisponible("WeasyPrint no carga")

    monkeypatch.setattr(render, "_weasyprint", sin_weasy)
    monkeypatch.setattr(render, "comprobar_fuentes", lambda *a, **k: [])
    with pytest.raises(PdfNoDisponible):
        producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    assert (raiz / "fuente" / "respira-es-v1.html").is_file()
    log = (vault_respira / "log.md").read_text(encoding="utf-8")
    assert "v1: sin PDF (WeasyPrint no disponible)" in log and "respira-es-v1.html" in log


# --- revisión: el fetcher abre sin seguir enlaces (L5) ----------------------------------------------


def test_fetcher_no_sigue_un_enlace_que_aparece_tras_comprobar(tmp_path, monkeypatch):
    """Si el último componente pasa a ser un enlace entre ``realpath`` y la lectura, ``O_NOFOLLOW`` lo para."""
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"secreto")
    raiz = tmp_path / "raiz"
    (raiz / "medios").mkdir(parents=True)
    (raiz / "medios" / "a.png").symlink_to(fuera)
    f = fetcher_local(raiz)
    monkeypatch.setattr(render.os.path, "realpath", lambda p: str(p))  # la comprobación ya «pasó»
    with pytest.raises(ValueError, match="enlace|regular"):
        f(f"file://{raiz}/medios/a.png")


def test_fetcher_rechaza_lo_que_no_es_archivo_regular(tmp_path):
    raiz = tmp_path / "raiz"
    (raiz / "medios").mkdir(parents=True)
    os.mkfifo(raiz / "medios" / "a.png")
    with pytest.raises(ValueError):
        fetcher_local(raiz)(f"file://{raiz}/medios/a.png")
    with pytest.raises(ValueError):
        fetcher_local(raiz)(f"file://{raiz}/medios")


# --- revisión: fragmento con una etiqueta truncada al final (M1, de punta a punta) ------------------


@pytest.mark.parametrize("cola", ["\n<style", '\n<link rel="stylesheet" href="medios/x.css" x="',
                                  '\n<img src="medios/portada.png" alt="', '\n<script src="http://e/x'])
def test_seccion_truncada_no_llega_al_pdf(vault_respira, cola):
    from trovefy.pdf.maqueta import FragmentoInvalido

    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    s = raiz / "fuente" / "secciones" / "03-plan-21-dias.html"
    s.write_text(s.read_text(encoding="utf-8").rstrip() + cola, encoding="utf-8")
    with pytest.raises(FragmentoInvalido, match="03-plan-21-dias.html.*sin cerrar"):
        producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert list((raiz / "fuente").glob("*-v*.html")) == [] and list(raiz.glob("*.pdf")) == []


# --- revisión del primer producto: secciones en flujo, fichas que llenan la página y su número -----

_MM = 96 / 25.4


def _documento(html: str, raiz: Path):
    import weasyprint

    return weasyprint.HTML(string=html, base_url=str(raiz) + os.sep, url_fetcher=fetcher_local(raiz)).render()


def _cajas(caja):
    yield caja
    for hija in getattr(caja, "children", None) or []:
        yield from _cajas(hija)


def _caja_de_clase(pagina, clase: str):
    """Primera caja (no anónima) de la página con ``clase``."""
    for caja in _cajas(pagina._page_box):
        elemento = getattr(caja, "element", None)
        if (elemento is not None and not caja.element_tag.startswith("::")
                and clase in (elemento.get("class") or "").split()):
            return caja
    return None


def _texto_caja(caja) -> str:
    return "".join(c.text for c in _cajas(caja) if hasattr(c, "text"))


_VERBOS = ("respira", "cuenta", "suelta", "nota", "afloja", "escucha", "apoya", "baja", "estira", "repite",
           "mira", "piensa", "deja", "lleva", "vuelve", "toca", "siente")
_COSAS = ("la nariz", "los hombros", "la tripa", "las manos", "la espalda", "los pies", "la mandíbula",
          "el cuello", "la frente", "los brazos", "las piernas", "el pecho", "la lengua", "los ojos",
          "las rodillas", "la cadera", "la nuca")


def _parrafos(n: int, palabra: str) -> str:
    """``n`` párrafos distintos (sin repetir ninguno) de ~60 palabras."""
    salida = []
    for k in range(n):
        v, c = _VERBOS[k % len(_VERBOS)], _COSAS[(k * 5) % len(_COSAS)]
        salida.append(f"<p>{palabra}, paso {k + 1}: {v} despacio pensando en {c} y cuenta {k + 4} tiempos "
                      f"antes de seguir. Durante la noche {k + 2} conviene que {c} quede suelta mientras "
                      f"{v} sin prisa, con la luz baja y el teléfono lejos de la cama. Si aparece una idea, "
                      f"apúntala en el papel número {k + 7} y vuelve a {c}; así el cuerpo aprende el ritmo "
                      f"de la semana {k % 3 + 1} sin esfuerzo.</p>")
    return "\n".join(salida)


def _secciones_largas(raiz: Path) -> None:
    """Tres secciones de ~1,2 páginas, cada una con su ejercicio y su recordatorio al final."""
    carpeta = raiz / "fuente" / "secciones"
    for f in carpeta.glob("*.html"):
        f.unlink()
    for i, nombre in enumerate(("uno", "dos", "tres"), 1):
        bloques = [_parrafos(2, f"{nombre.capitalize()} {j}") for j in range(3)]
        (carpeta / f"0{i}-{nombre}.html").write_text(
            f"<h2>Apartado {nombre}</h2>\n"
            f'<div class="lograr"><p>Al terminar el apartado {nombre} sabrás respirar más lento.</p></div>\n'
            + "".join(f"<h3>Parte {j + 1} de {nombre}</h3>\n{b}\n" for j, b in enumerate(bloques))
            + f'<div class="ejercicio"><p>Ejercicio {nombre}: tres minutos de respiración lenta.</p></div>\n'
            f'<div class="recordar" id="r-0{i}"><p>Recuerda {nombre}: la salida más larga.</p></div>\n',
            encoding="utf-8")


@necesita_pdf
def test_secciones_fluyen_sin_paginas_casi_vacias(vault_respira, tmp_path):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    _secciones_largas(raiz)
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.apto
    paginas = _documento(r.html.read_text(encoding="utf-8"), raiz).pages
    anclas: dict[str, int] = {}
    for i, p in enumerate(paginas):
        for n in p.anchors:
            anclas.setdefault(n, i)
    # Cada sección ocupa ~1,2 páginas: la siguiente empieza en la página donde acaban sus cajas, nunca
    # en una nueva (con un salto forzado, la página de las cajas quedaba casi vacía).
    for anterior, siguiente in (("r-01", "s-02"), ("r-02", "s-03")):
        assert anclas[siguiente] == anclas[anterior], (anterior, siguiente, sorted(anclas.items(), key=lambda x: x[1]), len(paginas))
    # el índice y el aviso no se quedan solos: el primer apartado empieza en su misma página
    assert anclas["s-01"] == 1
    # portada + 3 secciones de ~1,2 páginas en flujo (≤ 5 págs. de texto) + ficha + fuentes
    assert r.paginas <= 1 + 5 + 1 + 1, r.paginas


@necesita_pdf
def test_ficha_ilustrada_de_casillas_con_notas_llena_la_pagina(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    sha = escribir_medio(raiz / "medios" / "f-01.png", _png_grande(1024, 1536))
    registrar_medio(raiz, "f-01", "f-01.png", sha, "apimart", task_id="t-0002")
    _ficha_yaml(raiz, {"id": "diario", "titulo": "Dishai 4-6", "imagen": "f-01", "tipo": "casillas",
                       "instrucciones": "Marca cada paso mientras lo haces. Te llevará unos cinco minutos.",
                       "filas": [f"Paso {i}: siéntate cómodo y respira despacio por la nariz." for i in range(5)],
                       "notas": "Mis notas"})
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.apto and r.desbordes == ()
    html = r.html.read_text(encoding="utf-8")
    assert '<p class="notas-titulo">Mis notas</p>' in html
    pagina = next(p for p in _documento(html, raiz).pages if "ini-diario" in p.anchors)
    img = next(c for c in _cajas(pagina._page_box) if getattr(c, "element_tag", "") == "img")
    assert img.height >= 100 * _MM  # la ilustración ya no es un sello de 70 mm
    notas = _caja_de_clase(pagina, "notas")
    assert notas is not None and "Mis notas" in _texto_caja(notas)
    abajo = notas.position_y + notas.margin_height()
    assert abajo >= pagina.anchors["fin-diario"][1] - 1  # llega hasta el pie de la ficha
    assert notas.margin_height() >= 15 * _MM


@necesita_pdf
@pytest.mark.parametrize(("filas", "alto_min_mm"), [(7, 150), (11, 150), (17, 150)])
def test_tablas_de_ficha_llenan_y_caben(vault_respira, filas, alto_min_mm):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    diario = raiz / "fuente" / "fichas" / "diario.yaml"
    diario.write_text(diario.read_text(encoding="utf-8").replace("filas: 7", f"filas: {filas}"), encoding="utf-8")
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.apto and r.desbordes == ()
    pagina = next(p for p in _documento(r.html.read_text(encoding="utf-8"), raiz).pages
                  if "ini-diario" in p.anchors)
    tabla = next(c for c in _cajas(pagina._page_box) if getattr(c, "element_tag", "") == "table")
    assert tabla.margin_height() >= alto_min_mm * _MM, tabla.margin_height() / _MM


@necesita_pdf
def test_fichas_llevan_numero_de_pagina(vault_respira):
    raiz = pieza(vault_respira, "p-0042-respira", "principal").raiz
    r = producir_pdf(vault_respira, "p-0042-respira", "principal", CFG, ahora=AHORA)
    assert r.apto
    paginas = _documento(r.html.read_text(encoding="utf-8"), raiz).pages
    i = next(i for i, p in enumerate(paginas) if "ini-diario" in p.anchors)
    pies = [c for c in _cajas(paginas[i]._page_box) if getattr(c, "at_keyword", None) == "@bottom-center"]
    assert [_texto_caja(c).strip() for c in pies] == [str(i + 1)]
    # y la página de texto anterior lleva el suyo con el mismo estilo
    pies_texto = [c for c in _cajas(paginas[i - 1]._page_box) if getattr(c, "at_keyword", None) == "@bottom-center"]
    assert [_texto_caja(c).strip() for c in pies_texto] == [str(i)]
