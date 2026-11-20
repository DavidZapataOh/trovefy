"""``test → muerto | candidato`` solo tras el resultado del ejecutor (plan 23, Tarea 7)."""
from trovefy.caja.config import cargar_caja
from trovefy.leer import propuestas as prop
from trovefy.leer.estado import aplicar_resultados, pasar_a_candidato
from trovefy.montar.tanda import bloque_pais
from unit.montar.ejemplos import copia_ejecutor

from .ejemplos import AHORA, CAMPANA, PAIS, P, vault_test

ID = "P-20261120-004"


def _memoria(tipo="pausar_campana", extra=None):
    m = {"propuestas": {}, "surf": {}}
    prop.anotar(m, f"{tipo}|{CAMPANA}", ID, tipo, {"ventas": 0, "gasto_usd_c": 2540}, AHORA, 360,
                extra or {"motivo": "0 ventas con 25,40 USD (C1 1:24:15)", "parte": "wiki/analisis/partes/2026-11-20.md"})
    return m


def test_muerto_solo_tras_ejecutada(tmp_path):
    v = vault_test(tmp_path)
    copia_ejecutor(v, ID, "pausar", "ejecutada", detalle="relectura PAUSED")
    m = _memoria()
    lineas = aplicar_resultados(v, P, PAIS, m, AHORA)
    b = bloque_pais(v, P, PAIS)
    assert b["estado"] == "muerto" and any("pasa a muerto" in x for x in lineas)
    evid = b["historial"][-1]["evidencia"]
    assert f"propuestas/{ID}.md" in evid and any(e.startswith("stop: [[wiki/analisis/partes/") for e in evid)
    assert cargar_caja(v).tests[0].estado == "cerrado"
    assert aplicar_resultados(v, P, PAIS, m, AHORA) == []  # idempotente


def test_aceptada_pero_fallo_sigue_en_test(tmp_path):
    v = vault_test(tmp_path)
    copia_ejecutor(v, ID, "pausar", "fallida", detalle="Meta devolvió un error")
    lineas = aplicar_resultados(v, P, PAIS, _memoria(), AHORA)
    assert bloque_pais(v, P, PAIS)["estado"] == "test" and "fallida" in lineas[0]


def test_rechazada_no_cambia_estado(tmp_path):
    v = vault_test(tmp_path)
    copia_ejecutor(v, ID, "pausar", "rechazada")
    motivo = v / "raw" / "telegram" / "motivos" / f"2026-11-20-{ID}.md"
    motivo.parent.mkdir(parents=True, exist_ok=True)
    motivo.write_text("---\ntipo: motivo\n---\n\n> espera un día más\n", encoding="utf-8")
    lineas = aplicar_resultados(v, P, PAIS, _memoria(), AHORA)
    assert bloque_pais(v, P, PAIS)["estado"] == "test" and "espera un día más" in lineas[0]


def test_surf_ejecutado_actualiza_vivo_y_caja(tmp_path):
    v = vault_test(tmp_path)
    copia_ejecutor(v, ID, "presupuesto", "ejecutada")
    m = _memoria("surf", {"a": {"4000000000000001": 40000}, "diario_usd": "20.00"})
    aplicar_resultados(v, P, PAIS, m, AHORA)
    b = bloque_pais(v, P, PAIS)
    assert b["lectura"]["surf"]["4000000000000001"]["presupuesto"] == 40000 and b["estado"] == "test"
    assert cargar_caja(v).tests[0].presupuesto_diario == 2000


def test_candidato(tmp_path):
    v = vault_test(tmp_path)
    assert pasar_a_candidato(v, P, PAIS, ["vende 3 días con ROAS neto 2,63"], AHORA)
    assert bloque_pais(v, P, PAIS)["estado"] == "candidato"
    assert not pasar_a_candidato(v, P, PAIS, ["otra vez"], AHORA)
