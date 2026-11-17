"""Tarea 8 del plan 18: capacidades de Impultienda, elección de hosting, empaquetado en línea y lo que la
sonda comprueba antes de abrir el navegador (sin Chromium: lo que lo usa está en tests/integracion)."""

import base64
import io
import json
import re
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
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
    assert out.endswith("</script>")  # L-6: sin salto final (un textarea lo puede comer y cambiar el SHA-256)


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


CONFIRMADA = "https://app.impultienda.ar/dashboard/tienda/123/diseno?tab=contenido"


def confirmar_en_vault(v: Path, url: str = CONFIRMADA) -> None:
    """La confirmación que deja `trovefy landing capturar` (en la configuración de trovefy, con su captura PNG en
    config/evidencia/ del vault), con una terminal de prueba."""
    import types
    from unittest import mock

    from trovefy.tienda import confirmacion

    ev = "config/evidencia/p05-diseno-contenido-2026-11-17.png"
    (v / ev).parent.mkdir(parents=True, exist_ok=True)
    (v / ev).write_bytes(b"\x89PNG\r\n\x1a\n captura")
    falso = types.SimpleNamespace(stdin=_Tty(100), stdout=_Tty(101))
    with mock.patch.object(confirmacion, "sys", falso), mock.patch.object(confirmacion.os, "isatty", lambda _fd: True):
        confirmacion.confirmar_pantalla(v, "impultienda", cargar_mapa(hosting.MAPA_IMPULTIENDA), "diseno_contenido",
                                        url, "sí", AHORA)


def test_sonda_url_distinta_de_la_confirmada_para(tmp_path):
    """I-2: con la confirmación del usuario, --url tiene que ser la URL confirmada."""
    v = vault_demo(tmp_path)
    confirmar_en_vault(v)
    with pytest.raises(ValueError, match="esa URL no es la que confirmaste: vuelve a capturar"):
        sondear(v, P, "ZZ", "https://tienda.demo.test", True,
                url_pantalla="https://app.impultienda.ar/dashboard/tienda/999/diseno", abrir=_no_abrir)
    assert not (ruta_landing(v, P, "ZZ") / "respaldo").exists()


def test_preparar_mapa_con_la_url_confirmada_vale(tmp_path):
    from trovefy.landing.panel import preparar_mapa

    v = vault_demo(tmp_path)
    confirmar_en_vault(v)
    for url in (None, CONFIRMADA, CONFIRMADA + "#ancla"):
        m = preparar_mapa(v, url_pantalla=url)
        assert m["pantallas"]["diseno_contenido"]["url"] == CONFIRMADA


class _Tty(io.StringIO):
    def __init__(self, fd: int):
        super().__init__()
        self.fd = fd

    def fileno(self):
        return self.fd


def test_cli_capturar_sin_terminal_se_niega(entorno, monkeypatch, capsys):
    """`trovefy landing capturar` exige una persona en una terminal (stdin y stdout TTY)."""
    from trovefy.landing import panel
    from trovefy.tienda.confirmacion import ruta_confirmaciones

    def nunca(*_a, **_k):
        raise AssertionError("no debía abrir nada")

    monkeypatch.setattr(panel, "capturar_pantalla", nunca)
    monkeypatch.setattr("sys.stdin", io.StringIO("sí\n"))  # una tubería: sin descriptor de terminal
    assert cli.main(["landing", "capturar"]) == 2
    assert "ejecútalo tú en tu terminal" in capsys.readouterr().err
    assert not ruta_confirmaciones().exists()


@pytest.mark.parametrize(("stdin", "stdout"), [(False, True), (True, False)])
def test_cli_capturar_con_una_sola_tty_se_niega(entorno, monkeypatch, stdin, stdout):
    from trovefy.landing import panel

    from .conftest import con_terminal

    monkeypatch.setattr(panel, "capturar_pantalla", lambda *_a, **_k: pytest.fail("no debía abrir nada"))
    con_terminal(monkeypatch, stdin, stdout)
    assert cli.main(["landing", "capturar"]) == 2


def test_cli_capturar_con_terminal_confirma(entorno, monkeypatch, capsys):
    from trovefy.landing import panel

    from .conftest import con_terminal

    llamadas = []

    def falso(vault, url=None, **_k):
        llamadas.append(url)
        return {"fecha": "2026-11-17", "url": CONFIRMADA}

    monkeypatch.setattr(panel, "capturar_pantalla", falso)
    con_terminal(monkeypatch)
    assert cli.main(["landing", "capturar"]) == 0 and llamadas == [None]


def test_capturar_pantalla_sin_terminal_no_abre(tmp_path):
    import inspect

    from trovefy.landing.panel import capturar_pantalla
    from trovefy.tienda.confirmacion import ruta_confirmaciones

    v = vault_demo(tmp_path)
    assert "terminal" not in inspect.signature(capturar_pantalla).parameters  # nada que inyectar (F1-1)
    with pytest.raises(ValueError, match="terminal"):
        capturar_pantalla(v, abrir=_no_abrir, preguntar=lambda _t: "sí", esperar=lambda _t: None)
    assert not ruta_confirmaciones().exists()


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
                 restaura=True, tras_pegar=None, al_restaurar=None, fallo_tienda=None, vaciar=False,
                 hosts=()):
        self.contenido, self.recorte, self.sin_script, self.marco = contenido, recorte, sin_script, marco
        self.firma, self.restaura = firma, restaura
        self.tras_pegar = tras_pegar  # excepción tras guardar lo pegado (el clic ya se hizo)
        self.al_restaurar = al_restaurar  # excepción en el guardado de la restauración (antes de guardar)
        self.fallo_tienda = fallo_tienda  # excepción al abrir la tienda pública
        self.vaciar = vaciar  # el primer guardado deja el campo vacío
        self.hosts = tuple(hosts)  # hosts que carga la tienda pública
        self.posts: list[str] = []

    def guardar(self, html: str) -> None:
        if self.al_restaurar is not None and self.posts:
            raise self.al_restaurar
        self.posts.append(html)
        if not self.restaura and len(self.posts) > 1:
            return  # el segundo guardado no llega
        if self.sin_script:
            html = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)
        if self.recorte:
            html = html[: self.recorte]
        if self.vaciar and len(self.posts) == 1:
            html = ""
        self.contenido = html
        if self.tras_pegar is not None and len(self.posts) == 1:
            raise self.tras_pegar

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


class _Peticion:
    def __init__(self, url):
        self.url = url


class PaginaTiendaFalsa:
    def __init__(self, t: TiendaFalsa):
        self.t = t
        self.visitas: list[str] = []
        self.oyentes: dict[str, list] = {}

    def on(self, evento, f):
        self.oyentes.setdefault(evento, []).append(f)

    def goto(self, url, **_kw):
        self.visitas.append(url)
        if self.t.fallo_tienda is not None:
            raise self.t.fallo_tienda
        for h in (urlsplit(url).hostname, *self.t.hosts):
            for f in self.oyentes.get("request", []):
                f(_Peticion(f"https://{h}/recurso.js"))
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
    respaldo = ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17T103000.html"
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
    assert (carpeta / "impultienda-2026-11-17T103000.html").read_text(encoding="utf-8") == ORIGINAL
    assert (carpeta / "impultienda-2026-11-17T103000-2.html").read_text(encoding="utf-8") == "<p>otro</p>"


# --- T: una excepción después de pegar siempre restaura ------------------------------------------


def _sin_evidencia(v: Path) -> bool:
    return not list((v / "config").glob("evidencia/p05-impultienda-*.json"))


def test_sondear_parada_de_pulsar_tras_guardar_restaura(tmp_path):
    from trovefy.tienda.conductor import Parada, VentanaNueva

    v, t = vault_demo(tmp_path), TiendaFalsa(tras_pegar=VentanaNueva("diseno_contenido", "se abrió otra ventana"))
    with pytest.raises(Parada, match="otra ventana"):
        sondar(v, t)
    assert t.contenido == ORIGINAL and t.posts == [HTML_SONDA, ORIGINAL]
    assert _sin_evidencia(v)


def test_sondear_fallo_al_medir_la_tienda_restaura(tmp_path):
    v, t = vault_demo(tmp_path), TiendaFalsa(fallo_tienda=RuntimeError("red caída"))
    with pytest.raises(NavegadorError, match="no se pudo abrir la tienda"):
        sondar(v, t)
    assert t.contenido == ORIGINAL and t.posts == [HTML_SONDA, ORIGINAL]
    assert _sin_evidencia(v)


@pytest.mark.parametrize("donde", ["tras_pegar", "fallo_tienda"])
def test_sondear_ctrl_c_restaura(tmp_path, donde):
    v, t = vault_demo(tmp_path), TiendaFalsa(**{donde: KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        sondar(v, t)
    assert t.contenido == ORIGINAL and t.posts == [HTML_SONDA, ORIGINAL]
    assert _sin_evidencia(v)


def test_restaurar_interrumpido_dice_de_donde_pegarlo(tmp_path, capsys):
    """L-1: un Ctrl-C a media restauración sigue su curso, pero antes dice de dónde pegar lo de antes."""
    v, t = vault_demo(tmp_path), TiendaFalsa(fallo_tienda=RuntimeError("x"), al_restaurar=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        sondar(v, t)
    err = capsys.readouterr().err
    assert "pégalo tú desde" in err and "respaldo/impultienda-2026-11-17T103000.html" in err
    assert t.contenido == HTML_SONDA  # no llegó a restaurarse: por eso se dice


# --- I-5: una sonda anterior a medias se reconoce por cualquiera de sus marcas -------------------


def _respaldos(v: Path) -> Path:
    carpeta = ruta_landing(v, P, "ZZ") / "respaldo"
    carpeta.mkdir(parents=True)
    for nombre in ("impultienda-2026-11-16.html", "impultienda-2026-11-17.html", "impultienda-2026-11-17-2.html",
                   "impultienda-2026-11-15-9.html"):
        (carpeta / nombre).write_text("<p>antes</p>", encoding="utf-8")
    return carpeta


@pytest.mark.parametrize("contenido", [HTML_SONDA, HTML_SONDA[:50_000], HTML_SONDA[:30],
                                       '<h1>Mi tienda</h1><div id="tf-sonda">tf-sonda</div>',
                                       "<p>hola</p><!-- relleno-tf-sonda relleno-tf-sonda"])
def test_sondear_campo_con_sonda_colgada(tmp_path, contenido):
    v = vault_demo(tmp_path)
    _respaldos(v)
    t = TiendaFalsa(contenido=contenido)
    with pytest.raises(NavegadorError, match="sonda anterior") as e:
        sondar(v, t)
    assert str(ruta_landing(v, P, "ZZ") / "respaldo" / "impultienda-2026-11-17-2.html") in str(e.value)
    assert t.posts == []


def test_sondear_sonda_colgada_sin_respaldos(tmp_path):
    t = TiendaFalsa(contenido=HTML_SONDA[:1000])
    with pytest.raises(NavegadorError, match="sonda anterior") as e:
        sondar(vault_demo(tmp_path), t)
    assert "no hay respaldos" in str(e.value)


def test_un_prefijo_corto_cualquiera_no_es_sonda():
    from trovefy.landing.hosting import es_sonda_colgada

    assert not es_sonda_colgada("") and not es_sonda_colgada("<") and not es_sonda_colgada("<style>")
    assert not es_sonda_colgada(ORIGINAL)
    assert es_sonda_colgada(HTML_SONDA[:16])


# --- L-3 -----------------------------------------------------------------------------------------


def test_sondear_relectura_vacia_no_es_un_limite(tmp_path):
    t = TiendaFalsa(vaciar=True)
    c = sondar(vault_demo(tmp_path), t)
    assert c.limite_caracteres is None and c.html_propio is False
    assert elegir_hosting(c).ruta == "cloudflare"
    assert t.contenido == ORIGINAL


def test_capacidades_ignora_evidencia_futura(tmp_path):
    v = vault_demo(tmp_path)
    _evidencia(v, "2026-11-17", script=True)
    _evidencia(v, "2026-11-18", script=False)
    assert capacidades_vigentes(v, hoy=date(2026, 11, 17)).fecha == "2026-11-17"
    assert capacidades_vigentes(v, hoy=date(2026, 11, 18)).fecha == "2026-11-18"
    _evidencia(v, "2999-01-01", script=False)
    assert capacidades_vigentes(v).fecha != "2999-01-01"  # sin `hoy`, la fecha de negocio


# --- I-4: la sonda anota qué hosts carga la tienda ---------------------------------------------


def test_sondear_anota_los_hosts_de_la_tienda(tmp_path):
    v = vault_demo(tmp_path)
    t = TiendaFalsa(hosts=("cdn.tiendas.test", "connect.facebook.net", "tienda.demo.test"))
    c = sondar(v, t)
    assert c.hosts_tienda == ("cdn.tiendas.test", "tienda.demo.test")  # sin los de Meta, ordenados
    ev = json.loads((v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json").read_text(encoding="utf-8"))
    assert ev["hosts_tienda"] == ["cdn.tiendas.test", "tienda.demo.test"]
    assert capacidades_vigentes(v, hoy=date(2026, 11, 17)) == c


def test_evidencia_vieja_sin_hosts_vale(tmp_path):
    v = vault_demo(tmp_path)
    ruta = _evidencia(v, "2026-11-17")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("hosts_tienda", None)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert capacidades_vigentes(v, hoy=date(2026, 11, 17)).hosts_tienda == ()


@pytest.mark.parametrize("hosts", ["cdn.test", [1], ["con espacio"], ["https://x.test/"]])
def test_evidencia_con_hosts_raros_es_error(tmp_path, hosts):
    v = vault_demo(tmp_path)
    ruta = _evidencia(v, "2026-11-17")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["hosts_tienda"] = hosts
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ValueError, match="hosts_tienda"):
        capacidades_vigentes(v, hoy=date(2026, 11, 17))


# --- F2-1: restaurar solo si el campo tiene lo que se pegó ----------------------------------------


class TiendaQueCambia(TiendaFalsa):
    """Mientras se mide la tienda, el usuario cambia el campo a mano."""

    def publica(self):
        self.contenido = "<p>lo que el usuario puso entretanto</p>"
        return super().publica()


def test_sondear_campo_cambiado_antes_de_restaurar_no_pega(tmp_path):
    from trovefy.landing.panel import CampoCambiado

    v, t = vault_demo(tmp_path), TiendaQueCambia()
    with pytest.raises(CampoCambiado) as e:
        sondar(v, t)
    assert t.posts == [HTML_SONDA]  # no se pegó nada encima
    assert t.contenido == "<p>lo que el usuario puso entretanto</p>"
    carpeta = ruta_landing(v, P, "ZZ") / "respaldo"
    antes, ahora = carpeta / "impultienda-2026-11-17T103000.html", carpeta / "impultienda-2026-11-17T103000-2.html"
    assert antes.read_text(encoding="utf-8") == ORIGINAL
    assert ahora.read_text(encoding="utf-8") == "<p>lo que el usuario puso entretanto</p>"
    assert str(antes) in str(e.value) and str(ahora) in str(e.value)
    assert _sin_evidencia(v)


def test_sondear_recorte_restaura_lo_releido(tmp_path):
    """Con recorte, el campo tiene lo releído (no lo pegado): también es «lo que se pegó»."""
    t = TiendaFalsa(recorte=50_000)
    sondar(vault_demo(tmp_path), t)
    assert t.contenido == ORIGINAL


# --- F2-3: el último respaldo de la tienda del país, de cualquier producto -------------------------


def test_ultimo_respaldo_busca_en_todos_los_productos_y_ordena_por_hora(tmp_path):
    from trovefy.landing.panel import ultimo_respaldo

    v = vault_demo(tmp_path)
    a = v / "productos" / P / "landing" / "ZZ" / "respaldo"
    b = v / "productos" / "p-0100-otro" / "landing" / "ZZ" / "respaldo"
    c = v / "productos" / "p-0101-ro" / "landing" / "ZY" / "respaldo"
    for carpeta, nombres in ((a, ["impultienda-2026-11-17.html", "impultienda-2026-11-17-3.html",
                                  "impultienda-2026-11-17T090000.html"]),
                             (b, ["impultienda-2026-11-17T153000.html", "impultienda-2026-11-16T235959.html"]),
                             (c, ["impultienda-2026-12-01T000000.html"])):
        carpeta.mkdir(parents=True)
        for n in nombres:
            (carpeta / n).write_text("x", encoding="utf-8")
    assert ultimo_respaldo(v, "ZZ") == b / "impultienda-2026-11-17T153000.html"
    assert ultimo_respaldo(v, "zy") == c / "impultienda-2026-12-01T000000.html"
    assert ultimo_respaldo(v, "ZX") is None


def test_sonda_colgada_senala_el_respaldo_de_otro_producto(tmp_path):
    v = vault_demo(tmp_path)
    otro = v / "productos" / "p-0100-otro" / "landing" / "ZZ" / "respaldo"
    otro.mkdir(parents=True)
    (otro / "impultienda-2026-11-17T090000.html").write_text("<p>antes</p>", encoding="utf-8")
    t = TiendaFalsa(contenido=HTML_SONDA[:40])
    with pytest.raises(NavegadorError, match="sonda anterior") as e:
        sondar(v, t)
    assert str(otro / "impultienda-2026-11-17T090000.html") in str(e.value)
