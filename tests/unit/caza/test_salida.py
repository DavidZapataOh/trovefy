import csv
import pathlib
import re
import sqlite3

from ejemplos import ejecucion_ejemplo, ejecucion_fuente_caida
from trovify.caza.salida import escribir, formatear_medida, render_ficha, render_informe
from trovify.caza.senales import Medida
from trovify.vault.andamio import crear_vault
from trovify.vault.frontmatter import leer, renderizar

GOLD = pathlib.Path(__file__).resolve().parents[2] / "golden/caza"


def test_formatear():
    assert formatear_medida(Medida(60, suelo=True)) == "≥ 60"
    assert formatear_medida(Medida(0.625)) == "0,625"
    assert formatear_medida(Medida(None, "primera caza")) == "no medido: primera caza"
    assert formatear_medida(Medida(None, "no medido: primera caza")) == "no medido: primera caza"
    assert formatear_medida(Medida(2.5, suelo=True)) == "≥ 2,5"
    assert formatear_medida(Medida(3, "desde 2026-11-09")) == "3 (desde 2026-11-09)"


def test_golden_informe():
    assert render_informe(ejecucion_ejemplo()) == (GOLD / "europa.md").read_text()


def test_golden_ficha():
    meta, cuerpo = render_ficha(ejecucion_ejemplo().resultados[0], None)
    assert meta["paises"]["RO"]["link_biblioteca"].startswith("https://www.facebook.com/ads/library/")
    assert cuerpo == (GOLD / "o-ejemplo.md").read_text()


def test_anti_mineria_fuente_caida():
    texto = render_informe(ejecucion_fuente_caida())
    assert texto == (GOLD / "europa_fuente_caida.md").read_text()
    assert "bloqueado" in texto
    fila_c8 = next(linea for linea in texto.splitlines() if linea.startswith("| C8"))
    assert "no medido" in fila_c8 and not re.search(r"\d", fila_c8.split("|")[2])


def test_informe_cierra_con_la_decision_del_usuario():
    for e in (ejecucion_ejemplo(), ejecucion_fuente_caida()):
        texto = render_informe(e)
        assert texto.rstrip("\n").endswith("La decisión de modelar es tuya: escríbela en veredicto.md")
        assert "pendiente: la confirma /modelar" in texto
        assert "Tres señales" in texto


def test_ficha_contrato_frontmatter():
    meta, _ = render_ficha(ejecucion_ejemplo().resultados[0], None)
    for clave in ("tipo", "fecha", "fuente", "oferta_id", "page_ids", "original_page_id", "origen", "checkout",
                  "gateway", "dominio", "paises", "idiomas", "precio", "moneda", "estado", "motivo",
                  "primera_vez", "ultima_vez", "banderas"):
        assert clave in meta, clave
    assert meta["tipo"] == "oferta" and meta["estado"] == "B" and meta["oferta_id"] == "o-ejemplo"
    ro = meta["paises"]["RO"]
    assert ro["c8"] == 15 and ro["total"] == 32 and ro["edad_max"] is None  # no medido = null
    assert meta["fuente"] == ro["link_biblioteca"]


def test_ficha_no_medido_es_null_y_conserva_lo_previo():
    caida = ejecucion_fuente_caida().resultados[0]
    previa = {"tipo": "oferta", "primera_vez": "2026-11-01", "strikes": 1,
              "paises": {"IT": {"c8": 20, "total": 40, "edad_max": 30, "link_biblioteca": "https://www.facebook.com/ads/library/?x"}},
              "idiomas": ["it"]}
    meta, cuerpo = render_ficha(caida, previa)
    assert meta["paises"]["RO"]["c8"] is None and meta["paises"]["RO"]["total"] is None
    assert meta["paises"]["IT"]["c8"] == 20  # otros países se conservan
    assert meta["primera_vez"] == "2026-11-01" and meta["ultima_vez"] == "2026-11-10"
    assert meta["strikes"] == 1  # claves ajenas (vigilar) se conservan
    assert meta["precio"] is None and "no medido" in cuerpo


def test_cota_inferior_queda_marcada_en_la_ficha():
    import dataclasses
    r = ejecucion_ejemplo().resultados[0]
    r = dataclasses.replace(r, senales=dataclasses.replace(r.senales, c8=Medida(60, suelo=True)))
    meta, cuerpo = render_ficha(r, None)
    assert meta["paises"]["RO"]["c8"] == 60 and "c8" in meta["paises"]["RO"]["cota_inferior"]
    assert "≥ 60" in cuerpo


def test_el_verificador_02_acepta_la_ficha(tmp_path):
    from trovify.arranque.verificadores.caza import verificar_caza
    v = tmp_path / "v"
    crear_vault(v)
    meta, cuerpo = render_ficha(ejecucion_ejemplo().resultados[0], None)
    (v / "wiki/ofertas/o-ejemplo.md").write_text(renderizar(meta, cuerpo), encoding="utf-8")
    assert verificar_caza(v).ok


def test_escribir_competidores_y_entidades(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v, ejecucion_ejemplo())
    assert list((v / "wiki/competidores").glob("*.md"))
    assert (v / "data/caza/palabras.csv").read_text().splitlines()[0].startswith("palabra,pais,resultados")
    meta, _ = leer(v / "wiki/competidores/100000000000001.md")
    assert meta["tipo"] == "competidor" and meta["c7"] == 10 and meta["total"] == 20
    assert meta["ofertas"] == ["o-ejemplo"] and meta["fuente"].startswith("https://www.facebook.com/ads/library/")
    entidades = (v / "wiki/entidades.md").read_text()
    assert "o-ejemplo" in entidades and "100000000000002" in entidades


def test_escribir_todas_las_salidas(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    rutas = escribir(v, ejecucion_ejemplo())
    rel = {p.relative_to(v).as_posix() for p in rutas}
    for esperado in ("raw/2026-11-10/caza-europa.md", "wiki/caza/2026-11-10/europa.md",
                     "wiki/caza/2026-11-10/veredicto.md", "wiki/ofertas/o-ejemplo.md",
                     "wiki/ofertas/o-tienda-ejemplo.md", "data/caza/snapshots.sqlite",
                     "data/caza/historico.csv", "data/caza/tasas.csv", "data/caza/palabras.csv"):
        assert esperado in rel, esperado
    assert "Decisión del usuario: pendiente" in (v / "wiki/caza/2026-11-10/veredicto.md").read_text()
    meta, cuerpo = leer(v / "wiki/caza/2026-11-10/europa.md")
    assert meta["tipo"] == "caza" and cuerpo == render_informe(ejecucion_ejemplo())
    index = (v / "index.md").read_text()
    for enlace in ("[[wiki/caza/2026-11-10/europa]]", "[[wiki/caza/2026-11-10/veredicto]]",
                   "[[wiki/ofertas/o-ejemplo]]", "[[wiki/competidores/100000000000001]]"):
        assert index.count(enlace) == 1, enlace
    log = (v / "log.md").read_text().splitlines()
    assert sum("cazar" in linea for linea in log) == 1
    hist = list(csv.DictReader((v / "data/caza/historico.csv").open()))
    assert {(h["oferta_id"], h["decision"]) for h in hist} == {("o-ejemplo", "B"), ("o-tienda-ejemplo", "descartada")}
    tasas = list(csv.DictReader((v / "data/caza/tasas.csv").open()))
    assert tasas[0]["tasa_senal"] == "1" and tasas[0]["tasa_modelo"] == "0.5" and tasas[0]["B"] == "1"
    palabras = list(csv.DictReader((v / "data/caza/palabras.csv").open()))
    assert palabras[0]["candidatos"] == "2" and palabras[0]["modelables"] == "1"


def test_snapshot_solo_cifras_exactas(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v, ejecucion_ejemplo())
    escribir(v, ejecucion_fuente_caida())
    con = sqlite3.connect(v / "data/caza/snapshots.sqlite")
    filas = {f[0]: f[1:] for f in con.execute(
        "SELECT oferta_id, total, activos, c7, c8, nuevos, parados, fuente FROM snapshots")}
    assert filas["o-ejemplo"][:4] == (32, 32, 16, 15)
    assert filas["o-ejemplo"][6].startswith("https://www.facebook.com/ads/library/")
    assert filas["o-caida-ejemplo"][:6] == (None,) * 6  # nada medido = NULL, nunca 0


def test_raw_inmutable_y_veredicto_no_se_pisa(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v, ejecucion_ejemplo())
    veredicto = v / "wiki/caza/2026-11-10/veredicto.md"
    veredicto.write_text(veredicto.read_text().replace("pendiente", "modelo o-ejemplo"))
    primero = (v / "raw/2026-11-10/caza-europa.md").read_text()
    escribir(v, ejecucion_ejemplo())
    escribir(v, ejecucion_ejemplo())
    assert (v / "raw/2026-11-10/caza-europa.md").read_text() == primero
    assert (v / "raw/2026-11-10/caza-europa-2.md").exists() and (v / "raw/2026-11-10/caza-europa-3.md").exists()
    assert "modelo o-ejemplo" in veredicto.read_text()
    assert (v / "index.md").read_text().count("[[wiki/ofertas/o-ejemplo]]") == 1
    assert len((v / "wiki/entidades.md").read_text().split("- o-ejemplo ·")) == 2


def test_sin_medios_de_terceros(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v, ejecucion_ejemplo())
    for p in v.rglob("*"):
        assert p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}


def test_lint_sin_problemas_nuevos(tmp_path):
    from trovify.vault.lint import lint
    v = tmp_path / "v"
    crear_vault(v)
    antes = {(p.tipo, p.ruta) for p in lint(v)}
    escribir(v, ejecucion_ejemplo())
    nuevos = [p for p in lint(v) if (p.tipo, p.ruta) not in antes]
    assert nuevos == []
