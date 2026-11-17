"""Tarea 6 del plan 18: evaluación pura de la QA, `QA.md` y `utm_intactos` (sin navegador: mediciones fijas)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy import cli, landing_cli
from trovefy.landing import qa
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
CLIC_BIEN = Clic("http://127.0.0.1:8000/checkout" + UTM_PRUEBA, None)


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
    r = _ev(clic=Clic("http://127.0.0.1:8000/checkout?utm_source=fb", None))
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
    assert _ev(publicada=True).ok


def test_local_no_mira_la_respuesta():
    assert not any(f[0].startswith("Respuesta") for f in _ev().filas)


def test_render_qa_golden(tmp_path):
    d = cargar(vault_demo(tmp_path))
    meds = [_med("movil"), _med("escritorio", lcp_ms=[800.0, 850.0, 820.0], peso_bytes=190_000)]
    r = _ev(meds)
    texto = render_qa(d, r, meds, AHORA, None, clic=CLIC_BIEN, version=VERSION)
    assert texto == GOLDEN.read_text(encoding="utf-8")


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

    def __init__(self, lcp=(1000.0, 1100.0, 1050.0)):
        self.lcp = list(lcp)
        self.llamadas: list[tuple] = []

    def medir(self, url, vista, captura, permitidos, red_4g, silenciar=()):
        self.llamadas.append(("medir", url, vista, permitidos, red_4g, silenciar))
        captura.parent.mkdir(parents=True, exist_ok=True)
        captura.write_bytes(b"\x89PNG falso")
        return _med(vista, lcp_ms=self.lcp, captura=captura, hitos=self.hitos, version_servida=self.version)

    def clic(self, url, checkout_url, interceptar=True):
        self.llamadas.append(("clic", url, checkout_url, interceptar))
        return Clic(url.rsplit("/", 1)[0] + "/checkout" + UTM_PRUEBA, None, intactos=True)


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
    falso.version = qa.version_guardada(v, cargar(v))
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
    falso = Falso()
    falso.hitos, falso.version = _hitos(), qa.version_guardada(v, cargar(v))
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    qa.ejecutar_qa(v, cargar(v))
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert all(set(x[5]) == {"connect.facebook.net", "www.facebook.com"} for x in medidas)
    assert next(x for x in falso.llamadas if x[0] == "clic")[2] == "https://tienda.demo.test/checkout"


def test_ejecutar_qa_publicada_mide_la_url(montada):
    v, falso = montada
    qa.ejecutar_qa(v, cargar(v), url="https://ejemplo-demo.test/")
    medidas = [x for x in falso.llamadas if x[0] == "medir"]
    assert all(x[1] == "https://ejemplo-demo.test/" and x[3] == ("ejemplo-demo.test",) for x in medidas)
    meta, _ = frontmatter.leer(ruta_landing(v, P, "ZZ") / "QA.md")
    assert meta["url"] == "https://ejemplo-demo.test/"


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
