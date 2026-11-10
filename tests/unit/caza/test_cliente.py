import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from trovify.caza import cliente as m
from trovify.caza.cache import Cache
from trovify.caza.cliente import (
    ClienteBibliotecaPublica,
    ErrorDeRed,
    PaginaCapturada,
    SesionBloqueada,
)
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.presupuesto import ParadaPorErrores, Presupuesto

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures/biblioteca"


class NavegadorFalso:
    def __init__(self, paginas):
        self.paginas, self.llamadas = paginas, []

    def abrir(self, url, desplazar):
        self.llamadas.append((url, desplazar))
        p = self.paginas.pop(0)
        if isinstance(p, Exception):
            raise p
        return p


def de_fixture(nombre):
    d = json.loads((FIX / nombre).read_text())
    return PaginaCapturada(d["url_final"], d["html_final"], d["html_final"], [r["cuerpo"] for r in d["respuestas"]])


def presupuesto(esperas=None):
    registro = esperas if esperas is not None else []
    return Presupuesto(30, 0, 0, dormir=registro.append)


def cliente(paginas, cache=None, esperas=None):
    return ClienteBibliotecaPublica(presupuesto(esperas), NavegadorFalso(paginas), cache)


def test_busqueda_ok():
    r = cliente([de_fixture("pagina_therapy_toolkit.json")]).buscar("ALL", page_id="102506312071455")
    assert r.estado == "ok" and r.anuncios and r.url.startswith("https://www.facebook.com/ads/library/")


def test_bloqueo_detiene_la_sesion():
    c = cliente([PaginaCapturada("https://www.facebook.com/login/?next=x", "", "", [])])
    assert c.buscar("RO", q="fise").estado == "bloqueado"
    assert c.presupuesto.bloqueos == 1
    with pytest.raises(SesionBloqueada):
        c.buscar("RO", q="otra")


def test_vacio_solo_con_marcador():
    c = cliente([de_fixture("vacio.json")])
    assert c.buscar("RO", q="zzqxv").estado == "vacio"
    assert c.presupuesto.vacios == 1
    roto = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])
    assert cliente([roto]).buscar("RO", q="x").estado == "error"


def test_contexto_efimero(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    llamadas = []
    monkeypatch.setattr(m, "_lanzar_chromium", lambda **kw: llamadas.append(kw) or m._ChromiumFalso())
    m.NavegadorEfimero().abrir("https://www.facebook.com/ads/library/?q=x", desplazar=0)
    assert llamadas and all("user_data_dir" not in kw and "storage_state" not in kw for kw in llamadas)
    assert all(kw.get("chromium_sandbox") is True and kw.get("headless") is True for kw in llamadas)
    assert m._ChromiumFalso.nuevos_contextos == [{}]  # new_context() sin storage_state


def test_error_de_red_reintenta_con_esperas():
    esperas = []
    ok = de_fixture("pagina_therapy_toolkit.json")
    c = cliente([ErrorDeRed("x"), ErrorDeRed("y"), ok], esperas=esperas)
    assert c.buscar("ALL", page_id="1").estado == "ok"
    assert esperas[:2] == [30, 90]
    assert len(c.navegador.llamadas) == 3
    assert c.presupuesto.usadas == 1  # los reintentos no gastan presupuesto


def test_tres_errores_paran_la_sesion():
    c = cliente([ErrorDeRed("a"), ErrorDeRed("b"), ErrorDeRed("c")])
    with pytest.raises(ParadaPorErrores):
        c.buscar("RO", q="x")


def test_exito_reinicia_errores():
    ok = lambda: de_fixture("pagina_therapy_toolkit.json")
    c = cliente([ErrorDeRed("a"), ErrorDeRed("b"), ok(), ErrorDeRed("c"), ErrorDeRed("d"), ok()])
    assert c.buscar("ALL", page_id="1").estado == "ok"
    assert c.buscar("ALL", page_id="2").estado == "ok"


def test_pausa_tras_navegar():
    esperas = []
    c = ClienteBibliotecaPublica(
        Presupuesto(30, 7, 7, dormir=esperas.append), NavegadorFalso([de_fixture("vacio.json")])
    )
    c.buscar("RO", q="zzqxv")
    assert esperas == [7]


def test_cache_acierto_no_navega_ni_gasta(tmp_path):
    cache = Cache(tmp_path)
    esperas = []
    c = cliente([de_fixture("pagina_therapy_toolkit.json")], cache, esperas)
    r1 = c.buscar("ALL", page_id="102506312071455", max_anuncios=5)
    n_esperas, usadas = len(esperas), c.presupuesto.usadas
    r2 = c.buscar("ALL", page_id="102506312071455", max_anuncios=5)
    assert len(c.navegador.llamadas) == 1
    assert c.presupuesto.usadas == usadas and len(esperas) == n_esperas
    assert r2.estado == "ok" and r2.anuncios == r1.anuncios and r2.total_aprox == r1.total_aprox


def test_cache_no_guarda_bloqueo_ni_error(tmp_path):
    cache = Cache(tmp_path)
    roto = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])
    c = cliente([roto], cache)
    assert c.buscar("RO", q="x").estado == "error"
    assert list(tmp_path.iterdir()) == []
    c = cliente([PaginaCapturada("https://www.facebook.com/checkpoint/", "", "", [])], cache)
    assert c.buscar("RO", q="x").estado == "bloqueado"
    assert list(tmp_path.iterdir()) == []


def test_cache_vacio_se_guarda(tmp_path):
    cache = Cache(tmp_path)
    cliente([de_fixture("vacio.json")], cache).buscar("RO", q="zzqxv")
    assert cache.leer(m.url_biblioteca("RO", q="zzqxv")).estado == "vacio"


def test_cache_caduca(tmp_path):
    url = "https://www.facebook.com/ads/library/?q=x"
    r = ResultadoBusqueda("vacio", url, 0, [], None, datetime(2026, 1, 1, 10, tzinfo=UTC))
    ahora = [datetime(2026, 1, 1, 10, tzinfo=UTC)]
    cache = Cache(tmp_path, ttl_h=12, ahora=lambda: ahora[0])
    cache.guardar(url, r)
    ahora[0] += timedelta(hours=11)
    assert cache.leer(url) is not None
    ahora[0] += timedelta(hours=2)
    assert cache.leer(url) is None


def test_cache_corrupta_es_fallo(tmp_path):
    cache = Cache(tmp_path)
    url = "https://www.facebook.com/ads/library/?q=x"
    cache.guardar(url, ResultadoBusqueda("vacio", url, 0, [], None, datetime.now(UTC)))
    for f in tmp_path.iterdir():
        f.write_text("{no es json")
    assert cache.leer(url) is None


def test_cache_ida_y_vuelta_y_sin_medios(tmp_path):
    r = cliente([de_fixture("pagina_therapy_toolkit.json")]).buscar("ALL", page_id="102506312071455")
    cache = Cache(tmp_path)
    cache.guardar(r.url, r, 5)
    assert cache.leer(r.url, 5).anuncios == r.anuncios
    contenido = "".join(f.read_text() for f in tmp_path.iterdir())
    assert "fbcdn" not in contenido and "scontent" not in contenido


def test_cache_por_defecto_en_el_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("TROVIFY_VAULT", str(tmp_path))
    assert Cache.por_defecto().dir == tmp_path / "data" / "cache" / "biblioteca"


def _pagina_con_total(total, texto=""):
    nodo = {"collated_results": [{"ad_archive_id": "1", "page_id": "2", "page_name": "P",
                                  "start_date": 1700000000, "end_date": None, "is_active": True,
                                  "publisher_platform": ["FACEBOOK"], "snapshot": {"body": {"text": "t"}}}]}
    doc = {"search_results_connection": {"count": total, "edges": [{"node": nodo}]}}
    html = f'<html><script type="application/json">{json.dumps(doc)}</script></html>'
    return PaginaCapturada("https://www.facebook.com/ads/library/?q=x", html, texto, [])


def test_tope_de_meta_en_total_json():
    r = cliente([_pagina_con_total(50001)]).buscar("RO", q="x")
    assert r.estado == "ok"
    assert r.total_aprox == 50000 and "más de 50.000 (tope de Meta)" in r.motivo


def test_total_json_manda_sobre_el_texto():
    r = cliente([_pagina_con_total(120, "~900 resultados")]).buscar("RO", q="x")
    assert r.total_aprox == 120


def test_total_texto_con_mayor_que():
    r = cliente([_pagina_con_total(None, ">50.000 resultados")]).buscar("RO", q="x")
    assert r.total_aprox == 50000 and "más de 50.000 (tope de Meta)" in r.motivo
    r = cliente([_pagina_con_total(None, "~230 resultados")]).buscar("RO", q="x")
    assert r.total_aprox == 230 and not r.motivo


def test_descartados_en_el_motivo(monkeypatch):
    from trovify.caza.modelo import Parseo

    real = m.parsear_detalle
    monkeypatch.setattr(m, "parsear_detalle", lambda *a, **k: Parseo(real(*a, **k).anuncios, 3, 10))
    r = cliente([_pagina_con_total(10)]).buscar("RO", q="x")
    assert r.estado == "ok" and "3 anuncios descartados por formato" in r.motivo


def test_max_anuncios_recorta_y_decide_desplazamiento():
    c = cliente([de_fixture("pagina_therapy_toolkit.json")])
    r = c.buscar("ALL", page_id="102506312071455", max_anuncios=5)
    assert len(r.anuncios) == 5
    assert c.navegador.llamadas[0][1] == 0


def test_cache_distingue_max_anuncios(tmp_path):
    cache = Cache(tmp_path)
    c = cliente([de_fixture("pagina_therapy_toolkit.json"), de_fixture("pagina_therapy_toolkit.json")], cache)
    r5 = c.buscar("ALL", page_id="102506312071455", max_anuncios=5)
    r60 = c.buscar("ALL", page_id="102506312071455", max_anuncios=60)
    assert len(r5.anuncios) == 5 and len(r60.anuncios) > 5
    assert len(c.navegador.llamadas) == 2


def test_cache_no_sirve_resultado_incompleto(tmp_path):
    url = "https://www.facebook.com/ads/library/?q=x"
    base = cliente([de_fixture("pagina_therapy_toolkit.json")]).buscar("ALL", page_id="102506312071455")
    parcial = ResultadoBusqueda("ok", url, 3, base.anuncios[:3], None, datetime.now(UTC), completo=False)
    exhaustivo = ResultadoBusqueda("ok", url, None, base.anuncios[:3], None, datetime.now(UTC), completo=True)
    cache = Cache(tmp_path)
    cache.guardar(url, parcial, 60)
    assert cache.leer(url, 60) is None
    cache.guardar(url, exhaustivo, 60)
    leido = cache.leer(url, 60)
    assert leido is not None and leido.completo is True


def test_error_cargado_reinicia_errores_de_red():
    roto = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])
    ok = de_fixture("pagina_therapy_toolkit.json")
    c = cliente([ErrorDeRed("a"), ErrorDeRed("b"), roto, ErrorDeRed("c"), ok])
    assert c.buscar("RO", q="a").estado == "error"
    assert c.buscar("ALL", page_id="1").estado == "ok"


@pytest.mark.parametrize("codigo", [429, 403])
def test_http_limitado_es_bloqueo(codigo):
    p = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [], codigo)
    c = cliente([p])
    r = c.buscar("RO", q="x")
    assert r.estado == "bloqueado" and f"HTTP {codigo}" in r.motivo
    assert c.presupuesto.bloqueos == 1
    with pytest.raises(SesionBloqueada):
        c.buscar("RO", q="y")


def test_http_5xx_es_error_de_red():
    esperas = []
    p500 = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "", "", [], 503)
    c = cliente([p500, de_fixture("pagina_therapy_toolkit.json")], esperas=esperas)
    assert c.buscar("ALL", page_id="1").estado == "ok"
    assert esperas[0] == 30


def test_tres_errores_seguidos_paran():
    def roto():
        return PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])

    c = cliente([roto(), roto(), roto(), roto()])
    assert c.buscar("RO", q="a").estado == "error"
    assert c.buscar("RO", q="b").estado == "error"
    with pytest.raises(ParadaPorErrores, match="3 búsquedas seguidas con error"):
        c.buscar("RO", q="c")
    assert len(c.navegador.llamadas) == 3


def test_ok_reinicia_errores_seguidos():
    def roto():
        return PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])

    c = cliente([roto(), roto(), de_fixture("vacio.json"), roto(), roto()])
    assert c.buscar("RO", q="a").estado == "error"
    assert c.buscar("RO", q="b").estado == "error"
    assert c.buscar("RO", q="c").estado == "vacio"
    assert c.buscar("RO", q="d").estado == "error"
    assert c.buscar("RO", q="e").estado == "error"


def test_cota_inferior_menor_que_el_tope():
    r = cliente([_pagina_con_total(None, ">1.000 resultados")]).buscar("RO", q="x")
    assert r.total_aprox == 1000 and "más de 1.000 (cota inferior)" in r.motivo
    assert "tope" not in r.motivo


def test_parada_por_errores_de_red_es_persistente():
    esperas = []
    ok = de_fixture("pagina_therapy_toolkit.json")
    c = cliente([ErrorDeRed("a"), ErrorDeRed("b"), ErrorDeRed("c"), ok, ok], esperas=esperas)
    with pytest.raises(ParadaPorErrores):
        c.buscar("RO", q="x")
    navegaciones, usadas, n_esperas = len(c.navegador.llamadas), c.presupuesto.usadas, len(esperas)
    for q in ("y", "z"):
        with pytest.raises(ParadaPorErrores):
            c.buscar("RO", q=q)
    assert len(c.navegador.llamadas) == navegaciones == 3
    assert c.presupuesto.usadas == usadas and len(esperas) == n_esperas


def test_tercer_error_conserva_su_motivo():
    def roto():
        return PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])

    c = cliente([roto(), roto(), roto()])
    c.buscar("RO", q="a")
    c.buscar("RO", q="b")
    with pytest.raises(ParadaPorErrores, match="última: formato de la Biblioteca no reconocido"):
        c.buscar("RO", q="c")
    with pytest.raises(ParadaPorErrores, match="última: formato de la Biblioteca no reconocido"):
        c.buscar("RO", q="d")


def _pagina(conexion_html, texto=""):
    html = f'<html><script type="application/json">{json.dumps(conexion_html)}</script></html>'
    return PaginaCapturada("https://www.facebook.com/ads/library/?q=x", html, texto, [])


def _con(ids, hay_mas=None, count=None):
    nodos = [{"node": {"collated_results": [{
        "ad_archive_id": i, "page_id": "2", "page_name": "P", "start_date": 1700000000, "end_date": None,
        "is_active": True, "publisher_platform": ["FACEBOOK"], "snapshot": {"body": {"text": "t"}}}]}} for i in ids]
    con = {"edges": nodos}
    if hay_mas is not None:
        con["page_info"] = {"has_next_page": hay_mas}
    if count is not None:
        con["count"] = count
    return {"x": {"search_results_connection": con}}


def test_completo_solo_cuando_meta_dice_que_no_hay_mas():
    # primera página real: 30 de 234, has_next_page true
    assert cliente([de_fixture("pagina_therapy_toolkit.json")]).buscar("ALL", page_id="1").completo is False
    assert cliente([de_fixture("vacio.json")]).buscar("RO", q="zzqxv").completo is True
    assert cliente([_pagina(_con(["1", "2"], hay_mas=False))]).buscar("RO", q="x").completo is True
    assert cliente([_pagina(_con(["1", "2"], count=2))]).buscar("RO", q="x").completo is True
    assert cliente([_pagina(_con(["1", "2"], count=3))]).buscar("RO", q="x").completo is False
    assert cliente([_pagina(_con(["1", "2"]))]).buscar("RO", q="x").completo is False  # no se sabe


def test_recortar_o_descartar_no_es_completo(monkeypatch):
    r = cliente([_pagina(_con(["1", "2", "3"], hay_mas=False))]).buscar("RO", q="x", max_anuncios=2)
    assert len(r.anuncios) == 2 and r.completo is False
    from trovify.caza.modelo import Parseo

    real = m.parsear_detalle
    monkeypatch.setattr(m, "parsear_detalle", lambda *a, **k: Parseo(real(*a, **k).anuncios, 1, None, False))
    assert cliente([_pagina(_con(["1"], hay_mas=False))]).buscar("RO", q="x").completo is False


def test_bloqueo_y_error_no_son_completos():
    assert cliente([PaginaCapturada("https://www.facebook.com/login/", "", "", [])]).buscar("RO", q="x").completo is False
    roto = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", "<html></html>", "", [])
    assert cliente([roto]).buscar("RO", q="x").completo is False


def test_ok_sin_total_lo_dice():
    r = cliente([_pagina(_con(["1"], hay_mas=False))]).buscar("RO", q="x")
    assert r.total_aprox is None and "total no medido: Meta no mostró recuento" in r.motivo


def test_marcador_sin_resultados_en_js_con_formato_desconocido_es_error():
    html = ("<html><script>var t = 'No hay ningún anuncio que coincida';</script>"
            '<script type="application/json">{"data": {"otra_cosa": 1}}</script></html>')
    p = PaginaCapturada("https://www.facebook.com/ads/library/?q=x", html, "", [])
    assert cliente([p]).buscar("RO", q="x").estado == "error"
