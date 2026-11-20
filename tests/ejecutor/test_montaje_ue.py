"""Plan 22, Tarea 5: DSA, url_tags, hora de salida, sexo, catálogo apagado y conjuntos nuevos en una campaña viva."""
from __future__ import annotations

from ejecutor.fabricas_graph import RUTA_IMG, anuncio, conjunto, estructura
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.modelo import Dsa
from trovefy_ejecutor.montaje import CATALOGO_OPT_OUT, montar

NADA = lambda s: None
DSA = Dsa("Beneficiario Prueba", "Pagador Prueba")
UTM = ("utm_source=fb&utm_medium=paid&utm_campaign={{campaign.name}}|{{campaign.id}}"
       "&utm_term={{adset.name}}|{{adset.id}}&utm_content={{ad.name}}|{{ad.id}}")
INICIO = "2026-11-13T00:00:00-05:00"


def _p_ue(**cambios):
    cj = conjunto(inicio=INICIO, generos=(2,),
                  anuncios=(anuncio(url_tags=UTM, url="https://ejemplo.test/ro"),
                            anuncio(nombre="AD02 vid", medio="vid01", url_tags=UTM,
                                    miniatura="productos/p-0001/creativos/RO/t1/miniaturas/AD02.jpg")))
    base = {"conjuntos": [cj], "dsa": DSA, "origen": "/montar"}
    base.update(cambios)
    return estructura(**base)


def _reales(g, arista):
    return [x for x in g.llamadas if x.metodo == "crear" and not x.validate_only and x.ruta.endswith("/" + arista)]


def test_conjunto_lleva_dsa_y_no_toca_advantage(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada", r.detalle
    c = _reales(g, "adsets")[0].datos
    assert c["dsa_beneficiary"] == "Beneficiario Prueba" and c["dsa_payor"] == "Pagador Prueba"
    assert c["start_time"] == INICIO and c["targeting"]["genders"] == [2]
    assert "targeting_automation" not in c["targeting"]


def test_creativo_con_url_tags_y_solo_catalogo_apagado(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    for x in _reales(g, "adcreatives"):
        assert x.datos["url_tags"] == UTM
        spec = x.datos["degrees_of_freedom_spec"]["creative_features_spec"]
        assert spec == {CATALOGO_OPT_OUT: {"enroll_status": "OPT_OUT"}}
        assert "miniaturas/AD02.jpg" not in str(x.datos)  # la miniatura de la tanda no se sube a Meta


def test_sin_campos_nuevos_no_se_envian(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    montar(estructura(), g, alm, aud, vault, esperar=NADA)
    c = _reales(g, "adsets")[0].datos
    assert not {"start_time", "dsa_beneficiary", "dsa_payor"} & set(c) and "genders" not in c["targeting"]
    assert all("url_tags" not in x.datos for x in _reales(g, "adcreatives"))


def test_campos_nuevos_no_cambian_paused(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    creaciones = [x for x in g.llamadas if x.metodo == "crear" and not x.ruta.endswith("/adcreatives")]
    assert r.estado == "ejecutada" and creaciones
    assert all(x.datos["status"] == "PAUSED" for x in creaciones)


def test_relectura_detecta_start_time_distinto(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    leer = g.leer

    def leer_otro(id, campos):
        r = leer(id, campos)
        if "start_time" in r:
            r["start_time"] = "2026-11-14T00:00:00-0500"
        return r

    g.leer = leer_otro
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and "start_time" in r.detalle
    assert r.nueva_propuesta is None


def test_relectura_mismo_instante_en_otro_formato_ok(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    leer = g.leer

    def leer_meta(id, campos):
        r = leer(id, campos)
        if "start_time" in r:
            r["start_time"] = "2026-11-13T05:00:00+0000"
        return r

    g.leer = leer_meta
    assert montar(_p_ue(), g, alm, aud, vault, esperar=NADA).estado == "ejecutada"


def test_relectura_detecta_url_tags_distintos(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    leer = g.leer

    def leer_otro(id, campos):
        r = leer(id, campos)
        if "url_tags" in r:
            r["url_tags"] = "utm_source=otro"
        return r

    g.leer = leer_otro
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "discrepancia" and "url_tags" in r.detalle


def test_vista_previa_en_ids_creados(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    vistas = r.ids_creados["vistas_previas"]
    assert set(vistas) == {"AD01 img", "AD02 vid"} and all(v.startswith("https://fb.me/") for v in vistas.values())


def test_sin_vista_previa_no_medido_no_es_discrepancia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    g.dar_vista_previa = False
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada" and r.ids_creados["vistas_previas"] == {}
    assert "no medido" in r.detalle


def test_activar_trae_anuncios_en_evidencia(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    nueva = r.nueva_propuesta
    cargar_propuesta(nueva)
    anuncios = nueva["evidencia"]["anuncios"]
    assert [a["nombre"] for a in anuncios] == ["AD01 img", "AD02 vid"]
    assert anuncios[0]["miniatura"] == RUTA_IMG and anuncios[0]["miniatura_url"] is None
    assert anuncios[1]["miniatura"].endswith("miniaturas/AD02.jpg") and anuncios[1]["miniatura_url"] == g.miniatura
    assert anuncios[0]["vista_previa"].startswith("https://fb.me/")
    assert nueva["motivo"].startswith("Activar campaña PRUEBA RO | ABO: 1 × 20.000 COP/día, techo 120.000 COP")
    assert any(op["entidad"] == "campaign" for op in nueva["operaciones"])


# -- campana_existente (renovación en la misma ABO, Tarea 13) ---------------------------------------------------------
def _montada(g, alm, aud, vault) -> str:
    r = montar(_p_ue(), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "ejecutada", r.detalle
    return r.ids_creados["campana"]


def _renovacion(campana: str, **cambios):
    cj = conjunto(nombre="AD06 G2 nuevo", inicio=INICIO,
                  anuncios=(anuncio(nombre="AD06 G2 nuevo", url_tags=UTM),))
    return _p_ue(id="P-20261112-003", conjuntos=[cj], campana_existente=campana, **cambios)


def test_campana_existente_crea_solo_conjuntos(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    campana = _montada(g, alm, aud, vault)
    antes = len(g.llamadas)
    r = montar(_renovacion(campana), g, alm, aud, vault, esperar=NADA)
    nuevas = g.llamadas[antes:]
    assert r.estado == "ejecutada", r.detalle
    assert not [x for x in nuevas if x.metodo == "crear" and x.ruta.endswith("/campaigns")]
    adsets = [x for x in nuevas if x.metodo == "crear" and not x.validate_only and x.ruta.endswith("/adsets")]
    assert len(adsets) == 1 and adsets[0].datos["campaign_id"] == campana and adsets[0].datos["status"] == "PAUSED"
    assert r.ids_creados["campana"] is None and list(r.ids_creados["conjuntos"]) == ["AD06 G2 nuevo"]
    ops = r.nueva_propuesta["operaciones"]
    assert {op["entidad"] for op in ops} == {"adset", "ad"} and len(ops) == 2
    assert "misma campaña" in r.nueva_propuesta["motivo"]
    # la campaña no se tocó ni se releyó como propia
    assert not [x for x in nuevas if x.metodo == "escribir"]


def test_campana_existente_ajena_rechazada(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    for campana in ("c1", "x9"):  # c1: de la cuenta pero no la creó Trovefy; x9: de otra cuenta
        r = montar(_renovacion(campana), g, alm, aud, vault, esperar=NADA)
        assert r.estado == "fallida" and campana in r.detalle
    assert g.escrituras() == []


def test_campana_existente_inexistente_rechazada(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    r = montar(_renovacion("123456"), g, alm, aud, vault, esperar=NADA)
    assert r.estado == "fallida" and g.escrituras() == []


def test_campana_existente_solo_validar_valida_conjuntos(entorno_montaje):
    g, alm, aud, vault = entorno_montaje
    campana = _montada(g, alm, aud, vault)
    antes = len(g.llamadas)
    r = montar(_renovacion(campana, solo_validar=True), g, alm, aud, vault, esperar=NADA)
    nuevas = [x for x in g.llamadas[antes:] if x.metodo == "crear"]
    assert r.estado == "ejecutada" and r.nueva_propuesta is None
    assert nuevas and all(x.validate_only and x.ruta.endswith("/adsets") for x in nuevas)
    assert not [x for x in g.llamadas[antes:] if x.metodo in ("subir_imagen", "subir_video")]
