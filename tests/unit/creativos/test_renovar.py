"""Renovación cada 48 h sobre el ángulo ganador (plan 21, Tarea 13)."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.creativos import coste, renovar
from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.contexto import ruta_tanda

from .ejemplos import AHORA, PAIS, P
from .test_manifest import cerrada

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "creativos" / "anuncios-lectura.json"
FORMATOS = ("broll_voz", "ugc", "claymation", "3d", "scroll_pdf", "zoom_lento")


def _lectura(vault, datos=None):
    ruta = vault / "productos" / P / "trafico" / PAIS / "anuncios.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if datos is None:
        shutil.copy(FIX, ruta)
    else:
        ruta.write_text(json.dumps(datos), encoding="utf-8")
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_ganador_por_ventas(tmp_path):
    vault, *_ = cerrada(tmp_path)
    g = renovar.angulo_ganador(_lectura(vault), renovar.leer_manifiestos(vault, P, PAIS))
    assert g.angulo == "пет минути вечер" and g.anuncio == "AD02" and g.ventas == Decimal(2)


def test_ganador_por_pi_sin_ventas(tmp_path):
    vault, *_ = cerrada(tmp_path)
    lectura = _lectura(vault, [{"nombre": "AD01 G1 сън без хапчета", "ventas": 0, "pi": 2, "fiabilidad": "media"},
                               {"nombre": "AD03 G1 спри мислите", "ventas": 0, "pi": 5, "fiabilidad": "media"}])
    assert renovar.angulo_ganador(lectura, renovar.leer_manifiestos(vault, P, PAIS)).angulo == "спри мислите"


def test_fiabilidad_baja_none(tmp_path):
    vault, *_ = cerrada(tmp_path)
    lectura = _lectura(vault, [{"nombre": "AD02 G1 пет минути вечер", "ventas": 3, "pi": 4, "fiabilidad": "baja"}])
    assert renovar.angulo_ganador(lectura, renovar.leer_manifiestos(vault, P, PAIS)) is None


def test_usa_reserva_del_ganador(tmp_path):
    vault, *_ = cerrada(tmp_path)
    lectura = _lectura(vault)
    man = renovar.leer_manifiestos(vault, P, PAIS)
    plan = renovar.plan_renovacion(renovar.angulo_ganador(lectura, man), renovar.reservas_libres(man), lectura, man,
                                   FORMATOS)
    assert plan.reservas == ("AD06", "AD10") and plan.nuevas_sobre_ganador == 0 and plan.nuevas_angulo_nuevo == 1


def test_sin_reserva_dos_nuevas_mas_una(tmp_path):
    vault, *_ = cerrada(tmp_path)
    lectura = _lectura(vault)
    man = renovar.leer_manifiestos(vault, P, PAIS)
    plan = renovar.plan_renovacion(renovar.angulo_ganador(lectura, man), [], lectura, man, FORMATOS)
    assert (plan.nuevas_sobre_ganador, plan.nuevas_angulo_nuevo) == (2, 1)
    assert plan.formatos[0] == "broll_voz" and len(plan.formatos) == 2  # el del ganador y otro


def test_sin_lectura_no_crea_nada(tmp_path):
    vault, *_ = cerrada(tmp_path)
    with pytest.raises(ValueError, match="sin lectura de /leer"):
        renovar.abrir_renovacion(vault, P, PAIS, FORMATOS, AHORA)
    assert not ruta_tanda(vault, P, PAIS, "t2").exists()


def test_tope_de_renovacion(tmp_path):
    vault, _ctx, cfg, *_ = cerrada(tmp_path)
    _lectura(vault)
    tanda, _plan = renovar.abrir_renovacion(vault, P, PAIS, FORMATOS, AHORA)
    assert tanda == "t2"
    carpeta = ruta_tanda(vault, P, PAIS, "t2")
    assert tanda_md.tipo(carpeta) == "renovacion" and renovar.plan_de(carpeta).angulo_ganador == "пет минути вечер"
    assert coste.limite(vault, P, PAIS, "t2", cfg) == (Decimal("2.00"), coste.SIN_APROBAR)
    coste.fijar_tope(vault, P, PAIS, "renovacion", Decimal("2.00"), "dos dólares por renovación, ok", AHORA)
    assert coste.limite(vault, P, PAIS, "t2", cfg) == (Decimal("2.00"), None)
