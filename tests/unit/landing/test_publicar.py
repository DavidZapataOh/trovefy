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
from trovefy.landing.entrada import EntradaInvalida, EstadoNoPermite, ruta_landing
from trovefy.landing.hosting import CAPACIDADES_FASE0, Hosting, empaquetar_en_linea
from trovefy.landing.nativo import registrar_veredicto
from trovefy.landing.plantilla import leer_landing_yaml, manifiesto_landing
from trovefy.landing.publicar import (
    HtmlRecortado,
    NoPublicable,
    Pegada,
    listo_para_publicar,
    publicar,
    publicar_impultienda,
    registrar_publicacion,
    verificar_cloudflare,
)
from trovefy.landing.qa import ResultadoQA
from trovefy.mapa import cargar as cargar_mapa
from trovefy.tienda.conductor import FirmaNoCasa, MapaSinConfirmar
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
    """`QA.md` como lo deja `ejecutar_qa`: con la versión y el manifiesto de los archivos medidos (I-6). Con
    `url`, la QA publicada: `QA-publicada.md` y capturas `-publicada` (M2)."""
    ver = ver or version(v)
    raiz = ruta_landing(v, P, "ZZ")
    nombre, sufijo = ("QA-publicada.md", "-publicada") if url is not None else ("QA.md", "")
    ruta = raiz / nombre
    frontmatter.escribir(ruta, {
        "tipo": "qa_landing", "pais": "ZZ", "version": ver, "manifiesto": manifiesto_landing(raiz), "ok": ok,
        "fecha": AHORA.isoformat(), "url": url,
        "movil_390": {"http": 200, "captura": f"landing/ZZ/qa/movil-{ver}{sufijo}.png"},
        "utm_checkout": {"ok": True, "destino": "https://x.test/checkout?utm_source=fb", "captura": None,
                         "interceptado": True, "fuente": f"landing/ZZ/{nombre}"},
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


def _cloudflare_sin_pixel(tmp_path) -> Path:
    from trovefy.landing.plantilla import guardar, preparar

    v = montar_landing(tmp_path, "cloudflare")
    d = cargar(v)
    b = preparar(v, d, "cloudflare", tmp_path / "b2")
    html = (ruta_landing(v, P, "ZZ") / "index.html").read_text(encoding="utf-8")
    (b / "index.html").write_text(html.replace('href="/checkout"', 'href="https://tienda.demo.test/checkout"'),
                                  encoding="utf-8")
    guardar(v, d, b)
    escribir_qa(v)
    nativo_ok(v)
    evidencia(v, replace(TODO_SI, dominio_propio=False))
    return v


def test_cloudflare_sin_pixel_publica_con_aviso_y_pixel_pendiente(tmp_path):
    """Ruling B: sin TRACKING.md se publica SIN píxel, con aviso explícito y `pixel: pendiente` en landing.yaml
    (el 19 y /listo lo exigen antes de anunciar)."""
    from trovefy.landing.publicar import avisos_publicacion

    v = _cloudflare_sin_pixel(tmp_path)
    assert listo_para_publicar(v, cargar(v)) == []
    avisos = avisos_publicacion(v, cargar(v))
    assert len(avisos) == 1 and "sin píxel" in avisos[0] and "TRACKING.md" in avisos[0]
    url = f"https://zz.{DOMINIO}/"
    assert publicar(v, cargar(v), url, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA) == url
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly["pixel"] == "pendiente" and ly["publicada"]
    assert producto(v)[0]["paises"]["ZZ"]["estado"] == "con_landing"


def test_cli_publicar_cloudflare_sin_pixel_avisa(tmp_path, monkeypatch, capsys):
    from trovefy import landing_cli
    from trovefy.landing import publicar as mod

    from .conftest import Ejecutar

    v = _cloudflare_sin_pixel(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    monkeypatch.setattr(mod, "verificar_cloudflare", lambda *_a: True)
    monkeypatch.setattr(mod, "_qa_publicada", QAFalsa())
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ", "--url", f"https://zz.{DOMINIO}/"]) == 0
    salida = capsys.readouterr()
    assert "Aviso: sin píxel" in salida.out + salida.err and "pixel: pendiente" in salida.out + salida.err


def test_cloudflare_con_pixel_no_lo_marca_pendiente(tmp_path):
    from trovefy.landing.publicar import avisos_publicacion

    v = _cloudflare_lista(tmp_path)
    assert avisos_publicacion(v, cargar(v)) == []
    url = f"https://zz.{DOMINIO}/"
    publicar(v, cargar(v), url, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA)
    assert leer_landing_yaml(v, P, "ZZ")["pixel"] == "activo"


def test_publicar_cloudflare_solo_dominio_o_subdominio_del_pais(tmp_path):
    """I2: la misma regla que la QA publicada (dominio propio o `<pais>.<dominio>`), antes de tocar nada."""
    v = _cloudflare_lista(tmp_path)
    for mala in (f"https://otro.zz.{DOMINIO}/", f"https://zz.{DOMINIO}:8443/", f"https://u@zz.{DOMINIO}/"):
        with pytest.raises(NoPublicable, match="dominio"):
            publicar(v, cargar(v), mala, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA)
    assert leer_landing_yaml(v, P, "ZZ").get("url") is None


# --- registrar_publicacion ----------------------------------------------------------------------


def test_registrar_avanza_producido_a_con_landing(tmp_path):
    v = lista(tmp_path)
    ver = version(v)
    escribir_qa(v, url=URL)  # la QA publicada de esta versión y esta URL (L-5)
    meta0, cuerpo0 = producto(v)
    estado = registrar_publicacion(v, cargar(v), URL, Hosting("impultienda", "x"), ver, VERDE, AHORA)
    assert estado == "con_landing"
    meta, cuerpo = producto(v)
    zz = meta["paises"]["ZZ"]
    assert zz["estado"] == "con_landing" and zz["historial"][-1]["de"] == "producido"
    assert zz["landing"]["url"] == URL and zz["landing"]["hosting"] == "impultienda"
    assert zz["landing"]["version"] == ver and zz["landing"]["fecha"] == "2026-11-17"
    qa = zz["landing"]["qa"]
    assert qa["archivo"] == "landing/ZZ/QA-publicada.md" and qa["version"] == ver  # M2: aparte de la local
    assert qa["movil_390"] == {"http": 200, "captura": f"landing/ZZ/qa/movil-{ver}-publicada.png"}
    assert qa["utm_checkout"]["interceptado"] is True
    assert qa["utm_checkout"]["fuente"] == "landing/ZZ/QA-publicada.md"
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
    escribir_qa(v, url=URL)
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
    pegada = _publicar_imp(v, t)
    assert pegada.url == URL
    assert t.contenido == empaquetar_en_linea(ruta_landing(v, P, "ZZ")) == pegada.pegado
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
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
        return Pegada(URL, None)

    assert publicar(v, cargar(v), qa=qa, publicar_imp=imp, ahora=AHORA) == URL
    assert qa.urls == [URL] and llamadas == [TODO_SI]
    assert producto(v)[0]["paises"]["ZZ"]["estado"] == "con_landing"


def test_qa_publicada_falla_no_registra(tmp_path):
    v = lista(tmp_path)
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="QA-publicada.md"):
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly["url"] == URL and ly["publicada"] is None
    assert frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA-publicada.md")[0]["ok"] is False


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
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA)


def test_publicar_hosting_distinto_de_la_sonda(tmp_path):
    v = lista(tmp_path)
    evidencia(v, replace(TODO_SI, script=False))
    with pytest.raises(NoPublicable, match="--rehacer"):
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA)


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
    with pytest.raises(NoPublicable, match=f"zz.{DOMINIO}") as e:
        publicar(v, cargar(v), qa=QAFalsa(), ahora=AHORA)
    assert str(ruta_landing(v, P, "ZZ") / "publicar") in str(e.value)
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
    monkeypatch.setattr(mod, "publicar_impultienda", lambda *a, **k: Pegada(URL, None))
    monkeypatch.setattr(mod, "_qa_publicada", QAFalsa())
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ"]) == 0
    assert f"ZZ → con_landing: {URL}" in capsys.readouterr().out
    assert yaml.safe_load((ruta_landing(v, P, "ZZ") / "landing.yaml").read_text(encoding="utf-8"))["publicada"]


# --- T: una excepción después de pegar siempre restaura ------------------------------------------


def test_publicar_impultienda_parada_de_pulsar_tras_guardar_restaura(tmp_path):
    from trovefy.tienda.conductor import Parada, VentanaNueva

    v, t = lista(tmp_path), TiendaFalsa(tras_pegar=VentanaNueva("diseno_contenido", "se abrió otra ventana"))
    original = t.contenido
    with pytest.raises(Parada):
        _publicar_imp(v, t)
    assert t.contenido == original and len(t.posts) == 2 and t.posts[1] == original


def test_publicar_impultienda_ctrl_c_restaura(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(tras_pegar=KeyboardInterrupt())
    original = t.contenido
    with pytest.raises(KeyboardInterrupt):
        _publicar_imp(v, t)
    assert t.contenido == original and t.posts[-1] == original


# --- I-5: una sonda colgada en el campo para la publicación -----------------------------------


@pytest.mark.parametrize("trozo", [10_000, 40])
def test_publicar_impultienda_con_sonda_colgada_para(tmp_path, trozo):
    from trovefy.landing.hosting import HTML_SONDA
    from trovefy.navegador import NavegadorError

    v = lista(tmp_path)
    carpeta = ruta_landing(v, P, "ZZ") / "respaldo"
    carpeta.mkdir(parents=True)
    (carpeta / "impultienda-2026-11-16.html").write_text("<p>antes</p>", encoding="utf-8")
    t = TiendaFalsa(contenido=HTML_SONDA[:trozo])
    with pytest.raises(NavegadorError, match="sonda anterior") as e:
        _publicar_imp(v, t)
    assert str(carpeta / "impultienda-2026-11-16.html") in str(e.value)
    assert t.posts == []


# --- L-6 ----------------------------------------------------------------------------------------


def test_publicar_impultienda_pega_sin_salto_final(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa()
    _publicar_imp(v, t)
    assert not t.posts[0].endswith("\n")


# --- L-4: QA publicada en rojo en Impultienda → se restaura lo de antes ------------------------


class Restaurador:
    def __init__(self, falla: Exception | None = None):
        self.llamadas: list[Path] = []
        self.esperados: list = []
        self.falla = falla

    def __call__(self, vault, respaldo, *, esperado, **_kw):
        self.llamadas.append(respaldo)
        self.esperados.append(esperado)
        if self.falla is not None:
            raise self.falla


def test_qa_publicada_en_rojo_restaura_lo_de_antes(tmp_path):
    from trovefy.landing.publicar import Pegada

    v = lista(tmp_path)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    restaurar = Restaurador()
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="He vuelto a dejar en Impultienda lo que había") as e:
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: Pegada(URL, respaldo, "<v2/>"),
                 restaurar_imp=restaurar, ahora=AHORA)
    assert restaurar.llamadas == [respaldo] and restaurar.esperados == ["<v2/>"]
    assert str(respaldo) in str(e.value) and "la QA publicada no pasa" in str(e.value)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly.get("url") is None and ly.get("publicada") is None


def test_qa_publicada_en_rojo_y_restaurar_falla_lo_dice(tmp_path):
    from trovefy.landing.publicar import Pegada
    from trovefy.navegador import NavegadorError

    v = lista(tmp_path)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    restaurar = Restaurador(NavegadorError(f"no pude restaurar el contenido: pégalo tú desde {respaldo}"))
    with pytest.raises(NoPublicable, match="pégalo tú desde"):
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: Pegada(URL, respaldo),
                 restaurar_imp=restaurar, ahora=AHORA)


def test_qa_publicada_en_rojo_sin_pegar_nada_no_restaura(tmp_path):
    """La misma versión ya estaba en el campo (no se pegó nada): no hay un «antes» que devolver."""
    from trovefy.landing.publicar import Pegada

    v = lista(tmp_path)
    restaurar = Restaurador()
    with pytest.raises(NoPublicable, match="QA-publicada.md"):
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: Pegada(URL, None),
                 restaurar_imp=restaurar, ahora=AHORA)
    assert restaurar.llamadas == []


def test_qa_publicada_en_rojo_en_cloudflare_no_restaura(tmp_path):
    v = _cloudflare_lista(tmp_path)
    restaurar = Restaurador()
    with pytest.raises(NoPublicable, match="QA-publicada.md"):
        publicar(v, cargar(v), f"https://zz.{DOMINIO}/", qa=QAFalsa(LCP_ALTO), verificar=lambda *_a: True,
                 restaurar_imp=restaurar, ahora=AHORA)
    assert restaurar.llamadas == []


def test_restaurar_desde_respaldo_pega_el_archivo(tmp_path):
    from trovefy.landing.panel import restaurar_desde_respaldo

    v, t = lista(tmp_path), TiendaFalsa(contenido="<p>la landing</p>")
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    respaldo.parent.mkdir(parents=True)
    respaldo.write_text("<h1>lo de antes</h1>", encoding="utf-8")
    restaurar_desde_respaldo(v, respaldo, esperado="<p>la landing</p>", mapa=_mapa_confirmado(),
                             abrir=abridor(t, []), dormir=lambda _s: None, ahora=AHORA)
    assert t.contenido == "<h1>lo de antes</h1>"


def test_restaurar_con_el_campo_cambiado_no_pega_y_nombra_los_dos(tmp_path):
    """F2-1: el campo no tiene lo que se pegó (el usuario lo cambió): se guarda lo que hay, no se pega nada."""
    from trovefy.landing.panel import CampoCambiado, restaurar_desde_respaldo

    v, t = lista(tmp_path), TiendaFalsa(contenido="<p>lo nuevo del usuario</p>")
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T090000.html"
    respaldo.parent.mkdir(parents=True)
    respaldo.write_text("<h1>lo de antes</h1>", encoding="utf-8")
    with pytest.raises(CampoCambiado) as e:
        restaurar_desde_respaldo(v, respaldo, esperado="<p>la landing</p>", mapa=_mapa_confirmado(),
                                 abrir=abridor(t, []), dormir=lambda _s: None, ahora=AHORA)
    assert t.posts == [] and t.contenido == "<p>lo nuevo del usuario</p>"
    nuevo = respaldo.parent / "impultienda-2026-11-17T103000.html"
    assert nuevo.read_text(encoding="utf-8") == "<p>lo nuevo del usuario</p>"
    assert str(respaldo) in str(e.value) and str(nuevo) in str(e.value)


def test_restaurar_con_el_campo_ya_restaurado_no_pega(tmp_path):
    from trovefy.landing.panel import restaurar_desde_respaldo

    v, t = lista(tmp_path), TiendaFalsa(contenido="<h1>lo de antes</h1>")
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T090000.html"
    respaldo.parent.mkdir(parents=True)
    respaldo.write_text("<h1>lo de antes</h1>", encoding="utf-8")
    restaurar_desde_respaldo(v, respaldo, esperado="<p>la landing</p>", mapa=_mapa_confirmado(),
                             abrir=abridor(t, []), dormir=lambda _s: None, ahora=AHORA)
    assert t.posts == []


class TiendaQueCambiaAntesDeRestaurar(TiendaFalsa):
    """Entre la relectura (recortada) y la sesión de restaurar, el usuario cambia el campo a mano."""

    def panel(self):
        if self.posts:
            self.contenido = "<p>lo nuevo del usuario</p>"
        return super().panel()


def test_publicar_recorte_con_el_campo_cambiado_no_pega_encima(tmp_path):
    """F2-1 en la restauración por recorte: si el campo ya no tiene lo pegado, no se pega nada."""
    v, t = lista(tmp_path), TiendaQueCambiaAntesDeRestaurar(recorte=500)
    with pytest.raises(HtmlRecortado, match="ya no tiene lo que pegué"):
        _publicar_imp(v, t)
    assert len(t.posts) == 1 and t.contenido == "<p>lo nuevo del usuario</p>"


# --- F2-2: una excepción durante la QA publicada devuelve lo de antes --------------------------------


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), EntradaInvalida("QA.md roto"), RuntimeError("inesperado")])
def test_excepcion_durante_la_qa_publicada_restaura(tmp_path, capsys, exc):
    v = lista(tmp_path)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    restaurar = Restaurador()

    def qa(*_a):
        raise exc

    with pytest.raises(type(exc)):
        publicar(v, cargar(v), qa=qa, publicar_imp=lambda *a, **k: Pegada(URL, respaldo, "<v2/>"),
                 restaurar_imp=restaurar, ahora=AHORA)
    assert restaurar.llamadas == [respaldo] and restaurar.esperados == ["<v2/>"]
    err = capsys.readouterr().err
    assert str(respaldo) in err and type(exc).__name__ in err
    assert leer_landing_yaml(v, P, "ZZ").get("url") is None


def test_excepcion_antes_de_pegar_no_restaura(tmp_path):
    v = lista(tmp_path)
    restaurar = Restaurador()

    def imp(*_a, **_k):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=imp, restaurar_imp=restaurar, ahora=AHORA)
    assert restaurar.llamadas == []


# --- F2-4 ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("falla", [MapaSinConfirmar("diseno_contenido", "no medido: mapa sin confirmar"),
                                   FirmaNoCasa("diseno_contenido", "otra pantalla"), ValueError("raro")])
def test_qa_en_rojo_y_restaurar_para_lo_dice_con_el_respaldo(tmp_path, falla):
    v = lista(tmp_path)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    with pytest.raises(NoPublicable) as e:
        publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO), publicar_imp=lambda *a, **k: Pegada(URL, respaldo, "<v2/>"),
                 restaurar_imp=Restaurador(falla), ahora=AHORA)
    msg = str(e.value)
    assert "la QA publicada no pasa" in msg and "NO he devuelto lo de antes" in msg and str(respaldo) in msg


def test_v2_en_rojo_restaurada_deja_la_v1_en_landing_yaml(tmp_path):
    """Con la v1 publicada, una v2 con la QA en rojo y restaurada deja landing.yaml con la URL y la versión
    publicadas de la v1 (las de PRODUCTO.md)."""
    v = lista(tmp_path)
    v1 = version(v)
    assert publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA) == URL
    ly1 = leer_landing_yaml(v, P, "ZZ")
    assert ly1["version_publicada"] == v1 and ly1["publicada"]
    # una v2 guardada: otra versión local, con su QA y su nativo
    ly = dict(ly1, version="0123456789ab")
    (ruta_landing(v, P, "ZZ") / "landing.yaml").write_text(yaml.safe_dump(ly), encoding="utf-8")
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    import trovefy.landing.publicar as mod

    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    original = mod.listo_para_publicar
    mod.listo_para_publicar = lambda *_a: []
    try:
        with pytest.raises(NoPublicable, match="sigue publicada la anterior"):
            publicar(v, cargar(v), qa=QAFalsa(LCP_ALTO),
                     publicar_imp=lambda *a, **k: Pegada(URL, respaldo, "<v2/>"), restaurar_imp=Restaurador(),
                     ahora=AHORA)
    finally:
        mod.listo_para_publicar = original
    ly2 = leer_landing_yaml(v, P, "ZZ")
    assert (ly2["url"], ly2["publicada"], ly2["version_publicada"]) == (ly1["url"], ly1["publicada"], v1)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    assert producto(v)[0]["paises"]["ZZ"]["landing"]["version"] == ly2["version_publicada"]


# --- Cloudflare: lo que se sube es solo index.html y assets/ -----------------------------------------


def test_carpeta_de_subida_solo_lleva_index_y_assets(tmp_path):
    v = _cloudflare_lista(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    (raiz / "respaldo").mkdir()
    (raiz / "respaldo" / "impultienda-2026-11-17T103000.html").write_text("<p>mi tienda</p>", encoding="utf-8")
    (raiz / "qa").mkdir(exist_ok=True)
    (raiz / "publicar").mkdir()
    (raiz / "publicar" / "viejo.txt").write_text("de antes", encoding="utf-8")
    with pytest.raises(NoPublicable) as e:
        publicar(v, cargar(v), qa=QAFalsa(), ahora=AHORA)
    msg = str(e.value)
    carpeta = raiz / "publicar"
    assert str(carpeta) in msg and "solo index.html y assets/" in msg
    for nombre in ("respaldo", "landing.yaml", "QA.md", "nativo.md", "qa/"):
        assert nombre not in msg.replace(str(carpeta), ""), nombre
    archivos = sorted(p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*"))
    esperados = sorted(["index.html", "assets"] + [f"assets/{a.name}" for a in (raiz / "assets").iterdir()])
    assert archivos == esperados
    assert (carpeta / "index.html").read_bytes() == (raiz / "index.html").read_bytes()


# --- L-5 ----------------------------------------------------------------------------------------


def test_registrar_avanza_antes_de_escribir_la_landing(tmp_path, monkeypatch):
    """Si el estado cambió entre la lectura y la escritura, `avanzar_estado` para y no queda nada a medias."""
    from trovefy.landing import publicar as mod
    from trovefy.vault.producto import EstadoInesperado

    v = lista(tmp_path)
    escribir_qa(v, url=URL)
    d, ver = cargar(v), version(v)
    editar_md(v, "PRODUCTO", lambda m: m["paises"]["ZZ"].update(estado="modelado"))
    monkeypatch.setattr(mod, "estado_pais", lambda *_a: "producido")  # lo leyó antes del cambio
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(EstadoInesperado):
        registrar_publicacion(v, d, URL, Hosting("impultienda", "x"), ver, VERDE, AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


@pytest.mark.parametrize(("ver", "url"), [(None, None), (None, "https://otra.test/"), ("000000000000", URL)])
def test_registrar_qa_de_otra_publicacion_no_vale(tmp_path, ver, url):
    """`landing.qa` solo sale de QA-publicada.md de esta versión y esta URL."""
    v = lista(tmp_path)
    escribir_qa(v, ver=ver, url=url)
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="QA-publicada.md"):
        registrar_publicacion(v, cargar(v), URL, Hosting("impultienda", "x"), version(v), VERDE, AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


# --- I-6: la versión publicada cubre todos los archivos, no solo index.html -----------------------


@pytest.mark.parametrize("archivo", ["assets/estilo.css", "assets/utm.js", "assets/medios.json",
                                     "assets/vista-p1-480.webp"])
def test_cambio_tras_la_qa_bloquea_publicar(tmp_path, archivo):
    v = lista(tmp_path)
    ruta = ruta_landing(v, P, "ZZ") / archivo
    ruta.write_bytes(ruta.read_bytes() + b"\n/* cambio */\n")
    motivos = listo_para_publicar(v, cargar(v))
    assert any("cambiaron después de la QA" in m for m in motivos), motivos


def test_css_cambiado_tras_la_qa_no_publica(tmp_path):
    v = lista(tmp_path)
    css = ruta_landing(v, P, "ZZ") / "assets" / "estilo.css"
    css.write_text(css.read_text(encoding="utf-8") + "\nbody{color:red}\n", encoding="utf-8")

    def nunca(*_a, **_k):
        raise AssertionError("no debía publicar")

    with pytest.raises(NoPublicable, match="cambiaron después de la QA"):
        publicar(v, cargar(v), qa=nunca, publicar_imp=nunca, ahora=AHORA)


def test_qa_sin_manifiesto_no_vale(tmp_path):
    v = lista(tmp_path)
    ruta = ruta_landing(v, P, "ZZ") / "QA.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta.pop("manifiesto")
    frontmatter.escribir(ruta, meta, cuerpo)
    assert any("cambiaron después de la QA" in m for m in listo_para_publicar(v, cargar(v)))


def test_manifiesto_ve_un_archivo_nuevo_en_assets(tmp_path):
    from trovefy.landing.plantilla import manifiesto_landing

    v = lista(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    antes = manifiesto_landing(raiz)
    (raiz / "assets" / "extra.webp").write_bytes(b"RIFF")
    assert manifiesto_landing(raiz) != antes


def test_manifiesto_con_enlace_es_error(tmp_path):
    from trovefy.landing.plantilla import manifiesto_landing

    v = lista(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    (raiz / "assets" / "enlace.webp").symlink_to(raiz / "assets" / "estilo.css")
    with pytest.raises(ValueError, match="enlace"):
        manifiesto_landing(raiz)
    assert any("enlace" in m for m in listo_para_publicar(v, cargar(v)))


def test_abrir_seguro_se_presenta_como_navegador(monkeypatch):
    """Impultienda está detrás de Cloudflare, que responde 403 al agente por defecto de urllib."""
    import urllib.request

    from trovefy.landing import publicar as mod

    vistos = []

    class Opener:
        def open(self, req, timeout=None):
            vistos.append(req)
            return "respuesta"

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    assert mod._abrir_seguro("https://tienda.demo.test/") == "respuesta"
    ua = vistos[0].get_header("User-agent")
    assert ua and "Mozilla/5.0" in ua and "Python-urllib" not in ua
