"""Plan 20, Tarea 2: gates puros sobre la evidencia de los planes 18 y 19."""

import json
from types import SimpleNamespace

import yaml
from trovefy.listo.gates import (
    datasets_de_otros,
    gate_compra,
    gate_creativos,
    gate_dataset,
    gate_dominio,
    gate_entrega,
    gate_reembolso,
    gate_utm,
)

from .conftest import escribir_tracking, preparar_vault, romper

DESTINO = "https://pago.tienda-prueba.example/c/1?utm_source=fb&utm_medium=paid&utm_campaign=c|1&utm_content=a|3"


def paso(id_, estado, evidencia):
    return SimpleNamespace(id=id_, estado=estado, evidencia=evidencia)


def test_todos_verdes_en_la_fixture(ficha_verde):
    _, f = ficha_verde
    assert [g.estado for g in (gate_utm(f), gate_compra(f), gate_entrega(f), gate_reembolso(f))] == ["ok"] * 4


# --- UTM ------------------------------------------------------------------------------------------------------------


def test_utm_sin_term_falla(ficha_verde):
    g = gate_utm(romper(ficha_verde[1], "landing.qa.utm_checkout.destino", DESTINO))
    assert g.estado == "falla" and "utm_term" in g.texto


def test_utm_a_otro_host_falla(ficha_verde):
    g = gate_utm(romper(ficha_verde[1], "landing.qa.utm_checkout.destino",
                        "https://otro.example/c?utm_source=fb&utm_medium=paid&utm_campaign=a&utm_term=b&utm_content=c"))
    assert g.estado == "falla" and "otro.example" in g.texto


def test_utm_al_dominio_propio_de_la_tienda_vale(ficha_verde):
    # la landing la sirve Impultienda en su dominio propio: el checkout en ese dominio es la tienda
    g = gate_utm(romper(ficha_verde[1], "landing.qa.utm_checkout.destino",
                        "https://tienda-prueba.example/checkout?utm_source=fb&utm_medium=paid&utm_campaign=a"
                        "&utm_term=b&utm_content=c"))
    assert g.estado == "ok"


def test_utm_interceptado_no_medido(ficha_verde):
    g = gate_utm(romper(ficha_verde[1], "landing.qa.utm_checkout.interceptado", True))
    assert g.estado == "no_medido"


def test_utm_sin_captura_no_medido(ficha_verde):
    g = gate_utm(romper(ficha_verde[1], "landing.qa.utm_checkout.captura", "landing/ZZ/qa/no-existe.png"))
    assert g.estado == "no_medido" and g.texto.startswith("no medido: ")


# --- compra ---------------------------------------------------------------------------------------------------------


def test_compra_dos_purchase_falla_doble_emisor(ficha_verde):
    g = gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager.purchase", 2))
    assert g.estado == "falla" and "2 veces" in g.texto and "D-17" in g.texto


def test_compra_cero_purchase_falla(ficha_verde):
    g = gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager.purchase", 0))
    assert g.estado == "falla" and "Meta no vio la compra de prueba" in g.texto


def test_compra_purchase_true_no_es_uno(ficha_verde):
    assert gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager.purchase", True)).estado == "no_medido"


def test_compra_en_otro_dataset_falla(ficha_verde):
    g = gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager.dataset_id", "999"))
    assert g.estado == "falla" and "otro dataset" in g.texto


def test_compra_sin_events_manager_no_medido(ficha_verde):
    g = gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager", None))
    assert g.estado == "no_medido" and g.texto.startswith("no medido: ")


def test_compra_no_vista_en_plataforma_falla(ficha_verde):
    assert gate_compra(romper(ficha_verde[1], "compra_prueba.plataforma.visto", False)).estado == "falla"


def test_compra_nunca_admite_excepcion(ficha_verde):
    assert gate_compra(romper(ficha_verde[1], "compra_prueba.events_manager.purchase", 0)).cubre_excepcion is False


# --- la evidencia tal como la dejó el plan 19 (índice de pegados y resumen de eventos) -------------------------------


def pegar(f, clave, tipo, fecha="2026-11-21T11:45:01-05:00", valores=None, ext="png"):
    carpeta = f.carpeta / "checkout" / f.pais / "evidencia"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{clave}-{fecha[:19].replace(':', '')}.{ext}"
    (carpeta / nombre).write_bytes(b"x")
    indice = carpeta / "indice.yaml"
    lista = yaml.safe_load(indice.read_text()) if indice.exists() else []
    lista.append({"clave": clave, "ruta": f"checkout/{f.pais}/evidencia/{nombre}", "tipo": tipo, "sha256": "0" * 64,
                  "fecha": fecha, "valores": valores or {}, "nota": ""})
    indice.write_text(yaml.safe_dump(lista))


def resumen_eventos(f, conteo, pedidos=1, **extra):
    ruta = f.carpeta / "checkout" / f.pais / "compra" / "events-manager.json"
    ruta.write_text(json.dumps({"fuente": "mcp", "pedidos": pedidos, "conteo": conteo, **extra}))


def sin_compra_prueba(f):
    return romper(f, "compra_prueba", None)


def test_compra_desde_lo_pegado_y_el_resumen_de_eventos(ficha_verde):
    f = sin_compra_prueba(ficha_verde[1])
    pegar(f, "pedido", "captura", valores={"pedido": "3600"})
    resumen_eventos(f, {"PageView": 7, "ViewContent": 0, "InitiateCheckout": 0, "Purchase": 1})
    g = gate_compra(f)
    assert g.estado == "ok" and "3600" in g.texto
    assert "checkout/ZZ/compra/events-manager.json" in g.evidencia


def test_compra_dicha_no_basta(ficha_verde):
    f = sin_compra_prueba(ficha_verde[1])
    pegar(f, "pedido", "dicho", ext="md")
    resumen_eventos(f, {"Purchase": 1})
    assert gate_compra(f).estado == "falla"


def test_compra_resumen_con_dos_purchase_falla(ficha_verde):
    f = sin_compra_prueba(ficha_verde[1])
    pegar(f, "pedido", "captura")
    resumen_eventos(f, {"Purchase": 2})
    g = gate_compra(f)
    assert g.estado == "falla" and "2 veces" in g.texto and "D-17" in g.texto


def test_compra_resumen_de_otro_dataset_falla(ficha_verde):
    f = sin_compra_prueba(ficha_verde[1])
    pegar(f, "pedido", "captura")
    resumen_eventos(f, {"Purchase": 1}, dataset_id="999")
    assert gate_compra(f).estado == "falla"


def test_entrega_desde_lo_pegado(ficha_verde):
    f = romper(ficha_verde[1], "compra_prueba.entrega", None)
    assert gate_entrega(f).estado == "no_medido"
    pegar(f, "email-entrega", "captura")
    assert gate_entrega(f).estado == "no_medido"
    pegar(f, "pdf-descargado", "dicho", ext="md")
    assert gate_entrega(f).estado == "ok"


def test_reembolso_desde_lo_pegado(ficha_verde):
    f = romper(ficha_verde[1], "compra_prueba.reembolso", None)
    assert gate_reembolso(f).estado == "no_medido"
    pegar(f, "reembolso", "dicho", ext="md")
    assert gate_reembolso(f).estado == "falla"
    pegar(f, "reembolso", "captura", fecha="2026-11-22T10:00:00-05:00")
    assert gate_reembolso(f).estado == "ok"


# --- entrega y reembolso --------------------------------------------------------------------------------------------


def test_entrega_sin_pdf_falla(ficha_verde):
    assert gate_entrega(romper(ficha_verde[1], "compra_prueba.entrega.pdf_descargable", False)).estado == "falla"


def test_reembolso_antes_de_la_compra_falla(ficha_verde):
    assert gate_reembolso(romper(ficha_verde[1], "compra_prueba.reembolso.fecha", "2026-11-20")).estado == "falla"


def test_reembolso_sin_evidencia_no_vale(ficha_verde):
    g = gate_reembolso(romper(ficha_verde[1], "compra_prueba.reembolso.evidencia", "checkout/ZZ/compra/nada.json"))
    assert g.estado == "no_medido"


# --- dominio --------------------------------------------------------------------------------------------------------


def test_dominio_ok():
    g = gate_dominio("https://tienda-prueba.example/zz/", "tienda-prueba.example",
                     paso("08", "verificado", ["config/evidencia/08.png"]))
    assert g.estado == "ok"


def test_dominio_paso_08_hecho_vale_en_fase_2():
    # resolución 32: el verificador del 08 lee un panel con sesión y ya no se ejecuta; «hecho» vale en la fase 2
    g = gate_dominio("https://www.tienda-prueba.example/", "tienda-prueba.example", paso("08", "hecho", []))
    assert g.estado == "ok" and "hecho" in g.texto


def test_dominio_paso_08_pendiente_falla():
    g = gate_dominio("https://tienda-prueba.example/", "tienda-prueba.example", paso("08", "pendiente", []))
    assert g.estado == "falla" and g.cubre_excepcion


def test_dominio_landing_fuera_del_dominio_verificado():
    for url in ["https://prueba.impultienda.ar/zz", "https://prueba.pages.dev/",
                "https://tienda-prueba.example.evil.test/"]:
        assert gate_dominio(url, "tienda-prueba.example", paso("08", "verificado", ["e"])).estado == "falla"


def test_dominio_sin_dominio_no_medido():
    g = gate_dominio("https://tienda-prueba.example/", None, paso("08", "verificado", ["e"]))
    assert g.estado == "no_medido" and "paso 07" in g.texto


# --- dataset --------------------------------------------------------------------------------------------------------


def test_dataset_ok(ficha_verde):
    assert gate_dataset(ficha_verde[1], {}).estado == "ok"


def test_dataset_compartido_falla(ficha_verde):
    g = gate_dataset(ficha_verde[1], {"123456789012345": "p-9002-otro/ZZ"})
    assert g.estado == "falla" and "p-9002-otro/ZZ" in g.texto and not g.cubre_excepcion


def test_dataset_nombre_sin_pais_falla(ficha_verde):
    assert gate_dataset(romper(ficha_verde[1], "tracking.dataset_nombre", "PRUEBA"), {}).estado == "falla"


def test_dataset_dos_emisores_falla(ficha_verde):
    g = gate_dataset(romper(ficha_verde[1], "tracking.emisor_purchase", ["impultienda", "landing"]), {})
    assert g.estado == "falla" and "D-17" in g.texto and not g.cubre_excepcion


def test_dataset_eventos_sin_verificar_falla_y_lo_cubre_la_excepcion(ficha_verde):
    vault, f = ficha_verde
    escribir_tracking(vault, estado="configurado", motivos=["eventos: no medido: InitiateCheckout no llegó"])
    g = gate_dataset(f, {})
    assert g.estado == "falla" and "InitiateCheckout" in g.texto and g.cubre_excepcion


def test_dataset_ficha_ilegible_no_medido(ficha_verde):
    g = gate_dataset(ficha_verde[1], {}, ["no se pudo leer productos/p-9002-otro/PRODUCTO.md"])
    assert g.estado == "no_medido" and "no se pudo leer" in g.texto


def test_datasets_de_otros_lee_el_vault(tmp_path):
    vault = preparar_vault(tmp_path)
    otro = vault / "productos" / "p-9002-otro"
    otro.mkdir()
    (otro / "PRODUCTO.md").write_text("---\npaises:\n  ZZ:\n    tracking:\n      dataset_id: '555'\n---\n")
    roto = vault / "productos" / "p-9003-roto"
    roto.mkdir()
    (roto / "PRODUCTO.md").write_text("---\npaises: {ZZ: [\n---\n")
    otros, notas = datasets_de_otros(vault, "p-9001-prueba", "ZZ")
    assert otros == {"555": "p-9002-otro/ZZ"}
    assert notas == ["no se pudo leer productos/p-9003-roto/PRODUCTO.md"]


# --- creativos ------------------------------------------------------------------------------------------------------


def test_creativos_sin_carpeta_no_aplica(ficha_verde):
    g = gate_creativos(ficha_verde[1])
    assert g.estado == "no_aplica" and g.texto == "no aplica hasta la fase 3: aún no hay creativos"


def test_creativos_presentes_sin_revision_falla(ficha_verde):
    (ficha_verde[1].carpeta / "creativos/ZZ").mkdir(parents=True)
    (ficha_verde[1].carpeta / "creativos/ZZ/a1.png").write_bytes(b"")
    assert gate_creativos(ficha_verde[1]).estado == "falla"
