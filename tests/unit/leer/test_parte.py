"""El parte diario e intradía con la tabla de los vídeos (plan 23, Tarea 8)."""
import os
import re
from pathlib import Path

from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import Metricas
from trovefy.leer.parte import Informe, escribir_parte, seccion
from trovefy.leer.reglas import veredicto_conjunto

from .ejemplos import AHORA, ECO, U, conj, of, vault_test

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "leer" / "parte-diario.md"
F = Fiabilidad("media", True, ("37 clics acumulados (< 300)",))


def _c1_5420():
    """La tabla de C1 54:20: AD1 4,57 / 12 visitas / 0 PI; AD2 4,27 / 13 / 1 PI; AD3 5,58 / 22 / 4 PI y 1 venta."""
    cs = [conj(gasto="4.57", visitas=12, pi=0, cpc="0.16", ventas=0, bruto="0", nombre="AD01 G1 mapa",
               sid="4000000000000001"),
          conj(gasto="4.27", visitas=13, pi=1, cpc="0.12", ventas=0, bruto="0", nombre="AD02 G1 villano",
               sid="4000000000000002"),
          conj(gasto="5.58", visitas=22, pi=4, cpc="0.16", ventas=1, bruto="15.01", nombre="AD03 G1 sueño",
               sid="4000000000000003")]
    return of("14.42", ventas=1, bruto="15.01", pixel=1, horas=31, conjuntos=cs)


def _informe(o, **kw):
    ver = [veredicto_conjunto(c, U, True) for c in o.conjuntos]
    return Informe(o, F, ECO, ver, "test", **kw)


def test_golden_parte_c1_5420():
    texto = seccion(_informe(_c1_5420(), propuestas=["P-20261120-001: lote · AD01, AD02"],
                             renovar=["AD01 G1 mapa (mapa)", "AD02 G1 villano (villano)"]), U, "PRUEBA · ZZ")
    if os.environ.get("TROVEFY_GOLDEN") == "escribir":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(texto, encoding="utf-8")
    assert texto == GOLDEN.read_text(encoding="utf-8")
    assert "| AD01 G1 mapa | mapa | 4,57 |" in texto and "| APAGAR |" in texto and "| MANTENER |" in texto


def test_dato_ausente_es_raya_con_motivo():
    o = of("5", conjuntos=[conj(gasto="5")])
    from dataclasses import replace

    c = replace(o.conjuntos[0], metricas=Metricas(None, None, None, None, None, None, None, None))
    o = replace(o, conjuntos=(c,), motivos=("no medido: sin TRM del 2026-11-19",))
    texto = seccion(_informe(o), U, "x")
    assert "| AD01 G1 mapa | mapa | — | — | — | — | — |" in texto
    assert "- no medido: sin TRM del 2026-11-19" in texto


def test_intradia_anade_seccion(tmp_path):
    v = vault_test(tmp_path)
    r = escribir_parte(v, AHORA.date(), "p:ZZ:parte", "## parte\nuno\n", AHORA, anadir=False)
    escribir_parte(v, AHORA.date(), "p:ZZ:parte", "## parte\ndos\n", AHORA, anadir=False)  # sustituye
    escribir_parte(v, AHORA.date(), "p:ZZ:intradia", "## ronda 10:00\n", AHORA, anadir=True)
    escribir_parte(v, AHORA.date(), "p:ZZ:intradia", "## ronda 12:00\n", AHORA, anadir=True)
    t = r.read_text(encoding="utf-8")
    assert "uno" not in t and t.count("## parte") == 1 and "## ronda 10:00" in t and "## ronda 12:00" in t
    assert t.startswith("---\n") and "tipo: parte" in t


def test_parte_enlaza_el_anterior(tmp_path):
    from datetime import timedelta

    v = vault_test(tmp_path)
    escribir_parte(v, AHORA.date() - timedelta(days=1), "a", "## a\n", AHORA, anadir=False)
    r = escribir_parte(v, AHORA.date(), "a", "## b\n", AHORA, anadir=False)
    assert "[[wiki/analisis/partes/2026-11-19]]" in r.read_text(encoding="utf-8")


def test_sin_datos_personales():
    texto = seccion(_informe(_c1_5420()), U, "x")
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", texto)
    assert "comprador" not in texto.lower()
