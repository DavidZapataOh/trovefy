"""Ronda de revisión de las Tareas 3–5 sobre el catálogo del MCP de Impultienda (H-1, H-2, M-1…M-5, L-1, L-2, R-e).

Nunca se llama al MCP: catálogo real guardado (`config/impultienda_tools.json`) y catálogos ficticios en tmp_path.
"""

import hashlib
import json
from pathlib import Path

import pytest
from plan_aprobado import plan_aprobado
from trovefy.tienda import mcp
from trovefy.tienda.mcp import (
    CatalogoInvalido,
    cargar_catalogo,
    escritura_aprobada,
    huella_catalogo,
    huella_del_plan,
    huella_evidencia,
    huella_plan,
    redactar_urls_firmadas,
    violaciones,
)

RAIZ = Path(__file__).resolve().parents[3]
EJEMPLO = RAIZ / "tests" / "fixtures" / "tienda" / "catalogo-mcp-ejemplo.json"
TOKEN_VP = {"type": "string", "description": "Token de la vista previa", "maxLength": 64}


def _doc() -> dict:
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def _con(tmp_path: Path, *herramientas: dict) -> Path:
    doc = _doc()
    doc["herramientas"].extend(herramientas)
    ruta = tmp_path / "catalogo.json"
    ruta.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return ruta


def _h(nombre, clase="escritura", props=None, descripcion="Hace algo.", motivo="motivo de prueba", **extra):
    return {"nombre": nombre, "descripcion": descripcion, "clase": clase, "motivo": motivo,
            "esquema": {"type": "object", "properties": props or {"store_id": {"type": "string"}}}, **extra}


# --- M-2: conjuntos exactos del catálogo real ------------------------------------------------------------------

LECTURA = {
    "campanas_utm", "carritos_abandonados", "conocimiento", "estadisticas", "estado_generacion", "estado_onboarding",
    "faq", "leer_html",
    "leer_html_postcompra", "listar_embudos", "listar_productos", "listar_tiendas", "listar_ventas",
    "listar_versiones_html", "resumen_cuenta", "snippet_upsells_externos", "ver_landing", "ver_markets", "ver_plan",
    "ver_postcompra", "ver_recursos", "version", "visitantes_en_vivo",
}
ESCRITURA = {
    "activar_markets", "actualizar_embudo", "agregar_item_embudo", "agregar_oferta_postcompra",
    "alternar_funnel_postcompra", "alternar_html_postcompra", "asignar_paises", "bloques_checkout", "cambiar_idioma",
    "cambiar_logo", "cambiar_producto_oferta_postcompra", "cambiar_titulo_pagina", "cargar_entregable",
    "conectar_oferta_postcompra", "configurar_agradecimiento", "configurar_checkout", "configurar_disparo_postcompra",
    "configurar_mercado", "configurar_tienda", "crear_embudo", "crear_funnel_postcompra", "crear_producto",
    "desactivar_producto", "disenar_checkout", "editar_producto", "fijar_precio", "guardar_html_postcompra",
    "link_subida_recursos", "modificar_oferta_postcompra", "precio_por_pais", "quitar_item_embudo",
    "reordenar_oferta_postcompra", "subir_recurso_desde_url",
}


def test_golden_lectura_y_escritura_exactas():
    cat = cargar_catalogo()
    assert {n.removeprefix("impultienda_") for n in mcp.permitidas(cat, "lectura")} == LECTURA
    assert {n.removeprefix("impultienda_") for n in mcp.permitidas(cat, "escritura")} == ESCRITURA
    assert len(cat) - len(LECTURA) - len(ESCRITURA) == 38


def test_ver_cobros_plan_sigue_prohibida():
    assert cargar_catalogo()["impultienda_ver_cobros_plan"].clase == "prohibida"


def test_r_f_configurar_checkout():
    h = cargar_catalogo()["impultienda_configurar_checkout"]
    assert h.clase == "escritura"
    assert h.parametros_permitidos_por_ruling == {"color_boton_pagar": "R-f", "texto_boton_pagar": "R-f"}
    bien = {"store_id": "x", "pedir_telefono": True, "texto_boton_pagar": "Купи", "color_boton_pagar": "#112233"}
    assert violaciones(h, bien) == []
    assert any("metodo_pago" in p for p in violaciones(h, {**bien, "metodo_pago": "x"}))


def test_r_g_faq_y_conocimiento():
    cat = cargar_catalogo()
    for nombre in ("impultienda_faq", "impultienda_conocimiento"):
        assert cat[nombre].clase == "lectura"
        assert cat[nombre].lectura_por_ruling == "R-g"


@pytest.mark.parametrize("caso", ["sin_ruling", "ruling_mal", "en_escritura", "confirmar", "modo", "token",
                                  "tema", "escribe"])
def test_lectura_por_ruling_estrecha(tmp_path, caso):
    props = {"consulta": {"type": "string"}}
    extra = {"lectura_por_ruling": "R-g"}
    clase, descripcion = "lectura", "Busca en la base de conocimiento."
    if caso == "sin_ruling":
        extra = {}
    elif caso == "ruling_mal":
        extra = {"lectura_por_ruling": "porque sí"}
    elif caso == "en_escritura":
        clase = "escritura"
    elif caso in ("confirmar", "modo"):
        props[caso] = {"type": "boolean"}
    elif caso == "token":
        props.update({"confirmar": {"type": "boolean"}, "token": TOKEN_VP})
    elif caso == "tema":
        props["pasarela"] = {"type": "string"}
    else:
        descripcion = "Busca y escribe en la base."
    h = _h("impultienda_base_conocimiento", clase=clase, props=props, descripcion=descripcion, **extra)
    with pytest.raises(CatalogoInvalido, match="impultienda_base_conocimiento"):
        cargar_catalogo(_con(tmp_path, h))
    # La misma sin el defecto, con su ruling, vale.
    bien = _h("impultienda_base_conocimiento", clase="lectura", props={"consulta": {"type": "string"}},
              descripcion="Busca en la base de conocimiento.", lectura_por_ruling="R-g")
    assert cargar_catalogo(_con(tmp_path, bien))["impultienda_base_conocimiento"].clase == "lectura"


@pytest.mark.parametrize("param", ["pixel_id", "pixelId", "metaads", "MetaAds", "fbPixel"])
def test_temas_pixel_y_metaads(tmp_path, param):
    props = {"store_id": {"type": "string"}, param: {"type": "string"}}
    with pytest.raises(CatalogoInvalido, match="toca"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_fijar_cosa_dos", props=props)))


# --- H-2: una «lectura» no puede esconder escrituras -----------------------------------------------------------


def test_prefijo_real_no_esconde_el_verbo(tmp_path):
    with pytest.raises(CatalogoInvalido, match="impultienda_listar_productos"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_listar_productos", clase="escritura")))


def test_lectura_necesita_verbo_de_consulta_o_solo_lectura(tmp_path):
    with pytest.raises(CatalogoInvalido, match="impultienda_hace_cosas"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_hace_cosas", clase="lectura")))
    assert cargar_catalogo(_con(tmp_path, _h("impultienda_hace_cosas", clase="lectura",
                                              descripcion="SOLO LECTURA. Muestra cosas.")))
    assert cargar_catalogo(_con(tmp_path, _h("impultienda_ver_cosas", clase="lectura")))


def test_lectura_con_escribe_en_minusculas(tmp_path):
    with pytest.raises(CatalogoInvalido, match="escribe"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_ver_cosas", clase="lectura",
                                          descripcion="SOLO LECTURA. Escribe en la tienda.")))
    # «describe» no es «escribe».
    assert cargar_catalogo(_con(tmp_path, _h("impultienda_ver_cosas", clase="lectura",
                                              descripcion="SOLO LECTURA. Describe la tienda.")))


@pytest.mark.parametrize("param", ["confirmar", "token", "modo"])
def test_lectura_sin_confirmar_token_ni_modo(tmp_path, param):
    props = {"store_id": {"type": "string"}, param: TOKEN_VP if param == "token" else {"type": "boolean"}}
    if param == "token":
        props["confirmar"] = {"type": "boolean"}
    with pytest.raises(CatalogoInvalido, match="impultienda_ver_cosas"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_ver_cosas", clase="lectura", props=props,
                                          descripcion="SOLO LECTURA. Sin confirmar: vista previa.")))


# --- M-1: temas prohibidos ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("param", [
    "metaAdAccountId", "fb_pixel", "clave_api", "metodo_de_cobro", "devolucion", "pagar", "paymentMethod",
    "bank_account", "iban", "cbu", "cvu", "card_number", "ig_account", "instagram", "whatsapp", "credencial",
    "accessKey", "ads", "dataset_id", "ad_account", "gateway", "reintegro", "authCode", "login_url",
])
def test_temas_nuevos_y_camel_case(tmp_path, param):
    props = {"store_id": {"type": "string"}, param: {"type": "string"}}
    with pytest.raises(CatalogoInvalido, match="toca"):
        cargar_catalogo(_con(tmp_path, _h("impultienda_fijar_cosa_dos", props=props)))


@pytest.mark.parametrize("nombre", ["impultienda_cobrar_pedido", "impultienda_devolver_compra"])
def test_tema_en_el_nombre(tmp_path, nombre):
    with pytest.raises(CatalogoInvalido, match="toca"):
        cargar_catalogo(_con(tmp_path, _h(nombre)))


def _esquema_con(tmp_path, **cambios):
    h = _h("impultienda_fijar_cosa_dos")
    h["esquema"].update(cambios)
    return _con(tmp_path, h)


@pytest.mark.parametrize("cambios", [
    {"$defs": {"X": {"type": "object", "properties": {"capi_token": {"type": "string"}}}},
     "properties": {"x": {"$ref": "#/$defs/X"}}},
    {"definitions": {"X": {"type": "object", "properties": {"pasarela": {"type": "string"}}}}},
    {"properties": {"e": {"type": "object", "additionalProperties": {
        "type": "object", "properties": {"pasarela": {"type": "string"}}}}}},
    {"patternProperties": {"^pasarela_.*$": {"type": "string"}}},
    {"not": {"type": "object", "properties": {"iban": {"type": "string"}}}},
    {"if": {"properties": {"a": {}}}, "then": {"properties": {"tarjeta": {}}}},
    {"else": {"properties": {"webhook": {}}}},
    {"properties": {"l": {"type": "array", "prefixItems": [{"type": "object", "properties": {"cbu": {}}}]}}},
])
def test_temas_en_todo_el_esquema(tmp_path, cambios):
    with pytest.raises(CatalogoInvalido, match="toca"):
        cargar_catalogo(_esquema_con(tmp_path, **cambios))


def test_ref_sin_resolver_es_error(tmp_path):
    with pytest.raises(CatalogoInvalido, match=r"\$ref"):
        cargar_catalogo(_esquema_con(tmp_path, properties={"x": {"$ref": "#/$defs/NoExiste"}}))
    with pytest.raises(CatalogoInvalido, match=r"\$ref"):
        cargar_catalogo(_esquema_con(tmp_path, properties={"x": {"$ref": "https://fuera.example/e.json"}}))


def test_ref_ciclica_no_cuelga(tmp_path):
    defs = {"N": {"type": "object", "properties": {"hijo": {"$ref": "#/$defs/N"}}}}
    assert cargar_catalogo(_esquema_con(tmp_path, **{"$defs": defs, "properties": {"n": {"$ref": "#/$defs/N"}}}))


# --- L-1: el token de la vista previa, estrecho ------------------------------------------------------------------


def _token(tmp_path, token, *, confirmar=True, anidado=False):
    props = {"store_id": {"type": "string"}}
    if confirmar:
        props["confirmar"] = {"type": "boolean"}
    if anidado:
        props["opciones"] = {"type": "object", "properties": {"token": token}}
    else:
        props["token"] = token
    return _con(tmp_path, _h("impultienda_fijar_cosa_dos", props=props))


def test_token_vista_previa_valido(tmp_path):
    assert cargar_catalogo(_token(tmp_path, TOKEN_VP))
    hex16 = {"type": "string", "description": "El token de la vista previa. OBLIGATORIO con confirmar: true",
             "pattern": "^[0-9a-f]{16}$"}
    assert cargar_catalogo(_token(tmp_path, hex16))


@pytest.mark.parametrize("caso", ["sin_confirmar", "anidado", "largo", "sin_cota", "descripcion"])
def test_token_vista_previa_estrecho(tmp_path, caso):
    token = dict(TOKEN_VP)
    if caso == "largo":
        token["maxLength"] = 4096
    elif caso == "sin_cota":
        del token["maxLength"]
    elif caso == "descripcion":
        token["description"] = "Token de acceso (no el de la vista previa)"
    ruta = _token(tmp_path, token, confirmar=caso != "sin_confirmar", anidado=caso == "anidado")
    with pytest.raises(CatalogoInvalido, match="token"):
        cargar_catalogo(ruta)


# --- L-2: la excepción del Pixel ID, solo por nombre de herramienta ------------------------------------------------


def test_excepcion_pixel_cerrada(tmp_path, monkeypatch):
    props = {"store_id": {"type": "string"}, "meta_pixel_id": {"type": "string"}}
    h = _h("impultienda_configurar_ficha", props=props, motivo="excepción: pixel sin token")
    assert mcp.EXCEPCION_PIXEL == frozenset()
    with pytest.raises(CatalogoInvalido, match="toca «(meta|pixel)»"):
        cargar_catalogo(_con(tmp_path, h))
    monkeypatch.setattr(mcp, "EXCEPCION_PIXEL", frozenset({"impultienda_configurar_ficha"}))
    assert cargar_catalogo(_con(tmp_path, h))["impultienda_configurar_ficha"].clase == "escritura"


# --- M-3 / M-4 / R-e: restricciones por herramienta ------------------------------------------------------------


def test_r_e_titulo_y_diseno_son_escritura():
    cat = cargar_catalogo()
    titulo = cat["impultienda_cambiar_titulo_pagina"]
    assert titulo.clase == "escritura"
    assert titulo.parametros_permitidos_por_ruling == {"meta_descripcion": "R-e"}
    diseno = cat["impultienda_disenar_checkout"]
    assert diseno.clase == "escritura"
    assert set(diseno.parametros_prohibidos) == {
        "pago_expres_arriba", "pago_al_final", "anuncio_bonos", "texto_anuncio_bonos"}
    assert diseno.valores_prohibidos == {"estilo_bump": ("escasez",)}
    assert diseno.valores_obligatorios == {"minutos_timer_bump": 0}
    assert cat["impultienda_bloques_checkout"].valores_prohibidos == {"bloques[].tipo": ("countdown", "stock")}
    faltan = " ".join(cat.faltan)
    assert "disenar_checkout es prohibida" not in faltan and "cambiar_titulo_pagina es prohibida" not in faltan
    assert "configurar_checkout" not in faltan  # R-f


def _diseno(**args):
    return {"store_id": "00000000-0000-4000-8000-000000000000", "minutos_timer_bump": 0, **args}


def test_disenar_checkout_positivo_y_negativo():
    h = cargar_catalogo()["impultienda_disenar_checkout"]
    assert violaciones(h, _diseno(plantilla="kiwify", estilo_bump="classic")) == []
    assert violaciones(h, _diseno(barra_superior={"oculta": True})) == []
    for malo, que in [
        (_diseno(pago_expres_arriba=True), "pago_expres_arriba"),
        (_diseno(pago_al_final=False), "pago_al_final"),
        (_diseno(anuncio_bonos="count"), "anuncio_bonos"),
        (_diseno(estilo_bump="Escasez"), "escasez"),
        ({"store_id": "x", "plantilla": "kiwify"}, "minutos_timer_bump"),
        (_diseno(minutos_timer_bump=5), "minutos_timer_bump"),
        (_diseno(minutos_timer_bump=False), "minutos_timer_bump"),
        (_diseno(color_nuevo="#000000"), "color_nuevo"),
        (_diseno(barra_superior={"oculta": True, "extra": 1}), "extra"),
    ]:
        problemas = violaciones(h, malo)
        assert problemas and any(que in p for p in problemas), (malo, problemas)


def test_cambiar_titulo_pagina_positivo_y_negativo():
    h = cargar_catalogo()["impultienda_cambiar_titulo_pagina"]
    assert violaciones(h, {"store_id": "x", "titulo": "Somatix", "meta_descripcion": "Para buscadores"}) == []
    assert violaciones(h, {"store_id": "x", "titulo": "Somatix", "pixel": "1"})


def test_bloques_checkout_sin_countdown_ni_stock():
    h = cargar_catalogo()["impultienda_bloques_checkout"]
    bien = {"store_id": "x", "posicion": "arriba", "bloques": [{"tipo": "image", "url": "https://x.example/a.webp"}]}
    assert violaciones(h, bien) == []
    for tipo in ("countdown", "stock", "STOCK"):
        mal = {**bien, "bloques": [{"tipo": "text", "texto": "hola"}, {"tipo": tipo}]}
        assert any("bloques[].tipo" in p for p in violaciones(h, mal)), tipo


def test_restricciones_se_validan_al_cargar(tmp_path):
    props = {"store_id": {"type": "string"}, "pago_rapido": {"type": "boolean"}, "estilo": {"type": "string"}}
    base = _h("impultienda_disenar_cosa", props=props)
    # Sin restricción, el tema manda a prohibida; con el parámetro prohibido, vale.
    with pytest.raises(CatalogoInvalido, match="pago"):
        cargar_catalogo(_con(tmp_path, base))
    assert cargar_catalogo(_con(tmp_path, {**base, "parametros_prohibidos": ["pago_rapido"]}))
    for malo in (
        {"parametros_prohibidos": ["pago_rapido", "no_existe"]},
        {"parametros_prohibidos": "pago_rapido"},
        {"parametros_prohibidos": ["pago_rapido"], "valores_prohibidos": {"no_existe": ["x"]}},
        {"parametros_prohibidos": ["pago_rapido"], "valores_prohibidos": {"estilo": "escasez"}},
        {"parametros_prohibidos": ["pago_rapido"], "valores_obligatorios": {"no_existe": 0}},
        {"parametros_permitidos_por_ruling": {"pago_rapido": "porque sí"}},
        {"parametros_prohibidos": ["pago_rapido"], "devuelve_url_firmada": "sí"},
        {"parametros_prohibidos": ["pago_rapido"], "otra_clave": 1},
    ):
        with pytest.raises(CatalogoInvalido, match="impultienda_disenar_cosa"):
            cargar_catalogo(_con(tmp_path, {**base, **malo}))
    con_ruling = cargar_catalogo(_con(tmp_path, {**base, "parametros_permitidos_por_ruling": {"pago_rapido": "R-z"}}))
    assert con_ruling["impultienda_disenar_cosa"].parametros_permitidos_por_ruling == {"pago_rapido": "R-z"}


def test_violaciones_claves_desconocidas_recursivas():
    h = cargar_catalogo()["impultienda_bloques_checkout"]
    assert any("store" in p for p in violaciones(h, {"store": "x", "posicion": "arriba", "bloques": []}))
    assert any("html" in p for p in violaciones(h, {"store_id": "x", "posicion": "arriba",
                                                      "bloques": [{"tipo": "text", "html": "<b>"}]}))


# --- M-5: URLs firmadas ------------------------------------------------------------------------------------------


def test_bandera_url_firmada():
    cat = cargar_catalogo()
    firmadas = {n.removeprefix("impultienda_") for n, h in cat.items() if h.devuelve_url_firmada}
    assert firmadas == {"cargar_entregable", "cambiar_logo", "editar_producto", "link_subida_recursos"}


def test_redactar_urls_firmadas():
    s3 = ("https://bucket.s3.amazonaws.com/sub/archivo.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256"
          "&X-Amz-Credential=AKIAXXXX%2F20261117&X-Amz-Signature=abcdef0123456789")
    gcs = "https://storage.googleapis.com/b/o.png?X-Goog-Signature=0a1b2c&X-Goog-Expires=1800"
    supa = "https://abc.supabase.co/storage/v1/object/upload/sign/recursos/x.webp?token=eyJhbGciOiJIUzI1NiJ9.e30.zz"
    subida = "https://impultienda.ar/subir/k7Qm2ZpX9vT4rW8yB1nC5dF0"
    texto = f'{{"url": "{s3}", "otra": "{gcs}"}} y {supa} y {subida} y https://impultienda.ar/ayuda?tema=logo'
    limpio = redactar_urls_firmadas(texto)
    for url in (s3, gcs, supa, subida):
        assert url not in limpio
    for trozo in ("X-Amz-Signature", "abcdef0123456789", "eyJhbGci", "k7Qm2ZpX9vT4rW8yB1nC5dF0"):
        assert trozo not in limpio
    assert "https://impultienda.ar/ayuda?tema=logo" in limpio
    assert limpio.count(mcp.URL_REDACTADA) == 4
    assert redactar_urls_firmadas("sin urls") == "sin urls"


# --- huellas -----------------------------------------------------------------------------------------------------


def test_huella_evidencia_solo_nombre_descripcion_y_esquema(tmp_path):
    a = cargar_catalogo(EJEMPLO)
    doc = _doc()
    doc["herramientas"][0]["motivo"] = "otro motivo"
    doc["herramientas"][0]["clase"] = "prohibida"
    doc["faltan"] = []
    ruta = tmp_path / "c.json"
    ruta.write_text(json.dumps(doc), encoding="utf-8")
    b = cargar_catalogo(ruta)
    assert huella_evidencia(a) == huella_evidencia(b)
    assert huella_catalogo(a) != huella_catalogo(b)
    doc["herramientas"][0]["descripcion"] += " Cambió."
    ruta.write_text(json.dumps(doc), encoding="utf-8")
    assert huella_evidencia(cargar_catalogo(ruta)) != huella_evidencia(a)


def test_huella_catalogo_cubre_restricciones():
    cat = cargar_catalogo()
    otra = mcp.Catalogo(dict(cat), fuente=cat.fuente, fecha=cat.fecha, servidor=cat.servidor, plan=cat.plan,
                        faltan=cat.faltan)
    h = cat["impultienda_disenar_checkout"]
    otra[h.nombre] = mcp.Herramienta(**{**h.__dict__, "valores_obligatorios": {}})
    assert huella_catalogo(otra) != huella_catalogo(cat)
    assert huella_evidencia(otra) == huella_evidencia(cat)


# --- H-1: plan y aprobación (contrato mínimo hasta la Tarea 11) --------------------------------------------------

P = "p-0099-prueba-abc123"
OPS = [{"herramienta": "impultienda_fijar_precio",
        "argumentos": {"store_id": "00000000-0000-4000-8000-000000000000", "item_id": "i-1", "precio": 13.9}}]


def _plan(vault: Path, ops=OPS, *, huella=None, cita=None, pais="ZZ", plan_huella=None,
          registrar=True) -> Path:
    """Un plan aprobado como lo deja `trovefy checkout aprobar` (`plan_aprobado`), con lo que pida el test roto."""
    d, plan = plan_aprobado(vault, ops, pais=pais, cita=cita, registrar=registrar and cita != "")
    if huella is not None:
        plan["huella"] = huella
        (d / "PLAN-MCP.json").write_text(json.dumps(plan), encoding="utf-8")
    if huella is not None or plan_huella is not None:
        texto = (d / "APROBACION.md").read_text(encoding="utf-8")
        nueva = plan_huella or huella
        texto = texto.replace(f"plan_huella: {huella_del_plan(plan) if huella else plan['huella']}",
                              f"plan_huella: {nueva}")
        (d / "APROBACION.md").write_text(texto, encoding="utf-8")
    return d


def test_huella_plan_canonica():
    texto = json.dumps(OPS, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert huella_plan(OPS) == hashlib.sha256(texto.encode("utf-8")).hexdigest()
    assert huella_plan([{"argumentos": OPS[0]["argumentos"], "herramienta": OPS[0]["herramienta"]}]) == huella_plan(OPS)


def test_escritura_aprobada(tmp_path):
    cat = cargar_catalogo()
    h = cat["impultienda_fijar_precio"]
    args = OPS[0]["argumentos"]
    assert escritura_aprobada(tmp_path, h, args) is not None  # sin aprobación
    _plan(tmp_path)
    assert escritura_aprobada(tmp_path, h, args) is None
    assert escritura_aprobada(tmp_path, h, {**args, "precio": 1}) is not None
    assert escritura_aprobada(tmp_path, cat["impultienda_crear_embudo"], args) is not None


@pytest.mark.parametrize("roto", ["huella_falsa", "aprobacion_otra", "sin_cita", "pais_raro", "sin_mensaje",
                                  "otra_frase"])
def test_aprobacion_rota_no_vale(tmp_path, roto):
    h = cargar_catalogo()["impultienda_fijar_precio"]
    if roto == "huella_falsa":
        _plan(tmp_path, huella="0" * 64)
    elif roto == "aprobacion_otra":
        _plan(tmp_path, plan_huella="1" * 64)
    elif roto == "sin_cita":
        _plan(tmp_path, cita="")
    elif roto == "sin_mensaje":  # C1: plan y aprobación íntegros, pero el usuario nunca escribió la frase
        _plan(tmp_path, registrar=False)
    elif roto == "otra_frase":  # H3: una cita que no es la frase de este plan
        _plan(tmp_path, cita="sí, dale")
    else:
        _plan(tmp_path, pais="../ZZ")
    assert escritura_aprobada(tmp_path, h, OPS[0]["argumentos"]) is not None


def test_dos_pasos_confirmar_con_token(tmp_path):
    h = cargar_catalogo()["impultienda_precio_por_pais"]
    args = {"store_id": "s", "item_id": "i", "market_id": "m", "precio": 13.9}
    _plan(tmp_path, [{"herramienta": h.nombre, "argumentos": args}])
    assert escritura_aprobada(tmp_path, h, args) is None
    assert escritura_aprobada(tmp_path, h, {**args, "confirmar": True, "token": "0123456789abcdef"}) is None
    assert escritura_aprobada(tmp_path, h, {**args, "confirmar": True, "token": "x" * 65}) is not None
    assert escritura_aprobada(tmp_path, h, {**args, "precio": 1, "confirmar": True, "token": "0123456789abcdef"})


def test_home_aislado(tmp_path):
    assert Path.home() == tmp_path
