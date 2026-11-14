"""Render y escritura de OFERTA.md, ESCALERA.md, BRANDBOOK.md y comparativa.md (plan 16, Tarea 7)."""

import os
import pathlib
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy import secretos
from trovefy.config.mercados import cargar as cargar_mercados
from trovefy.economia.config import PLANTILLA, cargar_texto, costes_de
from trovefy.economia.escalera import escalera_pais
from trovefy.fx import Cambio
from trovefy.modelar.autopsia import puntuar, senal_se_puede_mejorar
from trovefy.modelar.esquema import cargar_modelado
from trovefy.modelar.salida import (
    cargar_brandbook,
    cargar_escalera,
    cargar_oferta,
    economia_pais,
    escribir_modelado,
    render_brandbook,
    render_comparativa,
    render_escalera,
    render_oferta,
)
from trovefy.vault import frontmatter
from trovefy.vault.producto import EstadoInesperado

P = "p-0042-kit-demo"
HOY = date(2026, 11, 13)
AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
CAMBIO = Cambio({"USD": 1.08, "RON": 4.977}, "2026-11-12")
RAIZ = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "fixtures/modelar/modelar-demo.yaml"
GOLDEN = RAIZ / "golden/modelar"
ARCHIVOS = ("OFERTA", "ESCALERA", "BRANDBOOK", "comparativa")
MERCADOS = """\
XE: {idioma: bg, moneda: EUR, zona: Zona demo, banda_eur: [11.90, 15.90], estado: activo}
XR: {idioma: ro, moneda: RON, zona: Zona demo, banda_eur: [11.90, 15.90], estado: activo}
"""


def _config(ruta_activa="impultienda_whop"):
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    datos["ruta_activa"]["valor"] = ruta_activa
    for campo in ("comision_pct", "comision_fija_usd", "impuestos_pct"):
        datos["plataformas"]["impultienda"][campo]["valor"] = 0
        datos["plataformas"]["whop"][campo]["valor"] = 0
    datos["plataformas"]["whop"]["comision_pct"]["valor"] = 0.10
    return cargar_texto(yaml.safe_dump(datos, allow_unicode=True))


def _modelado():
    return cargar_modelado(FIXTURE, P, "XE", "bg")


def _vault(tmp_path, xe="aprobado", xr="auditado"):
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / "config/mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    frontmatter.escribir(v / "wiki/ofertas/o-demo.md",
                         {"tipo": "oferta", "id": "o-demo", "dominio": "oferta-demo.test", "precio": 9.0,
                          "moneda": None}, "# Oferta demo\n")
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md",
                         {"tipo": "producto", "oferta_id": "o-demo",
                          "paises": {"XE": {"estado": xe}, "XR": {"estado": xr}}},
                         f"# Producto {P}\n")
    frontmatter.escribir(v / "productos" / P / "decisiones/2026-11-12-eleccion.md",
                         {"tipo": "decision", "pais": "XE", "reserva": "XR"}, "Elección.\n")
    return v


def _escribir(v, config=None, cambio=CAMBIO, precios=None):
    return escribir_modelado(v, P, _modelado(), config or _config(), cambio, precios or {}, HOY, AHORA)


def _piezas_y_autopsias():
    m, config = _modelado(), _config()
    original = puntuar(m.ejes_original, config.autopsia.pesos)
    nuestra = puntuar(m.ejes_nuestra, config.autopsia.pesos)
    senal = senal_se_puede_mejorar(original, nuestra, m.ejes_original, m.ejes_nuestra, config.autopsia)
    mercados = cargar_mercados_texto()
    escaleras = {
        "XE": escalera_pais(mercados["XE"], config.escalera, CAMBIO, (9.0, None), None, 1, None),
        "XR": escalera_pais(mercados["XR"], config.escalera, CAMBIO, (9.0, None), None, 1, None),
    }
    economias = {p: economia_pais(e, config, CAMBIO) for p, e in escaleras.items()}
    return m, config, original, nuestra, senal, escaleras, economias


def cargar_mercados_texto():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ruta = pathlib.Path(d) / "mercados.yaml"
        ruta.write_text(MERCADOS, encoding="utf-8")
        return cargar_mercados(ruta)


def _render_todos():
    m, config, original, nuestra, senal, escaleras, economias = _piezas_y_autopsias()
    return {
        "OFERTA": render_oferta(m, original, nuestra, senal, HOY, vende_por_presupuesto=True),
        "ESCALERA": render_escalera(escaleras, economias, CAMBIO, HOY, producto=P, piezas=m.escalera_piezas,
                                   costes=costes_de(config)),
        "BRANDBOOK": render_brandbook(m.brandbook, HOY, producto=P),
        "comparativa": render_comparativa(m, original, nuestra, escaleras, HOY),
    }


def test_golden_files():
    textos = _render_todos()
    for nombre, texto in textos.items():
        ruta = GOLDEN / f"{nombre}.md"
        if os.environ.get("UPDATE_GOLDEN"):
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(texto, encoding="utf-8")
        assert texto == ruta.read_text(encoding="utf-8"), nombre


def test_oferta_frontmatter_contrato():
    meta, _ = frontmatter_de(_render_todos()["OFERTA"])
    assert meta["tipo"] == "oferta" and meta["aprobacion"] == "presentada"
    assert meta["fuente"] == f"productos/{P}/modelar.yaml"
    assert meta["autopsia"]["original"]["nota"] == "56.5"
    assert meta["se_puede_mejorar"] is True
    core = meta["core"]
    assert core["avatar"] and core["angulo"]
    assert all(set(b) == {"nombre", "objecion"} for b in core["bonos"])
    assert core["garantia_dias"] == 30
    assert len(meta["estructura_landing"]) == 15
    assert meta["estructura_landing"][0] == {"orden": 1, "tipo": "hero", "palabras": 40, "cta": True}
    assert meta["teardown"]["checkout"]["precio"] == "9.00"
    assert meta["teardown"]["checkout"]["moneda"] is None


def frontmatter_de(texto):
    _, resto = texto.split("---\n", 1)
    yaml_txt, cuerpo = resto.split("\n---\n", 1)
    return yaml.safe_load(yaml_txt), cuerpo


def test_escalera_frontmatter_xe(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    paises = cargar_escalera(v, P)
    xe = paises["XE"]
    assert xe["moneda"] == "EUR" and xe["fuente_precio"] == "banda del país"
    assert xe["pasos"]["front"]["precio"] == "13.90"
    assert xe["pasos"]["front"]["titulo"] == "Подреден дом за 14 дни"
    assert xe["pasos"]["bump"]["activo"] is False
    assert "apagado en el test 1" in xe["pasos"]["bump"]["motivo_inactivo"]
    assert set(xe["pasos"]) == {"front", "bump", "u1", "u2", "u3", "downsell"}
    assert xe["be_usd"] == "14.58"
    assert xe["cpa_be_usd"] == xe["be_usd"]
    assert xe["cpa_test_usd"] == "7.29" and xe["cpa_escala_usd"] == "9.48" and xe["roas_be"] == "1.18"
    meta = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[0]
    assert meta["cambio"] == {"fuente": "BCE", "fecha": "2026-11-12", "url": CAMBIO.url}
    assert set(paises) == {"XE", "XR"}
    assert paises["XR"]["pasos"]["front"]["precio"] == "69"


def test_escalera_md_con_economia_no_medida(tmp_path):
    v = _vault(tmp_path)
    rutas = _escribir(v, config=_config(ruta_activa=None))
    assert (v / "productos" / P / "ESCALERA.md") in rutas
    xe = cargar_escalera(v, P)["XE"]
    assert xe["be_usd"] is None and "falta ruta_activa" in xe["be_usd_motivo"]
    assert xe["cpa_be_usd"] is None and "falta ruta_activa" in xe["cpa_be_usd_motivo"]
    assert xe["aov_usd"] == "17.16"
    assert xe["pasos"]["front"]["precio"] == "13.90"


def test_escalera_sin_cambio_no_medida(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, cambio=None)
    paises = cargar_escalera(v, P)
    assert paises["XE"]["pasos"]["front"]["precio"] == "13.90"
    assert paises["XE"]["be_usd"] is None and "USD" in paises["XE"]["be_usd_motivo"]
    assert paises["XR"]["pasos"] is None and "RON" in paises["XR"]["pasos_motivo"]
    meta = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[0]
    assert meta["cambio"]["fecha"] is None and meta["cambio"]["fecha_motivo"].startswith("no medido")


def test_no_cambia_estado(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    meta, cuerpo = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    assert meta["paises"]["XE"]["estado"] == "aprobado"
    assert meta["paises"]["XR"]["estado"] == "auditado"
    assert meta["oferta"] == {"aprobacion": "presentada", "fecha": "2026-11-13", "aprobacion_cita": None,
                              "aprobacion_fecha": None}
    assert meta["senales"]["se_puede_mejorar"] is True
    assert meta["senales"]["fuente"] == f"productos/{P}/OFERTA.md"
    for nombre in ARCHIVOS:
        assert f"[[productos/{P}/{nombre}]]" in cuerpo
    assert cargar_oferta(v, P)["aprobacion"] == "presentada"


def test_rehacer_en_modelado_versiona(tmp_path, capsys):
    v = _vault(tmp_path)
    _escribir(v)
    oferta = v / "productos" / P / "OFERTA.md"
    previa = oferta.read_text(encoding="utf-8").replace("aprobacion: presentada", "aprobacion: aprobada")
    oferta.write_text(previa, encoding="utf-8")
    meta, cuerpo = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    meta["paises"]["XE"]["estado"] = "modelado"
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", meta, cuerpo)
    capsys.readouterr()
    _escribir(v)
    assert "rehace" in capsys.readouterr().out
    versiones = v / "productos" / P / "versiones"
    for nombre in ARCHIVOS:
        assert (versiones / f"{nombre}-2026-11-13.md").is_file()
    assert (versiones / "OFERTA-2026-11-13.md").read_text(encoding="utf-8") == previa
    assert cargar_oferta(v, P)["aprobacion"] == "presentada"
    assert frontmatter.leer(v / "productos" / P / "PRODUCTO.md")[0]["paises"]["XE"]["estado"] == "modelado"
    _escribir(v)
    assert (versiones / "OFERTA-2026-11-13-2.md").is_file()


def test_rehacer_en_producido_se_niega(tmp_path):
    v = _vault(tmp_path, xe="producido")
    antes = sorted(p.relative_to(v) for p in v.rglob("*"))
    with pytest.raises(EstadoInesperado, match="producido"):
        _escribir(v)
    assert sorted(p.relative_to(v) for p in v.rglob("*")) == antes


def test_pais_auditado_se_niega(tmp_path):
    v = _vault(tmp_path, xe="auditado")
    with pytest.raises(EstadoInesperado, match="auditado"):
        _escribir(v)
    assert not (v / "productos" / P / "OFERTA.md").exists()


def test_log_una_linea(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    lineas = (v / "log.md").read_text(encoding="utf-8").splitlines()
    con_archivos = [linea for linea in lineas if "OFERTA.md" in linea and "ESCALERA.md" in linea]
    assert len(con_archivos) == 1
    assert "modelar" in con_archivos[0]
    assert all(f"productos/{P}/{n}.md" in con_archivos[0] for n in ARCHIVOS)
    # la otra línea es la de PRODUCTO.md (actualizar_producto)
    assert len(lineas) == 2


def test_brandbook_7_secciones_en_orden():
    texto = _render_todos()["BRANDBOOK"]
    meta, cuerpo = frontmatter_de(texto)
    titulos = [linea for linea in cuerpo.splitlines() if linea.startswith("## ")]
    assert titulos == ["## 1. Nombre local", "## 2. Paleta", "## 3. Tipografías", "## 4. Tono",
                       "## 5. Iconografía", "## 6. Mockup", "## 7. Tokens CSS"]
    assert "```css\n:root {\n" in cuerpo and "  --color-primario: #1F4E5F;\n" in cuerpo
    assert meta["nombre_local"] == "Подреден дом" and meta["tono"]
    assert [t["uso"] for t in meta["tipografias"]] == ["titulos", "texto"]
    assert meta["tokens_css"]["--fuente-texto"] == "'Noto Sans', sans-serif"
    assert "marca" not in meta


def test_comparativa_cierre_tacito():
    texto = _render_todos()["comparativa"]
    for titulo in ("## Qué ofrecía el original", "## Qué ofrecemos", "## Por qué es mejor"):
        assert titulo in texto
    assert "La nota de nuestra oferta la pone Claude: léela con ojo crítico." in texto
    assert texto.rstrip().endswith(
        "Si no la rechazas en esta sesión, queda aprobada (aprobación tácita) y seguimos con el producto.")
    alto = texto.index("Garantía de 30 días")
    medio = texto.index("Plazo cerrado de 14 días")
    assert alto < medio


def test_original_mas_barato_en_comparativa(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    texto = (v / "productos" / P / "comparativa.md").read_text(encoding="utf-8")
    assert "9,00" in texto
    assert "no medido (moneda del original no medida)" in texto
    assert "13,90 EUR" in texto


def test_sin_revision_de_secretos_no_escribe(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    m = _modelado()
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "no-hay"])
    with pytest.raises(secretos.RevisionSecretosNoDisponible):
        escribir_modelado(v, P, m, _config(), CAMBIO, {}, HOY, AHORA)
    assert not (v / "productos" / P / "OFERTA.md").exists()


def test_precio_manual_reserva(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, precios={"XR": Decimal(65)})
    xr = cargar_escalera(v, P)["XR"]
    assert xr["fuente_precio"] == "usuario" and xr["pasos"]["front"]["precio"] == "65"


def test_precio_manual_de_pais_ajeno(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="XZ"):
        _escribir(v, precios={"XZ": Decimal(65)})


def test_lectores_sin_archivo(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(FileNotFoundError, match="falta OFERTA.md: /modelar"):
        cargar_oferta(v, P)
    with pytest.raises(FileNotFoundError, match="falta ESCALERA.md: /modelar"):
        cargar_escalera(v, P)
    with pytest.raises(FileNotFoundError, match="falta BRANDBOOK.md: /modelar"):
        cargar_brandbook(v, P)


def test_brandbook_se_lee(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    assert cargar_brandbook(v, P)["nombre_local"] == "Подреден дом"



# --- ronda de revisión de la Tarea 7 ---------------------------------------------------------------

MERCADOS_XM = MERCADOS + "XM: {idioma: ro, moneda: MDL, zona: Zona demo, banda_eur: [11.90, 15.90], estado: activo}\n"


def _con_reserva(v, reserva):
    frontmatter.escribir(v / "productos" / P / "decisiones/2026-11-12-eleccion.md",
                         {"tipo": "decision", "pais": "XE", "reserva": reserva}, "Elección.\n")


def _ficha(v, **campos):
    meta = {"tipo": "oferta", "id": "o-demo", "dominio": "oferta-demo.test", **campos}
    (v / "wiki/ofertas/o-demo.md").write_text(
        "---\n" + yaml.safe_dump(meta, allow_unicode=True) + "---\n# Oferta demo\n", encoding="utf-8")


def _poner_estado(v, estado):
    meta, cuerpo = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    meta["paises"]["XE"]["estado"] = estado
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", meta, cuerpo)


@pytest.mark.parametrize("valor", [
    "url(https://evil.test/f)",
    'image-set("//evil.test/x" 1x)',
    "#fff /* x",
    "#fff\n```\n# Inyectado",
])
def test_render_brandbook_no_pinta_tokens_inseguros(valor):
    import dataclasses

    m = _modelado()
    b = dataclasses.replace(m.brandbook, tokens_css={**m.brandbook.tokens_css, "--color-acento": valor})
    with pytest.raises(ValueError, match="--color-acento"):
        render_brandbook(b, HOY, producto=P)


def test_reserva_fuera_de_mercados_no_bloquea(tmp_path):
    v = _vault(tmp_path)
    _con_reserva(v, "XQ")
    _escribir(v)
    paises = cargar_escalera(v, P)
    assert paises["XE"]["pasos"]["front"]["precio"] == "13.90"
    assert paises["XQ"]["pasos"] is None
    assert paises["XQ"]["pasos_motivo"] == "no medido: XQ no está en config/mercados.yaml"


def test_pais_elegido_fuera_de_mercados_si_bloquea(tmp_path):
    v = _vault(tmp_path)
    (v / "config/mercados.yaml").write_text(MERCADOS.splitlines()[1] + "\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="elección de país"):  # pais_elegido ya lo salta
        _escribir(v)
    assert not (v / "productos" / P / "OFERTA.md").exists()


@pytest.mark.parametrize("campos", [
    {"precio": "9 €", "moneda": "EUR"},
    {"moneda": "EUR"},
    {"precio": float("nan"), "moneda": "EUR"},
    {"precio": -9.0, "moneda": "EUR"},
    {"precio": 0, "moneda": "EUR"},
    {"precio": float("inf"), "moneda": "EUR"},
])
def test_precio_original_inservible_es_no_medido(tmp_path, campos):
    v = _vault(tmp_path)
    _ficha(v, **campos)
    _escribir(v)
    aviso = "comparación con el original: no medido (precio de la ficha no legible)"
    paises = cargar_escalera(v, P)
    for pais in ("XE", "XR"):
        assert aviso in paises[pais]["avisos"], pais


def test_precio_original_float_pasa_por_str(tmp_path):
    v = _vault(tmp_path)
    _ficha(v, precio=12.1, moneda="EUR")
    _escribir(v)
    avisos = cargar_escalera(v, P)["XE"]["avisos"]
    assert any("el original cuesta 12,10 €" in a for a in avisos)


@pytest.mark.parametrize(("precio", "esperado"), [(Decimal("13.9"), "13.90"), (Decimal(15), "15.00"),
                                                  (13.9, "13.90")])
def test_precio_manual_eur_con_centimos(tmp_path, precio, esperado):
    v = _vault(tmp_path)
    _escribir(v, precios={"XE": precio})
    assert cargar_escalera(v, P)["XE"]["pasos"]["front"]["precio"] == esperado


def test_cambio_sin_tasa_usa_motivos_por_campo(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, cambio=None)
    cambio = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[0]["cambio"]
    assert "motivo" not in cambio
    assert cambio["fecha"] is None and cambio["fecha_motivo"].startswith("no medido")
    assert cambio["url"] is None and cambio["url_motivo"].startswith("no medido")


def test_pasos_null_solo_motivo(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, cambio=None)
    xr = cargar_escalera(v, P)["XR"]
    assert xr["fuente_precio"] is None and "RON" in xr["fuente_precio_motivo"]
    cuerpo = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[1]
    seccion = cuerpo.split("## XR", 1)[1]
    assert "Precio del front" not in seccion and "### Economía" not in seccion
    assert xr["pasos_motivo"] in seccion


@pytest.mark.parametrize("estado", ["producido", "con_landing", "con_checkout", "listo"])
def test_rechazo_tras_modelado_dice_produccion(tmp_path, estado):
    v = _vault(tmp_path, xe=estado)
    with pytest.raises(EstadoInesperado, match="ya pasó a producción"):
        _escribir(v)


@pytest.mark.parametrize("estado", ["auditado", "descartado", "cazado"])
def test_rechazo_generico_nombra_el_estado(tmp_path, estado):
    v = _vault(tmp_path, xe=estado)
    with pytest.raises(EstadoInesperado) as exc:
        _escribir(v)
    assert estado in str(exc.value) and "producción" not in str(exc.value)


def test_reserva_mdl_sin_tasa_con_cambio(tmp_path):
    v = _vault(tmp_path)
    (v / "config/mercados.yaml").write_text(MERCADOS_XM, encoding="utf-8")
    _con_reserva(v, "XM")
    _escribir(v)
    paises = cargar_escalera(v, P)
    assert paises["XE"]["pasos"]["front"]["precio"] == "13.90"
    assert paises["XM"]["pasos"] is None and "MDL" in paises["XM"]["pasos_motivo"]
    assert paises["XM"]["be_usd"] is None
    meta = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[0]
    assert meta["cambio"] == {"fuente": "BCE", "fecha": "2026-11-12", "url": CAMBIO.url}


@pytest.mark.parametrize("llamada", [3, 4])
def test_secreto_en_texto_tardio_no_escribe_nada(tmp_path, monkeypatch, llamada):
    from trovefy.modelar import salida

    v = _vault(tmp_path)
    _escribir(v)
    _poner_estado(v, "modelado")
    carpeta = v / "productos" / P
    antes = {p: p.read_bytes() for p in v.rglob("*") if p.is_file()}
    llamadas = []

    def falso(texto):
        llamadas.append(texto)
        return "patron-demo" if len(llamadas) == llamada else None

    monkeypatch.setattr(salida, "buscar_secreto", falso)
    with pytest.raises(ValueError, match="patron-demo"):
        _escribir(v)
    assert not (carpeta / "versiones").exists()
    assert {p: p.read_bytes() for p in v.rglob("*") if p.is_file()} == antes


@pytest.mark.parametrize(("nota_media", "esperado"), [([45, 70], True), ([10, 20], False)])
def test_vende_por_presupuesto_en_escribir(tmp_path, nota_media, esperado):
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    datos["autopsia"]["nota_media"]["valor"] = nota_media
    v = _vault(tmp_path)
    _escribir(v, config=cargar_texto(yaml.safe_dump(datos, allow_unicode=True)))
    assert cargar_oferta(v, P)["vende_por_presupuesto"] is esperado
    cuerpo = (v / "productos" / P / "OFERTA.md").read_text(encoding="utf-8")
    assert ("Vende por presupuesto" in cuerpo) is esperado


def test_cuerpo_con_economia_no_medida(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, config=_config(ruta_activa=None))
    cuerpo = frontmatter.leer(v / "productos" / P / "ESCALERA.md")[1]
    seccion = cuerpo.split("## XE", 1)[1].split("## XR", 1)[0]
    assert "- AOV: 17,16 USD" in seccion
    assert "- BE (CPA de equilibrio): no medido: falta ruta_activa" in seccion
    assert "- CPA de test: no medido" in seccion
    assert "- ROAS de equilibrio: no medido" in seccion
    assert "BE = AOV × (1 − comisión − impuestos − reembolsos) − comisión fija × cobros: no medido" in seccion


def test_orden_archivos_producto_log(tmp_path, monkeypatch):
    from trovefy.modelar import salida

    v = _vault(tmp_path)
    orden = []
    real_escribir, real_actualizar, real_log = salida.escribir_atomico, salida.actualizar_producto, salida.anadir_log
    monkeypatch.setattr(salida, "escribir_atomico", lambda r, t: (orden.append(("archivo", r.name)),
                                                                 real_escribir(r, t))[1])
    monkeypatch.setattr(salida, "actualizar_producto", lambda *a, **k: (orden.append(("producto",)),
                                                                       real_actualizar(*a, **k))[1])
    monkeypatch.setattr(salida, "anadir_log", lambda *a, **k: (orden.append(("log",)), real_log(*a, **k))[1])
    _escribir(v)
    assert [o[0] for o in orden] == ["archivo"] * 4 + ["producto", "log"]


def test_rehacer_borra_la_aprobacion_de_producto(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    meta, cuerpo = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")
    meta["oferta"].update(aprobacion="aprobada", aprobacion_cita="sí, adelante", aprobacion_fecha="2026-11-13")
    meta["paises"]["XE"]["estado"] = "modelado"
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", meta, cuerpo)
    _escribir(v)
    oferta = frontmatter.leer(v / "productos" / P / "PRODUCTO.md")[0]["oferta"]
    assert oferta["aprobacion"] == "presentada"
    assert oferta["aprobacion_cita"] is None and oferta["aprobacion_fecha"] is None


def test_reserva_avisa_titulos_en_idioma_del_elegido(tmp_path):
    v = _vault(tmp_path)
    _escribir(v)
    paises = cargar_escalera(v, P)
    aviso = "títulos en bg: se traducen al lanzar este país"
    assert aviso in paises["XR"]["avisos"]
    assert aviso not in paises["XE"]["avisos"]


@pytest.mark.parametrize("moneda", ["EURO-LARGO", "EU", "E1R", "€", "euros por unidad"])
def test_moneda_del_original_rara_no_medida(tmp_path, moneda):
    v = _vault(tmp_path)
    _ficha(v, precio="9.0", moneda=moneda)
    _escribir(v)
    texto = (v / "productos" / P / "comparativa.md").read_text(encoding="utf-8")
    assert texto.count("no medido (moneda del original no medida)") == 2  # XE y XR


def test_moneda_del_original_en_minusculas_vale(tmp_path):
    v = _vault(tmp_path)
    _ficha(v, precio="12.1", moneda=" eur ")
    _escribir(v)
    assert any("el original cuesta 12,10 €" in a for a in cargar_escalera(v, P)["XE"]["avisos"])


@pytest.mark.parametrize(("pais", "precio"), [("XE", Decimal("13.999")), ("XR", Decimal("65.5")),
                                              ("XE", 13.999)])
def test_precio_manual_con_decimales_de_mas(tmp_path, pais, precio):
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="decimales"):
        _escribir(v, precios={pais: precio})
    assert not (v / "productos" / P / "OFERTA.md").exists()


def test_precio_manual_sin_centimos_entero_con_ceros(tmp_path):
    v = _vault(tmp_path)
    _escribir(v, precios={"XR": Decimal("65.00")})
    assert cargar_escalera(v, P)["XR"]["pasos"]["front"]["precio"] == "65"
