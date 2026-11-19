"""Plan 20, Tarea 4: veredicto, excepciones aprobadas y texto del informe."""

import pytest
from trovefy.checkout.cierre import registrar_excepcion
from trovefy.listo import EXCEPCION_DE_GATE, GATES
from trovefy.listo.gates import Gate
from trovefy.listo.veredicto import (
    InformeListo,
    evaluar,
    listo_para_activar,
    texto_informe,
)

from .conftest import AHORA, PAIS, P, escribir_tracking, romper  # noqa: F401

PALABRAS = "Apruebo pasar a listo sin el reembolso de la compra de prueba."


def todos_ok() -> dict[str, str]:
    return dict.fromkeys(GATES, "ok")


def informe_con(estados: dict[str, str], ficha=None, be=True) -> InformeListo:
    gates = tuple(Gate(c, estados[c], "no medido: x" if estados[c] == "no_medido" else f"texto {c}",
                       arreglo=None if estados[c] == "ok" else f"arreglo {c}") for c in GATES)
    return InformeListo(P, PAIS, AHORA, gates, "BE 10 USD", be)


def test_verde_con_creativos_no_aplica():
    inf = informe_con({**todos_ok(), "creativos": "no_aplica"})
    assert inf.verde and inf.pasa and not listo_para_activar(inf)


def test_no_aplica_en_otro_gate_es_rojo():
    assert not informe_con({**todos_ok(), "caja": "no_aplica"}).verde


def test_no_medido_es_rojo():
    inf = informe_con({**todos_ok(), "ejecutor": "no_medido"})
    assert not inf.verde and not inf.pasa


def test_excepcion_no_es_verde_pero_pasa():
    inf = informe_con({**todos_ok(), "reembolso": "excepcion", "creativos": "no_aplica"})
    assert not inf.verde and inf.pasa and not listo_para_activar(inf)


def test_activar_exige_los_once_ok_y_el_be():
    assert listo_para_activar(informe_con(todos_ok()))
    assert not listo_para_activar(informe_con(todos_ok(), be=False))


def test_texto_informe_marcas():
    t = texto_informe(informe_con({**todos_ok(), "dominio": "falla", "creativos": "no_aplica",
                                   "reembolso": "excepcion"}))
    assert "✗ dominio" in t and "– creativos" in t and "! reembolso" in t and "Arreglos:" in t
    assert "Economía (nota, no es gate)" in t


def test_cada_gate_dice_su_excepcion():
    assert set(EXCEPCION_DE_GATE) == set(GATES)
    assert EXCEPCION_DE_GATE["compra"] is None and EXCEPCION_DE_GATE["entrega"] is None
    assert EXCEPCION_DE_GATE["reembolso"] == "reembolso registrado"
    assert EXCEPCION_DE_GATE["dataset"] == "tracking verificado"


# --- evaluar --------------------------------------------------------------------------------------------------------


def explota(*_a, **_k):
    raise RuntimeError("boom")


def test_evaluar_todo_verde(todo_verde):
    vault, fuentes = todo_verde
    inf = evaluar(vault, P, PAIS, AHORA, fuentes)
    assert tuple(g.clave for g in inf.gates) == GATES
    assert {g.clave: g.estado for g in inf.gates} == {**todos_ok(), "creativos": "no_aplica"}, texto_informe(inf)
    assert inf.verde


def test_evaluar_orden_y_error_interno(todo_verde, monkeypatch):
    vault, fuentes = todo_verde
    monkeypatch.setattr("trovefy.listo.gates.gate_entrega", explota)
    inf = evaluar(vault, P, PAIS, AHORA, fuentes)
    assert tuple(g.clave for g in inf.gates) == GATES
    assert next(g for g in inf.gates if g.clave == "entrega").texto == "no medido: error interno (RuntimeError)"
    assert not inf.pasa


def _sin_reembolso(vault):
    ruta = vault / "productos" / P / "PRODUCTO.md"
    texto = ruta.read_text()
    ruta.write_text(texto.replace("procesado: true", "procesado: false"))


def test_excepcion_del_cierre_vale_en_listo(todo_verde):
    vault, fuentes = todo_verde
    _sin_reembolso(vault)
    assert not evaluar(vault, P, PAIS, AHORA, fuentes).pasa
    registrar_excepcion(vault, P, PAIS, "reembolso registrado", PALABRAS, "el usuario se queda la compra", AHORA)
    inf = evaluar(vault, P, PAIS, AHORA, fuentes)
    g = next(g for g in inf.gates if g.clave == "reembolso")
    assert g.estado == "excepcion" and PALABRAS in g.texto and "no es verde" in g.texto
    assert inf.pasa and not inf.verde


def test_excepcion_tracking_cubre_solo_los_eventos(todo_verde):
    vault, fuentes = todo_verde
    escribir_tracking(vault, estado="configurado", motivos=["eventos: no medido: InitiateCheckout no llegó"])
    registrar_excepcion(vault, P, PAIS, "tracking verificado", "Apruebo sin InitiateCheckout.", "sin IC", AHORA)
    inf = evaluar(vault, P, PAIS, AHORA, fuentes)
    assert next(g for g in inf.gates if g.clave == "dataset").estado == "excepcion"
    # un dataset mal nombrado no lo excusa la misma excepción
    ruta = vault / "productos" / P / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("dataset_nombre: PRUEBA ZZ", "dataset_nombre: PRUEBA"))
    inf = evaluar(vault, P, PAIS, AHORA, fuentes)
    assert next(g for g in inf.gates if g.clave == "dataset").estado == "falla"


def test_excepcion_propia_de_listo_utm(todo_verde):
    vault, fuentes = todo_verde
    ruta = vault / "productos" / P / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("captura: landing/ZZ/qa/utm.png", "captura: landing/ZZ/qa/nada.png"))
    assert next(g for g in evaluar(vault, P, PAIS, AHORA, fuentes).gates if g.clave == "utm_checkout").estado \
        == "no_medido"
    registrar_excepcion(vault, P, PAIS, "utm-hasta-el-checkout", "Apruebo sin la captura.", "sin captura", AHORA)
    g = next(g for g in evaluar(vault, P, PAIS, AHORA, fuentes).gates if g.clave == "utm_checkout")
    assert g.estado == "excepcion"


@pytest.mark.parametrize("requisito", ["compra de prueba registrada", "checkout completo"])
def test_no_hay_excepcion_para_compra(todo_verde, requisito):
    vault, _ = todo_verde
    with pytest.raises(ValueError, match="no admite excepción"):
        registrar_excepcion(vault, P, PAIS, requisito, PALABRAS, "m", AHORA)


@pytest.mark.parametrize("requisito", ["entrega", "stop", "caja", "landing en móvil"])
def test_gates_sin_excepcion_no_se_registran(todo_verde, requisito):
    vault, _ = todo_verde
    with pytest.raises(ValueError, match="requisito desconocido"):
        registrar_excepcion(vault, P, PAIS, requisito, PALABRAS, "m", AHORA)


def test_excepcion_escrita_a_mano_para_entrega_no_vale(todo_verde):
    from trovefy.vault import frontmatter

    vault, fuentes = todo_verde
    ruta = vault / "productos" / P / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("pdf_descargable: true", "pdf_descargable: false"))
    frontmatter.escribir(vault / "productos" / P / "decisiones" / "2026-11-21-excepcion-entrega.md",
                         {"tipo": "decision", "decision": "excepcion_checkout", "fecha": "2026-11-21",
                          "fuente": "usuario", "producto": P, "pais": PAIS, "requisito": "entrega",
                          "motivo": "m", "palabras_del_usuario": "vale"}, "x\n")
    g = next(g for g in evaluar(vault, P, PAIS, AHORA, fuentes).gates if g.clave == "entrega")
    assert g.estado == "falla"
