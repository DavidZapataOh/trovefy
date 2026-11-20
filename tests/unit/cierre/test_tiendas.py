"""Tiendas del cierre y esquema de pedidos (plan 24, Tarea 2)."""
import copy
from datetime import date

import yaml
from trovefy.cierre import tiendas as t

from .ejemplos import PAIS, STORE, P, fx, vault_cierre


def test_empareja_por_subdominio(tmp_path):
    v = vault_cierre(tmp_path, tiendas=False)
    lista, avisos = t.emparejar_tiendas(fx("listar_tiendas.json"), v)
    assert [(x.store_id, x.producto, x.pais) for x in lista] == [(STORE, P, PAIS)]
    assert any("otra.impultienda.example" in a for a in avisos)


def test_empareja_por_dominio_propio(tmp_path):
    v = vault_cierre(tmp_path, tiendas=False)
    inst = copy.deepcopy(fx("listar_tiendas.json"))
    tienda = inst["structuredContent"]["tiendas"][1]
    tienda["dominio_propio"] = "landing-prueba.example"
    lista, _ = t.emparejar_tiendas(inst, v)
    assert any(x.store_id == tienda["id"] and (x.producto, x.pais) == (P, PAIS) for x in lista)


def test_tienda_sin_pareja_es_aviso(tmp_path):
    v = vault_cierre(tmp_path, tiendas=False)
    inst = {"structuredContent": {"tiendas": [{"id": "x", "url": "https://nadie.example"}]}}
    lista, avisos = t.emparejar_tiendas(inst, v)
    assert lista == [] and "no casa" in avisos[0]


def test_forma_desconocida_de_tiendas(tmp_path):
    v = vault_cierre(tmp_path, tiendas=False)
    assert t.emparejar_tiendas({"raro": 1}, v) == ([], ["no medido: forma de impultienda_listar_tiendas desconocida"])


def test_escribir_tiendas_conserva_comentarios_y_pruebas(tmp_path):
    v = vault_cierre(tmp_path)
    t.escribir_tiendas(v, [t.Tienda("nueva", "https://n.example", P, "YY")])
    texto = (v / "config/cierre.yaml").read_text()
    assert texto.startswith("# mis notas")
    datos = yaml.safe_load(texto)
    assert {x["store_id"] for x in datos["tiendas"]} == {STORE, "nueva"}
    assert t.pedidos_de_prueba(v, STORE) == {"ORD-0003"}


def test_registrar_prueba(tmp_path):
    v = vault_cierre(tmp_path, prueba=False)
    assert t.pedidos_de_prueba(v) == set()
    t.registrar_prueba(v, STORE, "ORD-9", "usuario, 2026-11-20: «sí, esa»")
    assert t.pedidos_de_prueba(v, STORE) == {"ORD-9"}


def test_esquema_de_respuesta_real(tmp_path):
    v = vault_cierre(tmp_path)
    esquema = t.esquema_pedidos(fx("listar_ventas.json"))
    assert esquema["detalle.ventas[].orden"] == "str" and esquema["detalle.has_more"] == "bool"
    ruta = t.escribir_esquema(v, esquema, date(2026, 11, 20))
    datos = yaml.safe_load(ruta.read_text())
    assert datos["fuente"].startswith("impultienda_listar_ventas") and datos["fecha"] == "2026-11-20"
    assert t.cargar_esquema(v) == esquema
    assert t.validar_ventas(fx("listar_ventas.json"), esquema) == []


def test_forma_rara_da_diferencias():
    difs = t.validar_ventas(fx("listar_ventas-forma-rara.json"))
    assert "falta detalle.ventas[].orden" in difs and "falta detalle.ventas[].fecha" in difs


def test_esquema_sin_datos_personales():
    esquema = t.esquema_pedidos(fx("listar_ventas-forma-rara.json"))
    assert not any("email" in k for k in esquema)
