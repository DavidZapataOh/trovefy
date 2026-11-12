from datetime import datetime

import pytest
from trovefy_ejecutor import callbacks
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.render import (
    AYUDA,
    BOTON_NO_VALIDO,
    PREGUNTA_MOTIVO,
    RECIBIDO,
    STOP_ACTIVO,
    Desenlace,
    ItemResumen,
    ResumenEstado,
    botones_propuesta,
    render_estado,
    render_resultado,
    render_resumen,
    texto_ya_procesada,
)

T = datetime(2026, 11, 12, 14, 7, tzinfo=ZONA_COT)
K = b"k" * 32
O = "P-20261112-004 · SUBIR PRESUPUESTO · prioridad normal"


def test_lineas_de_resultado():
    assert render_resultado(O, Desenlace("ejecutada", T, relectura="ACTIVE · 26.000 COP")).endswith(
        "\n\nEJECUTADA 14:07 · relectura OK: ACTIVE · 26.000 COP")
    assert render_resultado(O, Desenlace("fallida", T, codigo="#100 bot123:ABCdef")).endswith(
        "FALLÓ: #100 *** · no se cambió nada")
    assert render_resultado(O, Desenlace("discrepancia", T, relectura="PAUSED", nueva_propuesta="P-20261112-005 Reactivar")
                            ).endswith("DISCREPANCIA: Meta dice PAUSED → nueva propuesta P-20261112-005 Reactivar")
    assert render_resultado(O, Desenlace("caducada", T)).endswith("CADUCADA, no se ejecutó nada")
    assert render_resultado(O, Desenlace("rechazada", T)).endswith("RECHAZADA 14:07")
    assert render_resultado(O, Desenlace("ejecutando", T)).endswith("\n\nEJECUTANDO…")
    assert render_resultado(O, Desenlace("stop", T)).endswith("\n\n" + STOP_ACTIVO)
    assert render_resultado(O, Desenlace("obsoleta", T, relectura="20.000 COP")).endswith(
        "OBSOLETA: el valor cambió desde que se envió (20.000 COP); no se ejecutó nada")


def test_texto_externo_limpio_y_redactado():
    t = render_resultado(O, Desenlace("fallida", T, codigo="a\u202eb\nc " + "x" * 500))
    linea = t.split("\n\n")[-1]
    assert "\u202e" not in linea and "\n" not in linea and len(linea) < 300


def test_lote_largo_en_el_informe_se_corta():
    txt = render_resultado("x" * 3800, Desenlace("ejecutada", T, relectura="ok", lineas_lote=tuple(f"{i}. OK" for i in range(500))))
    assert len(txt) <= 4096 and "detalle en el vault" in txt and "… y " in txt


def test_ya_procesada():
    assert texto_ya_procesada("aceptada") == "Ya procesada (aceptada)"
    assert texto_ya_procesada("caducada") == "Caducada: no se ejecutó nada"
    assert texto_ya_procesada("recibida") == "Aún no enviada: no se hizo nada"


def test_textos_fijos():
    assert RECIBIDO == "Recibido" and BOTON_NO_VALIDO == "Botón no válido: no se hizo nada"
    assert PREGUNTA_MOTIVO.format(id="P-1") == "P-1 · ¿Motivo? (responde a este mensaje, opcional)"
    for c in ("/estado", "/stop", "/reanudar", "/pausar_todo", "/limites"):
        assert c in AYUDA


def test_botones_propuesta():
    b = botones_propuesta("P-20261112-004", 42, K)
    assert [x.texto for x in b[0]] == ["Aceptar", "Rechazar"]
    assert b[0][0].data == callbacks.firmar("P-20261112-004", "A", 42, K)
    assert b[0][1].data == callbacks.firmar("P-20261112-004", "R", 42, K)


def test_resumen_con_botones_solo_para_las_pendientes():
    items = [ItemResumen("P-20261112-004", "SUBIR PRESUPUESTO · 02 VIDEO G1 · 20.000 → 26.000 COP", "x", T, "enviada"),
             ItemResumen("P-20261112-005", "PAUSAR · AD03", "y", T, "rechazada")]
    texto, botones = render_resumen(items, "Resumen de la noche (06:30)", 42, K)
    assert len(botones) == 1 and botones[0][0].texto == "Aceptar …004" and botones[0][1].texto == "Rechazar …004"
    assert "RECHAZADA" in texto.upper() and "Caduca: 14:07 (hora Colombia)" in texto
    assert texto.startswith("Resumen de la noche (06:30)")


def test_resumen_maximo_cinco_y_limpia_motivo():
    mk = lambda i: ItemResumen(f"P-20261112-{i:03d}", "L", "m\u202e" * 100, T, "enviada")
    with pytest.raises(ValueError):
        render_resumen([mk(i) for i in range(6)], "t", 42, K)
    texto, _ = render_resumen([mk(1)], "t", 42, K)
    assert "\u202e" not in texto


def test_estado():
    t = render_estado(ResumenEstado({"act_…0000": "46.000 COP"}, [("P-20261112-004", "SUBIR PRESUPUESTO", T)], True))
    assert "STOP: activo" in t and "P-20261112-004" in t and "46.000 COP" in t
    t2 = render_estado(ResumenEstado({}, [], False))
    assert "STOP: no" in t2 and "Sin propuestas pendientes" in t2
