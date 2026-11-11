import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from ayudas import anuncio
from test_cliente import cliente as cliente_falso
from test_cliente import de_fixture
from trovify.caza import orquestador
from trovify.caza.biblioteca import url_biblioteca
from trovify.caza.cliente import SesionBloqueada
from trovify.caza.destino import Destino
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.orquestador import (
    aplicar_strikes,
    ejecutar,
    palabras_a_reescribir,
    texto_sin_pie,
)
from trovify.caza.presupuesto import Presupuesto, PresupuestoAgotado
from trovify.vault import frontmatter
from trovify.vault.andamio import crear_vault

HOY = date(2026, 11, 10)


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
            return ResultadoBusqueda("vacio", url, 0, [], None, datetime.now(UTC), True, "firecrawl", 1,
                                     total_exacto=True)
        if r.estado == "bloqueado":
            self.presupuesto.bloqueos += 1
        return replace(r, url=url)


def ok(anuncios, total=None, completo=True, exacto=True, via="firecrawl", creditos=1):
    total = len(anuncios) if total is None else total
    return ResultadoBusqueda("ok", "", total, list(anuncios), None, datetime.now(UTC), completo,
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
    # lo medido se escribe como muestra parcial, sin total inventado
    r = e.resultados[0]
    assert r.total_meta is None and r.completo is False


def test_presupuesto_agotado_detiene_y_lo_dice(tmp_path):
    v = _vault(tmp_path)
    c = ClientePorUrl({}, excepcion_en={url_biblioteca("RO", q="uno"): PresupuestoAgotado("Presupuesto del día agotado")})
    e = ejecutar(v, "nicho", [("RO", "uno")], "tomi", 3, cliente=c, resolver=resolver_fijo({}), hoy=HOY,
                 region="europa")
    assert e.parada and "PresupuestoAgotado" in e.parada and e.consultas[0].resultados is None


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
    # el total de la página no es el de una oferta: nunca se pasa como total exacto
    assert rs["hotmart:A1"].total_meta is None


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
    from trovify.caza.destino import clave_oferta, oferta_id
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
    from trovify.caza.destino import clave_oferta, oferta_id
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
    from trovify.caza.salida import Consulta
    cs = [Consulta("a", "RO", 5, "u"), Consulta("b", "RO", 50, "u"), Consulta("c", "RO", None, "u"),
          Consulta("d", "RO", 0, "u")]
    assert [c.palabra for c in palabras_a_reescribir(cs, 20)] == ["a", "d"]


def test_contador_diario_se_comparte_y_la_cache_no_consume(tmp_path):
    from test_cliente import NavegadorFalso
    from trovify.caza.cache import Cache
    from trovify.caza.cliente import ClienteBibliotecaPublica
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
    h = orquestador.medir_hueco(v, "o-hueco", "RO", ["fise de lucru", "fise pentru copii"], cliente=c, hoy=HOY)
    assert h.hueco is True and h.original == "sin_traducir"
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
    h = orquestador.medir_hueco(v, "o-hueco2", "RO", ["fise de lucru", "fise pentru copii"], cliente=c, hoy=HOY)
    assert h.hueco is None
    meta, _ = frontmatter.leer(v / "wiki/ofertas/o-hueco2.md")
    assert meta["estado"] == "B" and meta["huecos"]["RO"]["competencia"] is None


def test_hueco_guardado_entra_en_la_siguiente_caza(tmp_path):
    v = _vault(tmp_path)
    P = "100000000000091"
    url = "https://kit.example/ro/"
    from trovify.caza.destino import clave_oferta, oferta_id
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
