"""Tarea 6 del plan 18: evaluación pura de la QA, `QA.md` y `utm_intactos` (sin navegador: mediciones fijas)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy import cli, landing_cli
from trovefy.landing import qa
from trovefy.landing.constantes import HOSTS_META
from trovefy.landing.entrada import ruta_landing
from trovefy.landing.qa import (
    UTM_PRUEBA,
    Clic,
    Medicion,
    ResultadoQA,
    evaluar,
    render_qa,
    utm_intactos,
)
from trovefy.landing.validar import Resultado
from trovefy.vault import frontmatter

from .conftest import P, cargar, vault_demo
from .test_validar import montar

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "landing" / "QA-zz.md"
VERSION = "a1b2c3d4e5f6"
VALIDA = Resultado(True, (), ())
AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
CLIC_BIEN = Clic("http://127.0.0.1:8000/checkout" + UTM_PRUEBA, None, intactos=True)


def _wf(n: int = 15) -> list[dict]:
    return [{"orden": i, "tipo": "x", "palabras": 10, "cta": False, "y_rel": round((i - 1) / n, 3)}
            for i in range(1, n + 1)]


def _hitos(n: int = 15) -> dict[int, float]:
    return {i: round((i - 1) / n + 0.01, 3) for i in range(1, n + 1)}


def _med(vista: str = "movil", **kw) -> Medicion:
    base = {"vista": vista, "lcp_ms": [1200.0, 1300.0, 1250.0], "peso_bytes": 184_320, "peticiones_externas": (),
            "ancho_scroll": 390 if vista == "movil" else 1280, "desborde_selector": None, "hitos": _hitos(),
            "captura": Path(f"qa/{vista}-{VERSION}.png"), "motivo": None, "http": 200, "version_servida": VERSION}
    return Medicion(**(base | kw))


def _ev(mediciones=None, clic=CLIC_BIEN, nativo=("ok", VERSION), validacion=VALIDA, wf=None,
        publicada=False) -> ResultadoQA:
    if mediciones is None:
        mediciones = [_med("movil"), _med("escritorio")]
    return evaluar(validacion, mediciones, clic, wf or _wf(), nativo, VERSION, publicada)


def _fila(r: ResultadoQA, empieza: str) -> tuple[str, str, str]:
    filas = [f for f in r.filas if f[0].startswith(empieza)]
    assert filas, [f[0] for f in r.filas]
    return filas[0]


def _estados(r: ResultadoQA) -> set[str]:
    return {f[1] for f in r.filas}


def test_qa_todo_verde():
    r = _ev()
    assert r.ok and _estados(r) == {"OK"}, r.filas


def test_lcp_mediana_2600_falla():
    r = _ev([_med("movil", lcp_ms=[2400.0, 2600.0, 2700.0]), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "LCP")
    assert fila[1] == "FALLA" and "2.600 ms" in fila[2]


def test_lcp_de_escritorio_no_es_gate():
    r = _ev([_med("movil"), _med("escritorio", lcp_ms=[3000.0, 3100.0, 3200.0])])
    assert r.ok


def test_lcp_sin_dato_no_medido_bloquea():
    r = _ev([_med("movil", lcp_ms=None, motivo="el navegador no dio LCP"), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "LCP")
    assert fila[1] == "NO MEDIDO" and "el navegador no dio LCP" in fila[2]


def test_peso_sin_dato_no_medido_bloquea():
    r = _ev([_med("movil", peso_bytes=None, motivo="sin respuesta"), _med("escritorio")])
    assert not r.ok and _fila(r, "Peso (movil)")[1] == "NO MEDIDO"


def test_qa_desborde_movil_falla():
    r = _ev([_med("movil", ancho_scroll=412, desborde_selector="table.comparativa"), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "Desborde (movil)")
    assert fila[1] == "FALLA" and "table.comparativa" in fila[2] and "412" in fila[2]


def test_hito_desviado_es_aviso():
    h = _hitos()
    h[8] = round(h[8] + 0.15, 3)
    h[9], h[10] = round(h[8] + 0.01, 3), round(h[8] + 0.02, 3)  # el orden se mantiene
    r = _ev([_med("movil", hitos=h), _med("escritorio")])
    assert r.ok
    fila = _fila(r, "Hitos (movil)")
    assert fila[1] == "AVISO" and "sección 8" in fila[2]


def test_hitos_en_otro_orden_falla():
    h = _hitos()
    h[2], h[3] = h[3], h[2]
    r = _ev([_med("movil", hitos=h), _med("escritorio")])
    assert not r.ok and _fila(r, "Hitos (movil)")[1] == "FALLA"


def test_hito_ausente_falla():
    h = _hitos()
    del h[5]
    r = _ev([_med("movil", hitos=h), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "Hitos (movil)")
    assert fila[1] == "FALLA" and "5" in fila[2]


def test_peticion_externa_falla():
    r = _ev([_med("movil", peticiones_externas=("https://externo.test/a.webp",)), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "Peticiones externas (movil)")
    assert fila[1] == "FALLA" and "https://externo.test/a.webp" in fila[2]


def test_clic_sin_utm_falla():
    r = _ev(clic=Clic("http://127.0.0.1:8000/checkout?utm_source=fb", None, intactos=False))
    assert not r.ok and _fila(r, "Clic")[1] == "FALLA"


def test_clic_fuera_del_checkout_falla():
    r = _ev(clic=Clic("http://127.0.0.1:8000/otra" + UTM_PRUEBA, None, intactos=False))
    assert not r.ok and _fila(r, "Clic")[1] == "FALLA"


def test_clic_sin_dato_no_medido():
    r = _ev(clic=Clic(None, "no hay a[data-tf-checkout]"))
    assert not r.ok
    fila = _fila(r, "Clic")
    assert fila[1] == "NO MEDIDO" and "a[data-tf-checkout]" in fila[2]


def test_nativo_de_otra_version_no_medido():
    r = _ev(nativo=("ok", "000000000000"))
    assert not r.ok
    fila = _fila(r, "Idioma")
    assert fila[1] == "NO MEDIDO" and "000000000000" in fila[2]


def test_nativo_ausente_no_medido():
    r = _ev(nativo=None)
    assert not r.ok and _fila(r, "Idioma")[1] == "NO MEDIDO"


def test_nativo_corregir_falla():
    r = _ev(nativo=("corregir", VERSION))
    assert not r.ok and _fila(r, "Idioma")[1] == "FALLA"


def test_validacion_con_fallos_falla():
    r = _ev(validacion=Resultado(False, ("falta assets/estilo.css",), ()))
    assert not r.ok
    fila = _fila(r, "Validación")
    assert fila[1] == "FALLA" and "estilo.css" in fila[2]


def test_publicada_exige_200_y_la_version():
    r = _ev([_med("movil", http=404), _med("escritorio", version_servida="ffffffffffff")], publicada=True)
    assert not r.ok
    assert _fila(r, "Respuesta (movil)")[1] == "FALLA"
    assert _fila(r, "Versión servida (escritorio)")[1] == "FALLA"
    from trovefy.landing.qa import UTM_PUBLICADA

    assert _ev(publicada=True, clic=Clic("https://ejemplo-demo.test/checkout" + UTM_PUBLICADA, None,
                                         intactos=True)).ok


def test_local_no_mira_la_respuesta():
    assert not any(f[0].startswith("Respuesta") for f in _ev().filas)


def test_render_qa_golden(tmp_path):
    """Las capturas, como en `ejecutar_qa`: en `landing/<PAIS>/qa/` y relativas a `productos/<p-id>/`."""
    from trovefy.vault.producto import ruta_producto

    v = vault_demo(tmp_path)
    d = cargar(v)
    qa_dir = ruta_landing(v, P, "ZZ") / "qa"
    meds = [_med("movil", captura=qa_dir / f"movil-{VERSION}.png"),
            _med("escritorio", lcp_ms=[800.0, 850.0, 820.0], peso_bytes=190_000,
                 captura=qa_dir / f"escritorio-{VERSION}.png")]
    r = _ev(meds)
    texto = render_qa(d, r, meds, AHORA, None, clic=CLIC_BIEN, version=VERSION,
                      raiz_producto=ruta_producto(v, P).parent)
    assert texto == GOLDEN.read_text(encoding="utf-8")
    assert "  captura: landing/ZZ/qa/movil-a1b2c3d4e5f6.png\n" in texto
    assert "  fuente: landing/ZZ/QA.md\n" in texto  # M5: de dónde sale utm_checkout


# --- ronda de revisión T6–7 -----------------------------------------------------------------------


def test_desborde_con_culpable_falla_aunque_scrollwidth_cuadre():
    """I3: con ``overflow-x: hidden`` en html/body el scrollWidth no crece; manda el elemento que sale."""
    r = _ev([_med("movil", ancho_scroll=390, desborde_selector="table.comparativa"), _med("escritorio")])
    assert not r.ok
    fila = _fila(r, "Desborde (movil)")
    assert fila[1] == "FALLA" and "table.comparativa" in fila[2]


@pytest.mark.parametrize("peso", [0, -1])
def test_peso_cero_no_medido(peso):
    """M3: un peso de 0 bytes no es una medida (la página no se descargó o no hubo tamaños)."""
    r = _ev([_med("movil", peso_bytes=peso), _med("escritorio")])
    assert not r.ok and _fila(r, "Peso (movil)")[1] == "NO MEDIDO"


def test_clic_sin_intactos_no_medido():
    """M2: sin `intactos` (nadie comparó con el checkout de landing.yaml) no hay medida."""
    r = _ev(clic=Clic("http://127.0.0.1:8000/checkout" + UTM_PRUEBA, None))
    assert not r.ok and _fila(r, "Clic")[1] == "NO MEDIDO"


def test_version_servida_tambien_en_local():
    """I4: la QA local también comprueba que la página medida es la versión guardada."""
    r = _ev([_med("movil", version_servida="ffffffffffff"), _med("escritorio")])
    assert not r.ok and _fila(r, "Versión servida (movil)")[1] == "FALLA"
    r = _ev([_med("movil", version_servida=None), _med("escritorio")])
    assert not r.ok and _fila(r, "Versión servida (movil)")[1] == "NO MEDIDO"
    assert _fila(_ev(), "Versión servida (escritorio)")[1] == "OK"


def test_publicada_sin_fbclid():
    """M6: la QA publicada no lleva `fbclid` (no genera eventos falsos para Meta)."""
    from trovefy.landing.qa import UTM_PUBLICADA

    assert "fbclid" not in UTM_PUBLICADA and UTM_PRUEBA.startswith(UTM_PUBLICADA)
    bien = Clic("https://ejemplo-demo.test/checkout" + UTM_PUBLICADA, None, intactos=True)
    assert _ev(clic=bien, publicada=True).ok
    con_fbclid = Clic("https://ejemplo-demo.test/checkout" + UTM_PRUEBA, None, intactos=True)
    r = _ev(clic=con_fbclid, publicada=True)
    assert not r.ok and _fila(r, "Clic")[1] == "FALLA" and "fbclid" in _fila(r, "Clic")[2]
    assert not _ev(clic=bien, publicada=False).ok  # en local, sí: UTM_PRUEBA con fbclid


def test_perfil_4g_de_devtools():
    """M1: Slow 4G ajustado como DevTools (latencia ×3,75; caudal ×0,9)."""
    from trovefy.landing import constantes as k

    assert k.LATENCIA_MS == 562.5
    assert k.BAJADA_BPS == round(1.6 * 1024 * 1000 * 0.9) and k.SUBIDA_BPS == round(750 * 1000 * 0.9)
    assert qa.perfil_red() == "4G simulado: 562,5 ms, 1,47 Mbit/s bajada, 0,68 Mbit/s subida, CPU ×4"


def test_pagina_abre_contexto_movil_sin_service_workers(monkeypatch):
    """M1 + I5: móvil con is_mobile y DPR 2; en las dos vistas, service workers bloqueados."""
    from contextlib import contextmanager

    import trovefy.navegador

    vistas = []

    @contextmanager
    def sesion_falsa(servicio, **kw):
        vistas.append((servicio, kw))
        yield object()

    monkeypatch.setattr(trovefy.navegador, "sesion", sesion_falsa)
    for vista in ("movil", "escritorio"):
        with qa._pagina(vista):
            pass
    (s1, movil), (_, escritorio) = vistas
    assert s1 == qa.SERVICIO_QA and movil["perfil_persistente"] is False
    assert movil["viewport"] == (390, 844)
    assert movil["_contexto"] == {"service_workers": "block", "is_mobile": True, "has_touch": True,
                                  "device_scale_factor": 2}
    assert escritorio["_contexto"] == {"service_workers": "block"}


def test_utm_intactos():
    q = UTM_PRUEBA
    assert utm_intactos("https://x.test/checkout" + q, "/checkout", "https://x.test/index.html")
    assert utm_intactos("https://t.test/checkout?p=1&" + q[1:], "https://t.test/checkout", "https://x.test/")
    assert not utm_intactos("https://x.test/checkout" + q.replace("&fbclid=QA", ""), "/checkout", "https://x.test")
    assert not utm_intactos("https://x.test/otra" + q, "/checkout", "https://x.test")
    assert not utm_intactos("https://y.test/checkout" + q, "/checkout", "https://x.test")
    assert not utm_intactos("https://x.test/checkout" + q.replace("QA%7C0", "QA%7C1", 1), "/checkout", "https://x.test")


# --- ejecutar_qa y la CLI con un medidor falso ---------------------------------------------------


class Falso:
    """Sustituye a `medir` y `probar_clic`: anota las llamadas y escribe una captura de mentira."""

    def __init__(self, lcp=(1000.0, 1100.0, 1050.0), peticiones=()):
        self.lcp = list(lcp)
        self.llamadas: list[tuple] = []
        self.peticiones = list(peticiones)  # lo que pediría la página, pasado por la política real de la QA

    def medir(self, url, vista, captura, permitidos, red_4g, silenciar=(), propios=()):
        self.llamadas.append(("medir", url, vista, permitidos, red_4g, silenciar, propios))
        captura.parent.mkdir(parents=True, exist_ok=True)
        captura.write_bytes(b"\x89PNG falso")
        clases = {p: qa.clasificar_peticion(p, permitidos, silenciar, propios) for p in self.peticiones}
        return _med(vista, lcp_ms=self.lcp, captura=captura, hitos=self.hitos, version_servida=self.version,
                    peticiones_externas=tuple(p for p, c in clases.items() if c == "externa"),
                    peticiones_propias=tuple(p for p, c in clases.items() if c == "propia"))

    def clic(self, url, checkout_url, interceptar=True, utm=UTM_PRUEBA):
        self.llamadas.append(("clic", url, checkout_url, interceptar, utm))
        return Clic(url.rsplit("/", 1)[0] + "/checkout" + utm, None, intactos=True)


@pytest.fixture
def montada(tmp_path, monkeypatch):
    v = montar(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from .conftest import Ejecutar

    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    falso = Falso()
    wf = qa.leer_hitos_esperados(v, cargar(v))
    falso.hitos = {s["orden"]: s["y_rel"] + 0.001 for s in wf}
    falso.version = qa.version_guardada(v, P, "ZZ")
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    return v, falso


def test_ejecutar_qa_local_escribe_qa_md(montada):
    v, falso = montada
    d = cargar(v)
    r = qa.ejecutar_qa(v, d)
    assert not r.ok  # sin veredicto del nativo
    assert _fila(r, "Idioma")[1] == "NO MEDIDO"
    raiz = ruta_landing(v, P, "ZZ")
    meta, _ = frontmatter.leer(raiz / "QA.md")
    assert meta["tipo"] == "qa_landing" and meta["pais"] == "ZZ" and meta["ok"] is False and meta["url"] is None
    assert meta["version"] == falso.version
    assert meta["movil_390"] == {"http": 200, "captura": f"landing/ZZ/qa/movil-{falso.version}.png"}
    assert meta["utm_checkout"]["interceptado"] is True and meta["utm_checkout"]["ok"] is True
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert {x[2] for x in medidas} == {"movil", "escritorio"}
    assert all(x[1].startswith("http://127.0.0.1:") and x[3] == ("127.0.0.1",) for x in medidas)
    assert [x[4] for x in medidas if x[2] == "movil"] == [True]
    assert (raiz / "qa" / f"movil-{falso.version}.png").is_file()
    assert "QA" in (v / "log.md").read_text(encoding="utf-8")


def test_ejecutar_qa_cloudflare_silencia_el_pixel(tmp_path, monkeypatch):
    v = montar(tmp_path, hosting="cloudflare")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))  # T3: ni el HOME ni el vault reales
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    falso = Falso()
    falso.hitos, falso.version = _hitos(), qa.version_guardada(v, P, "ZZ")
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    qa.ejecutar_qa(v, cargar(v))
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert all(set(x[5]) == set(HOSTS_META) and x[6] == () for x in medidas)
    assert next(x for x in falso.llamadas if x[0] == "clic")[2] == "https://tienda.demo.test/checkout"


def test_ejecutar_qa_publicada_mide_la_url(montada):
    v, falso = montada
    qa.ejecutar_qa(v, cargar(v), url="https://ejemplo-demo.test/")
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert all(x[1] == "https://ejemplo-demo.test/" and x[3] == ("ejemplo-demo.test",) for x in medidas)
    meta, _ = frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA-publicada.md")
    assert meta["url"] == "https://ejemplo-demo.test/"
    clic = next(x for x in falso.llamadas if x[0] == "clic")
    assert clic[1] == "https://ejemplo-demo.test/" and "fbclid" not in clic[4]  # M6
    assert "fbclid" not in meta["utm_checkout"]["destino"] and meta["utm_checkout"]["ok"] is True


def test_ejecutar_qa_local_lleva_fbclid(montada):
    v, falso = montada
    qa.ejecutar_qa(v, cargar(v))
    assert next(x for x in falso.llamadas if x[0] == "clic")[4] == UTM_PRUEBA


@pytest.mark.parametrize("url", [
    "http://ejemplo-demo.test/", "https://usuario@ejemplo-demo.test/", "https://u:clave@ejemplo-demo.test/",
    "https://ejemplo-demo.test:8443/", "https://127.0.0.1/", "https://[::1]/", "https://169.254.169.254/",
    "https://otro.test/", "https://ejemplo-demo.test.evil.test/", "https://zz.ejemplo-demo.test/",
    "file:///etc/passwd", "https:///sin-host", "https://2130706433/", "https://0x7f.0.0.1/",
])
def test_ejecutar_qa_rechaza_url_publicada_fuera_de_lo_nuestro(montada, url):
    """I2: solo https, sin usuario, puerto por defecto, sin IP y al dominio propio o la tienda."""
    from trovefy.landing.entrada import EntradaInvalida

    v, falso = montada
    with pytest.raises(EntradaInvalida):
        qa.ejecutar_qa(v, cargar(v), url=url)
    assert falso.llamadas == []
    assert not (ruta_landing(v, P, "ZZ") / "QA.md").exists()


@pytest.mark.parametrize("url", ["https://ejemplo-demo.test/", "https://EJEMPLO-demo.test:443/x",
                                 "https://tienda.demo.test/"])
def test_ejecutar_qa_admite_dominio_y_tienda_en_impultienda(montada, url):
    v, falso = montada
    qa.ejecutar_qa(v, cargar(v), url=url)
    assert falso.llamadas


def test_ejecutar_qa_cloudflare_admite_dominio_y_subdominio_del_pais(tmp_path, monkeypatch):
    from trovefy.landing.entrada import EntradaInvalida

    v = montar(tmp_path, hosting="cloudflare")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    falso = Falso()
    falso.hitos, falso.version = _hitos(), qa.version_guardada(v, P, "ZZ")
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    for url in ("https://ejemplo-demo.test/", "https://zz.ejemplo-demo.test/"):
        qa.ejecutar_qa(v, cargar(v), url=url)
    with pytest.raises(EntradaInvalida):  # en Cloudflare la landing no la sirve la tienda
        qa.ejecutar_qa(v, cargar(v), url="https://tienda.demo.test/")


def test_ejecutar_qa_sin_guardar_es_error(tmp_path):
    from trovefy.landing.entrada import EntradaInvalida

    v = vault_demo(tmp_path)
    with pytest.raises(EntradaInvalida, match="guardar"):
        qa.ejecutar_qa(v, cargar(v))


def test_cli_qa(montada, capsys):
    args = ["landing", "qa", "--producto", P, "--pais", "ZZ"]
    assert cli.main(args) == 1  # falta el veredicto del nativo
    out = capsys.readouterr().out
    assert "NO MEDIDO" in out and "QA.md" in out
    assert cli.main([*args, "--publicada"]) == 2  # sin url en landing.yaml
    assert "publicar" in capsys.readouterr().err


# --- I-4: política de peticiones por ruta en la QA publicada -------------------------------------

TERCERO = "https://tercero.test/rastreo.js"
TIENDA_CDN = "https://cdn.demo.test/tema.css"  # mismo dominio registrable que la tienda (tienda.demo.test)
META = "https://connect.facebook.net/en_US/fbevents.js"


@pytest.mark.parametrize(("url", "clase"), [
    ("https://ejemplo-demo.test/a.webp", "seguir"),
    (META, "silenciar"), ("https://www.facebook.com/tr?id=1", "silenciar"), ("https://scontent.fbcdn.net/x", "silenciar"),
    (TIENDA_CDN, "propia"), ("https://demo.test/x", "propia"), ("https://cdn.tiendas-cdn.test/app.js", "propia"),
    (TERCERO, "externa"), ("https://otro.tiendas-cdn.test/app.js", "externa"), ("https://demo.test.evil.test/", "externa"),
    ("https://facebook.com.evil.test/", "externa"),
])
def test_clasificar_peticion(url, clase):
    propios = (".demo.test", "cdn.tiendas-cdn.test")
    assert qa.clasificar_peticion(url, ("ejemplo-demo.test",), HOSTS_META, propios) == clase


class _Req:
    def __init__(self, url, method, page):
        self.url, self.method = url, method
        self.frame = type("F", (), {"page": page})()


class _Ruta:
    def __init__(self, req):
        self.request, self.hecho = req, None

    def abort(self):
        self.hecho = "abort"

    def continue_(self):
        self.hecho = "continue"


class _Ctx:
    def __init__(self):
        self.rutas = []

    def on(self, *_a):
        pass

    def route(self, _patron, f):
        self.rutas.append(f)


@pytest.mark.parametrize(("url", "metodo", "hecho"), [
    (TIENDA_CDN, "GET", "continue"), (TIENDA_CDN, "POST", "abort"), ("https://demo.test/carrito", "PUT", "abort"),
    ("https://ejemplo-demo.test/a.webp", "GET", "continue"), (TERCERO, "GET", "abort"),
])
def test_filtro_de_la_qa_publicada_solo_lee_de_la_tienda(url, metodo, hecho):
    """F2-4: en la QA publicada en Impultienda, a los hosts de la tienda solo se les hace GET (como probar_clic)."""
    page = type("P", (), {})()
    page.context = _Ctx()
    externas, propias = [], []
    qa._filtro(page, ("ejemplo-demo.test",), HOSTS_META, externas, (".demo.test",), propias)
    ruta = _Ruta(_Req(url, metodo, page))
    page.context.rutas[0](ruta)
    assert ruta.hecho == hecho


def test_fila_de_peticiones_de_la_tienda_es_aviso():
    r = _ev([_med("movil", peticiones_propias=(TIENDA_CDN,)), _med("escritorio")])
    assert _fila(r, "Peticiones de la tienda (movil)")[1] == "AVISO"
    assert _fila(r, "Peticiones externas (movil)")[1] == "OK"
    assert r.ok


def _publicada(tmp_path, monkeypatch, hosting, peticiones, hosts_tienda=()):
    import json
    from dataclasses import asdict, replace

    from trovefy.landing.hosting import CAPACIDADES_FASE0

    v = montar(tmp_path, hosting=hosting)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    c = replace(CAPACIDADES_FASE0, script=True, estilos=True, titulo_propio=True, sin_marco=True,
                dominio_propio=True, tienda="https://tienda.demo.test", fecha="2026-11-17", fuente="prueba",
                hosts_tienda=tuple(hosts_tienda))
    ruta = v / "config" / "evidencia" / "p05-impultienda-2026-11-17.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(asdict(c)), encoding="utf-8")
    falso = Falso(peticiones=peticiones)
    falso.hitos, falso.version = _hitos(), qa.version_guardada(v, P, "ZZ")
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    url = "https://ejemplo-demo.test/" if hosting == "impultienda" else "https://zz.ejemplo-demo.test/"
    return v, falso, qa.ejecutar_qa(v, cargar(v), url=url)


def test_qa_publicada_impultienda_tienda_aviso_tercero_falla(tmp_path, monkeypatch):
    """Ruling I-4: en Impultienda, lo de la tienda es AVISO, otro tercero es FALLA y Meta ni se cuenta."""
    v, falso, r = _publicada(tmp_path, monkeypatch, "impultienda", [TIENDA_CDN, TERCERO, META])
    for vista in ("movil", "escritorio"):
        fila = _fila(r, f"Peticiones de la tienda ({vista})")
        assert fila[1] == "AVISO" and "cdn.demo.test" in fila[2]
        fila = _fila(r, f"Peticiones externas ({vista})")
        assert fila[1] == "FALLA" and TERCERO in fila[2] and "facebook" not in fila[2] and "cdn.demo.test" not in fila[2]
    assert not r.ok
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert all(set(x[5]) == set(HOSTS_META) and ".demo.test" in x[6] for x in medidas)
    texto = (ruta_landing(v, P, "ZZ") / "QA-publicada.md").read_text(encoding="utf-8")
    assert "| Peticiones de la tienda (movil) | AVISO |" in texto


def test_qa_publicada_impultienda_solo_tienda_no_bloquea(tmp_path, monkeypatch):
    _, _, r = _publicada(tmp_path, monkeypatch, "impultienda", [TIENDA_CDN, META, "https://cdn.otra-cdn.test/a.js"],
                         hosts_tienda=["cdn.otra-cdn.test"])
    assert _fila(r, "Peticiones de la tienda (movil)")[1] == "AVISO"
    assert _fila(r, "Peticiones externas (movil)")[1] == "OK"


def test_qa_publicada_cloudflare_la_tienda_es_un_tercero(tmp_path, monkeypatch):
    _, falso, r = _publicada(tmp_path, monkeypatch, "cloudflare", [TIENDA_CDN, META])
    assert _fila(r, "Peticiones externas (movil)")[1] == "FALLA"
    assert not [f for f in r.filas if f[0].startswith("Peticiones de la tienda")]
    assert all(x[6] == () for x in falso.llamadas if x[0] == "medir")


def test_qa_local_impultienda_sin_propios(montada):
    v, falso = montada
    qa.ejecutar_qa(v, cargar(v))
    assert all(x[6] == () and set(x[5]) == set(HOSTS_META) for x in falso.llamadas if x[0] == "medir")


def test_qa_anota_el_manifiesto(montada):
    """I-6: QA.md lleva el manifiesto de los archivos medidos (index.html y assets/)."""
    from trovefy.landing.plantilla import manifiesto_landing

    v, _ = montada
    qa.ejecutar_qa(v, cargar(v))
    raiz = ruta_landing(v, P, "ZZ")
    assert frontmatter.leer(raiz / "QA.md")[0]["manifiesto"] == manifiesto_landing(raiz)


def test_hosts_propios_incluye_la_plataforma_de_impultienda(tmp_path, monkeypatch):
    """Impultienda sirve la tienda con sus fuentes, su almacenamiento de imágenes y la analítica de Cloudflare
    (QA publicada real de BG, 2026-11-17): son de la plataforma, no terceros añadidos por la landing."""
    from types import SimpleNamespace

    from trovefy.landing import hosting
    from trovefy.landing.constantes import casa_host

    monkeypatch.setattr(hosting, "capacidades_vigentes", lambda _v: (_ for _ in ()).throw(ValueError("x")))
    reglas = qa.hosts_propios(tmp_path, SimpleNamespace(tienda="https://somatika.impultienda.ar"))
    for host in ("fonts.googleapis.com", "fonts.gstatic.com", "static.cloudflareinsights.com",
                 "aekpgsbqjzqntlbucbts.supabase.co", "sb.impultienda.ar"):
        assert casa_host(host, reglas), host
    assert not casa_host("otro.supabase.co", reglas)
    assert not casa_host("tracker.example.com", reglas)
    assert qa.hosts_propios(tmp_path, SimpleNamespace(tienda=None)) == ()
