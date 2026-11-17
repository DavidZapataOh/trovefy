"""Catálogo clasificado del MCP de Impultienda (plan 19, Tarea 3; resolución 39).

Los tests nunca llaman al MCP: usan el catálogo real guardado en `config/impultienda_tools.json` (evidencia,
copiada de los esquemas que carga el cliente) y un catálogo ficticio en `tests/fixtures/tienda/`.
"""

import copy
import json
import re
from pathlib import Path

import pytest
from trovefy.tienda.mcp import (
    PROHIBIDAS_POR_TEMA,
    CatalogoInvalido,
    Herramienta,
    cargar_catalogo,
    huella_catalogo,
    nombre_mcp,
    permitidas,
)

RAIZ = Path(__file__).resolve().parents[3]
EJEMPLO = RAIZ / "tests" / "fixtures" / "tienda" / "catalogo-mcp-ejemplo.json"
REAL = RAIZ / "config" / "impultienda_tools.json"


def _doc() -> dict:
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def _guardar(tmp_path: Path, doc: dict) -> Path:
    ruta = tmp_path / "catalogo.json"
    ruta.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return ruta


def _con(tmp_path: Path, herramienta: dict) -> Path:
    doc = _doc()
    doc["herramientas"].append(herramienta)
    return _guardar(tmp_path, doc)


def _h(nombre, clase="escritura", props=None, descripcion="Hace algo.", motivo="motivo de prueba"):
    return {
        "nombre": nombre,
        "descripcion": descripcion,
        "esquema": {"type": "object", "properties": props or {"store_id": {"type": "string"}}},
        "clase": clase,
        "motivo": motivo,
    }


# --- catálogo real ---------------------------------------------------------------------------------------------


def test_catalogo_real_carga():
    cat = cargar_catalogo()
    assert len(cat) == 94
    assert all(isinstance(h, Herramienta) for h in cat.values())
    assert all(n.startswith("impultienda_") for n in cat)
    assert {h.clase for h in cat.values()} == {"lectura", "escritura", "prohibida"}
    # Las que deciden el 19.
    assert cat["impultienda_listar_ventas"].clase == "lectura"
    assert cat["impultienda_fijar_precio"].clase == "escritura"
    assert cat["impultienda_configurar_checkout"].clase == "escritura"
    assert cat["impultienda_bloques_checkout"].clase == "escritura"  # el nombre engañaba: reemplaza bloques
    # Llevan token CAPI o de UTMify: prohibida; el Pixel ID y Clarity van al respaldo manual.
    assert cat["impultienda_configurar_tracking"].clase == "prohibida"
    for nombre in ("impultienda_conectar_pasarela", "impultienda_activar_whop", "impultienda_ver_pago",
                   "impultienda_guardar_html", "impultienda_configurar_downsell", "impultienda_cambiar_email_comprador"):
        assert cat[nombre].clase == "prohibida", nombre
    assert cat.faltan, "lo que el MCP no cubre debe quedar anotado"
    assert cat.servidor == "https://mcp.impultienda.ar/mcp"


def test_catalogo_real_sin_datos_del_usuario():
    texto = REAL.read_text(encoding="utf-8")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", texto), "un id de tienda"
    assert "somatika" not in texto.lower()
    assert "mcp__impultienda__" not in texto  # se guarda el nombre sin el prefijo del cliente


def test_catalogo_real_guarda_el_esquema_tal_cual():
    cat = cargar_catalogo()
    esquema = cat["impultienda_fijar_precio"].esquema
    assert esquema["required"] == ["store_id", "precio"]
    assert esquema["properties"]["precio"] == {
        "description": "Precio de venta nuevo, en la moneda de la tienda", "exclusiveMinimum": 0, "type": "number"}
    assert "PISA el precio actual" in cat["impultienda_fijar_precio"].descripcion


# --- reglas de clasificación -----------------------------------------------------------------------------------


def test_ejemplo_carga():
    cat = cargar_catalogo(EJEMPLO)
    assert set(cat) == {"ficticia_listar_cosas", "ficticia_fijar_cosa", "ficticia_conectar_pasarela"}


@pytest.mark.parametrize("nombre", ["subir_creativo_meta", "reembolsar_pedido", "crear_anuncio",
                                     "ver_billetera_x", "cambiar_password"])
def test_meta_y_pagos_son_prohibidas(tmp_path, nombre):
    clase = "lectura" if nombre.startswith("ver_") else "escritura"
    with pytest.raises(CatalogoInvalido, match=nombre):
        cargar_catalogo(_con(tmp_path, _h(nombre, clase=clase)))
    # En `prohibida` sí vale.
    assert cargar_catalogo(_con(tmp_path, _h(nombre, clase="prohibida")))[nombre].clase == "prohibida"


def test_homoglifo_no_esquiva_el_tema(tmp_path):
    assert "creativ" in PROHIBIDAS_POR_TEMA
    # En un parámetro (con «і» cirílica) se normaliza y casa; en el nombre ni siquiera pasa (solo ASCII).
    props = {"store_id": {"type": "string"}, "creatіvo_id": {"type": "string"}}
    with pytest.raises(CatalogoInvalido, match="creativ"):
        cargar_catalogo(_con(tmp_path, _h("subir_cosa", props=props)))
    with pytest.raises(CatalogoInvalido, match="nombre no válido"):
        cargar_catalogo(_con(tmp_path, _h("subir_creatіvo", clase="prohibida")))


def test_parametro_token_obliga_prohibida(tmp_path):
    props = {"store_id": {"type": "string"}, "capi_token": {"type": "string", "description": "Token CAPI"}}
    with pytest.raises(CatalogoInvalido, match="capi_token"):
        cargar_catalogo(_con(tmp_path, _h("configurar_algo", props=props)))
    assert cargar_catalogo(_con(tmp_path, _h("configurar_algo", clase="prohibida", props=props)))


def test_parametro_anidado_cuenta(tmp_path):
    props = {"datos": {"type": "object", "properties": {"refund_days": {"type": "integer"}}}}
    with pytest.raises(CatalogoInvalido, match="refund"):
        cargar_catalogo(_con(tmp_path, _h("guardar_sitio", props=props)))


def test_token_de_vista_previa_no_es_credencial(tmp_path):
    # El de la vista previa (lo devuelve el servidor, ata lo aprobado con lo aplicado) no es un secreto.
    assert cargar_catalogo(EJEMPLO)["ficticia_fijar_cosa"].clase == "escritura"
    props = {"store_id": {"type": "string"}, "token": {"type": "string", "description": "Token de acceso a la API"}}
    with pytest.raises(CatalogoInvalido, match="token"):
        cargar_catalogo(_con(tmp_path, _h("configurar_otra", props=props)))


def test_lectura_no_escribe(tmp_path):
    with pytest.raises(CatalogoInvalido, match="listar_productos"):
        cargar_catalogo(_con(tmp_path, _h("listar_productos", clase="escritura")))
    with pytest.raises(CatalogoInvalido, match="resumen_raro"):
        cargar_catalogo(_con(tmp_path, _h("resumen_raro", clase="lectura",
                                          descripcion="ESCRIBE AL INSTANTE, sin vista previa.")))
    with pytest.raises(CatalogoInvalido, match="cambiar_cosa"):
        cargar_catalogo(_con(tmp_path, _h("cambiar_cosa", clase="escritura",
                                          descripcion="SOLO LECTURA — no modifica nada.")))


def test_pixel_id_sin_token_puede_ser_escritura(tmp_path):
    props = {"store_id": {"type": "string"}, "meta_pixel_id": {"type": "string"}}
    h = _h("configurar_pixel", props=props, motivo="excepción: pixel como parámetro de la tienda, sin token")
    assert cargar_catalogo(_con(tmp_path, h))["configurar_pixel"].clase == "escritura"
    # Sin decirlo en el motivo, no.
    with pytest.raises(CatalogoInvalido, match="configurar_pixel"):
        cargar_catalogo(_con(tmp_path, {**h, "motivo": "receta"}))
    # Con un parámetro de token al lado, tampoco.
    props_token = {**props, "capi_token": {"type": "string"}}
    with pytest.raises(CatalogoInvalido, match="configurar_pixel"):
        cargar_catalogo(_con(tmp_path, {**h, "esquema": {"type": "object", "properties": props_token}}))


@pytest.mark.parametrize("campo", ["clase", "motivo"])
def test_falta_clase_o_motivo(tmp_path, campo):
    h = _h("listar_cosas_dos", clase="lectura")
    h[campo] = "" if campo == "motivo" else None
    with pytest.raises(CatalogoInvalido, match="listar_cosas_dos"):
        cargar_catalogo(_con(tmp_path, h))
    del h[campo]
    with pytest.raises(CatalogoInvalido, match="listar_cosas_dos"):
        cargar_catalogo(_con(tmp_path, h))


def test_nombre_repetido(tmp_path):
    doc = _doc()
    doc["herramientas"].append(copy.deepcopy(doc["herramientas"][0]))
    with pytest.raises(CatalogoInvalido, match="repetid"):
        cargar_catalogo(_guardar(tmp_path, doc))


def test_huella_cambia_con_el_catalogo(tmp_path):
    a = cargar_catalogo(EJEMPLO)
    assert huella_catalogo(a) == huella_catalogo(cargar_catalogo(EJEMPLO))
    assert re.fullmatch(r"[0-9a-f]{64}", huella_catalogo(a))
    doc = _doc()
    doc["herramientas"][1]["esquema"]["properties"]["precio"]["minimum"] = 1
    assert huella_catalogo(cargar_catalogo(_guardar(tmp_path, doc))) != huella_catalogo(a)
    doc = _doc()
    doc["herramientas"][0]["clase"] = "prohibida"
    assert huella_catalogo(cargar_catalogo(_guardar(tmp_path, doc))) != huella_catalogo(a)
    # El orden de las herramientas en el archivo no cambia la huella.
    doc = _doc()
    doc["herramientas"].reverse()
    assert huella_catalogo(cargar_catalogo(_guardar(tmp_path, doc))) == huella_catalogo(a)


def test_faltan_se_conserva(tmp_path):
    assert cargar_catalogo(EJEMPLO).faltan == ("precio propio del embudo: solo en el panel",)
    doc = _doc()
    del doc["faltan"]
    assert cargar_catalogo(_guardar(tmp_path, doc)).faltan == ()
    doc["faltan"] = "no es lista"
    with pytest.raises(CatalogoInvalido, match="faltan"):
        cargar_catalogo(_guardar(tmp_path, doc))


def test_permitidas_y_nombre_mcp():
    cat = cargar_catalogo(EJEMPLO)
    assert permitidas(cat, "lectura") == ["ficticia_listar_cosas"]
    assert permitidas(cat, "escritura") == ["ficticia_fijar_cosa"]
    with pytest.raises(ValueError):
        permitidas(cat, "prohibida")
    assert nombre_mcp("impultienda_listar_ventas") == "mcp__impultienda__impultienda_listar_ventas"
    with pytest.raises(ValueError):
        nombre_mcp("listar ventas; rm")


def test_catalogo_ilegible(tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text("{no json", encoding="utf-8")
    with pytest.raises(CatalogoInvalido):
        cargar_catalogo(ruta)
    with pytest.raises(CatalogoInvalido):
        cargar_catalogo(_guardar(tmp_path, {"herramientas": "x"}))
