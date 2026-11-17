"""Tarea 8 del plan 18: capacidades de Impultienda, elección de hosting, empaquetado en línea y lo que la
sonda comprueba antes de abrir el navegador (sin Chromium: lo que lo usa está en tests/integracion)."""

import base64
import json
import re
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy import cli
from trovefy.landing import hosting
from trovefy.landing.entrada import ruta_landing
from trovefy.landing.hosting import (
    CAPACIDADES_FASE0,
    HTML_SONDA,
    Capacidades,
    CapacidadNoMedida,
    Hosting,
    capacidades_vigentes,
    elegir_hosting,
    empaquetar_en_linea,
    guardar_tienda,
    mapa_impultienda,
    sondear,
)
from trovefy.landing.medios import preparar_medios
from trovefy.landing.plantilla import UTM_JS, guardar, preparar
from trovefy.mapa import cargar as cargar_mapa
from trovefy.navegador import NavegadorError
from trovefy.tienda.conductor import FirmaNoCasa, MapaSinConfirmar
from unit.tienda.pagina_falsa import ElementoFalso, PaginaFalsa

from .conftest import Ejecutar, P, cargar, vault_demo

BUENA = Path(__file__).resolve().parents[2] / "fixtures" / "landing" / "buena-zz.html"
AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
TODO_SI = replace(CAPACIDADES_FASE0, html_propio=True, script=True, estilos=True, titulo_propio=True,
                  sin_marco=True, dominio_propio=True, tienda="https://tienda.demo.test", fecha="2026-11-17",
                  fuente="prueba")


def montar(tmp_path, hosting_="impultienda") -> Path:
    v = vault_demo(tmp_path)
    d = cargar(v)
    preparar_medios(v, d, ejecutar=Ejecutar())
    b = preparar(v, d, hosting_, tmp_path / "borrador")
    shutil.copyfile(BUENA, b / "index.html")
    guardar(v, d, b)
    return v


# --- elegir_hosting --------------------------------------------------------------------------------


def test_elegir_fase0_no_medido():
    with pytest.raises(CapacidadNoMedida) as e:
        elegir_hosting(CAPACIDADES_FASE0)
    assert "script" in str(e.value) and "dominio_propio" in str(e.value)
    assert "html_propio" not in str(e.value)  # la captura del usuario ya lo midió


def test_elegir_todo_si_impultienda():
    h = elegir_hosting(TODO_SI)
    assert h == Hosting("impultienda", h.motivo) and h.motivo


def test_elegir_sin_script_cloudflare():
    h = elegir_hosting(replace(TODO_SI, script=False))
    assert h.ruta == "cloudflare" and "no ejecuta el script UTM" in h.motivo


def test_elegir_sin_dominio_propio_cloudflare():
    h = elegir_hosting(replace(TODO_SI, dominio_propio=False))
    assert h.ruta == "cloudflare" and "dominio propio" in h.motivo


def test_elegir_un_false_manda_sobre_lo_no_medido():
    h = elegir_hosting(replace(CAPACIDADES_FASE0, sin_marco=False))
    assert h.ruta == "cloudflare" and "marco" in h.motivo


def test_elegir_con_marco_y_sin_titulo_dice_los_dos():
    h = elegir_hosting(replace(TODO_SI, sin_marco=False, titulo_propio=False))
    assert h.ruta == "cloudflare" and "marco" in h.motivo and "título" in h.motivo


# --- capacidades_vigentes --------------------------------------------------------------------------


def _evidencia(v: Path, fecha: str, **campos) -> Path:
    c = replace(TODO_SI, fecha=fecha, **campos)
    ruta = v / "config" / "evidencia" / f"p05-impultienda-{fecha}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(c.__dict__), encoding="utf-8")
    return ruta


def test_capacidades_sin_evidencia_son_las_de_la_fase_0(tmp_path):
    assert capacidades_vigentes(vault_demo(tmp_path)) == CAPACIDADES_FASE0
    assert CAPACIDADES_FASE0.html_propio is True and CAPACIDADES_FASE0.script is None
    assert CAPACIDADES_FASE0.fuente == "config/evidencia/09-captura-usuario-2026-11-12.png"


def test_capacidades_la_mas_reciente(tmp_path):
    v = vault_demo(tmp_path)
    _evidencia(v, "2026-11-15", script=False)
    _evidencia(v, "2026-11-17", script=True)
    _evidencia(v, "2026-11-16", script=False)
    c = capacidades_vigentes(v)
    assert c.fecha == "2026-11-17" and c.script is True


def test_capacidades_rotas_es_error(tmp_path):
    v = vault_demo(tmp_path)
    ruta = _evidencia(v, "2026-11-17")
    ruta.write_text("{roto", encoding="utf-8")
    with pytest.raises(ValueError, match="p05-impultienda-2026-11-17.json"):
        capacidades_vigentes(v)


def test_capacidades_con_tipo_raro_es_error(tmp_path):
    v = vault_demo(tmp_path)
    ruta = _evidencia(v, "2026-11-17")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["script"] = "si"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ValueError, match="script"):
        capacidades_vigentes(v)


# --- HTML_SONDA ------------------------------------------------------------------------------------


def test_html_sonda_lleva_las_marcas_y_el_relleno_al_final():
    for trozo in ("<style>#tf-sonda{color:rgb(1,2,3)}</style>", "<title>tf-sonda</title>",
                  '<div id="tf-sonda">tf-sonda</div>', 'dataset.ok="1"</script>'):
        assert trozo in HTML_SONDA
    assert len(HTML_SONDA) > 200_000
    assert HTML_SONDA.index("</script>") < 1_000  # un recorte deja intacto lo que se mide
    assert HTML_SONDA.rstrip().endswith("-->")


# --- empaquetar_en_linea ---------------------------------------------------------------------------


def test_empaquetar_en_linea(tmp_path):
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    html = (raiz / "index.html").read_text(encoding="utf-8")
    version = re.search(r'data-tf-version="([0-9a-f]{12})"', html).group(1)
    out = empaquetar_en_linea(raiz)
    assert "assets/" not in out
    assert out.count("<script") == 1 and UTM_JS.read_text(encoding="utf-8").strip() in out
    assert f'data-tf-version="{version}"' in out
    assert out.count('<main id="tf-landing"') == 1
    assert "<title>Somatix · Спокойно тяло за 14 дни</title>" in out
    assert 'name="description"' in out and "<style>" in out
    assert (raiz / "assets" / "estilo.css").read_text(encoding="utf-8").strip()[:40] in out
    # las vistas previas (fuera del hero) van solo con la de 480 px
    imgs = re.findall(r"<img[^>]*>", out)
    assert len(imgs) == 2 and all("srcset" not in i and "sizes=" not in i for i in imgs)
    datos = (raiz / "assets" / "vista-p1-480.webp").read_bytes()
    assert f"data:image/webp;base64,{base64.b64encode(datos).decode()}" in out
    assert "<link" not in out and "<!DOCTYPE" not in out.upper()


def test_empaquetar_hero_conserva_srcset(tmp_path):
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    ruta = raiz / "index.html"
    html = ruta.read_text(encoding="utf-8")
    img = ('<img src="assets/vista-p1-480.webp" srcset="assets/vista-p1-480.webp 480w, assets/vista-p1-960.webp '
           '960w" sizes="100vw" alt="x">')
    html = html.replace('data-tf-tipo="hero">', f'data-tf-tipo="hero">\n  {img}', 1)
    ruta.write_text(html, encoding="utf-8")
    out = empaquetar_en_linea(raiz)
    hero = re.search(r'data-tf-tipo="hero">.*?</section>', out, re.DOTALL).group(0)
    assert hero.count("data:image/webp;base64,") == 3 and " 960w" in hero and "sizes=" in hero


def test_empaquetar_url_en_css(tmp_path):
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    css = raiz / "assets" / "estilo.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n.x{background:url('vista-p2-480.webp')}\n", encoding="utf-8")
    out = empaquetar_en_linea(raiz)
    assert "url('data:image/webp;base64," in out


def test_empaquetar_asset_que_falta_es_error(tmp_path):
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    (raiz / "assets" / "vista-p2-480.webp").unlink()
    with pytest.raises(ValueError, match="vista-p2-480.webp"):
        empaquetar_en_linea(raiz)


def test_empaquetar_no_sigue_enlaces(tmp_path):
    v = montar(tmp_path)
    raiz = ruta_landing(v, P, "ZZ")
    fuera = tmp_path / "fuera.webp"
    fuera.write_bytes(b"ajeno")
    (raiz / "assets" / "vista-p2-480.webp").unlink()
    (raiz / "assets" / "vista-p2-480.webp").symlink_to(fuera)
    with pytest.raises(ValueError, match="enlace"):
        empaquetar_en_linea(raiz)


# --- mapa y sonda (lo que pasa antes de abrir el navegador) ---------------------------------------


def _no_abrir(*_a, **_k):
    raise AssertionError("no debía abrir el navegador")


def test_mapa_impultienda_sin_confirmar(tmp_path):
    m = mapa_impultienda(vault_demo(tmp_path))
    assert m["pantallas"]["diseno_contenido"]["capturado"] is None


def test_sonda_sin_confirmar_no_medido(tmp_path):
    v = vault_demo(tmp_path)
    with pytest.raises(MapaSinConfirmar, match="no medido: mapa sin confirmar") as e:
        sondear(v, P, "ZZ", "https://tienda.demo.test", True, abrir=_no_abrir)
    assert "trovefy landing capturar" in str(e.value)
    assert not (ruta_landing(v, P, "ZZ") / "respaldo").exists()


def _mapa_confirmado() -> dict:
    m = cargar_mapa(hosting.MAPA_IMPULTIENDA)
    m["pantallas"]["diseno_contenido"]["capturado"] = "2026-11-17"
    return m


def test_sonda_url_de_otro_host_rechazada(tmp_path):
    v = vault_demo(tmp_path)
    with pytest.raises(ValueError, match="app.impultienda.ar"):
        sondear(v, P, "ZZ", "https://tienda.demo.test", True, url_pantalla="https://otro.test/diseno",
                mapa=_mapa_confirmado(), abrir=_no_abrir)


@pytest.mark.parametrize("url", ["http://app.impultienda.ar/x", "https://app.impultienda.ar:8443/x"])
def test_sonda_url_mismo_host_otro_origen_rechazada(tmp_path, url):
    with pytest.raises(ValueError):
        sondear(vault_demo(tmp_path), P, "ZZ", "https://tienda.demo.test", True, url_pantalla=url,
                mapa=_mapa_confirmado(), abrir=_no_abrir)


@pytest.mark.parametrize("tienda", ["http://tienda.demo.test", "ftp://x", "tienda.demo.test"])
def test_sonda_tienda_https(tmp_path, tienda):
    with pytest.raises(ValueError, match="https"):
        sondear(vault_demo(tmp_path), P, "ZZ", tienda, True, mapa=_mapa_confirmado(), abrir=_no_abrir)


# --- tienda en mercados.yaml (resolución 24) ------------------------------------------------------


def test_guardar_tienda_flujo(tmp_path):
    v = vault_demo(tmp_path)
    assert guardar_tienda(v, "ZY", "https://ro.tienda.test", AHORA) is True
    texto = (v / "config" / "mercados.yaml").read_text(encoding="utf-8")
    datos = yaml.safe_load(texto)
    assert datos["ZY"]["tienda"] == "https://ro.tienda.test"
    assert datos["ZZ"]["tienda"] == "https://tienda.demo.test"  # el otro país, intacto
    assert "usuario, 2026-11-17" in texto
    assert guardar_tienda(v, "ZY", "https://ro.tienda.test", AHORA) is False  # ya estaba


def test_guardar_tienda_bloque_conserva_comentarios(tmp_path):
    v = vault_demo(tmp_path)
    ruta = v / "config" / "mercados.yaml"
    ruta.write_text("# Mercados semilla\n\nZZ:\n  idioma: bg\n  moneda: EUR\n  zona: Europe/Sofia\n"
                    "  banda_eur: [9, 19]\n  estado: activo\n  tienda: null\n  dataset: null\n\n"
                    "ZY:\n  idioma: ro\n  moneda: EUR\n  zona: Europe/Bucharest\n  banda_eur: [9, 19]\n"
                    "  estado: activo\n  tienda: null\n", encoding="utf-8")
    assert guardar_tienda(v, "ZZ", "https://tienda.demo.test/", AHORA) is True
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("# Mercados semilla\n")
    datos = yaml.safe_load(texto)
    assert datos["ZZ"]["tienda"] == "https://tienda.demo.test" and datos["ZY"]["tienda"] is None
    assert datos["ZZ"]["dataset"] is None


def test_guardar_tienda_distinta_no_pisa(tmp_path):
    v = vault_demo(tmp_path)
    antes = (v / "config" / "mercados.yaml").read_bytes()
    with pytest.raises(ValueError, match="ya tiene"):
        guardar_tienda(v, "ZZ", "https://otra.tienda.test", AHORA)
    assert (v / "config" / "mercados.yaml").read_bytes() == antes


@pytest.mark.parametrize("tienda", ["http://x.test", "https://x.test/ruta", "https://x"])
def test_guardar_tienda_invalida(tmp_path, tienda):
    with pytest.raises(ValueError):
        guardar_tienda(vault_demo(tmp_path), "ZY", tienda, AHORA)


# --- CLI ----------------------------------------------------------------------------------------


def test_cli_sonda_sin_confirmar_sale_1(entorno, capsys):
    args = ["landing", "sonda", "--producto", P, "--pais", "ZZ", "--tienda", "https://tienda.demo.test",
            "--dominio-propio", "si"]
    assert cli.main(args) == 1
    err = capsys.readouterr().err
    assert "no medido: mapa sin confirmar" in err


def test_cli_preparar_usa_la_sonda(entorno, tmp_path, monkeypatch, capsys):
    from trovefy import landing_cli

    monkeypatch.setattr(landing_cli, "_cache", lambda: tmp_path / "cache")
    _evidencia(entorno, "2026-11-17")
    assert cli.main(["landing", "preparar", "--producto", P, "--pais", "ZZ"]) == 0
    ly = yaml.safe_load((ruta_landing(entorno, P, "ZZ") / "landing.yaml").read_text(encoding="utf-8"))
    assert ly["hosting"] == "impultienda" and ly["checkout_url"] == "/checkout"


def test_capacidades_es_inmutable():
    with pytest.raises(AttributeError):
        CAPACIDADES_FASE0.script = True  # type: ignore[misc]
    assert isinstance(CAPACIDADES_FASE0, Capacidades)


# --- la sonda con páginas falsas (sin navegador) -------------------------------------------------

URL_PANEL = "https://app.impultienda.ar/dashboard/diseno/contenido"
ORIGINAL = "<h1>Mi tienda</h1>\n<p>Contenido del usuario</p>"


class TiendaFalsa:
    """El servidor de Impultienda: guarda lo que se pega (con sus manías) y lo sirve en la tienda."""

    def __init__(self, contenido=ORIGINAL, recorte=None, sin_script=False, marco=False, firma=True,
                 restaura=True):
        self.contenido, self.recorte, self.sin_script, self.marco = contenido, recorte, sin_script, marco
        self.firma, self.restaura = firma, restaura
        self.posts: list[str] = []

    def guardar(self, html: str) -> None:
        self.posts.append(html)
        if not self.restaura and len(self.posts) > 1:
            return  # el segundo guardado no llega
        if self.sin_script:
            html = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)
        if self.recorte:
            html = html[: self.recorte]
        self.contenido = html

    def panel(self) -> PaginaFalsa:
        texto = "Diseño de tienda\nHTML completo de la tienda\nGuardar cambios" if self.firma else "Diseño de tienda"
        area = ElementoFalso(self.contenido)
        p = PaginaFalsa(texto=texto, elementos={"textarea": [area], "Guardar cambios": [ElementoFalso()]},
                        al_pulsar=lambda _p, _clave: self.guardar(area.valor))
        ir = p.goto

        def goto(url, **kw):
            ir(url, **kw)
            area.valor = self.contenido  # recargar enseña lo guardado

        p.goto = goto
        return p

    def publica(self):
        return PaginaTiendaFalsa(self)


class _Marco:
    def __init__(self, r):
        self.r = r

    def evaluate(self, _js):
        return self.r


class PaginaTiendaFalsa:
    def __init__(self, t: TiendaFalsa):
        self.t = t
        self.visitas: list[str] = []

    def goto(self, url, **_kw):
        self.visitas.append(url)
        c = self.t.contenido
        r = None if 'id="tf-sonda"' not in c else {
            "ok": "<script>" in c, "color": COLOR if "<style>" in c else "rgb(0, 0, 0)",
            "fuera": 120 if self.t.marco else 0}
        self.main_frame = _Marco(r)
        self.frames = [self.main_frame]

    def title(self):
        return "tf-sonda" if "<title>tf-sonda</title>" in self.t.contenido else "Mi tienda"


COLOR = hosting.COLOR_SONDA


def abridor(t: TiendaFalsa, sesiones: list):
    @contextmanager
    def abrir(servicio, visible=True, perfil_persistente=True, viewport=None):
        assert servicio == "impultienda"
        sesiones.append(perfil_persistente)
        yield t.panel() if perfil_persistente else t.publica()
    return abrir


def sondar(v, t, sesiones=None, **kw):
    sesiones = [] if sesiones is None else sesiones
    return sondear(v, P, "ZZ", "https://tienda.demo.test", True, mapa=_mapa_confirmado(),
                   abrir=abridor(t, sesiones), dormir=lambda _s: None, ahora=AHORA, **kw)


def test_sondear_todo_bien_y_restaura(tmp_path):
    v, t, sesiones = vault_demo(tmp_path), TiendaFalsa(), []
    c = sondar(v, t, sesiones)
    assert (c.html_propio, c.script, c.estilos, c.titulo_propio, c.sin_marco) == (True,) * 5
    assert c.limite_caracteres is None and c.dominio_propio is True and c.fecha == "2026-11-17"
    assert c.url_pantalla == URL_PANEL and c.tienda == "https://tienda.demo.test"
    assert t.contenido == ORIGINAL and t.posts == [HTML_SONDA, ORIGINAL]
    assert sesiones == [True, False, True]  # panel con perfil, tienda sin perfil, panel para restaurar
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17.html"
    assert respaldo.read_text(encoding="utf-8") == ORIGINAL
    ev = json.loads((v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json").read_text(encoding="utf-8"))
    assert ev["script"] is True and "Mi tienda" not in json.dumps(ev) and "cookie" not in json.dumps(ev).lower()
    assert capacidades_vigentes(v) == c
    assert elegir_hosting(c).ruta == "impultienda"


def test_sondear_detecta_recorte(tmp_path):
    t = TiendaFalsa(recorte=50_000)
    c = sondar(vault_demo(tmp_path), t)
    assert c.limite_caracteres == 50_000 and c.script is True
    assert t.contenido == ORIGINAL


def test_sondear_script_quitado_es_false(tmp_path):
    t = TiendaFalsa(sin_script=True)
    c = sondar(vault_demo(tmp_path), t)
    assert c.script is False and c.estilos is True and c.limite_caracteres is None
    assert elegir_hosting(c).ruta == "cloudflare"
    assert t.contenido == ORIGINAL


def test_sondear_con_marco_es_false(tmp_path):
    c = sondar(vault_demo(tmp_path), TiendaFalsa(marco=True))
    assert c.sin_marco is False and c.html_propio is True


def test_sondear_firma_ausente_no_toca(tmp_path):
    v, t = vault_demo(tmp_path), TiendaFalsa(firma=False)
    with pytest.raises(FirmaNoCasa, match="--url"):
        sondar(v, t)
    assert t.posts == [] and t.contenido == ORIGINAL
    assert not (ruta_landing(v, P, "ZZ") / "respaldo").exists()


def test_sondear_restaurar_que_no_queda_igual(tmp_path):
    v, t = vault_demo(tmp_path), TiendaFalsa(restaura=False)
    with pytest.raises(NavegadorError, match="no pude restaurar el contenido: pégalo tú desde .*respaldo"):
        sondar(v, t)
    assert not list((v / "config").glob("evidencia/p05-impultienda-*.json"))


def test_sondear_campo_con_sonda_anterior(tmp_path):
    t = TiendaFalsa(contenido=HTML_SONDA)
    with pytest.raises(NavegadorError, match="sonda anterior"):
        sondar(vault_demo(tmp_path), t)
    assert t.posts == []


def test_sondear_contenido_con_secreto_no_toca(tmp_path):
    v = vault_demo(tmp_path)
    t = TiendaFalsa(contenido="<p>EAAB" + "x7Kq2" * 8 + "</p>")
    with pytest.raises(ValueError, match="secreto"):
        sondar(v, t)
    assert t.posts == [] and not (ruta_landing(v, P, "ZZ") / "respaldo").exists()


def test_sondear_no_pisa_un_respaldo_del_mismo_dia(tmp_path):
    v = vault_demo(tmp_path)
    sondar(v, TiendaFalsa())
    sondar(v, TiendaFalsa(contenido="<p>otro</p>"))
    carpeta = ruta_landing(v, P, "ZZ") / "respaldo"
    assert (carpeta / "impultienda-2026-11-17.html").read_text(encoding="utf-8") == ORIGINAL
    assert (carpeta / "impultienda-2026-11-17-2.html").read_text(encoding="utf-8") == "<p>otro</p>"
