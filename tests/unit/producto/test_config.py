from decimal import Decimal

import pytest
import yaml
from trovefy.producto.config import (
    PLANTILLA,
    ConfigInvalida,
    ConfigProducto,
    cargar_config,
    iniciar_config,
    tope_de,
)
from trovefy.vault import frontmatter

P = "p-0042-respira"


def _ruta(v):
    return v / "config" / "producto.yaml"


def _editar(v, clave, valor):
    datos = yaml.safe_load(_ruta(v).read_text(encoding="utf-8"))
    nodo = datos
    *camino, ultima = clave.split(".")
    for parte in camino:
        nodo = nodo[parte]
    nodo[ultima]["valor"] = valor
    _ruta(v).write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_plantilla_carga(tmp_path):
    iniciar_config(tmp_path)
    c = cargar_config(tmp_path)
    assert isinstance(c, ConfigProducto)
    assert c.tope_usd == Decimal("2.00")
    assert c.palabras_por_pagina == 350
    assert c.modelos_imagen == ("gpt-image-2",)
    assert c.resolucion == "1k"
    assert c.paginas_min == {"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}
    assert (c.seccion_palabras_min, c.puntuacion_min) == (300, 85)


def test_plantilla_hojas_valor_fuente_fecha():
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))

    def hojas(nodo):
        if isinstance(nodo, dict) and "valor" in nodo:
            yield nodo
        elif isinstance(nodo, dict):
            for v in nodo.values():
                yield from hojas(v)

    todas = list(hojas(datos))
    assert len(todas) == 11
    for h in todas:
        assert set(h) == {"valor", "fuente", "fecha"} and h["fuente"].strip()


@pytest.mark.parametrize("malo", [-1, "2.005", 0, "dos", 2.005, True, None])
def test_tope_negativo_o_float_raro(tmp_path, malo):
    iniciar_config(tmp_path)
    _editar(tmp_path, "apimart.tope_producto_usd", malo)
    with pytest.raises(ConfigInvalida):
        cargar_config(tmp_path)


@pytest.mark.parametrize(("clave", "malo"), [
    ("apimart.resolucion", "8k"),
    ("apimart.modelos_imagen", []),
    ("apimart.modelos_imagen", ["gpt-image-2", ""]),
    ("plan.palabras_por_pagina", 0),
    ("plan.palabras_por_pagina", 350.5),
    ("plan.paginas_min.ebook", -3),
    ("gates.puntuacion_min", 101),
])
def test_valores_invalidos(tmp_path, clave, malo):
    iniciar_config(tmp_path)
    _editar(tmp_path, clave, malo)
    with pytest.raises(ConfigInvalida):
        cargar_config(tmp_path)


def test_hoja_sin_fuente_es_invalida(tmp_path):
    iniciar_config(tmp_path)
    datos = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))
    del datos["apimart"]["resolucion"]["fuente"]
    _ruta(tmp_path).write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="fuente"):
        cargar_config(tmp_path)


def test_falta_una_clave(tmp_path):
    iniciar_config(tmp_path)
    datos = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))
    del datos["plan"]["paginas_min"]["bump"]
    _ruta(tmp_path).write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="bump"):
        cargar_config(tmp_path)


def test_falta_archivo(tmp_path):
    with pytest.raises(FileNotFoundError, match="trovefy producto iniciar"):
        cargar_config(tmp_path)


def test_iniciar_no_sobrescribe(tmp_path):
    ruta = iniciar_config(tmp_path)
    assert ruta == _ruta(tmp_path)
    ruta.write_text("editado: true", encoding="utf-8")
    with pytest.raises(FileExistsError):
        iniciar_config(tmp_path)
    assert ruta.read_text(encoding="utf-8") == "editado: true"


def _producto(v, **meta):
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", {"tipo": "producto", **meta}, "# x\n")


def test_tope_del_producto_gana(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="3.00")
    assert tope_de(tmp_path, P, cfg) == Decimal("3.00")


def test_tope_por_defecto(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    assert tope_de(tmp_path, P, cfg) == Decimal("2.00")  # sin PRODUCTO.md
    _producto(tmp_path)
    assert tope_de(tmp_path, P, cfg) == Decimal("2.00")  # sin la clave


@pytest.mark.parametrize("malo", ["-1", "3.005", 0])
def test_tope_del_producto_invalido(tmp_path, malo):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd=malo)
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_tope_de_producto_mal_escrito(tmp_path):
    iniciar_config(tmp_path)
    with pytest.raises(ValueError):
        tope_de(tmp_path, "../x", cargar_config(tmp_path))
