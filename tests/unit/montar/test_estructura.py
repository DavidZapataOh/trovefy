"""La estructura ABO del test, sus nombres, su huella y el resumen en seco (plan 22, Tarea 3)."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest
from trovefy.aprobaciones.fuentes import Lectura
from trovefy.montar import MontajeInvalido, NoMedido
from trovefy.montar.estructura import (
    cargar_contexto,
    construir,
    huella,
    inicio_programado,
    nombre_campana,
    resumen_en_seco,
)
from trovefy.montar.importes import calcular
from trovefy.montar.tanda import elegir, leer_tanda
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy_ejecutor.esquema import cargar_propuesta

from .ejemplos import AHORA, CUENTA, LIMITES, META, PAIS, TRM, P


@pytest.fixture
def todo(vault_zz):
    ctx = cargar_contexto(vault_zz, P, PAIS)
    piezas = elegir(leer_tanda(vault_zz, P, PAIS, "t1").piezas, n=5)
    imp = calcular(CUENTA, Lectura(META, None), Lectura(LIMITES, None), TRM, AHORA.date(), conjuntos=5,
                   usd_conjunto=Decimal(5), usd_tope=Decimal(100))
    return ctx, piezas, imp


def test_estructura_valida_para_el_ejecutor(todo):
    ctx, piezas, imp = todo
    d = construir(ctx, piezas, imp, 1, AHORA)
    p = cargar_propuesta({**d, "id": "P-20261120-002", "version": 1, "creada": AHORA.isoformat()})
    assert p.estructura.campana.spend_cap == 400000
    assert all(c.daily_budget == 20000 for c in p.estructura.conjuntos)


def test_nombres_del_metodo(todo):
    ctx, piezas, imp = todo
    d = construir(ctx, piezas, imp, 1, AHORA)
    assert d["campana"]["nombre"] == "PRUEBA ZZ | G1 | ABO | 20-11-26"
    c = d["conjuntos"][0]
    assert c["nombre"] == c["anuncios"][0]["nombre"] == piezas[0].nombre
    assert nombre_campana("TIHA VALNA BG", 2, datetime(2026, 11, 19).date()) == "TIHA VALNA BG | G2 | ABO | 19-11-26"


def test_ubicaciones_y_evento(todo):
    d = construir(*todo, 1, AHORA)
    assert all(c["ubicaciones_excluidas"] == ["audience_network", "threads"] and c["evento"] == "PURCHASE"
               for c in d["conjuntos"])
    assert d["campana"]["objetivo"] == "OUTCOME_SALES" and d["campana"]["tipo_presupuesto"] == "ABO"


def test_genero_solo_si_el_avatar_es_de_un_sexo(todo):
    ctx, piezas, imp = todo
    assert construir(ctx, piezas, imp, 1, AHORA)["conjuntos"][0]["generos"] == [2]  # «жени 30-55…»
    ambos = replace(ctx, avatar="жени и мъже 30-55")
    assert "generos" not in construir(ambos, piezas, imp, 1, AHORA)["conjuntos"][0]
    todos = replace(ctx, cfg=replace(ctx.cfg, sexo="todos"))
    assert "generos" not in construir(todos, piezas, imp, 1, AHORA)["conjuntos"][0]


def test_sin_status_en_la_entrada(todo):
    assert '"status"' not in json.dumps(construir(*todo, 1, AHORA))


def test_url_tags_y_miniatura(todo):
    d = construir(*todo, 1, AHORA)
    a = d["conjuntos"][0]["anuncios"][0]
    assert a["url"] == "https://prueba.example/" and a["url_tags"].startswith("utm_source=fb")
    assert a["miniatura"].startswith(f"productos/{P}/creativos/{PAIS}/t1/")


def test_inicio_proxima_medianoche_bogota():
    ahora = datetime(2026, 11, 19, 23, 0, tzinfo=ZONA_NEGOCIO)
    assert inicio_programado(ahora, "America/Bogota", "00:00") == datetime(2026, 11, 21, 0, 0, tzinfo=ZONA_NEGOCIO)
    ahora = datetime(2026, 11, 19, 10, 0, tzinfo=ZONA_NEGOCIO)
    assert inicio_programado(ahora, "America/Bogota", "00:00") == datetime(2026, 11, 20, 0, 0, tzinfo=ZONA_NEGOCIO)


def test_huella_cambia_con_un_byte(todo):
    d = construir(*todo, 1, AHORA)
    otra = copy.deepcopy(d)
    otra["medios"][0]["sha256"] = "0" * 64
    assert huella(d) != huella(otra)


def test_huella_ignora_solo_validar(todo):
    d = construir(*todo, 1, AHORA)
    assert huella(d) == huella({**d, "solo_validar": True, "id": "P-20261120-003"})


def test_sin_dsa_en_la_ue_no_medido(todo):
    ctx, piezas, imp = todo
    ue = replace(ctx, pais="BG", cfg=replace(ctx.cfg, dsa_beneficiario=None))
    with pytest.raises(NoMedido, match="dsa.beneficiario"):
        construir(ue, piezas, imp, 1, AHORA)


def test_dsa_en_la_ue(todo):
    ctx, piezas, imp = todo
    piezas = tuple(replace(p, url_base=p.url_base) for p in piezas)
    d = construir(replace(ctx, pais="BG"), piezas, imp, 1, AHORA)
    assert d["dsa"] == {"beneficiario": "Beneficiario Prueba", "pagador": "Pagador Prueba"}


def test_resumen_sin_ids_completos(todo):
    ctx, piezas, imp = todo
    d = construir(ctx, piezas, imp, 1, AHORA)
    r = resumen_en_seco(d, imp, piezas, ctx)
    assert "1111111111111111" not in r and CUENTA not in r and "2222222222222222" not in r
    assert "Todo se crea en PAUSED" in r and "techo 400.000 COP (US$ 100,00)" in r
    assert "2026-11-21 00:00 (America/Bogota)" in r


def test_idioma_sin_clave_de_meta(todo):
    ctx, piezas, imp = todo
    with pytest.raises(MontajeInvalido, match="IDIOMAS_META"):
        construir(replace(ctx, idioma="xx"), piezas, imp, 1, AHORA)


def test_renovacion_en_la_misma_campana(todo):
    ctx, piezas, imp = todo
    d = construir(ctx, piezas[:2], imp, 2, AHORA, campana_existente="9000001")
    assert d["campana_existente"] == "9000001" and len(d["conjuntos"]) == 2
    assert all(c["daily_budget"] == 20000 for c in d["conjuntos"])
