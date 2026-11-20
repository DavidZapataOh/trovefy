"""Propuestas de corte y de surf al buzón, sin reenvíos (plan 23, Tarea 7)."""
import ast
from datetime import timedelta
from pathlib import Path

import pytest
from trovefy.aprobaciones.fuentes import BuzonNoDisponible, depositar
from trovefy.leer import propuestas as prop
from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import Corte
from trovefy.leer.surf import Surf
from trovefy_ejecutor.esquema import cargar_propuesta

from .ejemplos import AHORA, CAMPANA, CUENTA, of

F = Fiabilidad("media", False, ("día en curso",))
O = of("25.40", ventas=0)


def _valida(datos):
    return cargar_propuesta({**datos, "version": 1, "id": "P-20261120-001", "creada": AHORA.isoformat()})


def corte_conjuntos(ids):
    return Corte("pausar_conjuntos", tuple(ids), "AD01: 3,40 gastados, 0 pagos iniciados de 14 visitas", "normal", {})


def test_lote_con_dos_conjuntos():
    p = prop.a_propuesta(corte_conjuntos(["111", "222"]), O, F, CUENTA, "/leer --parte")
    assert p["tipo"] == "lote" and len(p["operaciones"]) == 2
    assert p["operaciones"][0] == {"entidad": "adset", "id": "111", "campo": "status", "de_esperado": "ACTIVE",
                                   "a": "PAUSED"}
    _valida(p)


def test_un_conjunto_es_pausar():
    assert prop.a_propuesta(corte_conjuntos(["111"]), O, F, CUENTA, "/leer --parte")["tipo"] == "pausar"


def test_pausar_campana_prioridad_alta():
    c = Corte("pausar_campana", (CAMPANA,), "0 ventas con 25,40 USD gastados (corte US$ 25, C1 1:24:15)", "alta", {})
    p = prop.a_propuesta(c, O, F, CUENTA, "/leer --intradia")
    assert p["prioridad"] == "alta" and p["expira_en_min"] == 360 and p["operaciones"][0]["entidad"] == "campaign"
    assert p["motivo"].endswith("· fiabilidad media")
    _valida(p)


def test_surf_en_cop():  # ×2 de 20.000 COP → 40.000; de_esperado = daily_budget vivo
    s = Surf("4000000000000001", "AD01 G1 mapa", 20000, 40000, "ROAS 2,63 hoy y 1 venta nueva: ×2", "S1 10:27", 1)
    p = prop.surf_a_propuesta([s], O, F, CUENTA, "/leer --intradia")
    op = p["operaciones"][0]
    assert p["tipo"] == "presupuesto" and p["expira_en_min"] == 120 and p["reinicia_aprendizaje"] is True
    assert (op["de_esperado"], op["a"], op["unidad"], op["moneda"]) == (20000, 40000, "minima", "COP")
    _valida(p)


def test_base_lote_a_las_23():
    cambios = [Surf(str(i), f"AD0{i}", 40000, 20000, "base", "S2 14:40") for i in (1, 2)]
    p = prop.surf_a_propuesta(cambios, O, F, CUENTA, "/leer --base", base=True)
    assert p["tipo"] == "lote" and p["expira_en_min"] == 60 and "23:00" in p["motivo"]
    _valida(p)


def test_alerta_valida():
    _valida(prop.alerta("/leer: revisar /landing", "falla la página", "aviso", "/leer --parte"))


def test_motivo_cabe_en_300():
    c = Corte("pausar_conjuntos", ("111",), "x" * 600, "normal", {})
    assert len(prop.a_propuesta(c, O, F, CUENTA, "/leer --parte")["motivo"]) <= 300


def _memoria(estado_previo_id="P-20261120-001", huella=None, hace_min=30):
    m = {"propuestas": {}, "surf": {}}
    prop.anotar(m, "pausar_campana|1", estado_previo_id, "pausar_campana", huella or {"ventas": 0, "gasto_usd_c": 2540},
                AHORA - timedelta(minutes=hace_min), 360)
    return m


def test_no_repite_pendiente():
    m = _memoria()
    assert not prop.debe_proponer("pausar_campana|1", {"ventas": 0, "gasto_usd_c": 2600}, m, lambda _i: None, AHORA)


def test_no_reenvia_sin_cambio_material():
    m = _memoria()
    assert not prop.debe_proponer("pausar_campana|1", {"ventas": 0, "gasto_usd_c": 2700}, m,
                                  lambda _i: "caducada", AHORA)


def test_reenvia_con_venta_nueva_o_3_usd_mas():
    m = _memoria()
    assert prop.debe_proponer("pausar_campana|1", {"ventas": 1, "gasto_usd_c": 2540}, m, lambda _i: "rechazada",
                              AHORA)
    assert prop.debe_proponer("pausar_campana|1", {"ventas": 0, "gasto_usd_c": 2840}, m, lambda _i: "caducada", AHORA)


def test_pendiente_vieja_cuenta_como_caducada():
    m = _memoria(hace_min=600)
    assert prop.debe_proponer("pausar_campana|1", {"ventas": 0, "gasto_usd_c": 2840}, m, lambda _i: None, AHORA)


def test_pausa_ejecutada_no_se_repite():
    m = _memoria()
    assert not prop.debe_proponer("pausar_campana|1", {"ventas": 5, "gasto_usd_c": 9000}, m,
                                  lambda _i: "ejecutada", AHORA)


def test_stop_del_cerebro_no_deposita(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".trovefy").mkdir(parents=True)
    (vault / ".trovefy" / "STOP").write_text("")
    with pytest.raises(BuzonNoDisponible, match="STOP"):
        depositar(vault, prop.alerta("t", "x", "info", "/leer --parte"))
    assert not (tmp_path / "spool").exists()


def test_leer_no_importa_graph_ni_mcp():
    """Ningún módulo de trovefy.leer (ni la CLI) importa el ejecutor de Meta, urllib ni un cliente MCP."""
    raiz = Path(__file__).resolve().parents[3] / "scripts" / "trovefy"
    archivos = [*sorted((raiz / "leer").glob("*.py")), raiz / "leer_cli.py"]
    prohibidos = ("trovefy_ejecutor.graph", "trovefy_ejecutor.ejecutar", "urllib", "http.client", "requests",
                  "socket", "mcp")
    for a in archivos:
        texto = a.read_text(encoding="utf-8")
        assert "graph.facebook.com" not in texto, a.name
        for nodo in ast.walk(ast.parse(texto)):
            nombres = []
            if isinstance(nodo, ast.Import):
                nombres = [n.name for n in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                nombres = [nodo.module]
            for n in nombres:
                assert not any(n == p or n.startswith(p + ".") for p in prohibidos), (a.name, n)
