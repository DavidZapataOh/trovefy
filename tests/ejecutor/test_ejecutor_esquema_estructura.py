import pytest
from fabricas import alerta, estructura
from trovefy_ejecutor.esquema import (
    PropuestaInvalida,
    cargar_propuesta,
    volcar_propuesta,
)


def test_solo_validar():
    assert cargar_propuesta(estructura()).estructura.solo_validar is False
    p = cargar_propuesta(estructura(solo_validar=True))
    assert p.estructura.solo_validar is True and cargar_propuesta(volcar_propuesta(p)) == p
    assert volcar_propuesta(p)["solo_validar"] is True
    with pytest.raises(PropuestaInvalida, match="solo_validar"):
        cargar_propuesta(estructura(solo_validar="si"))


def test_estructura_abo_cop():
    p = cargar_propuesta(estructura())
    assert p.clase == "no_gasto" and p.estructura.campana.tipo_presupuesto == "ABO"
    assert p.estructura.conjuntos[0].daily_budget == 20000 and p.estructura.moneda == "COP"
    assert cargar_propuesta(volcar_propuesta(p)) == p


def test_estructura_cbo_ida_y_vuelta():
    d = estructura()
    d["campana"].update(tipo_presupuesto="CBO", daily_budget=40000)
    del d["conjuntos"][0]["daily_budget"]
    p = cargar_propuesta(d)
    assert p.estructura.campana.daily_budget == 40000 and p.estructura.conjuntos[0].daily_budget is None
    assert cargar_propuesta(volcar_propuesta(p)) == p


@pytest.mark.parametrize("mutar,motivo", [
    (lambda d: d["campana"].update(status="ACTIVE"), "campo no permitido: status"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(medio="vid99"), "medio"),
    (lambda d: d["medios"][0].update(ruta="../../etc/passwd"), "ruta"),
    (lambda d: d["medios"][0].update(ruta="/etc/passwd"), "ruta"),
    (lambda d: d["medios"][0].update(sha256="abc"), "sha256"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(url="http://somatikalab.com"), "https"),
    (lambda d: d["campana"].update(daily_budget=40000), "CBO"),
    (lambda d: d["conjuntos"][0].pop("daily_budget"), "daily_budget"),
    (lambda d: d["campana"].update(spend_cap=True), "spend_cap"),
    (lambda d: d["conjuntos"][0].update(paises=["bg"]), "paises"),
    (lambda d: d["medios"].append(dict(d["medios"][0])), "ref"),
    (lambda d: d.update(unidad="centavos"), "unidad"),
    (lambda d: d["conjuntos"][0].update(status="ACTIVE"), "campo no permitido: status"),
    (lambda d: d.update(pagina_id="１２３"), "pagina_id"),
])
def test_estructura_rechazos(mutar, motivo):
    d = estructura()
    mutar(d)
    with pytest.raises(PropuestaInvalida, match=motivo):
        cargar_propuesta(d)


def test_alerta():
    p = cargar_propuesta(alerta())
    assert p.clase == "notificacion" and p.alerta.nivel == "aviso" and p.cuenta is None
    assert cargar_propuesta(volcar_propuesta(p)) == p
    with pytest.raises(PropuestaInvalida, match="nivel"):
        cargar_propuesta(alerta(nivel="critico"))


def test_alerta_adjuntos_y_limites():
    p = cargar_propuesta(alerta(adjuntos=["productos/x/qc/c.png"]))
    assert p.alerta.adjuntos == ("productos/x/qc/c.png",)
    assert cargar_propuesta(volcar_propuesta(p)) == p
    for malo in (alerta(adjuntos=["../x"]), alerta(adjuntos=["a"] * 11), alerta(titulo=""), alerta(texto="x" * 3001),
                 alerta(extra=1)):
        with pytest.raises(PropuestaInvalida):
            cargar_propuesta(malo)


# -- plan 22, Tarea 5: campos para un montaje real en la UE ---------------------------------------------------------
UTM = ("utm_source=fb&utm_medium=paid&utm_campaign={{campaign.name}}|{{campaign.id}}"
       "&utm_term={{adset.name}}|{{adset.id}}&utm_content={{ad.name}}|{{ad.id}}")


def _completa() -> dict:
    d = estructura()
    cj = d["conjuntos"][0]
    cj.update(inicio="2026-11-13T00:00:00-05:00", generos=[2])
    cj["anuncios"][0].update(url_tags=UTM, miniatura="productos/p-0001/creativos/BG/t1/AD01.jpg")
    d["campana_existente"] = "120000000000001"
    return d


def test_volcar_y_cargar_ida_y_vuelta():
    p = cargar_propuesta(_completa())
    cj = p.estructura.conjuntos[0]
    assert cj.inicio == "2026-11-13T00:00:00-05:00" and cj.generos == (2,)
    assert cj.anuncios[0].url_tags == UTM and p.estructura.dsa.beneficiario == "Beneficiario Prueba"
    assert p.estructura.campana_existente == "120000000000001"
    v = volcar_propuesta(p)
    assert cargar_propuesta(v) == p and "None" not in str(v)
    # sin los campos nuevos, el volcado no los inventa
    v2 = volcar_propuesta(cargar_propuesta(estructura()))
    assert "inicio" not in v2["conjuntos"][0] and "url_tags" not in v2["conjuntos"][0]["anuncios"][0]


def test_dsa_obligatorio_en_la_ue():
    d = estructura()
    del d["dsa"]
    with pytest.raises(PropuestaInvalida, match="dsa"):
        cargar_propuesta(d)
    d["conjuntos"][0]["paises"] = ["NO"]  # fuera de la UE no hace falta
    assert cargar_propuesta(d).estructura.dsa is None


@pytest.mark.parametrize("mutar, motivo", [
    (lambda d: d["dsa"].update(otro="x"), "campo no permitido"),
    (lambda d: d["dsa"].update(pagador=""), "pagador"),
    (lambda d: d["conjuntos"][0].update(inicio="2026-11-13T00:00:00"), "zona"),
    (lambda d: d["conjuntos"][0].update(inicio="2026-11-30T00:00:00-05:00"), "rango"),
    (lambda d: d["conjuntos"][0].update(inicio="2026-11-10T00:00:00-05:00"), "rango"),
    (lambda d: d["conjuntos"][0].update(generos=[3]), "generos"),
    (lambda d: d["conjuntos"][0].update(generos=[1, 1]), "generos"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(url_tags=UTM + "&access_token=x"), "access_token"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(url_tags="utm source=fb"), "espacios"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(url_tags="utm_source"), "clave=valor"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(url_tags="a=1&&b=2"), "clave=valor"),
    (lambda d: d["conjuntos"][0]["anuncios"][0].update(miniatura="../fuera.jpg"), "miniatura"),
    (lambda d: d.update(campana_existente="act_1"), "campana_existente"),
])
def test_campos_nuevos_rechazos(mutar, motivo):
    d = estructura()
    mutar(d)
    with pytest.raises(PropuestaInvalida, match=motivo):
        cargar_propuesta(d)


def test_url_tags_con_token_rechazado():
    d = estructura()
    d["conjuntos"][0]["anuncios"][0]["url_tags"] = "utm_source=fb&ACCESS_TOKEN=abc"
    with pytest.raises(PropuestaInvalida, match="access_token"):
        cargar_propuesta(d)


def test_inicio_sin_zona_rechazado():
    d = estructura()
    d["conjuntos"][0]["inicio"] = "2026-11-13T00:00:00"
    with pytest.raises(PropuestaInvalida, match="zona"):
        cargar_propuesta(d)
