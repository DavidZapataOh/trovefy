"""Esquema de modelar.yaml: carga, errores juntos, material ajeno y secretos."""

from pathlib import Path

import pytest
import yaml
from trovefy import secretos
from trovefy.modelar.autopsia import EJES, EjeValorado
from trovefy.modelar.esquema import (
    ALFABETO,
    TIPOS_SECCION,
    TIPOS_TEARDOWN,
    ModeladoInvalido,
    cargar_modelado,
    material_ajeno,
)

RAIZ = Path(__file__).resolve().parents[3]
DEMO = RAIZ / "tests" / "fixtures" / "modelar" / "modelar-demo.yaml"
EJEMPLO = RAIZ / "skills" / "modelar" / "references" / "modelar-ejemplo.yaml"


def datos_demo() -> dict:
    return yaml.safe_load(DEMO.read_text(encoding="utf-8"))


def escribir(tmp_path: Path, datos: dict) -> Path:
    ruta = tmp_path / "modelar.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ruta


def errores(tmp_path: Path, datos: dict, idioma: str = "bg") -> list[str]:
    with pytest.raises(ModeladoInvalido) as exc:
        cargar_modelado(escribir(tmp_path, datos), "p-0042-kit-demo", "XE", idioma)
    assert str(exc.value)
    return exc.value.errores


def test_demo_carga():
    m = cargar_modelado(DEMO, "p-0042-kit-demo", "XE", "bg")
    assert (m.producto, m.pais) == ("p-0042-kit-demo", "XE")
    assert len(m.core.bonos) == 3 and m.core.bonos[0].objecion
    assert len(m.core.mecanismo_pasos) == 3 and len(m.core.sin) == 3
    assert m.brandbook.tokens_css["--color-primario"] == "#1F4E5F"
    assert len(m.teardown.secciones) == 6 and m.teardown.secciones[0].cta is True
    assert m.teardown.checkout["moneda"] is None and str(m.teardown.checkout["precio"]) == "9.00"
    assert set(m.ejes_original) == set(EJES) and isinstance(m.ejes_nuestra["precio"], EjeValorado)
    assert m.core.avatar and m.core.angulo
    assert [p.paso for p in m.escalera_piezas] == ["front", "bump", "u1", "u2", "u3", "downsell"]
    assert len(m.estructura_landing) == 15 and all(s.tipo in TIPOS_SECCION for s in m.estructura_landing)
    assert m.brandbook.nombre_local and m.brandbook.tono
    assert [t["uso"] for t in m.brandbook.tipografias] == ["titulos", "texto"]
    assert len(m.mapa_cambios) == 3 and m.comparativa[0] == (
        "Promesa", "Casa ordenada en pocos días", "Casa ordenada en 14 días con 15 minutos al día")


def test_tipos_y_alfabeto():
    assert "otro" in TIPOS_TEARDOWN and "verdad_incomoda" in TIPOS_TEARDOWN
    assert TIPOS_SECCION[0] == "hero" and "cta_final" in TIPOS_SECCION and "otro" not in TIPOS_SECCION
    assert ALFABETO["bg"] == "cyrillic" and ALFABETO["ro"] == "latin-ext" and ALFABETO["el"] == "greek"


def test_errores_juntos(tmp_path):
    d = datos_demo()
    d["core"]["bonos"] = d["core"]["bonos"][:2]
    d["core"]["mecanismo_pasos"].append("Repetir mañana")
    d["core"]["unidad_venta"] = "Un PDF de 40 páginas"
    errs = errores(tmp_path, d)
    assert len(errs) == 3, errs
    assert "core.bonos: hacen falta 3–5, hay 2" in errs
    assert any(e.startswith("core.mecanismo_pasos:") for e in errs)
    assert any(e.startswith("core.unidad_venta:") for e in errs)


def test_nota_sin_porque_invalida(tmp_path):
    d = datos_demo()
    d["ejes_nuestra"]["mecanismo"]["porque"] = "  "
    assert any(e.startswith("ejes_nuestra.mecanismo.porque:") for e in errores(tmp_path, d))


def test_eje_que_falta_o_sobra(tmp_path):
    d = datos_demo()
    del d["ejes_original"]["tiempo"]
    d["ejes_original"]["color"] = {"nota": 5, "porque": "x"}
    errs = errores(tmp_path, d)
    assert any(e.startswith("ejes_original:") and "tiempo" in e for e in errs)
    assert any(e.startswith("ejes_original:") and "color" in e for e in errs)


def test_nota_fuera_de_rango(tmp_path):
    d = datos_demo()
    d["ejes_original"]["precio"]["nota"] = 11
    assert any(e.startswith("ejes_original.precio.nota:") for e in errores(tmp_path, d))


def test_nota_null_es_no_valorado(tmp_path):
    d = datos_demo()
    d["ejes_original"]["precio"] = {"nota": None, "porque": "la landing no enseña el precio"}
    m = cargar_modelado(escribir(tmp_path, d), "p-0042-kit-demo", "XE", "bg")
    assert m.ejes_original["precio"].nota is None


def test_html_en_teardown(tmp_path):
    d = datos_demo()
    d["teardown"]["secciones"][0]["objetivo"] = "<div class=hero>Casa ordenada</div>"
    errs = errores(tmp_path, d)
    assert any(e.startswith("teardown.secciones[0].objetivo:") and "HTML" in e for e in errs)


def test_css_en_un_campo(tmp_path):
    d = datos_demo()
    d["brandbook"]["mockup"] = ".hero { color: red; }"
    assert any(e.startswith("brandbook.mockup:") and "CSS" in e for e in errores(tmp_path, d))


def test_url_de_imagen_ajena(tmp_path):
    d = datos_demo()
    d["teardown"]["avatar"] = "Madres, ver https://x.netlify.app/img/portada.png"
    assert any(e.startswith("teardown.avatar:") for e in errores(tmp_path, d))


def test_texto_largo_parece_copiado(tmp_path):
    d = datos_demo()
    d["teardown"]["promesa"] = "a" * 300
    errs = errores(tmp_path, d)
    assert any(e.startswith("teardown.promesa:") and "copiado" in e for e in errs)


def test_texto_largo_fuera_del_teardown_no_es_copia():
    assert material_ajeno("b" * 300) is None
    assert "copiado" in material_ajeno("b" * 300, de_teardown=True)
    assert material_ajeno("Hecho con Next.js y un método propio") is None
    assert material_ajeno("img/portada.webp") is not None


def test_secreto_en_yaml(tmp_path):
    d = datos_demo()
    valor = "EAA" + "x1Y2" * 10
    d["core"]["formato"] = f"PDF {valor}"
    errs = errores(tmp_path, d)
    assert any("secreto" in e for e in errs)
    assert all(valor not in e for e in errs)


def test_sin_revision_de_secretos_no_sigue(tmp_path, monkeypatch):
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "hooks"])
    with pytest.raises(secretos.RevisionSecretosNoDisponible):
        cargar_modelado(DEMO, "p-0042-kit-demo", "XE", "bg")


def test_sin_cirilico_para_bg(tmp_path):
    d = datos_demo()
    d["brandbook"]["tipografias"][1]["subconjuntos"] = ["latin"]
    assert any(e.startswith("brandbook.tipografias") and "cyrillic" in e for e in errores(tmp_path, d))


def test_idioma_latino_no_pide_cirilico(tmp_path):
    d = datos_demo()
    d["brandbook"]["idioma"] = "es"
    for t in d["brandbook"]["tipografias"]:
        t["subconjuntos"] = ["latin"]
    assert cargar_modelado(escribir(tmp_path, d), "p-0042-kit-demo", "XE", "es").brandbook.idioma == "es"


def test_tipografias_una_de_titulos_y_una_de_texto(tmp_path):
    d = datos_demo()
    d["brandbook"]["tipografias"][1]["uso"] = "titulos"
    assert any(e.startswith("brandbook.tipografias:") for e in errores(tmp_path, d))


def test_nombre_local_con_marca_original(tmp_path):
    d = datos_demo()
    d["brandbook"]["nombre_local"] = "Serena Casa"
    assert any(e.startswith("brandbook.nombre_local:") for e in errores(tmp_path, d))


def test_tokens_obligatorios(tmp_path):
    d = datos_demo()
    del d["brandbook"]["tokens_css"]["--fuente-texto"]
    d["brandbook"]["tokens_css"]["color-raro"] = "#000000"
    errs = errores(tmp_path, d)
    assert any(e.startswith("brandbook.tokens_css:") and "--fuente-texto" in e for e in errs)
    assert any(e.startswith("brandbook.tokens_css:") and "color-raro" in e for e in errs)


def test_paleta_minima(tmp_path):
    d = datos_demo()
    d["brandbook"]["paleta"] = {"primario": "#1F4E5F", "fondo": "blanco"}
    assert any(e.startswith("brandbook.paleta") for e in errores(tmp_path, d))


def test_producto_y_pais_coinciden(tmp_path):
    with pytest.raises(ModeladoInvalido) as exc:
        cargar_modelado(DEMO, "p-0043-otro", "XR", "bg")
    assert any(e.startswith("producto:") for e in exc.value.errores)
    assert any(e.startswith("pais:") for e in exc.value.errores)


def test_bono_con_id_o_sin_objecion(tmp_path):
    d = datos_demo()
    d["core"]["bonos"][0]["id"] = "bono-1"
    d["core"]["bonos"][1]["objecion"] = ""
    errs = errores(tmp_path, d)
    assert any(e.startswith("core.bonos[0]:") and "id" in e for e in errs)
    assert any(e.startswith("core.bonos[1].objecion:") for e in errs)


def test_estructura_landing_14_a_16(tmp_path):
    d = datos_demo()
    d["estructura_landing"] = d["estructura_landing"][:12]
    assert any(e.startswith("estructura_landing: hacen falta 14–16, hay 12") for e in errores(tmp_path, d))


def test_estructura_landing_tipo_orden_y_cta(tmp_path):
    d = datos_demo()
    d["estructura_landing"][1]["tipo"] = "verdad_incomoda"
    d["estructura_landing"][2]["orden"] = 9
    for s in d["estructura_landing"]:
        s["cta"] = False
    errs = errores(tmp_path, d)
    assert any(e.startswith("estructura_landing[1].tipo:") for e in errs)
    assert any(e.startswith("estructura_landing:") and "orden" in e for e in errs)
    assert any(e.startswith("estructura_landing:") and "cta" in e for e in errs)


def test_escalera_piezas_los_6_pasos(tmp_path):
    d = datos_demo()
    d["escalera_piezas"] = [p for p in d["escalera_piezas"] if p["paso"] != "downsell"]
    d["escalera_piezas"][0]["titulo"] = ""
    errs = errores(tmp_path, d)
    assert any(e.startswith("escalera_piezas:") and "downsell" in e for e in errs)
    assert any(e.startswith("escalera_piezas[0].titulo:") for e in errs)


def test_core_avatar_y_angulo(tmp_path):
    d = datos_demo()
    del d["core"]["avatar"]
    d["core"]["angulo"] = ""
    errs = errores(tmp_path, d)
    assert any(e.startswith("core.avatar:") for e in errs) and any(e.startswith("core.angulo:") for e in errs)


def test_mapa_cambios_y_teardown(tmp_path):
    d = datos_demo()
    d["mapa_cambios"] = d["mapa_cambios"][:2]
    d["mapa_cambios"][0]["impacto"] = "enorme"
    d["teardown"]["secciones"][0]["tipo"] = "carrusel"
    d["core"]["garantia_dias"] = 0
    d["core"]["mecanismo_nombre"] = "Zona"
    errs = errores(tmp_path, d)
    assert any(e.startswith("mapa_cambios: hacen falta al menos 3") for e in errs)
    assert any(e.startswith("mapa_cambios[0].impacto:") for e in errs)
    assert any(e.startswith("teardown.secciones[0].tipo:") for e in errs)
    assert any(e.startswith("core.garantia_dias:") for e in errs)
    assert any(e.startswith("core.mecanismo_nombre:") for e in errs)


def test_yaml_roto(tmp_path):
    ruta = tmp_path / "modelar.yaml"
    ruta.write_text("producto: [sin cerrar\n", encoding="utf-8")
    with pytest.raises(ModeladoInvalido) as exc:
        cargar_modelado(ruta, "p-0042-kit-demo", "XE", "bg")
    assert exc.value.errores[0].startswith("modelar.yaml:")


def test_ejemplo_de_la_skill_es_valido():
    m = cargar_modelado(EJEMPLO, "p-0042-kit-demo", "XE", "bg")
    assert m.producto == "p-0042-kit-demo"
    assert yaml.safe_load(EJEMPLO.read_text(encoding="utf-8")) == datos_demo()
