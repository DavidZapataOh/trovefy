import inspect

import pytest
from ejecutor.falsos.graph_falso import GraphFalso, mundo_basico
from trovefy_ejecutor.graph import ClienteGraph, DetenidoPorStop, ErrorGraph, ErrorRed


def test_forced_to_paused():
    g = mundo_basico()
    g.forzar_pausa.add("s1")
    assert g.escribir("s1", {"daily_budget": 26000}) == {"success": True}
    assert g.leer("s1", ["status", "daily_budget"]) == {"id": "s1", "status": "PAUSED", "daily_budget": "26000"}


def test_red_tras_escribir_aplica():
    g = mundo_basico()
    g.red_tras_escribir.add("s1")
    with pytest.raises(ErrorRed):
        g.escribir("s1", {"daily_budget": 26000})
    assert g.leer("s1", ["daily_budget"])["daily_budget"] == "26000"


def test_validate_only_no_cambia_nada():
    g = mundo_basico()
    g.escribir("s1", {"daily_budget": 1}, validate_only=True)
    assert g.leer("s1", ["daily_budget"])["daily_budget"] == "20000" and g.escrituras() == []
    assert len(g.llamadas) == 2 and g.llamadas[0].validate_only is True


def test_misma_interfaz_publica_que_cliente():
    for nombre in ("leer", "listar", "escribir", "crear", "subir_imagen", "subir_video", "cuenta"):
        real = list(inspect.signature(getattr(ClienteGraph, nombre)).parameters)
        falso = list(inspect.signature(getattr(GraphFalso, nombre)).parameters)
        assert real == falso, nombre


def test_leer_solo_campos_pedidos_y_ausentes_no_aparecen():
    g = mundo_basico()
    assert g.leer("s2", ["daily_budget", "bid_amount"]) == {"id": "s2", "daily_budget": "15000"}
    assert g.leer("s1", []) == {"id": "s1"}


def test_leer_inexistente_error_graph():
    with pytest.raises(ErrorGraph):
        mundo_basico().leer("nope", ["status"])


def test_ids_invalidos_value_error_y_none():
    g = mundo_basico()
    with pytest.raises(ValueError):
        g.leer("s1/../x", ["status"])
    with pytest.raises(ValueError):
        g.escribir("s1", {"daily_budget": None})
    with pytest.raises(ValueError):
        g.crear("c1", "adsets", {"name": None})


def test_mundo_basico_contenido():
    g = mundo_basico()
    c = g.cuenta("act_0000000000000000")
    assert (c.currency, c.offset, c.timezone_name, c.spend_cap, c.account_status, c.amount_spent) == (
        "COP", 1, "America/Bogota", 1000000, 1, 250000)
    assert g.cuenta("act_usd").offset == 100
    assert g.objetos["x9"]["account_id"] == "999"
    assert g.objetos["s1"]["account_id"] == "0000000000000000"
    assert g.objetos["s1"]["bid_amount"] == "1500" and g.objetos["c1"]["status"] == "ACTIVE"
    assert "a1" in g.objetos and "s2" in g.objetos


def test_cuenta_desconocida():
    with pytest.raises(ErrorGraph):
        mundo_basico().cuenta("act_999")


def test_listar_hijos_por_arista():
    g = mundo_basico()
    ids = [o["id"] for o in g.listar("act_0000000000000000", "adsets", ["id", "status"])]
    assert ids == ["s1", "s2"]
    assert g.listar("act_0000000000000000", "campaigns", ["name"]) == [{"id": "c1", "name": "Campaña"}]


def test_errores_una_vez_sin_aplicar():
    g = mundo_basico()
    g.errores["s1"] = ErrorGraph(100, 1487, "no")
    with pytest.raises(ErrorGraph):
        g.escribir("s1", {"daily_budget": 5})
    assert g.objetos["s1"]["daily_budget"] == "20000"
    g.escribir("s1", {"daily_budget": 5})
    assert g.objetos["s1"]["daily_budget"] == "5"


def test_errores_tambien_en_validate_only_y_se_consumen():
    g = mundo_basico()
    g.errores["s1"] = ErrorGraph(100, 1487, "no")
    with pytest.raises(ErrorGraph):
        g.escribir("s1", {"daily_budget": 5}, validate_only=True)
    assert "s1" not in g.errores and g.objetos["s1"]["daily_budget"] == "20000"
    g.errores["c1"] = ErrorGraph(100, None, "no")
    with pytest.raises(ErrorGraph):
        g.crear("c1", "adsets", {"name": "x"}, validate_only=True)
    assert "9000001" not in g.objetos


def test_inexistente_error_graph_100_tambien_validate_only():
    g = mundo_basico()
    for vo in (False, True):
        with pytest.raises(ErrorGraph) as e:
            g.escribir("nope", {"status": "PAUSED"}, validate_only=vo)
        assert e.value.codigo == 100
        with pytest.raises(ErrorGraph) as e:
            g.crear("nope", "adsets", {"name": "x"}, validate_only=vo)
        assert e.value.codigo == 100
    assert g.objetos.keys() == mundo_basico().objetos.keys()


def test_importe_negativo_rechazado():
    g = mundo_basico()
    for vo in (False, True):
        with pytest.raises(ErrorGraph) as e:
            g.escribir("s1", {"daily_budget": -5}, validate_only=vo)
        assert e.value.codigo == 100
    with pytest.raises(ErrorGraph):
        g.crear("act_0000000000000000", "adsets", {"daily_budget": "-1"})
    assert g.objetos["s1"]["daily_budget"] == "20000" and "9000001" not in g.objetos


def test_red_al_leer():
    g = mundo_basico()
    g.red_al_leer = True
    with pytest.raises(ErrorRed):
        g.leer("s1", ["status"])


def test_token_caduca_tras():
    g = mundo_basico()
    g.token_caduca_tras = 1
    g.escribir("s1", {"daily_budget": 1})
    with pytest.raises(ErrorGraph) as e:
        g.leer("s1", ["status"])
    assert (e.value.codigo, e.value.subcodigo) == (190, 463)
    with pytest.raises(ErrorGraph):
        g.escribir("s1", {"daily_budget": 2}, validate_only=True)


def test_redondeo():
    g = mundo_basico()
    g.redondeo["s1"] = 26100
    g.escribir("s1", {"daily_budget": 26000})
    assert g.leer("s1", ["daily_budget"])["daily_budget"] == "26100"


def test_stop_tras():
    g = mundo_basico()
    g.stop_tras = 1
    g.escribir("s1", {"daily_budget": 1})
    g.escribir("s1", {"daily_budget": 2}, validate_only=True)
    with pytest.raises(DetenidoPorStop):
        g.escribir("s1", {"daily_budget": 3})
    assert g.objetos["s1"]["daily_budget"] == "1"


def test_cambiar_edicion_manual():
    g = mundo_basico()
    g.cambiar("s1", status="PAUSED", daily_budget=777)
    assert g.leer("s1", ["status", "daily_budget"]) == {"id": "s1", "status": "PAUSED", "daily_budget": "777"}
    assert g.llamadas == [g.llamadas[0]] and g.llamadas[0].metodo == "leer"


def test_crear_ids_crecientes_y_validate_only():
    g = mundo_basico()
    assert g.crear("act_0000000000000000", "campaigns", {"name": "x"}, validate_only=True) == {"success": True}
    assert "9000001" not in g.objetos
    r1 = g.crear("act_0000000000000000", "campaigns", {"name": "x", "status": "PAUSED"})
    r2 = g.crear("act_0000000000000000", "adsets", {"name": "y"})
    assert (r1, r2) == ({"id": "9000001"}, {"id": "9000002"})
    assert g.objetos["9000001"]["name"] == "x"
    assert [o["id"] for o in g.listar("act_0000000000000000", "adsets", ["id"])][-1] == "9000002"
    assert len(g.escrituras()) == 2


def test_subidas():
    g = mundo_basico()
    h = g.subir_imagen("act_0000000000000000", b"abc", "a.png")
    assert isinstance(h, str) and h
    assert g.subir_imagen("act_0000000000000000", b"abc", "a.png") == h
    v = g.subir_video("act_0000000000000000", __import__("pathlib").Path(__file__))
    assert isinstance(v, str) and v
    assert [x.metodo for x in g.escrituras()] == ["subir_imagen", "subir_imagen", "subir_video"]
