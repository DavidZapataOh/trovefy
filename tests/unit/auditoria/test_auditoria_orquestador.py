from datetime import date, datetime

import pytest
from ejemplos_auditoria import oferta_ejemplo
from trovify.auditoria import orquestador
from trovify.caza.cliente import SesionBloqueada
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.orquestador import CazaEnCurso, cerrojo_caza
from trovify.caza.presupuesto import PresupuestoAgotado
from trovify.vault.andamio import crear_vault
from trovify.vault.frontmatter import escribir, leer

HOY = date(2026, 11, 10)
FRASES = {"RO": ["fise terapie", "kit terapie"], "IT": ["schede terapia", "kit terapia"]}


class ClienteFalso:
    def __init__(self, resultados=None, por_defecto=None):
        self.resultados = list(resultados or [])
        self.por_defecto = por_defecto
        self.llamadas = []

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60):
        self.llamadas.append((pais, q, page_id))
        r = self.resultados.pop(0) if self.resultados else self.por_defecto or vacio(pais)
        if isinstance(r, Exception):
            raise r
        return r


def vacio(pais="RO"):
    return ResultadoBusqueda("vacio", f"https://www.facebook.com/ads/library/?country={pais}&q=x", 0, [], None,
                             datetime(2026, 11, 10), True)


def bloqueado():
    return ResultadoBusqueda("bloqueado", "https://www.facebook.com/ads/library/?q=b", None, [], "captcha",
                             datetime(2026, 11, 10))


def nunca(*_a, **_k) -> None:
    """Sin cambio del BCE (sin red): el precio en EUR se mide; el local de cada país queda «no medido»."""


@pytest.fixture
def v(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v / "wiki/ofertas/o-ejemplo.md", oferta_ejemplo(), "")
    return v


def por_pais(r):
    return {p.pais: p for p in r.paises}


def test_audita_y_escribe(v):
    c = ClienteFalso()
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert r.ruta == v / "productos/p-0001-ejemplo/AUDITORIA.md" and r.ruta.exists()
    assert r.parada is None and r.tipo is None
    ps = por_pais(r)
    assert ps["RO"].hueco.hueco is True and ps["RO"].precio_eur.valor == pytest.approx(13.9)
    assert ps["RO"].precio_s.valor == 1.0 and ps["RO"].nota == pytest.approx(100)
    # 2 frases + 1 página del original por país
    assert len(c.llamadas) == 6
    assert ("RO", None, "100000000000001") in c.llamadas


def test_paises_por_defecto_son_los_candidatos(v):
    mercado = ("{p}:\n  idioma: {i}\n  moneda: EUR\n  zona: Europe/Rome\n  banda_eur: [11.90, 15.90]\n"
               "  fuente_banda: prueba\n  estado: {e}\n")
    (v / "config/mercados.yaml").write_text(
        mercado.format(p="RO", i="ro", e="candidato") + mercado.format(p="IT", i="it", e="descartado"),
        encoding="utf-8")
    r = orquestador.auditar(v, "o-ejemplo", None, FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    assert [p.pais for p in r.paises] == ["RO"]
    assert r.paises[0].banda == (11.9, 15.9) and r.paises[0].fuente_banda == "prueba"
    assert "banda de RO: 11,90–15,90 € (fuente: prueba, config/mercados.yaml)" in r.ruta.read_text()


def test_pais_desconocido(v):
    with pytest.raises(ValueError, match="ZZ"):
        orquestador.auditar(v, "o-ejemplo", ["ZZ"], {}, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)


def test_sin_ficha(v):
    with pytest.raises(FileNotFoundError):
        orquestador.auditar(v, "o-nada", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)


def test_bloqueo_de_meta_para_y_deja_el_resto_no_medido(v):
    c = ClienteFalso([SesionBloqueada("captcha")])
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert r.tipo == "meta" and len(c.llamadas) == 1
    ps = por_pais(r)
    assert ps["RO"].hueco.hueco is None
    assert ps["IT"].hueco.hueco is None and ps["IT"].hueco.competencia.motivo.startswith("no medido: Meta bloqueó")
    assert ps["IT"].hueco.motivo.startswith("no medido: Meta bloqueó")
    assert r.ruta.exists()  # lo medido se escribe igual


def test_resultado_bloqueado_tambien_para(v):
    c = ClienteFalso([vacio(), bloqueado()])
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert r.tipo == "meta" and len(c.llamadas) == 2
    assert por_pais(r)["IT"].hueco.motivo.startswith("no medido: Meta bloqueó")


def test_cuota_agotada_es_final_normal(v):
    c = ClienteFalso([vacio(), vacio(), vacio("RO"), PresupuestoAgotado("tope de 20")])
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert r.tipo == "cuota"
    ps = por_pais(r)
    assert ps["RO"].hueco.hueco is True
    assert ps["IT"].hueco.hueco is None


def test_cuota_agotada_antes_de_un_pais(v):
    c = ClienteFalso([vacio(), vacio(), vacio("RO"), PresupuestoAgotado("tope de 20")])
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT", "FR"], {**FRASES, "FR": ["a b", "c d"]}, cliente=c,
                            hoy=HOY, cambios=nunca)
    assert por_pais(r)["FR"].hueco.motivo == "no medido: cuota del día agotada"
    assert len(c.llamadas) == 4


def test_sin_frases_la_competencia_no_se_mide(v):
    c = ClienteFalso()
    r = orquestador.auditar(v, "o-ejemplo", ["RO"], {}, cliente=c, hoy=HOY, cambios=nunca)
    h = por_pais(r)["RO"].hueco
    assert h.hueco is None and "frases" in h.competencia.motivo
    assert all(q is None for _, q, _ in c.llamadas)


def test_moneda_ambigua_precio_no_medido(v):
    o = oferta_ejemplo()
    o["moneda"] = None
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "")
    r = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    p = por_pais(r)["RO"]
    assert p.precio_eur.valor is None and "moneda" in p.precio_eur.motivo
    assert p.precio_s.valor is None
    assert "13,90 (moneda no medida" in r.ruta.read_text()


def test_moneda_sin_cambio_no_medido(v):
    o = oferta_ejemplo()
    o["precio"], o["moneda"] = 79, "RON"
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "")
    r = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY,
                            cambios=lambda vault, hoy: None)
    assert por_pais(r)["RO"].precio_eur.motivo == "no medido: sin cambio de referencia para RON"
    r = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY,
                            cambios=lambda vault, hoy: {"EUR": 1.0, "RON": 5.0})
    assert por_pais(r)["RO"].precio_eur.valor == pytest.approx(15.8)


def test_sin_precio(v):
    o = oferta_ejemplo()
    o["precio"] = None
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "")
    r = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    assert por_pais(r)["RO"].precio_eur.motivo.startswith("no medido")


def test_cerrojo_de_la_caza(v):
    with cerrojo_caza(v), pytest.raises(CazaEnCurso):
        orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)


def test_reauditar_mismo_producto(v):
    r1 = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    r2 = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=date(2026, 11, 12),
                             cambios=nunca)
    assert r1.ruta == r2.ruta and r1.p_id == r2.p_id
    meta, _ = leer(r2.ruta)
    assert meta["fecha"] == "2026-11-12"


def test_por_defecto_con_la_plantilla_y_no_sin_comillas(v):
    """C-1: el cerebro de plantilla (y uno viejo con «NO:» sin comillas) audita sin --pais."""
    r = orquestador.auditar(v, "o-ejemplo", None, FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    assert "NO" in {p.pais for p in r.paises} and len(r.paises) == 15
    ruta = v / "config/mercados.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace('"NO":', "NO:"), encoding="utf-8")
    r = orquestador.auditar(v, "o-ejemplo", ["no"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    assert [p.pais for p in r.paises] == ["NO"]


def test_mercados_con_clave_rara_es_error_claro(v):
    (v / "config/mercados.yaml").write_text("true:\n  idioma: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="entre comillas"):
        orquestador.auditar(v, "o-ejemplo", None, FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)


def test_precio_con_su_procedencia_y_el_precio_local(v):
    from trovify import fx

    o = oferta_ejemplo()
    o["precio"], o["moneda"] = 79, "RON"
    del o["landing"]  # las fichas del plan 07 la llevan en el cuerpo
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "# Oferta\n\n## Destino\n\n- Landing: https://tienda.example/fichas?x=1\n")
    cambio = fx.Cambio({"EUR": 1.0, "RON": 5.0, "CZK": 25.0}, "2026-11-09", fx.URL)
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "CZ", "BG"], FRASES, cliente=ClienteFalso(), hoy=HOY,
                            cambios=lambda vault, hoy: cambio)
    texto = r.ruta.read_text()
    assert ("Precio del original en EUR: 79 RON ÷ 5 (cambio de referencia del BCE del 2026-11-09, "
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml) = 15,80 €") in texto
    assert "Precio del original: 79 RON — landing: https://tienda.example/fichas?x=1" in texto
    assert "precio local en RO: ≈ 79,00 RON" in texto
    assert "precio local en CZ: ≈ 395,00 CZK" in texto
    assert "precio local en BG: 15,80 EUR" in texto


def test_sin_cambio_del_bce_el_precio_local_no_se_mide(v):
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "BG"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    texto = r.ruta.read_text()
    assert "Precio del original en EUR: 13,90 € (la ficha ya está en euros: sin cambio)" in texto
    assert "precio local en RO: no medido: sin cambio de referencia para RON" in texto
    assert "precio local en BG: 13,90 EUR" in texto
    assert "landing: https://tienda.example/fichas" in texto  # del frontmatter de la ficha


# ------------------------------------------------------------------ presupuesto del día (I-4)

CUATRO = "".join(
    f"{p}:\n  idioma: {i}\n  moneda: EUR\n  zona: Europe/Rome\n  banda_eur: [11.90, 15.90]\n  estado: candidato\n"
    for p, i in (("RO", "ro"), ("IT", "it"), ("FR", "fr"), ("ES", "es")))
FRASES4 = {p: [f"{p.lower()} uno", f"{p.lower()} dos"] for p in ("RO", "IT", "FR", "ES")}


class ClienteConPresupuesto(ClienteFalso):
    def __init__(self, v, usadas, hoy=HOY):
        from trovify.caza.presupuesto import Presupuesto

        super().__init__()
        contador = v / "data/caza/presupuesto" / f"{hoy.isoformat()}.json"
        contador.parent.mkdir(parents=True, exist_ok=True)
        contador.write_text(f'{{"usadas": {usadas}, "rutina": 0}}\n', encoding="utf-8")
        self.presupuesto = Presupuesto(30, 0, 0, dormir=lambda s: None, contador=contador)

    def buscar(self, pais, **kw):
        self.presupuesto.antes_de_buscar()
        return super().buscar(pais, **kw)


def paises_llamados(c):
    return list(dict.fromkeys(p for p, _, _ in c.llamadas))


def test_por_defecto_mide_lo_que_cabe_en_la_cuota_empezando_por_los_de_la_ficha(v):
    (v / "config/mercados.yaml").write_text(CUATRO, encoding="utf-8")
    c = ClienteConPresupuesto(v, usadas=23)  # quedan 7: caben 2 países de 3 búsquedas
    r = orquestador.auditar(v, "o-ejemplo", None, FRASES4, cliente=c, hoy=HOY, cambios=nunca)
    assert paises_llamados(c) == ["ES", "RO"]  # ES está en la ficha: va primero
    ps = por_pais(r)
    assert ps["ES"].hueco.hueco is True and ps["RO"].hueco.hueco is True
    for p in ("IT", "FR"):
        assert ps[p].hueco.motivo == "no medido: cuota del día agotada — se retoma mañana"
    assert r.tipo == "cuota" and (r.usadas_hoy, r.max_hoy, r.hechas) == (29, 30, 6)
    texto = r.ruta.read_text()
    assert "Búsquedas de hoy: 29 de 30 usadas (quedan 1); esta auditoría hizo 6" in texto
    assert "3 por país" in texto


def test_volver_a_auditar_el_mismo_dia_continua_donde_se_quedo(v):
    (v / "config/mercados.yaml").write_text(CUATRO, encoding="utf-8")
    orquestador.auditar(v, "o-ejemplo", None, FRASES4, cliente=ClienteConPresupuesto(v, usadas=23), hoy=HOY,
                        cambios=nunca)
    c = ClienteConPresupuesto(v, usadas=24)  # quedan 6: los dos que faltaban
    r = orquestador.auditar(v, "o-ejemplo", None, FRASES4, cliente=c, hoy=HOY, cambios=nunca)
    assert paises_llamados(c) == ["IT", "FR"]
    ps = por_pais(r)
    assert all(ps[p].hueco.hueco is True for p in ("ES", "RO", "IT", "FR"))
    assert "medido el 2026-11-10 (en una auditoría anterior de esta oferta)" in ps["RO"].hueco_medido
    assert r.tipo is None


def test_reutiliza_el_hueco_reciente_de_la_ficha_sin_buscar(v):
    from trovify.caza.hueco import HuecoPais
    from trovify.caza.orquestador import hueco_a_dict
    from trovify.caza.senales import Medida

    o = oferta_ejemplo()
    enlace = "https://www.facebook.com/ads/library/?country=RO&q=fise"
    o["huecos"] = {
        "RO": hueco_a_dict(HuecoPais("RO", Medida(0), "ausente", True, [enlace]), date(2026, 11, 8)),
        "IT": hueco_a_dict(HuecoPais("IT", Medida(0), "ausente", True, []), date(2026, 11, 1)),  # 9 días
    }
    escribir(v / "wiki/ofertas/o-ejemplo.md", o, "")
    c = ClienteFalso()
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert paises_llamados(c) == ["IT"]
    ro = por_pais(r)["RO"]
    assert ro.hueco.hueco is True and ro.hueco.enlaces == [enlace]
    texto = r.ruta.read_text()
    assert "medido el 2026-11-08 (con trovify caza hueco, en la ficha de la oferta)" in texto
    assert "hoy no se volvió a buscar" in texto


def test_con_pais_explicito_no_se_planifica_la_cuota(v):
    c = ClienteConPresupuesto(v, usadas=27)  # quedan 3: un país; con --pais se intenta y la cuota corta
    r = orquestador.auditar(v, "o-ejemplo", ["RO", "IT"], FRASES, cliente=c, hoy=HOY, cambios=nunca)
    assert paises_llamados(c) == ["RO"] and r.tipo == "cuota"
