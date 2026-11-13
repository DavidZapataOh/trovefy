"""Montaje en PAUSED (Tarea 6): ``crear_estructura_pausada`` contra el Graph falso."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from ejecutor.fabricas_graph import (
    RUTA_IMG,
    anuncio,
    conjunto,
    estructura,
    medio,
    medio_video,
)
from trovefy_ejecutor import montaje
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.graph import DetenidoPorStop, ErrorGraph
from trovefy_ejecutor.montaje import PLATAFORMAS, montar

ARISTAS = ("campaigns", "adsets", "adcreatives", "ads")
NADA = lambda s: None


def _arista(l):
    return l.ruta.split("/")[-1]


def _reales(g, *aristas):
    return [l for l in g.llamadas if l.metodo == "crear" and not l.validate_only
            and (not aristas or _arista(l) in aristas)]


def _eventos(aud):
    lineas = aud.ruta.read_text().splitlines() if aud.ruta.exists() else []
    return [{"evento": d["evento"], **d["datos"]} for d in map(json.loads, lineas)]


def _sin_escritura(g):
    return not [l for l in g.llamadas if l.metodo in ("crear", "escribir", "subir_imagen", "subir_video")]


# -- PAUSED forzado y validate_only -------------------------------------------------------------
def test_status_paused_forzado(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    p = estructura(campana={"status": "ACTIVE"}, conjuntos=[conjunto(status="ACTIVE")])
    r = montar(p, g, alm, aud, vault, esperar=NADA)
    reales = _reales(g, "campaigns", "adsets", "ads")
    assert r.estado == "ejecutada", r.detalle
    assert len(reales) == 4 and all(l.datos["status"] == "PAUSED" for l in reales)


def test_validate_only_antes_de_cada_creacion(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    posts = [l for l in g.llamadas if l.metodo == "crear" and _arista(l) in ARISTAS]
    reales = [i for i, l in enumerate(posts) if not l.validate_only]
    assert len(reales) == 1 + 1 + 2 + 2  # campaña, conjunto, 2 creativos, 2 anuncios
    for i in reales:
        assert posts[i - 1].validate_only and posts[i - 1].ruta == posts[i].ruta
        assert posts[i - 1].datos == posts[i].datos


def test_solo_validar_no_crea_nada(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(origen="/montar", solo_validar=True), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada" and r.nueva_propuesta is None and r.ids_creados is None
    assert g.escrituras() == [] and all(l.validate_only for l in g.llamadas if l.metodo == "crear")
    assert [_arista(l) for l in g.llamadas if l.metodo == "crear"] == ["campaigns"]
    assert "conjuntos" in r.detalle and alm.ultimo_cambio("9000001", "estructura") is None
    evs = _eventos(aud)
    assert any(e["evento"] == "ejecucion" and e["tipo"] == "crear_estructura_pausada"
               and e["validate_only"] is True and e["ok"] is True for e in evs)
    assert all(e["validate_only"] is True for e in evs if e["evento"] == "ejecucion")


def test_solo_validar_con_error_es_fallida(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.fallar_validacion["campaigns"] = ErrorGraph(100, None, "Invalid")
    r = montar(estructura(solo_validar=True), g, alm, aud, vault)
    assert r.estado == "fallida" and g.escrituras() == [] and r.ids_creados is None
    assert any(e["evento"] == "ejecucion" and e["validate_only"] is True and e["ok"] is False for e in _eventos(aud))


def test_validacion_rechazada_no_crea(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.fallar_validacion["adsets"] = ErrorGraph(100, None, "Invalid targeting")
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.ids_creados["campana"] and r.ids_creados["conjuntos"] == {}
    assert _reales(g, "adsets") == []


# -- preparación: nada se escribe ---------------------------------------------------------------
def test_sha256_distinto_no_llama_a_meta(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(medios=[medio(sha256="0" * 64), medio_video()]), g, alm, aud, vault)
    assert r.estado == "fallida" and "sha256" in r.detalle and _sin_escritura(g) and g.llamadas == []


@pytest.mark.parametrize(("ruta", "motivo"), [("../secretos.env", "fuera del vault"), ("/etc/passwd", "fuera del vault"),
                                             ("no/existe.jpg", "no existe"), ("productos", "no es un archivo")])
def test_ruta_fuera_del_vault_o_invalida(entorno_montaje, ruta, motivo):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(medios=[medio(ruta=ruta), medio_video()]), g, alm, aud, vault)
    assert r.estado == "fallida" and motivo in r.detalle and g.llamadas == [] and r.ids_creados is None


def test_enlace_simbolico_que_sale_del_vault(entorno_montaje, tmp_path):
    g, alm, aud, vault = entorno_montaje
    os.symlink(tmp_path / "secretos.env", vault / "enlace.jpg")
    r = montar(estructura(medios=[medio(ruta="enlace.jpg"), medio_video()]), g, alm, aud, vault)
    assert r.estado == "fallida" and "fuera del vault" in r.detalle and g.llamadas == []


def test_extension_desconocida(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    (vault / "x.txt").write_bytes(b"a")
    m = medio(ruta="x.txt", sha256=__import__("hashlib").sha256(b"a").hexdigest())
    r = montar(estructura(medios=[m, medio_video()]), g, alm, aud, vault)
    assert r.estado == "fallida" and "no soportado" in r.detalle and g.llamadas == []


def test_idioma_sin_tabla(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(conjuntos=[conjunto(idiomas=("xx",))]), g, alm, aud, vault)
    assert r.estado == "fallida" and "idioma sin tabla: xx" in r.detalle and _sin_escritura(g)
    assert not [l for l in g.llamadas if l.metodo == "buscar"]


def test_idioma_por_nombre_exacto(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(conjuntos=[conjunto(idiomas=("ro", "es"))]), g, alm, aud, vault, esperar=NADA)
    (adset,) = _reales(g, "adsets")
    busquedas = [l.datos["q"] for l in g.llamadas if l.metodo == "buscar"]
    assert r.estado == "ejecutada" and busquedas == ["Romanian", "Spanish (All)"]
    assert adset.datos["targeting"]["locales"] == [10, 1001]  # entre varias filas por subcadena, la exacta


def test_idioma_sin_fila_exacta(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.locales = [x for x in g.locales if x["name"] != "Romanian"]  # quedan «Aromanian», «Romanian (Moldova)»
    r = montar(estructura(), g, alm, aud, vault)
    assert r.estado == "fallida" and "idioma sin resolver: ro" in r.detalle and _sin_escritura(g)


@pytest.mark.parametrize("filas", [
    [{"key": 10, "name": "Romanian"}, {"key": 11, "name": "Romanian"}],  # dos exactas
    [{"key": "abc", "name": "Romanian"}],  # clave no entera
    [{"key": True, "name": "Romanian"}],
    [{"name": "Romanian"}],
])
def test_idioma_ambiguo_o_ilegible(entorno_montaje, filas):
    g, alm, aud, vault = entorno_montaje
    g.locales = filas
    r = montar(estructura(), g, alm, aud, vault)
    assert r.estado == "fallida" and "idioma sin resolver: ro" in r.detalle and _sin_escritura(g)


def test_tabla_de_idiomas():
    assert montaje.IDIOMAS_META == {
        "bg": "Bulgarian", "ro": "Romanian", "ru": "Russian", "uk": "Ukrainian", "es": "Spanish (All)",
        "en": "English (All)", "pt": "Portuguese (All)", "fr": "French (All)", "de": "German", "it": "Italian",
        "pl": "Polish"}


def test_moneda_de_la_propuesta_distinta(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(moneda="USD"), g, alm, aud, vault)
    assert r.estado == "fallida" and r.error == "moneda" and _sin_escritura(g)


def test_moneda_sin_offset(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.cuentas["act_0000000000000000"]["currency"] = "XYZ"
    r = montar(estructura(moneda="XYZ"), g, alm, aud, vault)
    assert r.estado == "fallida" and r.error == "moneda" and _sin_escritura(g)


@pytest.mark.parametrize(("cambios", "motivo"), [
    ({"unidad": "centavos"}, "unidad"),
    ({"campana": {"tipo_presupuesto": "CBO"}}, "CBO: daily_budget de la campaña"),
    ({"campana": {"tipo_presupuesto": "CBO", "daily_budget": 50000}}, "CBO: los conjuntos"),
    ({"conjuntos": [conjunto(daily_budget=None)]}, "ABO: daily_budget del conjunto"),
    ({"campana": {"daily_budget": 50000}}, "ABO: la campaña"),
    ({"conjuntos": [conjunto(daily_budget=200.5)]}, "ABO: daily_budget del conjunto"),
    ({"conjuntos": [conjunto(daily_budget=True)]}, "ABO: daily_budget del conjunto"),
    ({"campana": {"spend_cap": 0}}, "spend_cap"),
    ({"campana": {"tipo_presupuesto": "XYZ"}}, "tipo_presupuesto"),
    ({"conjuntos": [conjunto(ubicaciones_excluidas=("tiktok",))]}, "ubicación desconocida"),
    ({"conjuntos": [conjunto(ubicaciones_excluidas=PLATAFORMAS)]}, "ninguna plataforma"),
    ({"conjuntos": [conjunto(anuncios=(anuncio(), anuncio()))]}, "anuncio repetido"),
    ({"conjuntos": [conjunto(), conjunto()]}, "conjunto repetido"),
    ({"conjuntos": [conjunto(anuncios=(anuncio(medio="nada"),))]}, "no está en medios"),
])
def test_forma_invalida_no_escribe(entorno_montaje, cambios, motivo):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(**cambios), g, alm, aud, vault)
    assert r.estado == "fallida" and motivo in r.detalle and g.llamadas == [] and r.ids_creados is None


def test_tipo_equivocado(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    from ejecutor.fabricas_graph import propuesta

    r = montar(propuesta(), g, alm, aud, vault)
    assert r.estado == "fallida" and g.llamadas == []


# -- datos enviados -------------------------------------------------------------------------------
def test_ubicaciones_automaticas_sin_publisher_platforms(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    (adset,) = _reales(g, "adsets")
    assert "publisher_platforms" not in adset.datos["targeting"]
    assert adset.datos["targeting"] == {"geo_locations": {"countries": ["RO"]}, "locales": [10]}


def test_ubicaciones_excluidas(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(conjuntos=[conjunto(ubicaciones_excluidas=("threads", "audience_network"))]),
           g, alm, aud, vault, esperar=NADA)
    (adset,) = _reales(g, "adsets")
    assert adset.datos["targeting"]["publisher_platforms"] == ["facebook", "instagram", "messenger"]


def test_abo(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    (camp,) = _reales(g, "campaigns")
    (adset,) = _reales(g, "adsets")
    assert camp.datos == {"name": "PRUEBA RO | ABO", "objective": "OUTCOME_SALES", "special_ad_categories": [],
                          "spend_cap": 120000, "status": "PAUSED", "is_adset_budget_sharing_enabled": False}
    assert adset.datos["daily_budget"] == 20000 and adset.datos["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert adset.datos["campaign_id"] == "9000001" and adset.datos["billing_event"] == "IMPRESSIONS"
    assert adset.datos["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert adset.datos["promoted_object"] == {"pixel_id": "8877665544", "custom_event_type": "PURCHASE"}


def test_cbo(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(campana={"tipo_presupuesto": "CBO", "daily_budget": 50000},
                          conjuntos=[conjunto(daily_budget=None)]), g, alm, aud, vault, esperar=NADA)
    (camp,) = _reales(g, "campaigns")
    (adset,) = _reales(g, "adsets")
    assert r.estado == "ejecutada", r.detalle
    assert camp.datos["daily_budget"] == 50000 and camp.datos["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert "is_adset_budget_sharing_enabled" not in camp.datos
    assert "daily_budget" not in adset.datos and "bid_strategy" not in adset.datos


def test_creativos_imagen_y_video(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    esperas = []
    r = montar(estructura(), g, alm, aud, vault, esperar=esperas.append)
    img, vid = _reales(g, "adcreatives")
    assert esperas == [10]  # vídeo listo a la segunda lectura
    hash_img, video_id = r.ids_creados["medios"]["img01"], r.ids_creados["medios"]["vid01"]
    ld = img.datos["object_story_spec"]["link_data"]
    assert img.datos["object_story_spec"]["page_id"] == "1357661930771909" and ld["image_hash"] == hash_img
    assert ld["link"] == "https://ejemplo.test/ro?utm_source=fb" and ld["message"] == "Texto del anuncio"
    assert ld["call_to_action"] == {"type": "LEARN_MORE", "value": {"link": "https://ejemplo.test/ro?utm_source=fb"}}
    vd = vid.datos["object_story_spec"]["video_data"]
    assert vd["video_id"] == video_id and vd["image_url"] == "https://scontent.example/miniatura.jpg"
    assert vd["call_to_action"]["type"] == "LEARN_MORE"
    ads = _reales(g, "ads")
    assert [a.datos["creative"] for a in ads] == [{"creative_id": c} for c in r.ids_creados["creativos"].values()]
    assert all(a.datos["adset_id"] == r.ids_creados["conjuntos"]["01 RO"] for a in ads)


def test_imagen_sube_los_bytes_verificados(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    (sub,) = [l for l in g.llamadas if l.metodo == "subir_imagen"]
    assert sub.datos == {"nombre": "img01.jpg", "bytes": len(b"\xff\xd8\xff imagen de prueba")}


def test_video_nunca_listo_es_fallida(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.video_listo_tras = None
    esperas = []
    r = montar(estructura(), g, alm, aud, vault, esperar=esperas.append)
    lecturas = [l for l in g.llamadas if l.metodo == "leer" and l.ruta == r.ids_creados["medios"]["vid01"]]
    assert r.estado == "fallida" and len(lecturas) == 30 and len(esperas) == 29
    assert _reales(g) == [] and "vid01" in r.ids_creados["medios"]


def test_video_en_error_es_fallida(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.video_error = True
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and _reales(g) == []


def _capturar_video(g, monkeypatch, antes=lambda: None) -> list[bytes]:
    """Envuelve ``subir_video``: ejecuta ``antes`` (el ataque) y guarda los bytes que de verdad saldrían
    hacia Meta (si recibe una ruta, la lee como hacía ``ClienteGraph``)."""
    real = g.subir_video
    subidos: list[bytes] = []

    def subir(act, *args):
        antes()
        dato = args[0]
        subidos.append(dato.read_bytes() if isinstance(dato, os.PathLike) else bytes(dato))
        return real(act, *args)

    monkeypatch.setattr(g, "subir_video", subir)
    return subidos


def test_video_cambiado_tras_verificar_sube_los_bytes_verificados(entorno_montaje, monkeypatch):
    from ejecutor.fabricas_graph import BYTES_VID, RUTA_VID
    g, alm, aud, vault = entorno_montaje
    subidos = _capturar_video(g, monkeypatch, lambda: (vault / RUTA_VID).write_bytes(b"otro"))
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert subidos == [BYTES_VID], r.detalle


def test_enlace_cambiado_tras_verificar_nunca_sube_el_secreto(entorno_montaje, monkeypatch):
    """TOCTOU: tras verificar el sha256, el vídeo se cambia por un enlace a un secreto del ejecutor."""
    from ejecutor.fabricas_graph import BYTES_VID, RUTA_VID
    g, alm, aud, vault = entorno_montaje
    secreto = vault.parent / "secretos.env"

    def cambiar_por_enlace():
        (vault / RUTA_VID).unlink()
        (vault / RUTA_VID).symlink_to(secreto)

    subidos = _capturar_video(g, monkeypatch, cambiar_por_enlace)
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert all(secreto.read_bytes() not in b for b in subidos)
    assert subidos == [BYTES_VID]


def test_enlace_entre_resolver_y_abrir_se_rechaza(entorno_montaje, monkeypatch):
    from ejecutor.fabricas_graph import RUTA_VID
    g, alm, aud, vault = entorno_montaje
    secreto = vault.parent / "secretos.env"
    resolver = montaje._resolver

    def resolver_y_cambiar(v, ruta):
        real = resolver(v, ruta)
        if ruta == RUTA_VID:
            real.unlink()
            real.symlink_to(secreto)
        return real

    monkeypatch.setattr(montaje, "_resolver", resolver_y_cambiar)
    subidos = _capturar_video(g, monkeypatch)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and _sin_escritura(g) and subidos == []
    assert "enlace" in r.detalle


def test_directorio_cambiado_por_enlace_se_rechaza(entorno_montaje, monkeypatch, tmp_path):
    from ejecutor.fabricas_graph import BYTES_VID, RUTA_VID
    g, alm, aud, vault = entorno_montaje
    resolver = montaje._resolver
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "vid01.mp4").write_bytes(BYTES_VID)

    def resolver_y_cambiar(v, ruta):
        real = resolver(v, ruta)
        if ruta == RUTA_VID:
            carpeta = real.parent
            carpeta.rename(carpeta.with_name("t1-aparte"))
            carpeta.symlink_to(fuera)
        return real

    monkeypatch.setattr(montaje, "_resolver", resolver_y_cambiar)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and _sin_escritura(g)


def test_medio_que_no_es_archivo_regular_se_rechaza(entorno_montaje, monkeypatch):
    from ejecutor.fabricas_graph import RUTA_VID
    g, alm, aud, vault = entorno_montaje
    resolver = montaje._resolver

    def resolver_y_cambiar(v, ruta):
        real = resolver(v, ruta)
        if ruta == RUTA_VID:
            real.unlink()
            os.mkfifo(real)
        return real

    monkeypatch.setattr(montaje, "_resolver", resolver_y_cambiar)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and _sin_escritura(g)


# -- resultado --------------------------------------------------------------------------------------
def test_genera_activar_valida(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    # Reloj fijo: el id del activar lleva la fecha del día de la cuenta (D-37), no la del sistema.
    fijo = datetime(2026, 11, 12, 17, 0, tzinfo=UTC)
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, ahora=lambda: fijo, esperar=NADA)
    act = cargar_propuesta(r.nueva_propuesta)
    ids = r.ids_creados
    assert r.estado == "ejecutada" and act.tipo == "activar" and act.cuenta == "act_0000000000000000"
    assert {o.id for o in act.operaciones} == (
        {ids["campana"]} | set(ids["conjuntos"].values()) | set(ids["anuncios"].values()))
    assert all(o.de_esperado == "PAUSED" and o.a == "ACTIVE" for o in act.operaciones)
    assert act.id.startswith("P-20261112-8") and act.evidencia["montaje"] == "P-20261112-002"
    assert list(act.evidencia["medios"]) == [RUTA_IMG, "productos/p-0001/creativos/RO/t1/vid01.mp4"]


def test_sin_origen_montar_no_hay_activar(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada" and r.nueva_propuesta is None


def test_sin_numero_libre_crea_a_mano(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    monkeypatch.setattr(montaje, "siguiente_id", lambda alm, ahora: None)
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada" and r.nueva_propuesta is None and "crea la propuesta a mano" in r.detalle


def test_fallo_a_mitad_no_borra_y_lista_lo_creado(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.fallar_creacion["adsets"] = ErrorGraph(100, None, "Invalid targeting")
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.ids_creados["campana"] == "9000001" and r.nueva_propuesta is None
    assert set(r.ids_creados["medios"]) == {"img01", "vid01"} and "9000001" in r.detalle
    assert len(_reales(g, "adsets")) == 1 and _reales(g, "ads") == []
    assert not [l for l in g.llamadas if l.metodo not in ("leer", "listar", "buscar", "crear", "subir_imagen",
                                                           "subir_video")]


def test_red_tras_crear_no_reenvia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.red_tras_crear.add("adsets")
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and len(_reales(g, "adsets")) == 1 and _reales(g, "ads") == []
    assert "puede haberse creado" in r.detalle and "Ads Manager" in r.detalle and r.nueva_propuesta is None
    assert alm.ultimo_cambio("9000001", "estructura") is not None


def test_ninguna_excepcion_escapa_tras_crear(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    real = g.crear

    def crear(padre, arista, datos, *, validate_only=False):
        if arista == "ads" and not validate_only:
            raise RuntimeError("inesperado")
        return real(padre, arista, datos, validate_only=validate_only)

    monkeypatch.setattr(g, "crear", crear)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and r.ids_creados["campana"] and len(r.ids_creados["creativos"]) == 1
    assert r.ids_creados["anuncios"] == {} and _eventos(aud)[-1]["ok"] is False


def test_auditoria_rota_no_tumba_tras_crear(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    r0 = montar(estructura(solo_validar=True), g, alm, aud, vault)
    assert r0.estado == "ejecutada"
    monkeypatch.setattr(aud, "anotar", lambda *a, **k: (_ for _ in ()).throw(OSError("disco")))
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and g.escrituras() == []  # sin auditoría no se crea nada


def test_stop_a_mitad(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.stop_tras = 3  # imagen, vídeo y campaña; el conjunto ya no
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.error == "stop" and r.parcial is True
    assert r.ids_creados["campana"] == "9000001" and r.ids_creados["conjuntos"] == {}


def test_stop_al_principio(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.stop_tras = 0
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.error == "stop" and g.escrituras() == []


def test_stop_lanzado_por_el_cliente_no_escapa(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    monkeypatch.setattr(g, "subir_video", lambda *a: (_ for _ in ()).throw(DetenidoPorStop()))
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.error == "stop" and "img01" in r.ids_creados["medios"]


def test_objeto_no_paused_tras_crear_es_discrepancia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.estado_tras_crear = "ACTIVE"
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and r.nueva_propuesta is None and "URGENTE" in r.detalle


def test_importe_releido_distinto_es_discrepancia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje

    def redondear():
        for o in g.objetos.values():
            if o.get("daily_budget") == "20000":
                o["daily_budget"] = "19900"

    g.al_escribir = redondear
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and "daily_budget" in r.detalle and r.nueva_propuesta is None


def test_relectura_sin_respuesta_es_discrepancia(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    real = g.leer

    def leer(id, campos):
        if "effective_status" in campos:
            raise RuntimeError("caída")
        return real(id, campos)

    monkeypatch.setattr(g, "leer", leer)
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and r.nueva_propuesta is None


def test_montaje_audita_y_registra_estructura(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert alm.ultimo_cambio(r.ids_creados["campana"], "estructura") is not None
    assert alm.ultimo_cambio(r.ids_creados["conjuntos"]["01 RO"], "estructura") is not None
    evs = [e for e in _eventos(aud) if e["evento"] == "ejecucion"]
    assert all(e["tipo"] == "crear_estructura_pausada" and e["id"] == "P-20261112-002" for e in evs)
    # la de la campaña antes de subir medios + una justo antes de cada una de las 6 creaciones
    assert sum(1 for e in evs if e["validate_only"] and e["ok"]) == 7
    assert evs[-1]["validate_only"] is False and evs[-1]["ok"] is True and evs[-1]["detalle"].startswith("ejecutada")
    assert r.ids_creados["anuncios"].keys() == {"AD01 img", "AD02 vid"}


# -- fix round 1: errores ambiguos, STOP en lecturas, parcial ----------------------------------------
@pytest.mark.parametrize("error", [ErrorGraph(2, None, "Service temporarily unavailable"),
                                   ErrorGraph(500, None, "HTTP 500"), ErrorGraph(1, None, "unknown"),
                                   ErrorGraph(12345, None, "raro")])
def test_error_ambiguo_al_crear_es_discrepancia(entorno_montaje, error):
    g, alm, aud, vault = entorno_montaje
    g.fallar_creacion["adsets"] = error
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and len(_reales(g, "adsets")) == 1 and _reales(g, "ads") == []
    assert f"Meta devolvió un error ambiguo ({error.codigo})" in r.detalle and "Ads Manager" in r.detalle
    assert r.nueva_propuesta is None and r.parcial is True


@pytest.mark.parametrize("codigo", [100, 190, 102, 10, 200, 299, 4, 17, 32, 613, 80004])
def test_rechazo_definitivo_al_crear_es_fallida(entorno_montaje, codigo):
    g, alm, aud, vault = entorno_montaje
    g.fallar_creacion["adsets"] = ErrorGraph(codigo, 1487, "rechazo")
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and "no se creó" in r.detalle and len(_reales(g, "adsets")) == 1


@pytest.mark.parametrize(("error", "estado"), [(ErrorGraph(500, None, "HTTP 500"), "discrepancia"),
                                              (ErrorGraph(2, None, "x"), "discrepancia"),
                                              (ErrorGraph(100, None, "Invalid image"), "fallida")])
def test_error_al_subir(entorno_montaje, monkeypatch, error, estado):
    g, alm, aud, vault = entorno_montaje

    def subir(*a):
        g.llamadas.append(type(g.llamadas[0])("subir_imagen", "x", {}))
        raise error

    monkeypatch.setattr(g, "subir_imagen", subir)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == estado and _reales(g) == []
    assert [l.metodo for l in g.llamadas].count("subir_imagen") == 1


def test_stop_en_lectura_del_video(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    real = g.leer

    def leer(id, campos):
        if id in g.videos:
            raise DetenidoPorStop()
        return real(id, campos)

    monkeypatch.setattr(g, "leer", leer)
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and r.error == "stop" and _reales(g) == []


def test_stop_en_relectura(entorno_montaje, monkeypatch):
    g, alm, aud, vault = entorno_montaje
    real = g.leer

    def leer(id, campos):
        if "effective_status" in campos:
            raise DetenidoPorStop()
        return real(id, campos)

    monkeypatch.setattr(g, "leer", leer)
    r = montar(estructura(origen="/montar"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and r.error == "stop" and r.nueva_propuesta is None


def test_montaje_completo_en_discrepancia_no_es_parcial(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.estado_tras_crear = "ACTIVE"
    r = montar(estructura(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and r.parcial is False
