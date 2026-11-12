"""Ritmo de envío y horario de silencio (plan 10, Tarea 9)."""
from __future__ import annotations

from datetime import datetime

from ejecutor.datos_telegram import alerta, presupuesto_cop
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.ritmo import Decision, Ritmo


def H(h, m=0):
    return datetime(2026, 11, 12, h, m, tzinfo=ZONA_COT)


normal = cargar_propuesta(presupuesto_cop())
alta = cargar_propuesta(presupuesto_cop(id="P-20261112-005", prioridad="alta"))
urgente = cargar_propuesta(alerta(nivel="urgente"))
info = cargar_propuesta(alerta(nivel="info"))


def test_silencio():
    r = Ritmo()
    assert r.decidir(normal, H(23, 0)) == Decision(False, False, "silencio")
    assert r.decidir(info, H(3, 0)).motivo == "silencio"
    assert r.decidir(alta, H(3, 0)) == Decision(True, True, "alta")
    assert r.decidir(urgente, H(3, 0)) == Decision(True, True, "urgente")
    assert r.decidir(normal, H(6, 30)).enviar is True


def test_alerta_ignora_prioridad():
    r = Ritmo()
    a = cargar_propuesta(alerta(nivel="info", prioridad="alta"))
    assert r.decidir(a, H(3, 0)).motivo == "silencio"


def test_seis_por_hora_y_resumen():
    r = Ritmo()
    for i in range(6):
        assert r.decidir(normal, H(10, i)).enviar
        r.anotar_envio(H(10, i))
    assert r.decidir(normal, H(10, 30)) == Decision(False, False, "ritmo")
    assert r.decidir(info, H(10, 30)).motivo == "ritmo"
    assert r.decidir(alta, H(10, 30)).enviar
    assert not r.toca_resumen(H(10, 30), en_cola=3)
    assert r.toca_resumen(H(11, 1), en_cola=3) and not r.toca_resumen(H(11, 1), en_cola=0)


def test_sembrar_tras_reinicio():
    r = Ritmo()
    r.sembrar([H(9, 0)] + [H(10, i) for i in range(6)])
    assert r.decidir(normal, H(10, 30)) == Decision(False, False, "ritmo")
    assert r.decidir(normal, H(11, 6)).enviar


def test_resumen_de_la_mañana():
    r = Ritmo()
    assert not r.toca_resumen(H(6, 29), 4) and r.toca_resumen(H(6, 30), 4)
