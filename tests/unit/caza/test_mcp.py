import json
from dataclasses import replace
from pathlib import Path

import pytest
from trovefy.caza.mcp import (
    ClienteMcp,
    LoteInvalido,
    cargar_lote,
    consultas_del_lote,
    parsear_mcp,
)
from trovefy.caza.modelo import ResultadoBusqueda
from trovefy.caza.salida import Ejecucion, _cabecera_via

FIX = Path(__file__).resolve().parents[2] / "fixtures/biblioteca/mcp_ads_library_search.json"


class FalsoPublico:
    def __init__(self, via):
        self.via = via
        self.presupuesto = None

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60, completa=False):
        from datetime import UTC, datetime

        return ResultadoBusqueda("vacio", "u", 0, [], None, datetime.now(UTC), via=self.via)


def _escribir(tmp_path, **cambios):
    d = json.loads(FIX.read_text())
    d.update(cambios)
    p = tmp_path / "lote.json"
    p.write_text(json.dumps(d))
    return p


def test_parsear_fixture():
    lote = cargar_lote(FIX)
    p = parsear_mcp(lote[0].respuesta, "RO")
    assert p.anuncios and p.anuncios[0].pais == "RO" and p.hay_mas is True
    assert p.total_json == 120 and p.anuncios[0].activo is True
    assert p.anuncios[1].activo is False and p.anuncios[1].inicio.isoformat() == "2026-08-15"


def test_cliente_responde_del_lote():
    c = ClienteMcp(cargar_lote(FIX))
    r = c.buscar("RO", q="  Fise de lucru ")
    assert r.via == "mcp" and r.estado == "ok" and r.completo is False and r.url.startswith("https://www.facebook.com/ads/library/")
    assert r.total_aprox == 120 and r.total_exacto is True


def test_malformado_cuenta_como_descartado_y_no_completo():
    lote = cargar_lote(FIX)
    p = parsear_mcp(lote[1].respuesta, "RO")
    assert p.descartados == 1 and len(p.anuncios) == 1 and p.hay_mas is None
    r = ClienteMcp(lote).buscar("RO", page_id="800000000001")
    assert r.completo is False and r.total_exacto is False


def test_fuera_del_lote_no_medido_y_anotado():
    c = ClienteMcp(cargar_lote(FIX))
    r = c.buscar("BG", q="x")
    assert r.estado == "error" and "fuera del lote del MCP" in r.motivo
    assert c.faltan == [{"pais": "BG", "q": "x", "page_id": None, "estado": "active"}]


def test_fuera_del_lote_con_respaldo_dice_su_via():
    r = ClienteMcp(cargar_lote(FIX), respaldo=FalsoPublico(via="firecrawl")).buscar("BG", q="x")
    assert r.via == "firecrawl"


def test_forma_desconocida_no_medido():
    lote = [replace(cargar_lote(FIX)[0], respuesta={"results": []})]
    r = ClienteMcp(lote).buscar("RO", q="fise de lucru")
    assert r.estado == "error" and "(P-01)" in r.motivo and r.anuncios == [] and r.total_aprox is None


def test_lote_de_otra_herramienta_se_rechaza(tmp_path):
    with pytest.raises(LoteInvalido):
        cargar_lote(_escribir(tmp_path, herramienta="mcp__meta-ads__ads_get_campaigns"))


def test_lote_con_secreto_se_rechaza(tmp_path):
    d = json.loads(FIX.read_text())
    d["busquedas"][0]["argumentos"]["token"] = "EAAB" + "x" * 60
    p = tmp_path / "l.json"
    p.write_text(json.dumps(d).replace("EAAB", "Bearer EAAB"))
    with pytest.raises(LoteInvalido):
        cargar_lote(p)


def test_lote_sin_pais_valido(tmp_path):
    d = json.loads(FIX.read_text())
    d["busquedas"][0]["pais"] = "romania"
    p = tmp_path / "l.json"
    p.write_text(json.dumps(d))
    with pytest.raises(LoteInvalido):
        cargar_lote(p)


def test_consultas_del_lote():
    assert consultas_del_lote(cargar_lote(FIX)) == [("RO", "fise de lucru")]


def test_cabecera_via_mcp():
    e = Ejecucion.__new__(Ejecucion)
    e.busquedas, e.via, e.creditos = 3, {"mcp": 2, "firecrawl": 1}, None
    assert "Firecrawl 1, MCP oficial 2" in _cabecera_via(e)


REAL = Path(__file__).resolve().parents[2] / "fixtures/caza/mcp_real_forma.json"


def test_forma_real_results_en_texto():
    lote = cargar_lote(REAL)
    p = parsear_mcp(lote[0].respuesta, "RO", lote[0].estado)
    assert len(p.anuncios) == 2 and p.descartados == 0
    a = p.anuncios[0]
    assert a.library_id == "900000000000101" and a.page_id == "800000000001"
    assert a.inicio.isoformat() == "2026-09-10" and a.titulo == "Titlu fictiv unu"
    assert a.texto == "" and a.plataformas == () and a.fin is None and a.activo is True
    assert a.collation_id is None and a.collation_count is None
    assert p.hay_mas is None


def test_forma_real_estado_all_no_inventa_activo():
    lote = cargar_lote(REAL)
    p = parsear_mcp(lote[0].respuesta, "RO", "all")
    assert p.anuncios[0].activo is False


def test_forma_real_cliente_ok_no_completo():
    r = ClienteMcp(cargar_lote(REAL)).buscar("RO", page_id="800000000001")
    assert r.estado == "ok" and r.motivo is None and len(r.anuncios) == 2 and r.completo is False


def test_forma_real_sin_envoltorio_y_ads_directo():
    cuerpo = json.loads(json.loads(REAL.read_text())["busquedas"][0]["respuesta"]["results"])
    assert len(parsear_mcp(cuerpo, "RO").anuncios) == 2


@pytest.mark.parametrize(
    "resp",
    [{"results": "no json"}, {"results": "[1]"}, {"results": json.dumps({"otra": 1})}, {"ads": "x"}, {"foo": "bar"}],
)
def test_forma_desconocida_se_sigue_rechazando(resp):
    from trovefy.caza.parser import FormatoDesconocido

    with pytest.raises(FormatoDesconocido):
        parsear_mcp(resp, "RO")


def _con_respuesta(resp):
    return [replace(cargar_lote(REAL)[0], respuesta=resp)]


@pytest.mark.parametrize("codigo", [4, 17, 32, 613, "17"])
@pytest.mark.parametrize("envuelto", [True, False])
def test_error_de_limite_es_bloqueado(codigo, envuelto):
    err = {"error": {"message": "(#4) Application request limit reached", "type": "OAuthException", "code": codigo}}
    resp = {"results": json.dumps(err)} if envuelto else err
    r = ClienteMcp(_con_respuesta(resp)).buscar("RO", page_id="800000000001")
    assert r.estado == "bloqueado" and r.anuncios == [] and r.via == "mcp"
    assert r.motivo and "limit reached" not in r.motivo


@pytest.mark.parametrize("http", [403, 429])
def test_error_http_limitado_es_bloqueado(http):
    resp = {"results": json.dumps({"error": {"message": "x", "code": 1, "http_status": http}})}
    r = ClienteMcp(_con_respuesta(resp)).buscar("RO", page_id="800000000001")
    assert r.estado == "bloqueado"


@pytest.mark.parametrize("err", [{"message": "Invalid parameter", "code": 100}, "algo falló"])
def test_otro_error_es_error(err):
    r = ClienteMcp(_con_respuesta({"results": json.dumps({"error": err})})).buscar("RO", page_id="800000000001")
    assert r.estado == "error" and r.anuncios == [] and "error" in r.motivo


def test_is_error_del_mcp_es_error():
    resp = {"isError": True, "content": [{"type": "text", "text": "fallo"}]}
    r = ClienteMcp(_con_respuesta(resp)).buscar("RO", page_id="800000000001")
    assert r.estado == "error"


@pytest.mark.parametrize("valor", [1789000000.0, "1789000000", 1789000000.7])
def test_epoch_float_o_texto(valor):
    cuerpo = json.loads(json.loads(REAL.read_text())["busquedas"][0]["respuesta"]["results"])
    for a in cuerpo["ads"] if "ads" in cuerpo else cuerpo["data"]:
        a["ad_delivery_start_time"] = valor
    p = parsear_mcp(cuerpo, "RO")
    assert p.descartados == 0 and p.anuncios[0].inicio.isoformat() == "2026-09-10"
