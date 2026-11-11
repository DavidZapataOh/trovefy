import sys
from datetime import date, datetime

sys.modules.pop("ejemplos", None)  # la caza también tiene un ejemplos.py: que no se crucen
from ejemplos import oferta_ejemplo

sys.modules.pop("ejemplos", None)

import pytest
from trovify.auditoria import orquestador
from trovify.caza.cliente import SesionBloqueada
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.orquestador import CazaEnCurso, _cerrojo_caza
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


def nunca(*_a, **_k):
    raise AssertionError("no hacía falta el cambio del BCE")


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
    ruta = v / "config/mercados.yaml"
    texto = ruta.read_text(encoding="utf-8").replace("estado: candidato", "estado: descartado")
    texto = texto.replace("RO:\n  idioma: ro\n  moneda: RON\n  zona: Europe/Bucharest\n  banda_eur: [11.90, 15.90]\n"
                          "  fuente_banda: \"vídeos: 11,90–15,90 €\"\n  precio_referencia: \"79 RON\"\n"
                          "  estado: descartado", "RO:\n  idioma: ro\n  moneda: RON\n  zona: Europe/Bucharest\n"
                          "  banda_eur: [11.90, 15.90]\n  fuente_banda: \"vídeos: 11,90–15,90 €\"\n"
                          "  precio_referencia: \"79 RON\"\n  estado: candidato")
    ruta.write_text(texto, encoding="utf-8")
    r = orquestador.auditar(v, "o-ejemplo", None, FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    assert [p.pais for p in r.paises] == ["RO"]


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
    with _cerrojo_caza(v), pytest.raises(CazaEnCurso):
        orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)


def test_reauditar_mismo_producto(v):
    r1 = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=HOY, cambios=nunca)
    r2 = orquestador.auditar(v, "o-ejemplo", ["RO"], FRASES, cliente=ClienteFalso(), hoy=date(2026, 11, 12),
                             cambios=nunca)
    assert r1.ruta == r2.ruta and r1.p_id == r2.p_id
    meta, _ = leer(r2.ruta)
    assert meta["fecha"] == "2026-11-12"
