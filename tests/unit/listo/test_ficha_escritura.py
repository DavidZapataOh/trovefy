"""Plan 20, Tarea 4: informe en PRODUCTO.md y paso con_checkout → listo."""

import pytest
from trovefy.listo.ficha import registrar_listo
from trovefy.vault import frontmatter

from .conftest import P
from .test_veredicto import informe_con, todos_ok


def _leer(f):
    return frontmatter.leer(f.carpeta / "PRODUCTO.md")


def test_registrar_verde_pasa_a_listo(ficha_verde):
    vault, f = ficha_verde
    assert registrar_listo(vault, informe_con({**todos_ok(), "creativos": "no_aplica"})) == "listo"
    meta, cuerpo = _leer(f)
    zz = meta["paises"]["ZZ"]
    assert zz["estado"] == "listo" and zz["listo"]["verde"] is True and zz["listo"]["pasa"] is True
    assert zz["historial"][-1]["de"] == "con_checkout" and zz["historial"][-1]["a"] == "listo"
    assert "## /listo · ZZ ·" in cuerpo
    assert f"· listo · {P} ZZ: verde" in (vault / "log.md").read_text()


def test_registrar_con_excepcion_pasa_a_listo_sin_ser_verde(ficha_verde):
    vault, f = ficha_verde
    assert registrar_listo(vault, informe_con({**todos_ok(), "reembolso": "excepcion"})) == "listo"
    meta, _ = _leer(f)
    listo = meta["paises"]["ZZ"]["listo"]
    assert listo["verde"] is False and listo["pasa"] is True and listo["excepciones"] == ["reembolso"]
    assert "excepción aprobada por el usuario, no es verde" in " ".join(meta["paises"]["ZZ"]["historial"][-1]
                                                                         ["evidencia"])
    assert "pasa con excepciones" in (vault / "log.md").read_text()


def test_registrar_rojo_no_cambia_estado(ficha_verde):
    vault, f = ficha_verde
    assert registrar_listo(vault, informe_con({**todos_ok(), "caja": "falla"})) == "con_checkout"
    meta, _ = _leer(f)
    assert meta["paises"]["ZZ"]["estado"] == "con_checkout" and meta["paises"]["ZZ"]["listo"]["verde"] is False


def test_listo_no_retrocede(ficha_verde):
    vault, f = ficha_verde
    registrar_listo(vault, informe_con(todos_ok()))
    assert registrar_listo(vault, informe_con({**todos_ok(), "ejecutor": "falla"})) == "listo"
    meta, cuerpo = _leer(f)
    assert meta["paises"]["ZZ"]["listo"]["verde"] is False and cuerpo.count("## /listo · ZZ") == 2
    assert meta["paises"]["ZZ"]["estado"] == "listo"


def test_estado_previo_no_avanza(ficha_verde):
    vault, f = ficha_verde
    ruta = f.carpeta / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("estado: con_checkout", "estado: con_landing"))
    assert registrar_listo(vault, informe_con(todos_ok())) == "con_landing"


def test_registrar_sustituye_entera_la_clave_listo(ficha_verde):
    vault, f = ficha_verde
    ruta = f.carpeta / "PRODUCTO.md"
    ruta.write_text(ruta.read_text().replace("    compra_prueba:", "    listo:\n      vieja: si\n    compra_prueba:"))
    registrar_listo(vault, informe_con(todos_ok()))
    meta, _ = _leer(f)
    assert "vieja" not in meta["paises"]["ZZ"]["listo"]


def test_registrar_conserva_claves_ajenas_y_cuerpo(ficha_verde):
    vault, f = ficha_verde
    antes, cuerpo_antes = _leer(f)
    registrar_listo(vault, informe_con(todos_ok()))
    meta, cuerpo = _leer(f)
    assert {k: v for k, v in meta.items() if k != "paises"} == {k: v for k, v in antes.items() if k != "paises"}
    assert meta["paises"]["ZZ"]["tracking"] == antes["paises"]["ZZ"]["tracking"] and cuerpo.startswith(cuerpo_antes)
    assert meta["paises"].keys() == antes["paises"].keys() and meta["paises"]["YZ"] == antes["paises"]["YZ"]


def test_secreto_no_se_escribe(ficha_verde):
    from dataclasses import replace

    vault, f = ficha_verde
    original = (f.carpeta / "PRODUCTO.md").read_bytes()
    inf = informe_con(todos_ok())
    malo = replace(inf.gates[0], texto="token EAAB" + "q7Zx" * 20)
    inf = replace(inf, gates=(malo, *inf.gates[1:]))
    with pytest.raises(ValueError, match="secreto"):
        registrar_listo(vault, inf)
    assert (f.carpeta / "PRODUCTO.md").read_bytes() == original
    assert not (vault / "log.md").exists()
