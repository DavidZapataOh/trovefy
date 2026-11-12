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
