"""Plan 20, Tarea 1: lectura del bloque del país y rutas de evidencia."""

import pytest
from trovefy.listo import GATES
from trovefy.listo.ficha import FichaIlegible, campo, leer_ficha, ruta_evidencia


def test_gates_en_orden_fijo():
    assert GATES == ("landing_movil", "utm_checkout", "compra", "entrega", "reembolso", "dominio", "dataset",
                     "creativos", "caja", "ejecutor", "stop")


def test_lee_bloque_del_pais(ficha_verde):
    _, f = ficha_verde
    assert f.estado == "con_checkout" and f.datos["tracking"]["dataset_id"] == "123456789012345"


def test_pais_sin_bloque_da_datos_vacios(ficha_verde):
    vault, _ = ficha_verde
    f = leer_ficha(vault, "p-9001-prueba", "YY")
    assert f.estado is None and f.datos == {}


@pytest.mark.parametrize("producto,pais", [("../x", "ZZ"), ("p-9001-prueba", "zz"), ("p-9001-prueba", "ZZZ")])
def test_ids_invalidos(ficha_verde, producto, pais):
    with pytest.raises(ValueError):
        leer_ficha(ficha_verde[0], producto, pais)


def test_producto_sin_ficha(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_ficha(tmp_path, "p-9001-prueba", "ZZ")


def test_frontmatter_roto_es_ilegible(ficha_verde):
    vault, f = ficha_verde
    (f.carpeta / "PRODUCTO.md").write_text("---\npaises: [1, 2]\n---\ncuerpo\n")
    with pytest.raises(FichaIlegible):
        leer_ficha(vault, "p-9001-prueba", "ZZ")
    (f.carpeta / "PRODUCTO.md").write_text("---\npaises: {ZZ: [\n---\ncuerpo\n")
    with pytest.raises(FichaIlegible):
        leer_ficha(vault, "p-9001-prueba", "ZZ")


def test_campo_anidado():
    assert campo({"a": {"b": 1}}, "a.b") == 1 and campo({"a": 3}, "a.b") is None and campo({}, "x") is None


def test_evidencia_fuera_del_producto_no_vale(ficha_verde, tmp_path):
    _, f = ficha_verde
    (tmp_path / "fuera.png").write_bytes(b"")
    (f.carpeta / "checkout/ZZ/compra/enlace.png").symlink_to(tmp_path / "fuera.png")
    (f.carpeta / "checkout/ZZ/dir-enlace").symlink_to(f.carpeta / "checkout/ZZ/compra")
    assert ruta_evidencia(f, "checkout/ZZ/compra/pedido.json") == "checkout/ZZ/compra/pedido.json"
    assert ruta_evidencia(f, "./checkout/ZZ/compra/pedido.json") == "checkout/ZZ/compra/pedido.json"
    for mala in ["../fuera.png", "/etc/passwd", "checkout/ZZ/compra/enlace.png", "checkout/ZZ/no-existe.png",
                 "checkout/ZZ/dir-enlace/pedido.json", "checkout/ZZ/compra", "", 7, None]:
        assert ruta_evidencia(f, mala) is None, mala
