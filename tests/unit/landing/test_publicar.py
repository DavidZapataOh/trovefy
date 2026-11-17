"""Tarea 9 del plan 18: publicar con relectura, QA publicada, `PRODUCTO.md` y estado (sin navegador)."""

import json
import urllib.error
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy import cli
from trovefy.landing.entrada import EstadoNoPermite, ruta_landing
from trovefy.landing.hosting import CAPACIDADES_FASE0, Hosting, empaquetar_en_linea
from trovefy.landing.nativo import registrar_veredicto
from trovefy.landing.plantilla import leer_landing_yaml
from trovefy.landing.publicar import (
    HtmlRecortado,
    NoPublicable,
    listo_para_publicar,
    publicar,
    publicar_impultienda,
    registrar_publicacion,
    verificar_cloudflare,
)
from trovefy.landing.qa import ResultadoQA
from trovefy.mapa import cargar as cargar_mapa
from trovefy.tienda.conductor import FirmaNoCasa
from trovefy.vault import frontmatter

from .conftest import DOMINIO, P, cargar, editar_md
from .test_hosting import TiendaFalsa, abridor
from .test_hosting import montar as montar_landing

AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
TODO_SI = replace(CAPACIDADES_FASE0, html_propio=True, script=True, estilos=True, titulo_propio=True,
                  sin_marco=True, dominio_propio=True, tienda="https://tienda.demo.test", fecha="2026-11-17",
                  fuente="prueba")
URL = f"https://{DOMINIO}/"
VERDE = ResultadoQA(True, (("LCP (movil, 4G simulado)", "OK", "mediana 1.200 ms"),))
LCP_ALTO = ResultadoQA(False, (("LCP (movil, 4G simulado)", "FALLA", "mediana 3.100 ms; máximo 2.500 ms"),))


def version(v: Path) -> str:
    return leer_landing_yaml(v, P, "ZZ")["version"]


def escribir_qa(v: Path, ok: bool = True, ver: str | None = None, url: str | None = None) -> Path:
    ver = ver or version(v)
    ruta = ruta_landing(v, P, "ZZ") / "QA.md"
    frontmatter.escribir(ruta, {
        "tipo": "qa_landing", "pais": "ZZ", "version": ver, "ok": ok, "fecha": AHORA.isoformat(), "url": url,
        "movil_390": {"http": 200, "captura": f"landing/ZZ/qa/movil-{ver}.png"},
        "utm_checkout": {"ok": True, "destino": "https://x.test/checkout?utm_source=fb", "captura": None,
                         "interceptado": True},
    }, "# QA\n")
    return ruta


def nativo_ok(v: Path) -> None:
    registrar_veredicto(v, P, "ZZ", "ok", "Se lee como búlgaro natural.\n\nVEREDICTO: ok\n", AHORA)


def evidencia(v: Path, c=TODO_SI) -> None:
    ruta = v / "config" / "evidencia" / f"p05-impultienda-{c.fecha}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(c.__dict__), encoding="utf-8")


def lista(tmp_path, hosting="impultienda") -> Path:
    """Landing guardada, QA local verde de su versión, nativo ok y la sonda con todo sí."""
    v = montar_landing(tmp_path, hosting)
    escribir_qa(v)
    nativo_ok(v)
    evidencia(v)
    return v


def producto(v: Path) -> tuple[dict, str]:
    return frontmatter.leer(v / "productos" / P / "PRODUCTO.md")


class QAFalsa:
    def __init__(self, r=VERDE):
        self.r, self.urls = r, []

    def __call__(self, v, d, url):
        self.urls.append(url)
        escribir_qa(v, ok=self.r.ok, url=url)
        return self.r


# --- listo_para_publicar ------------------------------------------------------------------------


def test_listo_cuando_todo_esta(tmp_path):
    v = lista(tmp_path)
    assert listo_para_publicar(v, cargar(v)) == []


def test_no_publica_sin_qa_local(tmp_path):
    v = lista(tmp_path)
    (ruta_landing(v, P, "ZZ") / "QA.md").unlink()
    motivos = listo_para_publicar(v, cargar(v))
    assert any("trovefy landing qa" in m for m in motivos), motivos


def test_no_publica_qa_en_rojo(tmp_path):
    v = lista(tmp_path)
    escribir_qa(v, ok=False)
    assert any("QA" in m and "verde" in m for m in listo_para_publicar(v, cargar(v)))


def test_no_publica_sin_nativo_aprobado(tmp_path):
    v = lista(tmp_path)
    registrar_veredicto(v, P, "ZZ", "corregir", "- «пари» suena raro aquí\n\nVEREDICTO: corregir\n", AHORA)
    assert any("nativo" in m for m in listo_para_publicar(v, cargar(v)))
    (ruta_landing(v, P, "ZZ") / "nativo.md").unlink()
    assert any("nativo" in m for m in listo_para_publicar(v, cargar(v)))


def test_no_publica_qa_de_otra_version(tmp_path):
    v = lista(tmp_path)
    escribir_qa(v, ver="000000000000")
    motivos = listo_para_publicar(v, cargar(v))
    assert any("otra versión" in m and "000000000000" in m for m in motivos), motivos


def test_no_publica_nativo_de_otra_version(tmp_path):
    v = lista(tmp_path)
    ruta = ruta_landing(v, P, "ZZ") / "nativo.md"
    meta, cuerpo = frontmatter.leer(ruta)
    frontmatter.escribir(ruta, {**meta, "version": "000000000000"}, cuerpo)
    assert any("nativo" in m and "otra versión" in m for m in listo_para_publicar(v, cargar(v)))


def test_no_publica_con_fallos_de_validar(tmp_path):
    v = lista(tmp_path)
    (ruta_landing(v, P, "ZZ") / "assets" / "utm.js").write_text("// otro", encoding="utf-8")
    assert any(m.startswith("validar") for m in listo_para_publicar(v, cargar(v)))


def test_cloudflare_sin_pixel_no_publica(tmp_path):
    v = lista(tmp_path, hosting="cloudflare")
    motivos = listo_para_publicar(v, cargar(v))
    assert any("TRACKING.md" in m for m in motivos), motivos


# --- registrar_publicacion ----------------------------------------------------------------------


def test_registrar_avanza_producido_a_con_landing(tmp_path):
    v = lista(tmp_path)
    ver = version(v)
    meta0, cuerpo0 = producto(v)
    estado = registrar_publicacion(v, cargar(v), URL, Hosting("impultienda", "x"), ver, VERDE, AHORA)
    assert estado == "con_landing"
    meta, cuerpo = producto(v)
    zz = meta["paises"]["ZZ"]
    assert zz["estado"] == "con_landing" and zz["historial"][-1]["de"] == "producido"
    assert zz["landing"]["url"] == URL and zz["landing"]["hosting"] == "impultienda"
    assert zz["landing"]["version"] == ver and zz["landing"]["fecha"] == "2026-11-17"
    qa = zz["landing"]["qa"]
    assert qa["archivo"] == "landing/ZZ/QA.md" and qa["version"] == ver
    assert qa["movil_390"] == {"http": 200, "captura": f"landing/ZZ/qa/movil-{ver}.png"}
    assert qa["utm_checkout"]["interceptado"] is True and qa["utm_checkout"]["fuente"] == "landing/ZZ/QA.md"
    assert meta["paises"]["ZY"] == meta0["paises"]["ZY"]  # el resto de países, intacto
    assert meta["entregable"] == meta0["entregable"]
    assert cuerpo.startswith(cuerpo0.rstrip("\n"))  # el cuerpo previo, intacto
    assert f"- Landing ZZ v{ver}: {URL} (2026-11-17, impultienda)" in cuerpo
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly["url"] == URL and ly["publicada"] == "2026-11-17" and ly["hosting"] == "impultienda"
    assert "con_landing" in (v / "log.md").read_text(encoding="utf-8")


def test_registrar_no_toca_estado_avanzado(tmp_path):
    v = lista(tmp_path)
    d = cargar(v)
    editar_md(v, "PRODUCTO", lambda m: m["paises"]["ZZ"].update(
        estado="con_checkout", landing={"url": "https://vieja.test/", "qa": "landing/ZZ/QA.md"}))
    estado = registrar_publicacion(v, d, URL, Hosting("impultienda", "x"), version(v), VERDE, AHORA)
    assert estado == "con_checkout"
    zz = producto(v)[0]["paises"]["ZZ"]
    assert zz["estado"] == "con_checkout" and zz["landing"]["url"] == URL
    assert isinstance(zz["landing"]["qa"], dict)  # la forma vieja (una ruta) pasa al diccionario (resolución 3)


def test_registrar_estado_modelado_falla(tmp_path):
    v = lista(tmp_path)
    d = cargar(v)
    editar_md(v, "PRODUCTO", lambda m: m["paises"]["ZZ"].update(estado="modelado"))
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(EstadoNoPermite):
        registrar_publicacion(v, d, URL, Hosting("impultienda", "x"), version(v), VERDE, AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


def test_registrar_con_qa_en_rojo_no_escribe(tmp_path):
    v = lista(tmp_path)
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable):
        registrar_publicacion(v, cargar(v), URL, Hosting("impultienda", "x"), version(v), LCP_ALTO, AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


# --- verificar_cloudflare -----------------------------------------------------------------------


class _Resp:
    def __init__(self, cuerpo: bytes, final: str):
        self.cuerpo, self.final = cuerpo, final

    def read(self, n=-1):
        return self.cuerpo if n < 0 else self.cuerpo[:n]

    def geturl(self):
        return self.final

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def _abrir(cuerpo: bytes, final: str | None = None, error: Exception | None = None):
    def abrir(url, timeout=None):
        if error is not None:
            raise error
        return _Resp(cuerpo, final or url)
    return abrir


def test_verificar_cloudflare_version(tmp_path):
    v = montar_landing(tmp_path, "cloudflare")
    raiz = ruta_landing(v, P, "ZZ")
    ver = version(v)
    html = (raiz / "index.html").read_bytes()
    url = f"https://zz.{DOMINIO}/"
    assert verificar_cloudflare(url, raiz, abrir=_abrir(html)) is True
    otra = html.replace(ver.encode(), b"0123456789ab")
    assert verificar_cloudflare(url, raiz, abrir=_abrir(otra)) is False
    assert verificar_cloudflare(url, raiz, abrir=_abrir(html, final="https://otro.test/")) is False
    redir = urllib.error.HTTPError(url, 302, "Found", {"Location": "https://otro.test/"}, None)
    assert verificar_cloudflare(url, raiz, abrir=_abrir(html, error=redir)) is False
    assert verificar_cloudflare(f"http://zz.{DOMINIO}/", raiz, abrir=_abrir(html)) is False
    grande = html + b" " * (5 * 1024 * 1024)
    assert verificar_cloudflare(url, raiz, abrir=_abrir(grande)) is False


# --- publicar_impultienda con páginas falsas ----------------------------------------------------


def _mapa_confirmado() -> dict:
    from trovefy.landing.panel import MAPA_IMPULTIENDA

    m = cargar_mapa(MAPA_IMPULTIENDA)
    m["pantallas"]["diseno_contenido"]["capturado"] = "2026-11-17"
    return m


def _publicar_imp(v, t, c=TODO_SI):
    return publicar_impultienda(v, cargar(v), c, mapa=_mapa_confirmado(), abrir=abridor(t, []),
                                dormir=lambda _s: None, ahora=AHORA)


def test_publicar_impultienda_relee_igual(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa()
    original = t.contenido
    assert _publicar_imp(v, t) == URL
    assert t.contenido == empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17.html"
    assert respaldo.read_text(encoding="utf-8") == original


def engordar(v: Path) -> None:
    """Una vista previa de 60 KB: la landing en línea pasa de 50.000 caracteres (las de prueba son mínimas)."""
    (ruta_landing(v, P, "ZZ") / "assets" / "vista-p1-480.webp").write_bytes(b"RIFF" + bytes(range(256)) * 240)


def test_publicar_detecta_recorte_y_restaura(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(recorte=50_000)
    engordar(v)
    original = t.contenido
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(HtmlRecortado, match=r"recortó el HTML \(50000 de \d+ caracteres\)"):
        _publicar_imp(v, t)
    assert t.contenido == original  # lo de antes, de vuelta
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


def test_publicar_detecta_script_quitado(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(sin_script=True)
    with pytest.raises(HtmlRecortado, match="quitó el script"):
        _publicar_imp(v, t)


def test_publicar_firma_ausente_no_toca(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(firma=False)
    with pytest.raises(FirmaNoCasa):
        _publicar_imp(v, t)
    assert t.posts == []


def test_publicar_mas_largo_que_el_limite_no_toca(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa()
    with pytest.raises(HtmlRecortado, match="como mucho 1000"):
        _publicar_imp(v, t, replace(TODO_SI, limite_caracteres=1000))
    assert t.posts == []


def test_publicar_sin_dominio_no_medido(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa()
    d = replace(cargar(v), dominio=None)
    with pytest.raises(NoPublicable, match="dominio"):
        publicar_impultienda(v, d, TODO_SI, mapa=_mapa_confirmado(), abrir=abridor(t, []), dormir=lambda _s: None)
    assert t.posts == []


# --- publicar -----------------------------------------------------------------------------------


def test_publicar_impultienda_completo(tmp_path):
    v = lista(tmp_path)
    qa = QAFalsa()
    llamadas = []

    def imp(vault, d, c, **_kw):
        llamadas.append(c)
        return URL

    assert publicar(v, cargar(v), qa=qa, publicar_imp=imp, ahora=AHORA) == URL
    assert qa.urls == [URL] and llamadas == [TODO_SI]
    assert producto(v)[0]["paises"]["ZZ"]["estado"] == "con_landing"


def test_qa_publicada_falla_no_registra(tmp_path):
    v = lista(tmp_path)
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="QA.md"):
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: URL, ahora=AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly["url"] == URL and ly["publicada"] is None
    assert frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA.md")[0]["ok"] is False


def test_publicar_no_listo_no_toca(tmp_path):
    v = lista(tmp_path)
    (ruta_landing(v, P, "ZZ") / "QA.md").unlink()

    def nunca(*_a, **_k):
        raise AssertionError("no debía publicar")

    with pytest.raises(NoPublicable, match="trovefy landing qa"):
        publicar(v, cargar(v), qa=nunca, publicar_imp=nunca, ahora=AHORA)


def test_publicar_sonda_no_medida(tmp_path):
    v = lista(tmp_path)
    for f in (v / "config" / "evidencia").glob("p05-*.json"):
        f.unlink()
    with pytest.raises(NoPublicable, match="no medido"):
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: URL, ahora=AHORA)


def test_publicar_hosting_distinto_de_la_sonda(tmp_path):
    v = lista(tmp_path)
    evidencia(v, replace(TODO_SI, script=False))
    with pytest.raises(NoPublicable, match="--rehacer"):
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: URL, ahora=AHORA)


def _cloudflare_lista(tmp_path) -> Path:
    from .test_pixel import ETIQUETA, tracking

    v = montar_landing(tmp_path, "cloudflare")
    tracking(v)
    d = cargar(v)
    from trovefy.landing.plantilla import guardar, preparar

    b = preparar(v, d, "cloudflare", tmp_path / "b2")
    html = (ruta_landing(v, P, "ZZ") / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="assets/utm.js" defer></script>',
                        f'<script src="assets/utm.js" defer></script>\n{ETIQUETA}')
    html = html.replace('href="/checkout"', 'href="https://tienda.demo.test/checkout"')
    (b / "index.html").write_text(html, encoding="utf-8")
    guardar(v, d, b)
    escribir_qa(v)
    nativo_ok(v)
    evidencia(v, replace(TODO_SI, dominio_propio=False))
    return v


def test_publicar_cloudflare(tmp_path):
    v = _cloudflare_lista(tmp_path)
    assert listo_para_publicar(v, cargar(v)) == []
    with pytest.raises(NoPublicable, match=f"zz.{DOMINIO}"):
        publicar(v, cargar(v), qa=QAFalsa(), ahora=AHORA)
    with pytest.raises(NoPublicable, match="dominio"):
        publicar(v, cargar(v), "https://otro.test/", qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA)
    with pytest.raises(NoPublicable, match="versión"):
        publicar(v, cargar(v), f"https://zz.{DOMINIO}/", qa=QAFalsa(), verificar=lambda *_a: False, ahora=AHORA)
    url = f"https://zz.{DOMINIO}/"
    assert publicar(v, cargar(v), url, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA) == url
    zz = producto(v)[0]["paises"]["ZZ"]
    assert zz["estado"] == "con_landing" and zz["landing"]["hosting"] == "cloudflare"


# --- CLI ----------------------------------------------------------------------------------------


def test_cli_publicar_no_listo_sale_1(entorno, capsys):
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ"]) == 1
    assert "No se publica" in capsys.readouterr().err


def test_cli_publicar_bien(tmp_path, monkeypatch, capsys):
    from trovefy import landing_cli
    from trovefy.landing import publicar as mod

    from .conftest import Ejecutar

    v = lista(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    monkeypatch.setattr(mod, "publicar_impultienda", lambda *a, **k: URL)
    monkeypatch.setattr(mod, "_qa_publicada", QAFalsa())
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ"]) == 0
    assert f"ZZ → con_landing: {URL}" in capsys.readouterr().out
    assert yaml.safe_load((ruta_landing(v, P, "ZZ") / "landing.yaml").read_text(encoding="utf-8"))["publicada"]
