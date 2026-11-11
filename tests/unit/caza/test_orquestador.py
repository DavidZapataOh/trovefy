import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from ayudas import anuncio
from test_cliente import cliente as cliente_falso
from test_cliente import de_fixture
from trovefy.caza import orquestador, snapshots
from trovefy.caza.biblioteca import url_biblioteca
from trovefy.caza.cliente import SesionBloqueada
from trovefy.caza.destino import Destino
from trovefy.caza.modelo import ResultadoBusqueda
from trovefy.caza.orquestador import (
    aplicar_strikes,
    ejecutar,
    palabras_a_reescribir,
    texto_sin_pie,
)
from trovefy.caza.presupuesto import Presupuesto, PresupuestoAgotado
from trovefy.vault import frontmatter
from trovefy.vault.andamio import crear_vault

HOY = date(2026, 11, 10)
# Hora de captura fija en HOY (Bogotá): las lecturas de otro día de negocio no registran vistos.
CAPTURA = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)


# --- pruebas del plan ---------------------------------------------------------------------


def test_ejecucion_completa_con_fixture(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=["102506312071455"],
                 cliente=cliente_falso([de_fixture("pagina_therapy_toolkit.json")]),
                 resolver=lambda url: None, hoy=date(2026, 11, 10))
    assert e.busquedas == 1 and len([r for r in e.resultados if r.descarte is None]) <= 3
    fichas = list((v / "wiki/ofertas").glob("o-*.md"))
    assert fichas and "link_biblioteca" in fichas[0].read_text()
    assert (v / "wiki/caza/2026-11-10/veredicto.md").exists()
    # sin landing abierta: agrupada por página y descartada, nada inventado
    assert all(r.descarte and r.descarte.codigo == "embudo_no_verificable" for r in e.resultados)


def test_strikes_podan_y_fallo_de_entorno_no_cuenta(tmp_path):
    fichas = {"o-1": {"estado": "B", "strikes": 2, "motivo_strike": "cayendo"}, "o-2": {"estado": "A", "strikes": 0}}
    nuevas = aplicar_strikes(fichas, {"o-1": ("observar", "cayendo"), "o-2": ("A", "")})
    assert nuevas["o-1"]["estado"] == "podada"
    entorno = aplicar_strikes(fichas, {"o-1": ("observar", "cayendo"), "o-2": ("descartada", "bloqueo")})
    assert entorno["o-1"]["strikes"] == 2          # más de la mitad fallan: no se cuenta


def test_presupuesto_del_dia_compartido(tmp_path):
    v = tmp_path / "v"; crear_vault(v)
    (v / "data/caza/presupuesto").mkdir(parents=True)
    (v / "data/caza/presupuesto/2026-11-10.json").write_text(json.dumps({"usadas": 30}))
    with pytest.raises(PresupuestoAgotado):
        Presupuesto.desde_umbrales(v, date(2026, 11, 10)).antes_de_buscar()


# --- cliente falso por URL -----------------------------------------------------------------


class Presu:
    def __init__(self):
        self.usadas = self.bloqueos = self.vacios = 0


class ClientePorUrl:
    """Devuelve el resultado preparado para cada URL; una URL sin preparar es un fallo de la prueba."""

    def __init__(self, respuestas: dict, excepcion_en: dict | None = None):
        self.respuestas, self.excepcion_en = respuestas, excepcion_en or {}
        self.presupuesto = Presu()
        self.llamadas: list[str] = []

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60, completa=False):
        url = url_biblioteca(pais, q, page_id, estado)
        self.llamadas.append(url)
        if url in self.excepcion_en:
            raise self.excepcion_en[url]
        self.presupuesto.usadas += 1
        r = self.respuestas.get(url)
        if r is None:
            return ResultadoBusqueda("vacio", url, 0, [], None, CAPTURA, True, "firecrawl", 1,
                                     total_exacto=True)
        if r.estado == "bloqueado":
            self.presupuesto.bloqueos += 1
        return replace(r, url=url)


def ok(anuncios, total=None, completo=True, exacto=True, via="firecrawl", creditos=1):
    total = len(anuncios) if total is None else total
    return ResultadoBusqueda("ok", "", total, list(anuncios), None, CAPTURA, completo,
                             via, creditos, None, total_exacto=exacto)


def viejos(page, n, dias, base, pais="RO", destino="https://kit.example/ro/", activo=True):
    return [replace(anuncio(str(base + i), page, HOY - timedelta(days=dias), pais=pais, destino=destino,
                            activo=activo), texto="Fișe de lucru pentru copii în format PDF, descarcă acum")
            for i in range(n)]


def destino_ok(url, checkout="https://pay.hotmart.com/K123", precio=49.0, moneda="RON"):
    return Destino(url, url, "hotmart", checkout, precio, moneda, None, False, False, "ok", None)


def resolver_fijo(mapa: dict, abiertas: list | None = None):
    def resolver(url):
        if abiertas is not None:
            abiertas.append(url)
        return mapa.get(url)
    return resolver


def _vault(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    return v


# --- búsqueda, total exacto y vistos --------------------------------------------------------


def test_nicho_mide_pagina_y_pasa_total_exacto(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000011"
    ads = viejos(P, 12, 20, 1000)
    c = ClientePorUrl({
        url_biblioteca("RO", q="fise de lucru"): ok(ads[:5], total=40, completo=False, exacto=False),
        url_biblioteca("RO", page_id=P): ok(ads, total=12),
    })
    url = "https://kit.example/ro/"
    e = ejecutar(v, "nicho", [("RO", "fise de lucru")], "tomi", 3, cliente=c,
                 resolver=resolver_fijo({url: (destino_ok(url), "Fișe PDF pentru copii. 49 lei")}), hoy=HOY,
                 region="europa")
    r = next(x for x in e.resultados if x.descarte is None)
    assert r.total_meta == 12 and r.completo is True
    assert r.senales.c8.valor == 12 and not r.senales.c8.suelo
    assert r.senales.nuevos.motivo  # primera corrida completa: no medido, nunca 0
    assert e.via == {"firecrawl": c.presupuesto.usadas} and e.creditos == c.presupuesto.usadas
    assert (v / "wiki/caza/2026-11-10/europa.md").exists()
    consulta = e.consultas[0]
    assert consulta.resultados == 40 and r.oferta.oferta_id in consulta.ofertas


def test_lectura_parcial_no_registra_vistos_ni_total(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000012"
    ads = viejos(P, 10, 20, 2000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads, total=300, completo=False, exacto=False)})
    url = "https://kit.example/ro/"
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.total_meta is None and r.completo is False and r.senales.c8.suelo
    assert "muestra parcial" in r.senales.nuevos.motivo
    import sqlite3
    conn = sqlite3.connect(v / "data/caza/snapshots.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 0
    assert conn.execute("SELECT total, activos FROM snapshots").fetchone() == (None, None)


def test_inactivos_solo_de_lectura_completa_all(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000013"
    ads = viejos(P, 9, 20, 3000)
    parados = [replace(a, library_id=f"9{a.library_id}", activo=False, fin=HOY - timedelta(days=2))
               for a in viejos(P, 3, 30, 3100)]
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(ads),
        url_biblioteca("RO", page_id=P, estado="all"): ok(ads + parados),
    })
    url = "https://kit.example/ro/"
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.senales.vida_mediana_dias.valor == 28
    c2 = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(ads),
        url_biblioteca("RO", page_id=P, estado="all"): ok(ads + parados, total=500, completo=False, exacto=False),
    })
    e2 = ejecutar(_vault(tmp_path / "b"), "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c2,
                  resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e2.resultados[0].senales.vida_mediana_dias.valor is None


# --- parada: nunca se sigue tras un bloqueo -----------------------------------------------


def test_bloqueo_detiene_la_ejecucion_y_marca_no_medido(tmp_path):
    v = _vault(tmp_path)
    bloqueado = ResultadoBusqueda("bloqueado", "", None, [], "Meta mostró captcha", datetime.now(UTC))
    c = ClientePorUrl({url_biblioteca("RO", q="uno"): bloqueado})
    e = ejecutar(v, "nicho", [("RO", "uno"), ("RO", "dos")], "tomi", 3, cliente=c,
                 resolver=resolver_fijo({}), hoy=HOY, region="europa")
    assert c.llamadas == [url_biblioteca("RO", q="uno")]  # la segunda nunca se pide
    assert e.parada and "captcha" in e.parada
    assert [x.resultados for x in e.consultas] == [None, None]
    assert any("no medido" in x for x in e.errores)
    assert e.bloqueos == 1
    informe = (v / "wiki/caza/2026-11-10/europa.md").read_text()
    assert "captcha" in informe and "| uno | RO | no medido" in informe
    assert "| uno | RO | 0" not in informe


def test_excepcion_del_cliente_detiene_la_ejecucion(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000014"
    ads = viejos(P, 5, 20, 4000)
    c = ClientePorUrl(
        {url_biblioteca("RO", q="uno"): ok(ads, completo=False, exacto=False)},
        excepcion_en={url_biblioteca("RO", page_id=P): SesionBloqueada("Meta bloqueó la sesión")},
    )
    url = "https://kit.example/ro/"
    e = ejecutar(v, "nicho", [("RO", "uno"), ("RO", "dos")], "tomi", 3, cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY, region="europa")
    assert url_biblioteca("RO", q="dos") in c.llamadas  # las consultas van antes del recuento
    assert c.llamadas[-1] == url_biblioteca("RO", page_id=P)  # tras la excepción no se busca nada más
    assert e.parada and "SesionBloqueada" in e.parada
    # tras la parada no quedan búsquedas: la oferta nueva queda pendiente, nunca medida a medias
    assert e.pendientes == 1 and e.resultados == []
    assert e.consultas[0].resultados == 5 and e.consultas[1].resultados == 0
    texto = _disco(v)
    assert "SesionBloqueada" in texto and "no medido" in texto


def test_presupuesto_agotado_detiene_y_lo_dice(tmp_path):
    # ola final I4: agotar la cuota no es una parada, pero se dice y no se busca más
    v = _vault(tmp_path)
    c = ClientePorUrl({}, excepcion_en={url_biblioteca("RO", q="uno"): PresupuestoAgotado("Presupuesto del día agotado")})
    e = ejecutar(v, "nicho", [("RO", "uno")], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY,
                 region="europa")
    assert e.parada is None and "Presupuesto del día agotado" in e.cuota and e.consultas[0].resultados is None
    assert "Presupuesto del día agotado" in (v / "raw/2026-11-10/caza-europa.md").read_text()


# --- tope de nuevas y de destinos --------------------------------------------------------


def test_tope_de_nuevas_y_pendientes(tmp_path):
    v = _vault(tmp_path)
    respuestas, mapa, todos = {}, {}, []
    for i in range(5):
        p = f"10000000000010{i}"
        url = f"https://kit{i}.example/"
        ads = viejos(p, 10 + i, 20, 5000 + 100 * i, destino=url)
        respuestas[url_biblioteca("RO", page_id=p)] = ok(ads)
        mapa[url] = destino_ok(url, checkout=f"https://pay.hotmart.com/K{i}")
        todos += ads[:2]
    respuestas[url_biblioteca("RO", q="fise")] = ok(todos, total=200, completo=False, exacto=False)
    c = ClientePorUrl(respuestas)
    e = ejecutar(v, "nicho", [("RO", "fise")], "tomi", 2, cliente=c, resolver=resolver_fijo(mapa), hoy=HOY,
                 region="europa")
    pasan = [r for r in e.resultados if r.descarte is None]
    assert len(pasan) == 2 and e.pendientes == 3
    # las de mayor C8 primero
    assert {r.oferta.page_ids[0] for r in pasan} == {"100000000000104", "100000000000103"}


def test_tope_de_destinos(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    P = "100000000000021"
    ads = [a for i in range(15) for a in viejos(P, 1, 20, 6000 + i, destino=f"https://l{i}.example/")]
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    abiertas: list[str] = []
    ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
             resolver=resolver_fijo({}, abiertas), hoy=HOY)
    assert len(abiertas) == 10  # caza.max_destinos_por_ejecucion de la plantilla


def test_landings_sin_pie_llegan_a_los_filtros(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000022"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 7000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    texto = "Fișe PDF pentru copii.\nProgramează un apel strategic gratuit.\nPolitica de confidențialitate"
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: (destino_ok(url), texto)}), hoy=HOY)
    # el texto de la landing llega a los filtros (cebo de back-end)
    assert e.resultados[0].descarte.codigo == "cebo_backend"


def test_precio_bajo_es_bandera_y_no_cambia_nota_ni_decision(tmp_path):
    from trovefy import fx

    P = "100000000000023"
    url = "https://kit.example/ro/"

    def cazar(v, cambios):
        c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(viejos(P, 9, 20, 7100))})
        return ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                        resolver=resolver_fijo({url: (destino_ok(url, precio=5.0), "Fișe PDF pentru copii")}),
                        hoy=HOY, cambios=cambios)

    vistos: list = []
    cambio = fx.Cambio({"EUR": 1.0, "USD": 1.08, "RON": 5.0}, "2026-11-10")
    con = cazar(_vault(tmp_path / "a"), lambda v, hoy: vistos.append(hoy) or cambio).resultados[0]
    sin = cazar(_vault(tmp_path / "b"), lambda v, hoy: None)
    assert vistos == [HOY]
    assert con.descarte is None and "precio_bajo" in con.senales.banderas
    assert "5 RON ≈ 1,08 USD" in con.senales.detalles_banderas["precio_bajo"]
    r = sin.resultados[0]
    assert "precio_bajo" not in r.senales.banderas  # sin cambio del BCE: no se mide, no se inventa
    assert (con.nota.valor, con.decision) == (r.nota.valor, r.decision)
    assert any("caza.precio.min_usd" in x for x in sin.errores)


def test_sin_cambios_la_caza_no_sale_a_la_red(tmp_path):
    # El fixture automático de tests/unit/caza deja el cambio del BCE en None: nunca sale a la red.
    assert orquestador._cambio_del_dia(tmp_path, HOY) is None


def test_texto_sin_pie():
    t = ("Fișe PDF pentru copii\nCumpără acum\nPolitica de confidențialitate\nTermeni și condiții\n"
         "© 2026 Kit SRL. Toate drepturile rezervate.\nThis site is not part of the Facebook website or Meta Platforms\n"
         "Cumpără acum")
    limpio = texto_sin_pie(t)
    assert "Fișe PDF" in limpio and "Politica" not in limpio and "©" not in limpio and "Facebook" not in limpio
    assert limpio.count("Cumpără acum") == 1


# --- original por dominio ----------------------------------------------------------------


def test_original_por_dominio_marca_copia(tmp_path):
    v = _vault(tmp_path)
    P, ORIG = "100000000000031", "100000000000032"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 8000)
    antiguos = viejos(ORIG, 3, 90, 8100)
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(ads),
        url_biblioteca("RO", q="kit.example"): ok(ads[:2] + antiguos, completo=False, exacto=False),
    })
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.descarte is not None and r.descarte.codigo == "posible_copia"
    assert ORIG in r.descarte.detalle


def test_dominio_contaminado_no_se_usa(tmp_path):
    v = _vault(tmp_path)
    P, OTRA = "100000000000041", "100000000000042"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 9000)
    ajenos = viejos(OTRA, 3, 90, 9100, destino="https://otra-cosa.example/")
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(ads),
        url_biblioteca("RO", q="kit.example"): ok(ajenos, completo=False, exacto=False),
    })
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e.resultados[0].descarte is None
    assert any("dominio contaminado" in x for x in e.errores)


# --- varias ofertas en una página ----------------------------------------------------------


def test_varias_ofertas_en_una_pagina_se_recuentan_con_frase(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000051"
    ua, ub = "https://a-kit.example/", "https://b-kit.example/"
    a = [replace(x, titulo="Fișe de matematică") for x in viejos(P, 9, 20, 10000, destino=ua)]
    b = [replace(x, titulo="Povești pentru somn") for x in viejos(P, 9, 20, 10100, destino=ub)]
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(a[:4] + b[:4], total=18, completo=False),
        url_biblioteca("RO", q="Fișe de matematică", page_id=P): ok(a, total=9),
        url_biblioteca("RO", q="Povești pentru somn", page_id=P): ok(b, total=9),
    })
    mapa = {ua: destino_ok(ua, checkout="https://pay.hotmart.com/A1"),
            ub: destino_ok(ub, checkout="https://pay.hotmart.com/B1")}
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo(mapa), hoy=HOY)
    assert url_biblioteca("RO", q="Fișe de matematică", page_id=P) in c.llamadas
    rs = {r.oferta.clave: r for r in e.resultados}
    assert rs["hotmart:A1"].senales.c8.valor == 9
    # el total de la página (18) no es el de una oferta; el recuento con frase completo y sin
    # anuncios ajenos sí lo es
    assert rs["hotmart:A1"].total_meta == 9


def test_recuento_con_frase_con_anuncios_ajenos_no_da_total(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000052"
    ua, ub = "https://a-kit.example/", "https://b-kit.example/"
    a = [replace(x, titulo="Fișe de matematică") for x in viejos(P, 9, 20, 10200, destino=ua)]
    b = [replace(x, titulo="Povești pentru somn") for x in viejos(P, 9, 20, 10300, destino=ub)]
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(a[:4] + b[:4], total=18, completo=False),
        url_biblioteca("RO", q="Fișe de matematică", page_id=P): ok(a + b[:1], total=10),
        url_biblioteca("RO", q="Povești pentru somn", page_id=P): ok(b, total=9, completo=False),
    })
    mapa = {ua: destino_ok(ua, checkout="https://pay.hotmart.com/A1"),
            ub: destino_ok(ub, checkout="https://pay.hotmart.com/B1")}
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo(mapa), hoy=HOY)
    rs = {r.oferta.clave: r for r in e.resultados}
    assert rs["hotmart:A1"].total_meta is None  # la frase trajo un anuncio de otra oferta
    assert rs["hotmart:B1"].total_meta is None  # lectura con frase incompleta


# --- vigilar y strikes ---------------------------------------------------------------------


def _ficha(v, oid, page, estado="B", strikes=0, motivo=None, pais="RO"):
    meta = {"tipo": "oferta", "fecha": "2026-11-01", "fuente": url_biblioteca(pais, page_id=page),
            "oferta_id": oid, "page_ids": [page], "estado": estado, "strikes": strikes,
            "paises": {pais: {"link_biblioteca": url_biblioteca(pais, page_id=page), "estado": estado}}}
    if motivo:
        meta["motivo_strike"] = motivo
    frontmatter.escribir(v / "wiki/ofertas" / f"{oid}.md", meta, f"# Oferta {oid}\n")


def test_vigilar_vuelve_a_medir_por_pagina_y_pais(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000061"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    _ficha(v, oid, P)
    _ficha(v, "o-podada-x", "100000000000062", estado="podada")
    ads = viejos(P, 9, 20, 11000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert url_biblioteca("RO", page_id=P) in c.llamadas
    assert not any("100000000000062" in u for u in c.llamadas)  # podada: no se vigila
    assert [r.oferta.oferta_id for r in e.resultados] == [oid]
    meta, _ = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    assert meta["ultima_vez"] == "2026-11-10" and "strikes" in meta


def test_vigilar_strike_hasta_podar(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000071"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    # pocos anuncios y jóvenes: queda en observar
    ads = viejos(P, 2, 2, 12000)
    _ficha(v, oid, P, strikes=2, motivo="nota baja")
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e.resultados[0].decision == "observar"
    meta, _ = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    assert meta["estado"] == "podada" and meta["strikes"] == 3


def test_strikes_reglas():
    f = {"o-1": {"estado": "B", "strikes": 2, "motivo_strike": "cayendo"}}
    otro = aplicar_strikes(f, {"o-1": ("observar", "nota baja")})
    assert otro["o-1"]["strikes"] == 1 and otro["o-1"]["motivo_strike"] == "nota baja"
    bien = aplicar_strikes(f, {"o-1": ("B", "")})
    assert bien["o-1"]["strikes"] == 0 and bien["o-1"].get("motivo_strike") is None
    assert f["o-1"]["strikes"] == 2  # pura: no toca la entrada
    sin_medir = aplicar_strikes(f, {})
    assert sin_medir["o-1"]["strikes"] == 2


# --- palabras y presupuesto diario ------------------------------------------------------


def test_palabras_a_reescribir(tmp_path):
    from trovefy.caza.salida import Consulta
    cs = [Consulta("a", "RO", 5, "u"), Consulta("b", "RO", 50, "u"), Consulta("c", "RO", None, "u"),
          Consulta("d", "RO", 0, "u")]
    assert [c.palabra for c in palabras_a_reescribir(cs, 20)] == ["a", "d"]


def test_contador_diario_se_comparte_y_la_cache_no_consume(tmp_path):
    from test_cliente import NavegadorFalso
    from trovefy.caza.cache import Cache
    from trovefy.caza.cliente import ClienteBibliotecaPublica
    v = _vault(tmp_path)
    p1 = Presupuesto.desde_umbrales(v, HOY)
    p1._dormir = lambda s: None
    cache = Cache(v / "data/cache/biblioteca")
    c = ClienteBibliotecaPublica(p1, NavegadorFalso([de_fixture("pagina_therapy_toolkit.json")]), cache)
    c.buscar("ALL", page_id="102506312071455")
    c.buscar("ALL", page_id="102506312071455")  # caché: no navega ni consume
    ruta = v / "data/caza/presupuesto/2026-11-10.json"
    assert json.loads(ruta.read_text())["usadas"] == 1
    p2 = Presupuesto.desde_umbrales(v, HOY)  # otra sesión (la rutina) ve el mismo contador
    p2.antes_de_buscar()
    assert json.loads(ruta.read_text())["usadas"] == 2 and p2.usadas == 1
    assert Presupuesto.desde_umbrales(v, HOY + timedelta(days=1)).usadas_hoy() == 0


def test_dia_por_defecto_en_bogota(monkeypatch):
    # 2026-11-11 03:00 UTC = 2026-11-10 22:00 en Bogotá
    monkeypatch.setattr(orquestador, "_ahora", lambda: datetime(2026, 11, 11, 3, 0, tzinfo=UTC))
    assert orquestador.hoy_negocio() == date(2026, 11, 10)


# --- hueco ---------------------------------------------------------------------------------


def _ficha_medida(v, oid, page, nota=80.0, c8=20, c7=20, estado="B"):
    meta = {"tipo": "oferta", "fecha": "2026-11-10", "fuente": url_biblioteca("BR", page_id=page),
            "oferta_id": oid, "page_ids": [page], "checkout": "https://pay.hotmart.com/K1", "precio": 49.0,
            "moneda": "BRL", "estado": estado, "motivo": "nota 80 ; sin hueco comprobado",
            "paises": {"BR": {"c8": c8, "c7": c7, "total": 25, "edad_max": 60, "nota": nota, "estado": estado,
                              "cota_inferior": [], "link_biblioteca": url_biblioteca("BR", page_id=page),
                              "fecha": "2026-11-10"}}}
    cuerpo = (f"# Oferta {oid}\n\nEstado: **{estado}** — nota 80; sin hueco comprobado\n\n## Nota\n\nx\n\n"
              "## Hueco por país\n\nHueco por país: no medido: no se buscó competencia local para esta oferta.\n\n"
              "## Anuncios de ejemplo\n\n- a\n")
    frontmatter.escribir(v / "wiki/ofertas" / f"{oid}.md", meta, cuerpo)


def test_hueco_actualiza_la_ficha_y_recalcula(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000081"
    _ficha_medida(v, "o-hueco", P)
    en_ingles = [replace(a, texto="Printable worksheets for kids, download the PDF and learn at home every day.")
                 for a in viejos(P, 3, 60, 13000)]
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(en_ingles)})
    h, parada, _ = orquestador.medir_hueco(v, "o-hueco", "RO", ["fise de lucru", "fise pentru copii"], cliente=c, hoy=HOY)
    assert h.hueco is True and h.original == "sin_traducir" and parada is None
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas/o-hueco.md")
    assert meta["huecos"]["RO"]["hueco"] is True and meta["huecos"]["RO"]["enlaces"]
    assert meta["estado"] == "A" and meta["paises"]["BR"]["estado"] == "A"
    assert "Estado: **A**" in cuerpo and "| RO |" in cuerpo and "## Anuncios de ejemplo" in cuerpo


def test_hueco_no_comprobado_no_inventa_a(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000082"
    _ficha_medida(v, "o-hueco2", P)
    bloqueado = ResultadoBusqueda("bloqueado", "", None, [], "Meta mostró captcha", datetime.now(UTC))
    c = ClientePorUrl({url_biblioteca("RO", q="fise de lucru"): bloqueado})
    h, _, _ = orquestador.medir_hueco(v, "o-hueco2", "RO", ["fise de lucru", "fise pentru copii"], cliente=c, hoy=HOY)
    assert h.hueco is None
    meta, _ = frontmatter.leer(v / "wiki/ofertas/o-hueco2.md")
    assert meta["estado"] == "B" and meta["huecos"]["RO"]["competencia"] is None


def test_hueco_guardado_entra_en_la_siguiente_caza(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000091"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    _ficha(v, oid, P)
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    meta["huecos"] = {"MD": {"competencia": 0, "competencia_suelo": False, "competencia_motivo": None,
                             "original": "sin_traducir", "hueco": True, "motivo": None, "enlaces": ["u"],
                             "fecha": "2026-11-09"}}
    frontmatter.escribir(v / "wiki/ofertas" / f"{oid}.md", meta, cuerpo)
    ads = viejos(P, 9, 20, 14000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert [h.pais for h in r.huecos] == ["MD"] and "sin hueco" not in r.explicacion


# --- ronda 1: alcance de totales y completitud (I1) ------------------------------------------


def _disco(v) -> str:
    return "\n".join(p.read_text() for p in (v / "wiki").rglob("*.md")) + "\n".join(
        p.read_text() for p in (v / "raw").rglob("*.md"))


def test_pagina_parcial_con_count_exacto_no_es_total_de_la_oferta(tmp_path):
    # ejemplo de la revisión: 300 anuncios en la página, se leen 10 y todos van a la oferta X
    v = _vault(tmp_path)
    P = "100000000000201"
    url = "https://kit.example/ro/"
    ads = viejos(P, 10, 20, 20000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads, total=300, completo=False, exacto=True)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.total_meta is None and r.completo is False
    assert r.senales.total.suelo and r.senales.total.valor == 10
    import sqlite3
    conn = sqlite3.connect(v / "data/caza/snapshots.sqlite")
    assert conn.execute("SELECT total FROM snapshots").fetchone() == (None,)


def test_crecimiento_de_la_pagina_se_muestra_aparte(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000202"
    url = "https://kit.example/ro/"
    conn = snapshots.abrir(v / "data/caza/snapshots.sqlite")
    snapshots.guardar_pagina(conn, P, "RO", HOY - timedelta(days=7), 200, url_biblioteca("RO", page_id=P))
    conn.close()
    ads = viejos(P, 10, 20, 21000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads, total=300, completo=False, exacto=True)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.senales.crecimiento_7d.valor is None  # el de la oferta no se mide con el total de la página
    assert [(p, m.valor) for p, m, _ in r.crecimiento_pagina] == [(P, 0.5)]
    texto = _disco(v)
    assert "crecimiento de la página (todas sus ofertas)" in texto
    assert url_biblioteca("RO", page_id=P) in texto
    conn = snapshots.abrir(v / "data/caza/snapshots.sqlite")
    assert [f.total for f in snapshots.historial_pagina(conn, P, "RO", HOY - timedelta(days=8))] == [200, 300]


def test_crecimiento_de_pagina_no_se_muestra_si_lleva_otras_ofertas(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000203"
    ua, ub = "https://a-kit.example/", "https://b-kit.example/"
    conn = snapshots.abrir(v / "data/caza/snapshots.sqlite")
    snapshots.guardar_pagina(conn, P, "RO", HOY - timedelta(days=7), 200, url_biblioteca("RO", page_id=P))
    conn.close()
    ads = viejos(P, 5, 20, 22000, destino=ua) + viejos(P, 5, 20, 22100, destino=ub)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads, total=300, completo=False, exacto=True)})
    mapa = {ua: destino_ok(ua, checkout="https://pay.hotmart.com/A1"),
            ub: destino_ok(ub, checkout="https://pay.hotmart.com/B1")}
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo(mapa), hoy=HOY)
    assert all(r.crecimiento_pagina == [] for r in e.resultados)


def test_anuncios_sin_atribuir_impiden_completo(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000204"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 23000) + viejos(P, 2, 20, 23100, destino="https://no-abre.example/")
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = next(x for x in e.resultados if x.oferta.clave == "hotmart:K123")
    assert r.completo is False and r.total_meta is None and r.senales.c8.suelo
    import sqlite3
    conn = sqlite3.connect(v / "data/caza/snapshots.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 0


def test_pagina_completa_y_atribuida_da_total_exacto(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000205"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 24000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.completo is True and r.total_meta == 9 and not r.senales.c8.suelo


# --- ronda 1: parada persistente (I2) ---------------------------------------------------


def test_parada_persiste_entre_procesos_hasta_el_dia_siguiente(tmp_path):
    from trovefy.caza.presupuesto import ParadaDelDia
    v = _vault(tmp_path)
    Presupuesto.desde_umbrales(v, HOY).registrar_parada("Meta mostró captcha")
    datos = json.loads((v / "data/caza/presupuesto/2026-11-10.json").read_text())
    assert datos["parada"] == "Meta mostró captcha"
    with pytest.raises(ParadaDelDia, match="captcha"):
        Presupuesto.desde_umbrales(v, HOY).antes_de_buscar()
    Presupuesto.desde_umbrales(v, HOY + timedelta(days=1)).antes_de_buscar()  # otro día: se puede


def test_el_cliente_guarda_el_bloqueo_en_el_archivo_del_dia(tmp_path):
    from test_cliente import NavegadorFalso
    from trovefy.caza.cliente import ClienteBibliotecaPublica, PaginaCapturada
    v = _vault(tmp_path)
    p = Presupuesto.desde_umbrales(v, HOY)
    p._dormir = lambda s: None
    c = ClienteBibliotecaPublica(p, NavegadorFalso([PaginaCapturada("https://www.facebook.com/login/?n=x", "", "", [])]))
    assert c.buscar("RO", q="x").estado == "bloqueado"
    assert "parada" in json.loads((v / "data/caza/presupuesto/2026-11-10.json").read_text())
    # otro proceso (la rutina, la siguiente tanda): ni siquiera abre el navegador
    nav = NavegadorFalso([])
    p2 = Presupuesto.desde_umbrales(v, HOY)
    p2._dormir = lambda s: None
    e = ejecutar(v, "nicho", [("RO", "fise")], "tomi", 3, cliente=ClienteBibliotecaPublica(p2, nav),
                 resolver=resolver_fijo({}), hoy=HOY, region="europa")
    assert nav.llamadas == [] and e.parada and "login" in e.parada
    assert "Parada" in _disco(v)


def test_hueco_informa_la_parada(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000206"
    _ficha_medida(v, "o-hp", P)
    bloqueado = ResultadoBusqueda("bloqueado", "", None, [], "Meta mostró captcha", datetime.now(UTC))
    c = ClientePorUrl({url_biblioteca("RO", q="fise de lucru"): bloqueado})
    h, parada, _ = orquestador.medir_hueco(v, "o-hp", "RO", ["fise de lucru", "fise pentru copii"], cliente=c,
                                        hoy=HOY)
    assert h.hueco is None and parada and "captcha" in parada


# --- ronda 1: cuotas (I3) ------------------------------------------------------------------


def test_cuota_de_la_rutina(tmp_path):
    v = _vault(tmp_path)
    r = Presupuesto.desde_umbrales(v, HOY, max_rutina=2)
    r.antes_de_buscar(); r.antes_de_buscar()
    with pytest.raises(PresupuestoAgotado, match="rutina"):
        r.antes_de_buscar()
    u = Presupuesto.desde_umbrales(v, HOY)  # el usuario conserva el resto del día
    u.antes_de_buscar()
    assert u.usadas_hoy() == 3 and u.restantes() == 27


def test_vigilar_rota_las_menos_recientes(tmp_path):
    v = _vault(tmp_path)
    paginas = {"o-a": "100000000000301", "o-b": "100000000000302", "o-c": "100000000000303",
               "o-d": "100000000000304"}
    fechas = {"o-a": "2026-11-01", "o-b": "2026-11-08", "o-c": "2026-10-20", "o-d": "2026-11-10"}
    for oid, p in paginas.items():
        _ficha(v, oid, p)
        meta, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
        meta["ultima_vez"] = fechas[oid]
        if fechas[oid] == "2026-11-10":
            meta["vigilada"] = fechas[oid]  # vigilada hoy: gasta turno
        frontmatter.escribir(v / "wiki/ofertas" / f"{oid}.md", meta, cuerpo)
    c = ClientePorUrl({})
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY, max_vigiladas=3)
    # o-d ya se midió hoy: cuenta para el tope del día; quedan 2 turnos para las más antiguas
    assert c.llamadas == [url_biblioteca("RO", page_id=paginas["o-c"]), url_biblioteca("RO", page_id=paginas["o-a"])]
    assert any("turno de vigilancia" in x and "o-b" in x for x in e.errores)


def test_nueva_queda_pendiente_si_quedan_pocas_busquedas(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000305"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 30000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    c.presupuesto.restantes = lambda: 2
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e.pendientes == 1 and not [r for r in e.resultados if r.descarte is None]
    assert c.llamadas == [url_biblioteca("RO", page_id=P)]  # sin búsquedas extra a medias


# --- ronda 1: strikes solo con medición entera (I4) ----------------------------------------


def test_strike_no_cuenta_si_la_oferta_no_se_midio_entera(tmp_path):
    v = _vault(tmp_path)
    P1, P2 = "100000000000401", "100000000000402"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    _ficha(v, oid, P1, strikes=2, motivo="nota baja")
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    meta["page_ids"] = [P1, P2]
    frontmatter.escribir(v / "wiki/ofertas" / f"{oid}.md", meta, cuerpo)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P1): ok(viejos(P1, 2, 2, 31000))},
                      excepcion_en={url_biblioteca("RO", page_id=P2): PresupuestoAgotado("agotado")})
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e.resultados[0].decision == "observar" and e.cuota
    meta, _ = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    assert meta["strikes"] == 2 and meta["estado"] != "podada"


def test_nada_medido_nunca_es_strike():
    f = {"o-1": {"estado": "B", "strikes": 2, "motivo_strike": "nada medido"}}
    assert aplicar_strikes(f, {"o-1": ("observar", "nada medido")})["o-1"]["strikes"] == 2


# --- ronda 1: menores ----------------------------------------------------------------------


def test_navegador_no_disponible_es_parada_controlada(tmp_path):
    from trovefy.navegador import NavegadorError
    v = _vault(tmp_path)
    c = ClientePorUrl({}, excepcion_en={url_biblioteca("RO", q="uno"): NavegadorError("no se pudo iniciar Chromium")})
    e = ejecutar(v, "nicho", [("RO", "uno"), ("RO", "dos")], "tomi", 3, cliente=c, resolver=resolver_fijo({}),
                 hoy=HOY, region="europa")
    assert e.parada and "navegador no disponible" in e.parada and len(c.llamadas) == 1
    texto = (v / "wiki/caza/2026-11-10/europa.md").read_text()
    assert "no medido" in texto and "navegador no disponible" in texto


# --- ola final: C1 lecturas de otro día ------------------------------------------------------


def test_lectura_de_otro_dia_no_registra_vistos(tmp_path):
    import sqlite3
    v = _vault(tmp_path)
    P = "100000000000501"
    url = "https://kit.example/ro/"
    ads = viejos(P, 9, 20, 50000)
    ayer = replace(ok(ads), capturado_en=datetime(2026, 11, 10, 1, 0, tzinfo=UTC))  # 2026-11-09 20:00 COT
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ayer})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    r = e.resultados[0]
    assert r.senales.nuevos.valor is None and r.senales.parados.valor is None
    conn = sqlite3.connect(v / "data/caza/snapshots.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 0


# --- ola final: I3 perfil validado antes de buscar --------------------------------------------


def test_perfil_desconocido_para_antes_de_buscar(tmp_path):
    v = _vault(tmp_path)
    c = ClientePorUrl({})
    with pytest.raises(ValueError, match="perfil desconocido: «Tommi»; los que hay son tomi, santino, europa_caro"):
        ejecutar(v, "nicho", [("RO", "fise")], "Tommi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY,
                 region="europa")
    assert c.llamadas == []
    _ficha_medida(v, "o-perfil", "100000000000601")
    with pytest.raises(ValueError, match="perfil desconocido"):
        orquestador.medir_hueco(v, "o-perfil", "RO", ["a b", "c d"], cliente=c, hoy=HOY, perfil="Tommi")
    assert c.llamadas == []


def test_perfil_se_normaliza(tmp_path):
    v = _vault(tmp_path)
    e = ejecutar(v, "nicho", [("RO", "fise")], "Europa-Caro", 3, cliente=ClientePorUrl({}),
                 resolver=resolver_fijo({}), hoy=HOY, region="europa")
    assert e.perfil == "europa_caro"


# --- ola final: I5 solo los bloqueos de Meta duran el día ----------------------------------------


@pytest.mark.parametrize("paginas", ["red", "respuestas"])
def test_racha_de_errores_no_bloquea_el_dia(tmp_path, paginas):
    from test_cliente import NavegadorFalso
    from trovefy.caza.cliente import (
        ClienteBibliotecaPublica,
        ErrorDeRed,
        PaginaCapturada,
    )
    from trovefy.caza.presupuesto import ParadaPorErrores
    v = _vault(tmp_path)
    p = Presupuesto.desde_umbrales(v, HOY)
    p._dormir = lambda s: None
    if paginas == "red":
        nav = NavegadorFalso([ErrorDeRed("a"), ErrorDeRed("b"), ErrorDeRed("c")])
    else:
        nav = NavegadorFalso([PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])
                              for _ in range(3)])
    c = ClienteBibliotecaPublica(p, nav)
    with pytest.raises(ParadaPorErrores):
        for q in ("a", "b", "c"):
            c.buscar("RO", q=q)
    with pytest.raises(ParadaPorErrores):  # este proceso no vuelve a buscar
        c.buscar("RO", q="d")
    datos = json.loads((v / "data/caza/presupuesto/2026-11-10.json").read_text())
    assert "parada" not in datos
    p2 = Presupuesto.desde_umbrales(v, HOY)  # otro proceso sí puede buscar hoy
    p2.antes_de_buscar()
    assert p2.restantes() > 0


def test_parada_por_errores_antigua_del_archivo_no_bloquea(tmp_path):
    v = _vault(tmp_path)
    ruta = v / "data/caza/presupuesto/2026-11-10.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"usadas": 3, "rutina": 0, "parada": "parada por errores: 3 búsquedas seguidas"}))
    p = Presupuesto.desde_umbrales(v, HOY)
    p.antes_de_buscar()
    assert p.parada_del_dia() is None


# --- ola final: I4 agotar la cuota es un final normal -------------------------------------------


class ClienteConPresupuesto(ClientePorUrl):
    """Como ClientePorUrl, pero con el presupuesto real del día (contador en el vault de la prueba)."""

    def __init__(self, respuestas, presupuesto):
        super().__init__(respuestas)
        self.presupuesto = presupuesto

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60, completa=False):
        self.presupuesto.antes_de_buscar()
        url = url_biblioteca(pais, q, page_id, estado)
        self.llamadas.append(url)
        r = self.respuestas.get(url)
        if r is None:
            return ResultadoBusqueda("vacio", url, 0, [], None, CAPTURA, True, "firecrawl", 1, total_exacto=True)
        return replace(r, url=url)


def _usadas(v, usadas, rutina=0):
    ruta = v / "data/caza/presupuesto/2026-11-10.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"usadas": usadas, "rutina": rutina}))


def _mercado_de_ofertas(n, base=60000):
    """n páginas, cada una con su oferta (landing propia), y las búsquedas por palabra que las traen."""
    respuestas, mapa, muestra = {}, {}, []
    for i in range(n):
        p = f"1000000000007{i:02d}"
        url = f"https://kit{i}.example/"
        ads = viejos(p, 10 + i, 20, base + 100 * i, destino=url)
        respuestas[url_biblioteca("RO", page_id=p)] = ok(ads)
        mapa[url] = destino_ok(url, checkout=f"https://pay.hotmart.com/Q{i}")
        muestra += ads[:2]
    return respuestas, mapa, muestra


def test_cuota_de_la_rutina_agotada_a_mitad_de_barrido_es_final_normal(tmp_path):
    v = _vault(tmp_path)
    _usadas(v, 15, rutina=15)  # vigilar ya gastó 15 de las 20 de la rutina
    respuestas, mapa, muestra = _mercado_de_ofertas(6)
    frases = ["fise a", "fise b", "fise c", "fise d"]
    for f in frases:
        respuestas[url_biblioteca("RO", q=f)] = ok(muestra, total=200, completo=False, exacto=False)
    p = Presupuesto.desde_umbrales(v, HOY, max_rutina=20)
    c = ClienteConPresupuesto(respuestas, p)
    e = ejecutar(v, "barrido", [("RO", f) for f in frases], "tomi", 3, cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY, region="europa", max_busquedas_rutina=20)
    assert len(c.llamadas) <= 5
    assert e.parada is None and e.cuota
    assert e.pendientes >= 1 and e.pendientes_por.get("cuota", 0) >= 1
    texto = orquestador.resumen(e, 20)
    assert "PARADA" not in texto and "cuota" in texto.lower() and "pendiente" in texto.lower()


def test_usuario_con_10_busquedas_evalua_algo(tmp_path):
    v = _vault(tmp_path)
    _usadas(v, 20)
    respuestas, mapa, muestra = _mercado_de_ofertas(6, base=61000)
    frases = ["fise a", "fise b", "fise c", "fise d"]
    for f in frases:
        respuestas[url_biblioteca("RO", q=f)] = ok(muestra, total=200, completo=False, exacto=False)
    p = Presupuesto.desde_umbrales(v, HOY)
    c = ClienteConPresupuesto(respuestas, p)
    e = ejecutar(v, "nicho", [("RO", f) for f in frases], "tomi", 3, cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY, region="europa")
    assert len(c.llamadas) <= 10 and e.parada is None
    assert [r for r in e.resultados if r.descarte is None]  # al menos una oferta nueva medida
    assert e.pendientes_por.get("cuota", 0) >= 1


def test_cuota_agotada_por_sorpresa_no_es_parada(tmp_path):
    v = _vault(tmp_path)
    c = ClientePorUrl({}, excepcion_en={url_biblioteca("RO", q="dos"): PresupuestoAgotado("Cuota de la rutina agotada")})
    e = ejecutar(v, "nicho", [("RO", "uno"), ("RO", "dos"), ("RO", "tres")], "tomi", 3, cliente=c,
                 resolver=resolver_fijo({}), hoy=HOY, region="europa")
    assert e.parada is None and "Cuota de la rutina agotada" in e.cuota
    assert url_biblioteca("RO", q="tres") not in c.llamadas
    assert e.consultas[2].resultados is None
    assert any("cuota del día agotada" in x for x in e.errores)


def test_vigilar_planifica_por_la_cuota(tmp_path):
    v = _vault(tmp_path)
    for i in range(4):
        _ficha(v, f"o-v{i}", f"10000000000080{i}")
    c = ClientePorUrl({})
    c.presupuesto.restantes = lambda: 2
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY)
    assert len(c.llamadas) == 2 and e.parada is None
    assert e.pendientes_por.get("cuota") == 2
    assert any("cuota del día agotada" in x for x in e.errores)


# --- ola final: menores ----------------------------------------------------------------------


def test_landings_sin_abrir_por_el_tope_quedan_pendientes_sin_ficha(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000901"
    urls = [f"https://l{i}.example/" for i in range(12)]
    ads = [a for i, url in enumerate(urls) for a in viejos(P, 1, 20, 90000 + i, destino=url)]
    mapa = {url: destino_ok(url, checkout=f"https://pay.hotmart.com/L{i}") for i, url in enumerate(urls)}
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(ads)})
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY)
    assert e.pendientes_por.get("landing_sin_abrir") == 1
    assert not any(r.oferta.clave.startswith("pagina:") for r in e.resultados)
    assert not list((v / "wiki/ofertas").glob("o-pagina*.md"))


def test_strike_no_cuenta_con_cohortes_de_cota_inferior(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000902"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    _ficha(v, oid, P, strikes=2, motivo="nota baja")
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(viejos(P, 2, 2, 92000), total=300, completo=False)})
    e = ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    assert e.resultados[0].decision == "observar" and e.resultados[0].senales.c8.suelo
    meta, _ = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    assert meta["strikes"] == 2 and meta["estado"] != "podada"


def test_dos_cazas_a_la_vez_no(tmp_path):
    import fcntl
    v = _vault(tmp_path)
    cerrojo = v / "data/caza/.caza.lock"
    cerrojo.parent.mkdir(parents=True, exist_ok=True)
    c = ClientePorUrl({})
    with open(cerrojo, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="otra caza"):
            ejecutar(v, "nicho", [("RO", "fise")], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY,
                     region="europa")
        _ficha_medida(v, "o-lock", "100000000000903")
        with pytest.raises(ValueError, match="otra caza"):
            orquestador.medir_hueco(v, "o-lock", "RO", ["a b", "c d"], cliente=c, hoy=HOY)
    assert c.llamadas == []
    ejecutar(v, "nicho", [("RO", "fise")], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY,
             region="europa")  # suelto el cerrojo, se puede
    assert c.llamadas


def test_turno_de_vigilar_solo_cuenta_las_vigiladas_hoy(tmp_path):
    v = _vault(tmp_path)
    paginas = {"o-a": "100000000000911", "o-b": "100000000000912", "o-n": "100000000000913"}
    for oid, p in paginas.items():
        _ficha(v, oid, p)
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas/o-n.md")
    meta["ultima_vez"] = "2026-11-10"  # la escribió hoy una caza nicho del usuario: no gasta el turno
    frontmatter.escribir(v / "wiki/ofertas/o-n.md", meta, cuerpo)
    c = ClientePorUrl({})
    ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY, max_vigiladas=2)
    assert len(c.llamadas) == 2


def test_vigilar_marca_la_ficha_vigilada(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000914"
    url = "https://kit.example/ro/"
    from trovefy.caza.destino import clave_oferta, oferta_id
    oid = oferta_id(clave_oferta(url, "https://pay.hotmart.com/K123"))
    _ficha(v, oid, P)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(viejos(P, 9, 20, 93000))})
    ejecutar(v, "vigilar", [], "tomi", 3, cliente=c, resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY)
    meta, _ = frontmatter.leer(v / "wiki/ofertas" / f"{oid}.md")
    assert meta["vigilada"] == "2026-11-10"


def test_consulta_sin_recuento_y_aproximada(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000915"
    ads = viejos(P, 3, 20, 94000)
    c = ClientePorUrl({
        url_biblioteca("RO", q="uno"): ok(ads, total=None, completo=False, exacto=False),
        url_biblioteca("RO", q="dos"): ok(ads, total=230, completo=False, exacto=False),
        url_biblioteca("RO", page_id=P): ok(ads),
    })
    c.respuestas[url_biblioteca("RO", q="uno")].total_aprox = None
    e = ejecutar(v, "nicho", [("RO", "uno"), ("RO", "dos")], "tomi", 3, cliente=c, resolver=resolver_fijo({}),
                 hoy=HOY, region="europa")
    uno, dos = e.consultas
    assert uno.resultados is None and uno.sin_recuento and uno.ofertas
    assert dos.resultados == 230 and dos.aproximado
    informe = (v / "wiki/caza/2026-11-10/europa.md").read_text()
    assert "| uno | RO | no medido: sin recuento de Meta | 1 |" in informe
    assert "| dos | RO | ≈ 230 |" in informe
    assert "búsqueda sin respuesta" not in informe


# --- ola final: I2 el enlace reproduce la cifra ------------------------------------------------


def _dos_ofertas_en_una_pagina(P, base):
    ua, ub = "https://a-kit.example/", "https://b-kit.example/"
    a = [replace(x, titulo="Fișe de matematică") for x in viejos(P, 9, 20, base, destino=ua)]
    b = [replace(x, titulo="Povești pentru somn") for x in viejos(P, 9, 20, base + 100, destino=ub)]
    mapa = {ua: destino_ok(ua, checkout="https://pay.hotmart.com/A1"),
            ub: destino_ok(ub, checkout="https://pay.hotmart.com/B1")}
    return a, b, mapa


def test_enlace_de_la_oferta_en_pagina_compartida_es_el_recuento(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000951"
    a, b, mapa = _dos_ofertas_en_una_pagina(P, 95000)
    frase_a = url_biblioteca("RO", q="Fișe de matematică", page_id=P)
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(a[:4] + b[:4], total=18, completo=False),
        frase_a: ok(a, total=9),
        url_biblioteca("RO", q="Povești pentru somn", page_id=P): ok(b, total=9),
    })
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY)
    ra = next(r for r in e.resultados if r.oferta.clave == "hotmart:A1")
    assert ra.enlace == frase_a
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{ra.oferta.oferta_id}.md")
    assert meta["paises"]["RO"]["link_biblioteca"] == frase_a == meta["fuente"]
    assert meta["paises"]["RO"]["pagina"] == url_biblioteca("RO", page_id=P)
    assert f"página: {url_biblioteca('RO', page_id=P)}" in cuerpo
    # la ficha del competidor guarda las cifras de cada oferta aparte y el total de la página
    comp, _ = frontmatter.leer(v / "wiki/competidores" / f"{P}.md")
    assert comp["total"] == 18
    ids = {r.oferta.oferta_id for r in e.resultados}
    assert set(comp["cifras"]) == ids
    assert all(comp["cifras"][oid]["RO"]["c7"] == 9 for oid in ids)
    assert comp["cifras"][ra.oferta.oferta_id]["RO"]["fuente"] == frase_a


def test_pagina_completa_con_otra_oferta_lo_dice_junto_al_enlace(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000952"
    a, b, mapa = _dos_ofertas_en_una_pagina(P, 96000)
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(a + b[:6], total=15)})  # recuentos: vacíos
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY)
    ra = next(r for r in e.resultados if r.oferta.clave == "hotmart:A1")
    assert ra.enlace == url_biblioteca("RO", page_id=P)
    _, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{ra.oferta.oferta_id}.md")
    assert "la página lleva otras ofertas: de los 15 anuncios del enlace, 9 son de esta (destino a-kit.example)" in cuerpo


def test_hueco_actualiza_las_lineas_del_pais_en_la_ficha(tmp_path):
    from ejemplos import ejecucion_ejemplo
    from trovefy.caza.salida import escribir
    v = _vault(tmp_path)
    escribir(v, ejecucion_ejemplo())
    P = "100000000000001"
    en_ingles = [replace(a, texto="Printable worksheets for kids, download the PDF and learn at home every day.")
                 for a in viejos(P, 3, 60, 97000)]
    c = ClientePorUrl({url_biblioteca("RO", page_id=P): ok(en_ingles)})
    orquestador.medir_hueco(v, "o-ejemplo", "RO", ["fise de lucru", "fise pentru copii"], cliente=c,
                                      hoy=HOY)
    meta, cuerpo = frontmatter.leer(v / "wiki/ofertas/o-ejemplo.md")
    assert "Hueco en RO: sí" in cuerpo
    assert "Decisión en RO: **B** — nota 62,4 < 70 para A\n" in cuerpo
    assert "Estado: **B** — nota 62,4 < 70 para A\n" in cuerpo
    assert meta["fuente"] == meta["paises"]["RO"]["link_biblioteca"]


# --- re-revisión: N1 y N2 ----------------------------------------------------------------------


def test_tras_un_bloqueo_las_nuevas_pendientes_lo_dicen(tmp_path):
    from trovefy.caza.salida import texto_pendientes
    v = _vault(tmp_path)
    P = "100000000000961"
    ads = viejos(P, 5, 20, 98000)
    c = ClientePorUrl(
        {url_biblioteca("RO", q="uno"): ok(ads, completo=False, exacto=False)},
        excepcion_en={url_biblioteca("RO", page_id=P): SesionBloqueada("Meta bloqueó la sesión")},
    )
    url = "https://kit.example/ro/"
    e = ejecutar(v, "nicho", [("RO", "uno")], "tomi", 3, cliente=c,
                 resolver=resolver_fijo({url: destino_ok(url)}), hoy=HOY, region="europa")
    assert e.pendientes == 1 and e.pendientes_por == {"bloqueo": 1} and e.cuota is None
    assert "Meta bloqueó" in texto_pendientes(e) and "cuota" not in texto_pendientes(e)


def test_recuento_exacto_con_frase_sin_cota_en_la_linea_de_la_pagina(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000962"
    a, b, mapa = _dos_ofertas_en_una_pagina(P, 98100)
    c = ClientePorUrl({
        url_biblioteca("RO", page_id=P): ok(a[:4] + b[:4], total=18, completo=False),
        url_biblioteca("RO", q="Fișe de matematică", page_id=P): ok(a, total=9),
        url_biblioteca("RO", q="Povești pentru somn", page_id=P): ok(b, total=9),
    })
    e = ejecutar(v, "oferta", [], "tomi", 3, page_ids=[P], paises=["RO"], cliente=c, resolver=resolver_fijo(mapa),
                 hoy=HOY)
    ra = next(r for r in e.resultados if r.oferta.clave == "hotmart:A1")
    _, cuerpo = frontmatter.leer(v / "wiki/ofertas" / f"{ra.oferta.oferta_id}.md")
    linea = next(x for x in cuerpo.splitlines() if x.startswith(f"- {P}"))
    assert ": 9 anuncios activos" in linea and "≥" not in linea
