"""Ronda de la revisión final del plan 18 (sin navegador): Cloudflare como salida (I1), la sonda sin Meta (I2),
el campo leído vacío (I3) y los menores M1–M10."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from trovefy import cli
from trovefy.landing import hosting, panel, plantilla, qa
from trovefy.landing import nativo as nativo_mod
from trovefy.landing import publicar as publicar_mod
from trovefy.landing.entrada import ruta_landing
from trovefy.landing.hosting import HTML_SONDA, empaquetar_en_linea
from trovefy.landing.plantilla import UTM_JS, guardar, leer_landing_yaml, preparar
from trovefy.landing.publicar import (
    HtmlRecortado,
    NoPublicable,
    Pegada,
    listo_para_publicar,
    publicar,
    publicar_impultienda,
)
from trovefy.navegador import NavegadorError
from trovefy.vault import frontmatter

from .conftest import DOMINIO, TIENDA, P, cargar, vault_demo
from .test_hosting import ORIGINAL, TiendaFalsa, abridor, sondar
from .test_hosting import _mapa_confirmado as mapa_hosting
from .test_publicar import (
    AHORA,
    TODO_SI,
    URL,
    VERDE,
    QAFalsa,
    _publicar_imp,
    engordar,
    escribir_qa,
    evidencia,
    lista,
    nativo_ok,
    producto,
)

URL_CF = f"https://zz.{DOMINIO}/"


def _vault(tmp_path):
    return vault_demo(tmp_path)


def _a_cloudflare(v: Path, tmp_path: Path) -> None:
    """Lo que dice el mensaje: `preparar --hosting cloudflare`, guardar, (validar), nativo y qa."""
    d = cargar(v)
    b = preparar(v, d, "cloudflare", tmp_path / "b-cf")
    html = (ruta_landing(v, P, "ZZ") / "index.html").read_text(encoding="utf-8")
    (b / "index.html").write_text(html.replace('href="/checkout"', f'href="{TIENDA}/checkout"'), encoding="utf-8")
    guardar(v, d, b)
    escribir_qa(v)
    nativo_ok(v)


# --- I1: Cloudflare como salida -----------------------------------------------------------------


def test_limite_medido_dice_la_orden_de_cloudflare_y_publica_alli(tmp_path):
    """La sonda dice Impultienda pero con un límite medido que la landing no cabe: el mensaje da la orden
    exacta y, siguiéndola, la landing se publica en Cloudflare aunque la sonda siga diciendo Impultienda."""
    v, t = lista(tmp_path), TiendaFalsa()
    corta = replace(TODO_SI, limite_caracteres=1000)
    evidencia(v, corta)
    with pytest.raises(HtmlRecortado) as e:
        _publicar_imp(v, t, corta)
    orden = f"trovefy landing preparar --producto {P} --pais ZZ --hosting cloudflare"
    assert orden in str(e.value) and "guardar" in str(e.value) and "qa" in str(e.value)
    assert t.posts == []
    _a_cloudflare(v, tmp_path)
    assert listo_para_publicar(v, cargar(v)) == []
    assert publicar(v, cargar(v), URL_CF, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA) == URL_CF
    zz = producto(v)[0]["paises"]["ZZ"]
    assert zz["estado"] == "con_landing" and zz["landing"]["hosting"] == "cloudflare"


def test_recorte_al_releer_tambien_da_la_orden_de_cloudflare(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(recorte=50_000)
    engordar(v)
    with pytest.raises(HtmlRecortado, match="--hosting cloudflare") as e:
        _publicar_imp(v, t)
    assert f"--producto {P} --pais ZZ" in str(e.value)
    assert t.contenido == ORIGINAL


@pytest.mark.parametrize("sonda", ["ninguna", "rota", "impultienda"])
def test_cloudflare_no_depende_de_la_sonda(tmp_path, sonda):
    v = lista(tmp_path)
    for f in (v / "config" / "evidencia").glob("p05-*.json"):
        f.unlink()
    if sonda == "rota":
        (v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json").write_text("{roto", encoding="utf-8")
    elif sonda == "impultienda":
        evidencia(v)
    _a_cloudflare(v, tmp_path)
    assert publicar(v, cargar(v), URL_CF, qa=QAFalsa(), verificar=lambda *_a: True, ahora=AHORA) == URL_CF
    assert leer_landing_yaml(v, P, "ZZ")["hosting"] == "cloudflare"


def test_impultienda_sigue_rechazada_si_la_sonda_dice_cloudflare(tmp_path):
    v = lista(tmp_path)
    evidencia(v, replace(TODO_SI, sin_marco=False))
    with pytest.raises(NoPublicable, match="la sonda dice cloudflare"):
        publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA)


# --- I2: la sonda silencia Meta ------------------------------------------------------------------


def test_medir_tienda_aborta_meta_con_una_ruta_puesta_antes_de_ir(tmp_path):
    t = TiendaFalsa(hosts=("connect.facebook.net", "www.facebook.com", "cdn.tiendas.test"))
    c = sondar(_vault(tmp_path), t)
    pagina = t.ultima_publica
    assert pagina.rutas_al_ir == 1 and pagina.context.rutas[0][0] == "**/*"
    assert pagina.peticiones["https://connect.facebook.net/recurso.js"] == "abortada"
    assert pagina.peticiones["https://www.facebook.com/recurso.js"] == "abortada"
    assert pagina.peticiones["https://cdn.tiendas.test/recurso.js"] == "sigue"
    assert pagina.peticiones["https://tienda.demo.test/recurso.js"] == "sigue"
    assert "connect.facebook.net" not in c.hosts_tienda


# --- I3: el campo se lee tras esperar a la red, y vacío no se toma por contenido ---------------------


def test_sonda_espera_la_red_antes_de_leer_el_campo(tmp_path):
    v, t = _vault(tmp_path), TiendaFalsa(tarde=True)
    sondar(v, t)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    assert respaldo.read_text(encoding="utf-8") == ORIGINAL
    assert t.contenido == ORIGINAL and t.posts == [HTML_SONDA, ORIGINAL]


def test_sonda_con_el_campo_vacio_para_sin_tocar(tmp_path):
    v, t = _vault(tmp_path), TiendaFalsa(contenido="")
    with pytest.raises(panel.CampoVacio, match="--campo-vacio") as e:
        sondar(v, t)
    assert isinstance(e.value, NavegadorError) and "No he tocado nada" in str(e.value)
    assert t.posts == []
    assert not (ruta_landing(v, P, "ZZ") / "respaldo").exists()
    assert not list((v / "config" / "evidencia").glob("p05-impultienda-*.json"))


def test_sonda_con_el_campo_vacio_a_sabiendas(tmp_path):
    v, t = _vault(tmp_path), TiendaFalsa(contenido="")
    c = sondar(v, t, campo_vacio=True)
    assert c.html_propio is True and t.contenido == "" and t.posts == [HTML_SONDA, ""]


def test_publicar_impultienda_espera_la_red_antes_de_leer(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(tarde=True, recorte=50_000)
    engordar(v)
    with pytest.raises(HtmlRecortado):
        _publicar_imp(v, t)
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
    assert respaldo.read_text(encoding="utf-8") == ORIGINAL and t.contenido == ORIGINAL


def test_publicar_impultienda_con_el_campo_vacio_para(tmp_path):
    v, t = lista(tmp_path), TiendaFalsa(contenido="")
    with pytest.raises(panel.CampoVacio, match="--campo-vacio"):
        _publicar_imp(v, t)
    assert t.posts == [] and not (ruta_landing(v, P, "ZZ") / "respaldo").exists()
    pegada = publicar_impultienda(v, cargar(v), TODO_SI, mapa=mapa_hosting(), abrir=abridor(t, []),
                                  dormir=lambda _s: None, ahora=AHORA, campo_vacio=True)
    assert t.contenido == pegada.pegado


def test_publicar_pasa_campo_vacio(tmp_path):
    v = lista(tmp_path)
    vistos = []

    def imp(vault, d, c, **kw):
        vistos.append(kw.get("campo_vacio"))
        return Pegada(URL, None)

    publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=imp, ahora=AHORA, campo_vacio=True)
    assert vistos == [True]


def test_cli_sonda_y_publicar_con_campo_vacio(entorno, monkeypatch, capsys):
    vistos = {}

    def sondear(*_a, **kw):
        vistos["sonda"] = kw.get("campo_vacio")
        return TODO_SI

    def publicar_falso(vault, d, url=None, **kw):
        vistos["publicar"] = kw.get("campo_vacio")
        return URL

    monkeypatch.setattr(hosting, "sondear", sondear)
    monkeypatch.setattr(publicar_mod, "publicar", publicar_falso)
    base = ["--producto", P, "--pais", "ZZ"]
    assert cli.main(["landing", "sonda", *base, "--tienda", TIENDA, "--campo-vacio"]) == 0
    assert cli.main(["landing", "publicar", *base, "--campo-vacio"]) == 0
    assert vistos == {"sonda": True, "publicar": True}
    vistos.clear()
    cli.main(["landing", "sonda", *base, "--tienda", TIENDA])
    cli.main(["landing", "publicar", *base])
    assert vistos == {"sonda": False, "publicar": False}


# --- M1: probar_clic sin interceptar --------------------------------------------------------------


class _Ruta:
    def __init__(self, url):
        self.request = type("R", (), {"url": url})()
        self.hecho = None

    def abort(self):
        self.hecho = "abortada"

    def continue_(self):
        self.hecho = "sigue"


class _PaginaClic:
    def __init__(self):
        self.context = type("C", (), {})()
        self.rutas = []
        self.context.route = lambda patron, f: self.rutas.append((patron, f))
        self.url = "about:blank"
        self.visitas = []

    def goto(self, url, **_kw):
        self.visitas.append(url)
        self.url = url

    def locator(self, css):
        assert css == "a[data-tf-checkout]"
        pagina = self

        class Boton:
            first = None

            def count(self):
                return 1

            def click(self, **_kw):
                pagina.url = f"{TIENDA}/checkout?" + pagina.url.split("?", 1)[1]  # utm.js reenvía la query

        b = Boton()
        b.first = b
        return b

    def wait_for_load_state(self, *_a, **_k):
        pass


def test_probar_clic_sin_interceptar_usa_la_publicada_y_silencia_meta(monkeypatch):
    pagina = _PaginaClic()

    @contextmanager
    def falsa(_vista):
        yield pagina

    monkeypatch.setattr(qa, "_pagina", falsa)
    c = qa.probar_clic(URL, f"{TIENDA}/checkout", interceptar=False)
    assert pagina.visitas == [URL + qa.UTM_PUBLICADA]
    assert c.intactos is True and "fbclid" not in c.url_pedida
    assert len(pagina.rutas) == 1
    meta, tienda = _Ruta("https://connect.facebook.net/en_US/fbevents.js"), _Ruta(f"{TIENDA}/checkout")
    pagina.rutas[0][1](meta)
    pagina.rutas[0][1](tienda)
    assert (meta.hecho, tienda.hecho) == ("abortada", "sigue")


# --- M2 y M3: la QA publicada va aparte y la fecha es un día ---------------------------------------


def test_qa_publicada_va_aparte_y_la_local_no_la_pisa(tmp_path, monkeypatch):
    from .test_qa_evaluar import Falso, _hitos, montar

    v = montar(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    falso = Falso()
    falso.hitos, falso.version = _hitos(), plantilla.version_guardada(v, P, "ZZ")
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    raiz = ruta_landing(v, P, "ZZ")
    ver = falso.version
    qa.ejecutar_qa(v, cargar(v), url=URL)
    assert not (raiz / "QA.md").exists()
    meta, _ = frontmatter.leer(raiz / "QA-publicada.md")
    assert meta["url"] == URL
    assert meta["movil_390"]["captura"] == f"landing/ZZ/qa/movil-{ver}-publicada.png"
    assert meta["utm_checkout"]["fuente"] == "landing/ZZ/QA-publicada.md"
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert len(medidas) == 2
    assert (raiz / "qa" / f"movil-{ver}-publicada.png").is_file()
    assert (raiz / "qa" / f"escritorio-{ver}-publicada.png").is_file()
    publicada = (raiz / "QA-publicada.md").read_bytes()
    qa.ejecutar_qa(v, cargar(v))  # una QA local después
    assert (raiz / "QA-publicada.md").read_bytes() == publicada
    assert frontmatter.leer(raiz / "QA.md")[0]["url"] is None
    assert (raiz / "qa" / f"movil-{ver}-publicada.png").is_file()


def test_landing_qa_apunta_a_la_publicada_con_fecha_de_dia(tmp_path):
    v = lista(tmp_path)
    ver = leer_landing_yaml(v, P, "ZZ")["version"]
    ruta = escribir_qa(v, url=URL)
    meta, cuerpo = frontmatter.leer(ruta)
    frontmatter.escribir(ruta, {**meta, "fecha": "2026-11-18T03:00:00+00:00"}, cuerpo)  # 22:00 en Bogotá
    from trovefy.landing.hosting import Hosting
    from trovefy.landing.publicar import registrar_publicacion

    registrar_publicacion(v, cargar(v), URL, Hosting("impultienda", "x"), ver, VERDE, AHORA)
    q = producto(v)[0]["paises"]["ZZ"]["landing"]["qa"]
    assert q["archivo"] == "landing/ZZ/QA-publicada.md" and q["fecha"] == "2026-11-17"
    assert q["movil_390"]["captura"] == f"landing/ZZ/qa/movil-{ver}-publicada.png"
    assert q["utm_checkout"]["fuente"] == "landing/ZZ/QA-publicada.md"
    assert q["utm_checkout"]["captura"] is None and q["utm_checkout"]["interceptado"] is True
    # la QA local sigue siendo la de publicar
    assert listo_para_publicar(v, cargar(v)) == []


def test_publicar_no_pisa_la_qa_local(tmp_path):
    v = lista(tmp_path)
    local = (ruta_landing(v, P, "ZZ") / "QA.md").read_bytes()
    publicar(v, cargar(v), qa=QAFalsa(), publicar_imp=lambda *a, **k: Pegada(URL, None), ahora=AHORA)
    assert (ruta_landing(v, P, "ZZ") / "QA.md").read_bytes() == local
    assert (ruta_landing(v, P, "ZZ") / "QA-publicada.md").is_file()


# --- M4: estado dice el hosting de la sonda ------------------------------------------------------


@pytest.mark.parametrize(("sonda", "linea"), [
    (None, "Hosting: impultienda (pegado manual)"),
    ("rota", "Hosting: impultienda (pegado manual)"),
    ("impultienda", "Hosting: impultienda"),
    ("cloudflare", "Hosting: cloudflare"),
])
def test_estado_dice_el_hosting(entorno, capsys, sonda, linea):
    if sonda == "rota":
        ruta = entorno / "config" / "evidencia" / "p05-impultienda-2026-11-17.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("{roto", encoding="utf-8")
    elif sonda is not None:
        evidencia(entorno, TODO_SI if sonda == "impultienda" else replace(TODO_SI, script=False))
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 0
    salida = capsys.readouterr().out
    assert linea in salida, salida
    if sonda in (None, "rota"):  # plan 18b: sin sonda, el pegado manual; la sonda automática sigue «no medido»
        assert "--manual" in salida and "no medido" in salida


# --- M7: un solo lector de la versión y un solo SHA ------------------------------------------------


def test_un_solo_lector_de_version_y_un_solo_sha(tmp_path):
    from trovefy.tienda import confirmacion

    assert qa.version_guardada is plantilla.version_guardada
    assert not hasattr(publicar_mod, "_version_actual") and not hasattr(nativo_mod, "_version_actual")
    assert publicar_mod.sha_texto is panel.sha_texto
    assert not hasattr(publicar_mod, "_sha") and not hasattr(panel, "_sha")
    assert hasattr(confirmacion, "url_confirmada") and not hasattr(confirmacion, "confirmada_en_vault")
    v = lista(tmp_path)
    assert plantilla.version_guardada(v, P, "ZZ") == leer_landing_yaml(v, P, "ZZ")["version"]
    assert plantilla.version_guardada(v, P, "ZY", exigir=False) is None


# --- M8: la ruta Impultienda exige dominio propio ---------------------------------------------------


@pytest.mark.parametrize("dominio_propio", [False, None])
def test_impultienda_sin_dominio_propio_no_publica(tmp_path, dominio_propio):
    v, t = lista(tmp_path), TiendaFalsa()
    with pytest.raises(NoPublicable, match="dominio propio"):
        _publicar_imp(v, t, replace(TODO_SI, dominio_propio=dominio_propio))
    assert t.posts == []


# --- M9: la evidencia de la sonda sin query ni fragmento, y sin secretos ------------------------------


def test_evidencia_sin_query_ni_fragmento(tmp_path):
    v, t = _vault(tmp_path), TiendaFalsa()
    url = "https://app.impultienda.ar/dashboard/diseno/contenido?tienda=123&token=abc#seccion"
    c = sondar(v, t, url_pantalla=url)
    assert c.url_pantalla == "https://app.impultienda.ar/dashboard/diseno/contenido"
    texto = (v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json").read_text(encoding="utf-8")
    assert "token" not in texto and "#seccion" not in texto


def test_evidencia_con_secreto_no_se_escribe(tmp_path, monkeypatch):
    v, t = _vault(tmp_path), TiendaFalsa()
    monkeypatch.setattr(hosting, "buscar_secreto", lambda _texto: "clave_falsa")
    with pytest.raises(ValueError, match="secreto"):
        sondar(v, t)
    assert not list((v / "config" / "evidencia").glob("p05-impultienda-*.json"))
    assert t.contenido == ORIGINAL  # restaurado antes


# --- M10: utm.js y pixel.js del vault, idénticos a la plantilla --------------------------------------


def test_empaquetar_usa_el_utm_del_vault_y_exige_la_plantilla(tmp_path):
    from .test_hosting import montar

    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    assert UTM_JS.read_text(encoding="utf-8").strip() in empaquetar_en_linea(raiz)
    (raiz / "assets" / "utm.js").write_bytes(UTM_JS.read_bytes() + b"\n// otro")
    with pytest.raises(ValueError, match="utm.js"):
        empaquetar_en_linea(raiz)
    (raiz / "assets" / "utm.js").unlink()
    with pytest.raises(ValueError, match="utm.js"):
        empaquetar_en_linea(raiz)


def test_empaquetar_mete_el_pixel_del_vault_si_es_la_plantilla(tmp_path):
    from .test_pixel import DATASET
    from .test_pixel import montar as montar_pixel

    v = montar_pixel(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    out = empaquetar_en_linea(raiz)
    assert out.count("<script>") == 2 and f"fbq('init', '{DATASET}')" in out
    assert out.index("utm") < out.index("fbq('init'")
    pix = raiz / "assets" / "pixel.js"
    pix.write_text(pix.read_text(encoding="utf-8").replace("'PageView'", "'Purchase'"), encoding="utf-8")
    with pytest.raises(ValueError, match="pixel.js"):
        empaquetar_en_linea(raiz)


# --- M6: el comentario del mapa ------------------------------------------------------------------


def test_mapa_no_nombra_una_orden_que_no_existe():
    texto = panel.MAPA_IMPULTIENDA.read_text(encoding="utf-8")
    assert "trovefy checkout capturar" not in texto and "trovefy landing capturar" in texto
