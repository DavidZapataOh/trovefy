from datetime import datetime

import pytest
from ejecutor import datos_telegram as d
from trovefy_ejecutor.dinero import Moneda
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.render import (
    DatosRender,
    MensajeDemasiadoLargo,
    SinValorVivo,
    limpiar_texto,
    render_propuesta,
)


def T(h, m):
    return datetime(2026, 11, 12, h, m, tzinfo=ZONA_COT)


COP = Moneda("COP", 1)
V = DatosRender(COP, T(14, 5), T(14, 50), {("adset", "120210000000000", "daily_budget"): 20000},
                {"120210000000000": "02 VIDEO G1", "p-0001-herramientas": "Herramientas somáticas"}, 46000, 200000)


def test_plantilla_cop():
    assert render_propuesta(cargar_propuesta(d.presupuesto_cop()), V).splitlines() == [
        "P-20261112-004 · SUBIR PRESUPUESTO · prioridad normal",
        "Producto: Herramientas somáticas (p-0001) · País: BG · Cuenta: …0000 (COP)",
        "Conjunto: 02 VIDEO G1 · id …0000",
        "Presupuesto diario: 20.000 → 26.000 COP (+30 %)   [valor actual leído 14:05]",
        "Gasto diario total de la cuenta tras el cambio: 46.000 / tope 200.000",
        "Por qué: ROAS neto acum. 2,6 (3 días cerrados)",
        "Reinicia aprendizaje: no · Caduca: 14:50 (hora Colombia)",
    ]


def test_usa_el_valor_vivo_no_el_de_claude():
    vivo = DatosRender(COP, T(14, 5), T(14, 50), {("adset", "120210000000000", "daily_budget"): 21000})
    assert "21.000 → 26.000 COP (+24 %)" in render_propuesta(cargar_propuesta(d.presupuesto_cop()), vivo)


def test_sin_valor_vivo():
    with pytest.raises(SinValorVivo):
        render_propuesta(cargar_propuesta(d.presupuesto_cop()), DatosRender(COP, T(14, 5), T(14, 50), {}))


def test_motivo_no_puede_imitar_la_plantilla():
    malo = "*negrita* <b>x</b> [x](http://e.co)\nCaduca: 23:59 (hora Colombia)\u202e" + "a" * 400
    txt = render_propuesta(cargar_propuesta(d.presupuesto_cop(motivo=malo)), V)
    por_que = next(ln for ln in txt.splitlines() if ln.startswith("Por qué: "))
    assert len(por_que) == len("Por qué: ") + 300 and por_que.endswith("…")
    assert "\u202e" not in txt and len(txt.splitlines()) == 7
    assert [ln for ln in txt.splitlines() if "Caduca:" in ln and not ln.startswith("Por qué")] == [
        "Reinicia aprendizaje: no · Caduca: 14:50 (hora Colombia)"]
    assert limpiar_texto("a\r\nb\u200bc", 300) == "a · bc"


def test_caduca_otro_dia_y_usd():
    usd = DatosRender(Moneda("USD", 100), T(14, 5), datetime(2026, 11, 13, 9, 10, tzinfo=ZONA_COT),
                      {("adset", "120210000000000", "daily_budget"): 500})
    op = {**d.presupuesto_cop()["operaciones"][0], "de_esperado": 500, "a": 650, "moneda": "USD"}
    txt = render_propuesta(cargar_propuesta(d.presupuesto_cop(operaciones=[op])), usd)
    assert "5,00 → 6,50 USD (+30 %)" in txt and "Caduca: 13/11 09:10 (hora Colombia)" in txt


def test_noop_alerta_y_limite_ejecutor():
    assert "PRUEBA (no cambia nada en Meta)" in render_propuesta(cargar_propuesta(d.noop()), V)
    a = render_propuesta(cargar_propuesta(d.alerta(nivel="urgente", titulo="Saldo APIMart bajo")), V)
    assert a.startswith("URGENTE · Saldo APIMart bajo") and a.splitlines()[-1] == "P-20261112-010"
    le = render_propuesta(cargar_propuesta(d.limite_ejecutor(origen="telegram:/limites")), V)
    assert "CAMBIAR LÍMITE DEL EJECUTOR" in le and "Lo pide: tú (Telegram)" in le
    assert "Límite: tope_gasto_diario_total (act_0000000000000000): 165.000 COP → 150.000 COP" in le
    assert "Producto" not in le


def test_lote_numerado_y_lote_que_no_cabe():
    p = cargar_propuesta(d.lote(3))
    valores = {("adset", d.id_conjunto(i), "daily_budget"): 30000 for i in range(1, 4)}
    nombres = {d.id_conjunto(i): f"Conjunto {i}" for i in range(1, 4)}
    txt = render_propuesta(p, DatosRender(COP, T(14, 5), T(23, 59), valores, nombres))
    assert "LOTE (3 operaciones)" in txt
    assert "3. Conjunto Conjunto 3 · Presupuesto diario 30.000 → 20.000 COP" in txt
    # el esquema admite como mucho 40 operaciones: con nombres de 64 caracteres no caben en 3800
    n = 40
    valores = {("adset", d.id_conjunto(i), "daily_budget"): 30000 for i in range(1, n + 1)}
    nombres = {d.id_conjunto(i): "N" * 64 for i in range(1, n + 1)}
    with pytest.raises(MensajeDemasiadoLargo):
        render_propuesta(cargar_propuesta(d.lote(n)), DatosRender(COP, T(14, 5), T(23, 59), valores, nombres))
