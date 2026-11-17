"""Tarea 1 del plan 18: entrada, precondición de estado y wireframe propio."""

import hashlib
import itertools
import shutil
from decimal import Decimal

import pytest
from trovefy import cli
from trovefy.landing.entrada import (
    TIPOS_SECCION,
    EntradaInvalida,
    EstadoNoPermite,
    wireframe,
)
from trovefy.modelar import esquema

from .conftest import PDF_FIJO, TIENDA, Ejecutar, P, cargar, editar_md, vault_demo


def test_carga_datos_demo(tmp_path):
    v = vault_demo(tmp_path)
    d = cargar(v)
    assert (d.idioma, d.moneda, d.precio, d.pdf_paginas) == ("bg", "EUR", Decimal("14.90"), 3)
    assert len(d.secciones) == 15 and d.dominio == "ejemplo-demo.test"
    assert (d.marca, d.tienda, d.estado, d.garantia_dias) == ("Somatix", TIENDA, "producido", 30)
    assert d.promesa_h1 == "Спокойно тяло за 14 дни" and d.angulo.startswith("Десет")
    assert d.pdf_sha256 == hashlib.sha256(PDF_FIJO.read_bytes()).hexdigest()
    assert [p.name for p in d.imagenes] == ["portada.png"]
    assert "--color-primario: #1F4E5F;" in d.tokens_css and d.tokens_css.startswith(":root {")


def test_tipos_seccion_es_el_de_modelar():
    assert TIPOS_SECCION is esquema.TIPOS_SECCION


@pytest.mark.parametrize("n", [13, 17])
def test_secciones_fuera_de_rango(tmp_path, n):
    with pytest.raises(EntradaInvalida, match="14–16"):
        cargar(vault_demo(tmp_path, secciones=n))


def test_estado_modelado_no_permite(tmp_path):
    with pytest.raises(EstadoNoPermite, match="producido"):
        cargar(vault_demo(tmp_path, estado="modelado"))


def test_pdf_vigente_es_el_de_producto_md(tmp_path):
    """Resolución 14: manda PRODUCTO.md, no «el de mayor N»."""
    v = vault_demo(tmp_path)
    ent = v / "productos" / P / "entregable"
    shutil.copyfile(PDF_FIJO, ent / "demo-bg-v2.pdf")
    assert cargar(v).pdf.name == "demo-bg-v1.pdf"
    editar_md(v, "PRODUCTO", lambda m: m["entregable"]["bg"]["principal"].update(pdf="entregable/demo-bg-v2.pdf",
                                                                                 version=2))
    assert cargar(v).pdf.name.endswith("-v2.pdf")


def test_sin_pdf_vigente_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "PRODUCTO", lambda m: m.pop("entregable"))
    with pytest.raises(EntradaInvalida, match="PDF vigente"):
        cargar(v)


def test_pdf_fuera_del_producto_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "PRODUCTO", lambda m: m["entregable"]["bg"]["principal"].update(pdf="../../x.pdf"))
    with pytest.raises(EntradaInvalida, match="entregable"):
        cargar(v)


def test_pdf_tras_carpeta_enlazada_falla(tmp_path):
    """Nit de la revisión: ningún componente de la ruta al PDF puede ser un enlace."""
    v = vault_demo(tmp_path)
    otra = tmp_path / "otra"
    otra.mkdir()
    shutil.copyfile(PDF_FIJO, otra / "demo-bg-v1.pdf")
    (v / "productos" / P / "entregable" / "v").symlink_to(otra)
    editar_md(v, "PRODUCTO", lambda m: m["entregable"]["bg"]["principal"].update(pdf="entregable/v/demo-bg-v1.pdf"))
    with pytest.raises(EntradaInvalida, match="enlace"):
        cargar(v)


def test_paginas_distintas_de_producto_md_falla(tmp_path):
    """R4: si pdfinfo no da las páginas de PRODUCTO.md, el PDF cambió tras cerrar: rehacer /producto."""
    v = vault_demo(tmp_path)
    with pytest.raises(EntradaInvalida, match="/producto"):
        cargar(v, correr=Ejecutar(paginas=4))


def test_producto_md_sin_paginas_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "PRODUCTO", lambda m: m["entregable"]["bg"]["principal"].pop("paginas"))
    with pytest.raises(EntradaInvalida, match="paginas"):
        cargar(v)


def test_resenas_de_otro_pais_no_cuentan(tmp_path):
    """M9: solo cuentan las reseñas completas del país."""
    import yaml

    v = vault_demo(tmp_path)
    raiz = v / "productos" / P / "landing" / "ZZ"
    raiz.mkdir(parents=True)
    otra = {"id": "r-20261116-1", "texto": "Добро е.", "fecha": "2026-11-16", "pais": "ZY", "fuente": "pedido 1"}
    (raiz / "resenas.yaml").write_text(yaml.safe_dump({"resenas": [otra]}, allow_unicode=True), encoding="utf-8")
    assert cargar(v).resenas == 0
    (raiz / "resenas.yaml").write_text(yaml.safe_dump({"resenas": [{**otra, "pais": "ZZ"}]}, allow_unicode=True),
                                       encoding="utf-8")
    assert cargar(v).resenas == 1


def test_orden_con_huecos_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "OFERTA", lambda m: m["estructura_landing"][2].update(orden=99))
    with pytest.raises(EntradaInvalida, match="orden"):
        cargar(v)


def test_tipo_desconocido_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "OFERTA", lambda m: m["estructura_landing"][1].update(tipo="otro"))
    with pytest.raises(EntradaInvalida, match="otro"):
        cargar(v)


def test_sin_cta_falla(tmp_path):
    v = vault_demo(tmp_path)
    editar_md(v, "OFERTA", lambda m: [s.update(cta=False) for s in m["estructura_landing"]])
    with pytest.raises(EntradaInvalida, match="cta"):
        cargar(v)


@pytest.mark.parametrize("precio", ["0", "-1.00", "14.905", "catorce"])
def test_precio_invalido_falla(tmp_path, precio):
    v = vault_demo(tmp_path)
    editar_md(v, "ESCALERA", lambda m: m["paises"]["ZZ"]["pasos"]["front"].update(precio=precio))
    with pytest.raises(EntradaInvalida, match="precio"):
        cargar(v)


def test_falta_un_archivo(tmp_path):
    v = vault_demo(tmp_path)
    (v / "productos" / P / "BRANDBOOK.md").unlink()
    with pytest.raises(EntradaInvalida, match="BRANDBOOK"):
        cargar(v)


def test_pais_fuera_de_mercados(tmp_path):
    with pytest.raises(EntradaInvalida, match="mercados"):
        cargar(vault_demo(tmp_path), "ZX")


def test_sin_dominio_es_none(tmp_path):
    v = vault_demo(tmp_path)
    (v / "config" / "arranque.yaml").unlink()
    assert cargar(v).dominio is None


def test_wireframe_y_rel_y_sustitucion(tmp_path):
    w = wireframe(cargar(vault_demo(tmp_path)))
    assert w[0]["y_rel"] == 0.0 and all(a["y_rel"] < b["y_rel"] for a, b in itertools.pairwise(w))
    ps = [s for s in w if s.get("sustituye") == "prueba_social"]
    assert len(ps) == 1 and ps[0]["tipo"] == "vista_previa"
    total = sum(s["palabras"] for s in w)
    assert w[1]["y_rel"] == round(w[0]["palabras"] / total, 3)


def test_wireframe_con_resenas_no_sustituye(tmp_path):
    from dataclasses import replace

    d = replace(cargar(vault_demo(tmp_path)), resenas=1)
    assert not [s for s in wireframe(d) if "sustituye" in s]


def test_cli_estado(entorno, capsys):
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 0
    out = capsys.readouterr().out
    assert "ZZ: producido" in out and "demo-bg-v1.pdf" in out and "falta" in out


def test_cli_estado_modelado_sale_1(entorno, capsys):
    editar_md(entorno, "PRODUCTO", lambda m: m["paises"]["ZZ"].update(estado="modelado"))
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 1
    assert "producido" in capsys.readouterr().out


def test_cli_estado_entrada_mala_sale_2(entorno, capsys):
    (entorno / "productos" / P / "OFERTA.md").unlink()
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 2
    assert "OFERTA" in capsys.readouterr().err
