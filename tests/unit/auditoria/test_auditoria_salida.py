import pathlib
from datetime import date

import pytest
from ejemplos_auditoria import CONTEXTO, link_pagina, oferta_ejemplo, paises_ejemplo
from trovefy.arranque.verificadores.cuenta import mercado_elegido
from trovefy.auditoria.paises import recomendar, tres_senales
from trovefy.auditoria.salida import (
    escribir_auditoria,
    producto_para,
    registrar_eleccion,
    render_auditoria,
)
from trovefy.vault.andamio import crear_vault
from trovefy.vault.frontmatter import escribir, leer

GOLD = pathlib.Path(__file__).resolve().parents[2] / "golden/auditoria/AUDITORIA.md"
HOY = date(2026, 11, 10)


def vault(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v / "wiki/ofertas/o-ejemplo.md", oferta_ejemplo(), "")
    return v


def test_golden():
    ps = paises_ejemplo()
    texto = render_auditoria(oferta_ejemplo(), ps, recomendar(ps), tres_senales("B", ps), [], HOY, **CONTEXTO)
    assert texto == GOLD.read_text()


def test_reauditar_reutiliza_el_producto(tmp_path):
    v = vault(tmp_path)
    r1 = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), date(2026, 11, 10))
    r2 = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), date(2026, 11, 12))
    assert r1 == r2 and len(list((v / "productos").iterdir())) == 1
    assert (r1.parent / "AUDITORIA-2026-11-10.md").exists()


def test_reauditar_el_mismo_dia_no_pisa_la_anterior(tmp_path):
    v = vault(tmp_path)
    r = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    assert (r.parent / "AUDITORIA-2026-11-10.md").exists()
    assert (r.parent / "AUDITORIA-2026-11-10-2.md").exists()


def test_eleccion_en_no_tirar_queda_advertida(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), date(2026, 11, 10)).parent.name
    d = registrar_eleccion(v, p, "FR", None, "Quiero Francia igual", date(2026, 11, 10))
    texto = d.read_text()
    assert "Quiero Francia igual" in texto and "Advertencia" in texto and "traducido" in texto
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["FR"]["estado"] == "aprobado"


def test_eleccion_sin_tres_senales_queda_como_excepcion(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), date(2026, 11, 10)).parent.name
    d = registrar_eleccion(v, p, "RO", "IT", "Vamos con Rumanía", date(2026, 11, 10),
                           senales3={"ya_se_vende": True, "hueco_por_pais": False, "se_puede_mejorar": None})
    assert "Excepción: faltan" in d.read_text() and "hueco_por_pais" in d.read_text()
    d2 = registrar_eleccion(v, p, "RO", "IT", "Vamos con Rumanía", date(2026, 11, 11),
                            senales3={"ya_se_vende": True, "hueco_por_pais": True, "se_puede_mejorar": None})
    assert "Excepción" not in d2.read_text()


# ------------------------------------------------------------------ extra


def test_producto_para_numera_y_reutiliza(tmp_path):
    v = vault(tmp_path)
    assert producto_para(v, "o-ejemplo", "ejemplo") == "p-0001-ejemplo"
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    assert producto_para(v, "o-ejemplo", "otro-slug") == "p-0001-ejemplo"
    assert producto_para(v, "o-otra", "otra") == "p-0002-otra"


def test_producto_md_y_auditoria(tmp_path):
    v = vault(tmp_path)
    r = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    assert r == v / "productos/p-0001-ejemplo/AUDITORIA.md"
    meta, _cuerpo = leer(r.parent / "PRODUCTO.md")
    assert meta["tipo"] == "producto" and meta["fecha"] == "2026-11-10"
    assert meta["oferta_id"] == "o-ejemplo" and meta["fuente"] == "wiki/ofertas/o-ejemplo.md"
    assert meta["paises"] == {"RO": {"estado": "auditado"}, "IT": {"estado": "auditado"},
                              "FR": {"estado": "auditado"}}
    am, texto = leer(r)
    assert am["tipo"] == "auditoria" and am["senales"]["hueco_por_pais"] is True
    assert "La elección es tuya: dímela y la registro" in texto


def test_reauditar_no_baja_un_pais_aprobado(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    registrar_eleccion(v, p, "RO", "IT", "Rumanía", HOY)
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), date(2026, 11, 12))
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["RO"]["estado"] == "aprobado"
    assert meta["paises"]["IT"]["estado"] == "auditado"


def test_mercados_index_y_log(tmp_path):
    v = vault(tmp_path)
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)  # misma línea del día: no se duplica
    meta, cuerpo = leer(v / "wiki/mercados/RO.md")
    assert meta["tipo"] == "mercado" and meta["pais"] == "RO" and meta["fecha"] == "2026-11-10"
    lineas = [x for x in cuerpo.splitlines() if x.startswith("- 2026-11-10")]
    assert len(lineas) == 1
    assert "o-ejemplo" in lineas[0] and "competencia local 0" in lineas[0]
    assert "sin traducir" in lineas[0] and "precio soportable 1" in lineas[0]
    indice = (v / "index.md").read_text()
    assert "[[productos/p-0001-ejemplo/PRODUCTO]]" in indice and "[[wiki/mercados/RO]]" in indice
    log = (v / "log.md").read_text().splitlines()
    assert sum("auditar" in x and "o-ejemplo" in x for x in log) == 2


def test_eleccion_frontmatter_y_mercado_elegido(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    assert mercado_elegido(v) is None
    d = registrar_eleccion(v, p, "RO", "IT", "Vamos con Rumanía,\nque tiene hueco", HOY)
    assert d == v / "productos" / p / "decisiones/2026-11-10-eleccion.md"
    meta, cuerpo = leer(d)
    assert meta["tipo"] == "decision" and meta["fuente"] == "usuario"
    assert meta["pais"] == "RO" and meta["reserva"] == "IT" and meta["fecha"] == "2026-11-10"
    assert "> Vamos con Rumanía,\n> que tiene hueco" in cuerpo
    assert "Advertencia" not in cuerpo and "Excepción" not in cuerpo
    assert mercado_elegido(v) == "Europe/Bucharest"


def test_otra_eleccion_el_mismo_dia_manda_y_no_borra_la_anterior(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    registrar_eleccion(v, p, "RO", None, "Rumanía", HOY)
    registrar_eleccion(v, p, "IT", None, "Mejor Italia", HOY)
    assert mercado_elegido(v) == "Europe/Rome"
    textos = [x.read_text() for x in (v / "productos" / p / "decisiones").glob("*-eleccion.md")]
    assert len(textos) == 2 and any("Rumanía" in t for t in textos)
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["IT"]["estado"] == "aprobado" and meta["paises"]["RO"]["estado"] == "auditado"


def test_eleccion_sin_hueco_comprobado_se_advierte_aunque_otro_lo_tenga(tmp_path):
    v = vault(tmp_path)
    ps = paises_ejemplo()
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida

    ps[1].hueco = HuecoPais("IT", Medida(None, "no medido: x"), "no_medido", None, [])
    p = escribir_auditoria(v, "o-ejemplo", ps, HOY).parent.name
    d = registrar_eleccion(v, p, "IT", None, "Italia", HOY)
    assert "Advertencia: este país no tiene hueco comprobado" in d.read_text()
    d = registrar_eleccion(v, p, "RO", None, "Rumanía", date(2026, 11, 11))
    assert "Advertencia" not in d.read_text()


def test_eleccion_pendiente_no_es_excepcion(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    d = registrar_eleccion(v, p, "RO", None, "Rumanía", HOY,
                           senales3={"ya_se_vende": False, "hueco_por_pais": None, "se_puede_mejorar": None})
    texto = d.read_text()
    assert "Excepción: faltan ya_se_vende" in texto and "hueco_por_pais" not in texto.split("Excepción")[1]


def test_eleccion_exige_cita_y_producto(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    with pytest.raises(ValueError):
        registrar_eleccion(v, p, "RO", None, "   ", HOY)
    with pytest.raises(FileNotFoundError):
        registrar_eleccion(v, "p-0099-nada", "RO", None, "x", HOY)


def test_historial_y_enlaces_en_la_auditoria(tmp_path):
    v = vault(tmp_path)
    escribir(v / "productos/p-0007-viejo/PRODUCTO.md",
             {"tipo": "producto", "oferta_id": "o-viejo",
              "paises": {"RO": {"estado": "MUERTO", "motivo": "0 ventas con US$ 25", "stop": "[[wiki/mercados/RO]]"}}},
             "")
    r = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY)
    texto = r.read_text()
    assert "p-0007-viejo" in texto and "0 ventas con US$ 25" in texto
    assert link_pagina("ES") in texto and link_pagina("RO") in texto


def test_precio_sin_moneda_no_se_asume(tmp_path):
    o = oferta_ejemplo()
    o["moneda"] = None
    ps = paises_ejemplo()
    texto = render_auditoria(o, ps, recomendar(ps), tres_senales("B", ps), [], HOY)
    assert "Precio del original: 13,90 EUR" not in texto and "moneda no medida" in texto


def _poner_estado(v, p, pais, estado):
    meta, cuerpo = leer(v / "productos" / p / "PRODUCTO.md")
    meta["paises"][pais] = {**meta["paises"].get(pais, {}), "estado": estado, "motivo": "0 ventas", "stop": "[[x]]"}
    escribir(v / "productos" / p / "PRODUCTO.md", meta, cuerpo)


def test_elegir_un_pais_muerto_no_cambia_su_estado(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    _poner_estado(v, p, "RO", "MUERTO")
    d = registrar_eleccion(v, p, "RO", None, "Otra vez Rumanía", HOY)
    texto = d.read_text()
    assert "Otra vez Rumanía" in texto
    assert "Advertencia: este país ya está en MUERTO; el estado no cambia" in texto
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["RO"]["estado"] == "MUERTO"
    # el historial de otro producto lo sigue viendo
    from trovefy.auditoria.salida import historial_de

    assert any("MUERTO" in x for x in historial_de(v, ["RO"]))


def test_elegir_otro_pais_no_toca_uno_mas_avanzado(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    _poner_estado(v, p, "RO", "TEST")
    d = registrar_eleccion(v, p, "IT", None, "Italia también", HOY)
    assert "Advertencia: RO ya está en TEST (1 producto × 1 país)" in d.read_text()
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["RO"]["estado"] == "TEST" and meta["paises"]["IT"]["estado"] == "aprobado"


def test_elegir_desde_cazado_aprueba(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    _poner_estado(v, p, "RO", "cazado")
    d = registrar_eleccion(v, p, "RO", None, "Rumanía", HOY)
    assert "el estado no cambia" not in d.read_text()
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["RO"]["estado"] == "aprobado"


def test_auditoria_cita_banda_y_pesos():
    ps = paises_ejemplo()
    texto = render_auditoria(oferta_ejemplo(), ps, recomendar(ps), tres_senales("B", ps), [], HOY)
    assert "medida sobre 45 de 100 puntos" in texto
    assert "banda de RO: 11,90–15,90 € (fuente: vídeos: 11,90–15,90 €, config/mercados.yaml)" in texto
    assert "auditar.peso.*" in texto
    assert "sin hueco comprobado" not in texto


def test_golden_conserva_la_nota_de_la_caza_y_la_cobertura_en_la_recomendacion():
    texto = GOLD.read_text()
    assert "Decisión de la caza: **B** — nota 62,4 < 70 para A" in texto
    assert "sin hueco comprobado" not in texto
    assert "RO (nota 100, medida sobre 45 de 100 puntos)" in texto
    assert "reserva: IT (nota 83, medida sobre 45 de 100 puntos)" in texto


def test_que_medir_en_el_informe_y_sin_recomendado(tmp_path):
    from trovefy.auditoria.paises import PaisAuditado
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida

    h = HuecoPais("RO", Medida(None, "x"), "no_medido", None, [], "no medido: cuota del día agotada")
    ps = [PaisAuditado("RO", h, Medida(13.9), Medida(1.0), 100, [], None)]
    texto = render_auditoria(oferta_ejemplo(), ps, recomendar(ps), tres_senales("B", ps), [], HOY)
    assert "## Qué medir" in texto
    assert "- RO: no medido: cuota del día agotada → vuelve a auditar mañana con la misma orden" in texto
    assert "no se recomienda ninguno" in texto
    meta, _ = leer(escribir_auditoria(vault(tmp_path), "o-ejemplo", ps, HOY))
    assert meta["recomendado"] is None


def test_ficha_sin_estado_no_dice_que_no_se_vende(tmp_path):
    v = vault(tmp_path)
    o = oferta_ejemplo()
    del o["estado"]
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "")
    texto = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).read_text()
    assert "Ya se vende (la caza la dejó en A o B): **pendiente** — la ficha no tiene decisión de la caza" in texto


def test_elegir_un_pais_fuera_de_mercados_avisa_y_no_aprueba(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    d = registrar_eleccion(v, p, "RU", None, "Rusia, sin duda", HOY)
    texto = d.read_text()
    assert "Rusia, sin duda" in texto and "Advertencia: RU no está en tus mercados" in texto
    meta, _ = leer(v / "productos" / p / "PRODUCTO.md")
    assert (meta["paises"].get("RU") or {}).get("estado") != "aprobado"


def test_ranking_pone_primero_los_de_hueco_comprobado():
    from trovefy.auditoria.paises import PaisAuditado, puntuar_pais
    from trovefy.auditoria.salida import orden_ranking
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida
    from trovefy.config.umbrales import cargar

    u = cargar(pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml")

    def pais(codigo, hueco):
        h = HuecoPais(codigo, Medida(0 if hueco else None, None if hueco else "no medido: x"),
                      "ausente" if hueco is not None else "no_medido", hueco, [], None if hueco else "no medido: x")
        nota, desglose = puntuar_pais(h, Medida(1.0), u)
        return PaisAuditado(codigo, h, Medida(13.9), Medida(1.0), nota, desglose, None)

    ps = [pais("BG", None), pais("RO", True), pais("CZ", None), pais("ES", True)]
    assert [p.pais for p in orden_ranking(ps)] == ["ES", "RO", "BG", "CZ"]


# ------------------------------------------------------------------ re-review (N-1..N-3)


def _pais_n1(codigo, hueco, precio=1.0):
    from trovefy.auditoria.paises import PaisAuditado, puntuar_pais
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida
    from trovefy.config.umbrales import cargar

    u = cargar(pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml")
    h = HuecoPais(codigo, Medida(0 if hueco else None, None if hueco else "no medido: x"),
                  "ausente" if hueco is not None else "no_medido", hueco, [], None if hueco else "no medido: x")
    nota, desglose = puntuar_pais(h, Medida(precio), u)
    return PaisAuditado(codigo, h, Medida(13.9), Medida(precio), nota, desglose, None)


def test_ranking_nota_parcial_y_puestos_compartidos():
    ps = [_pais_n1("RO", True), _pais_n1("MD", True), _pais_n1("IT", True, 0.5), _pais_n1("BG", None),
          _pais_n1("CZ", None)]
    texto = render_auditoria(oferta_ejemplo(), ps, recomendar(ps), tres_senales("B", ps), [], HOY)
    assert "| 1= | MD | 100 (medida sobre 45 de 100 puntos) | sí | — |" in texto
    assert "| 1= | RO | 100 (medida sobre 45 de 100 puntos) | sí | — |" in texto
    assert "| 3 | IT |" in texto
    assert ("| 4= | BG | sin hueco comprobado (nota parcial 100, medida sobre 15 de 100 puntos) | no comprobado | — |"
            in texto)
    assert "### 4= . BG" not in texto and "### 4=. BG — sin hueco comprobado (nota parcial 100" in texto
    meta, _ = leer_texto(texto)
    assert meta["paises"]["RO"]["puesto"] == 1 and meta["paises"]["CZ"]["puesto"] == 4


def leer_texto(texto):
    import yaml

    _, fm, cuerpo = texto.split("---\n", 2)
    return yaml.safe_load(fm), cuerpo


def test_eleccion_fuera_de_mercados_no_tapa_la_eleccion_valida_anterior(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    registrar_eleccion(v, p, "RO", None, "Rumanía", HOY)
    assert mercado_elegido(v) == "Europe/Bucharest"
    d = registrar_eleccion(v, p, "RU", None, "no está en tus mercados, ya lo sé", HOY)
    meta, _ = leer(d)
    assert meta["fuera_de_mercados"] is True
    assert mercado_elegido(v) == "Europe/Bucharest"  # la errata no tapa la elección válida


def test_cita_con_el_texto_del_aviso_no_marca_fuera_de_mercados(tmp_path):
    v = vault(tmp_path)
    p = escribir_auditoria(v, "o-ejemplo", paises_ejemplo(), HOY).parent.name
    d = registrar_eleccion(v, p, "RO", None, "RO, aunque diga que no está en tus mercados", HOY)
    meta, _ = leer(d)
    assert meta["fuera_de_mercados"] is False
