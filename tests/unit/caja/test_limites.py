from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from ejemplos_caja import CFG, TRM, con_test
from trovefy.aprobaciones.fuentes import Lectura
from trovefy.caja.calculo import calcular
from trovefy.caja.limites import Recomendacion, propuestas_de_limites, recomendar
from trovefy_ejecutor.esquema import cargar_propuesta

ACT = "act_0000000000000000"
HOY = date(2026, 11, 12)
COT = timezone(timedelta(hours=-5))
AHORA = datetime(2026, 11, 12, 10, 0, tzinfo=COT)
FECHA_META = "2026-11-12T13:30:00+00:00"  # 08:30 COT, hace 1 h 30


def meta(**kw):
    d = {"cuenta": ACT, "currency": "COP", "offset": 1, "amount_spent": 0, "spend_cap": 1000000,
         "fecha": FECHA_META}
    d.update(kw)
    return Lectura(d, None)


def lim(moneda="COP", offset=1, tope=5000000):
    return Lectura({"cuentas": {ACT: {"moneda": moneda, "offset": offset, "tope_gasto_diario_total": tope}}}, None)


NO_META = Lectura(None, "no medido: el ejecutor no ha escrito meta.json")


def rec(cfg=CFG, gastos=()):
    return recomendar(calcular(cfg, [], list(gastos)), cfg)


def prop(rec_, cfg=CFG, trm=TRM, limites=None, m=None, ahora=AHORA):
    return propuestas_de_limites(rec_, cfg, trm, HOY, limites or lim(), m or meta(), ahora=ahora)


def test_recomendacion_por_defecto():
    r = rec()
    assert (r.tope_diario, r.limite_cuenta_restante) == (5000, 28000)


def test_reserva_desbloqueada_sube_el_limite():
    cfg = replace(CFG, reserva_desbloqueada=True)
    r = rec(cfg)
    assert r.limite_cuenta_restante == 48000
    assert r.tope_diario == min(5000, 2500 * 2 + 2000)


def test_sin_tests_ni_reserva_no_propone_cero():
    cfg = replace(CFG, sobres={"herramientas": 2000, "tests": 0, "reserva": 0})
    r = rec(cfg)
    assert r.tope_diario is None and "sin tests ni reserva: no se propone un tope de 0" in r.motivos


def test_gasto_desconocido_deja_limite_en_none():
    r = rec(con_test("vivo"), [])
    assert r.limite_cuenta_restante is None


def test_limite_cuenta_en_cop():
    props, _ = prop(rec())
    c = next(p for p in props if p["tipo"] == "limite_cuenta")
    op = c["operaciones"][0]
    assert op["a"] == 923179 and op["de_esperado"] == 1000000 and op["unidad"] == "minima"
    assert op["entidad"] == "account" and op["id"] == ACT and op["campo"] == "spend_cap"
    assert "3.297,07" in c["motivo"] and c["cuenta"] == ACT and c["origen"] == "/caja"


def test_limite_cuenta_sumando_gasto_acumulado():
    props, _ = prop(rec(), m=meta(amount_spent=100000, spend_cap=None))
    op = next(p for p in props if p["tipo"] == "limite_cuenta")["operaciones"][0]
    assert op["a"] == 1023179 and op["de_esperado"] is None


def test_limite_ejecutor_cop():
    props, _ = prop(rec())
    op = next(p for p in props if p["tipo"] == "limite_ejecutor")["operaciones"][0]
    assert op["a"] == 164853 and op["de_esperado"] == 5000000
    assert op["entidad"] == "ejecutor" and op["campo"] == "tope_gasto_diario_total" and op["moneda"] == "COP"


CFG_USD = replace(CFG, cuenta=replace(CFG.cuenta, moneda="USD"))


def test_usd_offset_100_solo_limite_ejecutor():
    props, nm = prop(rec(), cfg=CFG_USD, limites=lim("USD", 100, 6000),
                     m=meta(currency="USD", offset=100, amount_spent=0, spend_cap=None), trm=None)
    assert [p["tipo"] for p in props] == ["limite_ejecutor"]
    assert props[0]["operaciones"][0]["a"] == 5000
    assert "no medido: el límite de la cuenta solo se propone en COP hasta confirmar la unidad (P-21)" in nm


def test_valida_con_esquema_del_ejecutor():
    props, _ = prop(rec())
    assert len(props) == 2
    for i, p in enumerate(props, 1):
        cargar_propuesta({**p, "version": 1, "id": f"P-20261112-00{i}", "creada": "2026-11-12T10:00:00-05:00"})


def test_valida_usd_con_esquema():
    props, _ = prop(rec(), cfg=CFG_USD, limites=lim("USD", 100, 6000),
                    m=meta(currency="USD", offset=100, spend_cap=None), trm=None)
    cargar_propuesta({**props[0], "version": 1, "id": "P-20261112-001", "creada": "2026-11-12T10:00:00-05:00"})


def test_sin_trm_no_propone():
    props, nm = prop(rec(), trm=None)
    assert props == [] and f"no medido: sin TRM del {HOY}" in nm


def test_sin_meta_no_propone():
    props, nm = prop(rec(), m=NO_META)
    assert props == []
    assert "no medido: moneda de la cuenta sin confirmar (paso 13, comprobar-meta)" in nm


def test_sin_cuenta_no_propone():
    cfg = replace(CFG, cuenta=replace(CFG.cuenta, id=None))
    props, nm = prop(rec(cfg), cfg=cfg)
    assert props == [] and "no medido: falta la cuenta en config/caja.yaml" in nm


def test_igual_al_vivo_no_propone():
    props, _ = prop(rec(), m=meta(spend_cap=923179), limites=lim(tope=164853))
    assert props == []


def test_sin_gasto_acumulado_no_propone_limite_cuenta():
    d = meta()
    del d.datos["amount_spent"]
    props, nm = prop(rec(), m=d)
    assert [p["tipo"] for p in props] == ["limite_ejecutor"]
    assert "no medido: el ejecutor aún no informa el gasto acumulado de la cuenta" in nm


def test_monedas_distintas_no_propone():
    props, nm = prop(rec(), limites=lim("USD", 100, 6000))
    assert props == []  # limite_cuenta también exige el mismo offset en limites.json
    assert any("moneda" in n for n in nm)


def test_sin_valor_vivo_en_limites():
    props, nm = prop(rec(), limites=Lectura(None, "no medido: el ejecutor no ha escrito limites.json"))
    assert props == []
    assert "no medido: el ejecutor no ha escrito limites.json" in nm
    props, nm = prop(rec(), limites=Lectura({"cuentas": {ACT: {"moneda": "COP", "offset": 1}}}, None))
    assert [p["tipo"] for p in props] == ["limite_cuenta"]
    assert "no medido: limites.json sin tope_gasto_diario_total vivo" in nm


def test_recomendacion_sin_datos_no_propone():
    r = Recomendacion(None, None, ("x",))
    props, nm = prop(r)
    assert props == [] and nm


def test_motivo_menciona_usd_y_cop():
    props, _ = prop(rec())
    assert all("USD" in p["motivo"] and "COP" in p["motivo"] for p in props)


def test_evidencia():
    props, _ = prop(rec())
    ev = props[0]["evidencia"]
    assert ev["trm_fecha"] == "2026-11-11" and ev["huecos"] == 9 and "TRM" in ev["trm"]


def test_sobregasto_fija_el_limite_en_lo_gastado():
    r = Recomendacion(5000, -1000, ())
    props, _ = prop(r, m=meta(amount_spent=500000, spend_cap=1000000))
    c = next(p for p in props if p["tipo"] == "limite_cuenta")
    assert c["operaciones"][0]["a"] == 500000
    assert c["motivo"].startswith(
        "Sobregasto: los sobres no tienen saldo; el límite se fija en lo ya gastado y la cuenta deja de gastar")
    assert "500.000 COP" in c["motivo"]
    cargar_propuesta({**c, "version": 1, "id": "P-20261112-001", "creada": "2026-11-12T10:00:00-05:00"})


def test_sobregasto_nunca_por_debajo_de_lo_gastado():
    r = Recomendacion(5000, -999999999, ())
    props, _ = prop(r, m=meta(amount_spent=500000, spend_cap=None))
    assert next(p for p in props if p["tipo"] == "limite_cuenta")["operaciones"][0]["a"] == 500000


def test_sobregasto_sin_gasto_no_propone_cero():
    props, nm = prop(Recomendacion(5000, -1, ()), m=meta(amount_spent=0))
    assert all(p["tipo"] != "limite_cuenta" for p in props) and nm


def test_spend_cap_cero_es_sin_limite():
    props, _ = prop(rec(), m=meta(spend_cap=0))
    assert next(p for p in props if p["tipo"] == "limite_cuenta")["operaciones"][0]["de_esperado"] is None


# --- meta.json fresco (≤ 24 h) y offset de limites.json para limite_cuenta ---

def _tipos(props):
    return [p["tipo"] for p in props]


def test_limite_cuenta_lleva_la_fecha_de_meta_en_motivo_y_evidencia():
    props, _ = prop(rec())
    c = next(p for p in props if p["tipo"] == "limite_cuenta")
    assert "gasto acumulado de la cuenta del 2026-11-12 08:30" in c["motivo"]
    assert c["evidencia"]["meta_fecha"] == FECHA_META


def test_meta_de_hace_mas_de_24h_no_propone_limite_cuenta():
    props, nm = prop(rec(), m=meta(fecha="2026-11-11T14:59:00+00:00"))  # 25 h antes
    assert _tipos(props) == ["limite_ejecutor"]
    assert ("no medido: gasto acumulado de la cuenta del 2026-11-11 09:59 "
            "(repite trovefy-ejecutor comprobar-meta)") in nm


def test_meta_de_justo_24h_vale():
    props, _ = prop(rec(), m=meta(fecha="2026-11-11T15:00:00+00:00"))
    assert "limite_cuenta" in _tipos(props)


def test_meta_sin_fecha_o_futura_no_propone_limite_cuenta():
    for f in (None, "ayer", "2026-11-12T10:00:00", "2026-11-13T15:00:00+00:00"):
        props, nm = prop(rec(), m=meta(fecha=f))
        assert _tipos(props) == ["limite_ejecutor"], f
        assert any("repite trovefy-ejecutor comprobar-meta" in x for x in nm), f


def test_limite_cuenta_exige_offset_de_limites_igual_a_meta():
    props, nm = prop(rec(), limites=Lectura({"cuentas": {ACT: {"moneda": "COP", "offset": 100,
                                                                 "tope_gasto_diario_total": 5000000}}}, None))
    assert "limite_cuenta" not in _tipos(props)
    props, nm = prop(rec(), limites=Lectura(None, "no medido: el ejecutor no ha escrito limites.json"))
    assert "limite_cuenta" not in _tipos(props)
    assert any("offset" in x and "limites.json" in x for x in nm)


def test_moneda_de_caja_yaml_distinta_de_meta_no_propone():
    cfg = replace(CFG, cuenta=replace(CFG.cuenta, moneda="USD"))
    props, nm = prop(rec(cfg), cfg=cfg)
    assert props == []
    assert "no medido: la moneda de config/caja.yaml (USD) no coincide con la de la cuenta en Meta (COP)" in nm
    cfg = replace(CFG, cuenta=replace(CFG.cuenta, moneda=None))
    assert len(prop(rec(cfg), cfg=cfg)[0]) == 2  # sin moneda en caja.yaml manda meta.json
