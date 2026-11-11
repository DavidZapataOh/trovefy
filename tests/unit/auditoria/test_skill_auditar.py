"""La skill /auditar dice lo que decidió el controlador (texto que lee Claude, no código)."""

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "skills"
SKILL = (RAIZ / "auditar/SKILL.md").read_text(encoding="utf-8")


def test_sin_confirmacion_extra_al_elegir_un_pais_con_aviso():
    assert "solo si él lo confirma" not in SKILL
    assert "No le pidas otra confirmación" in SKILL


def test_sin_recomendado_no_recomienda_y_con_empate_tampoco():
    assert "una recomendada" not in SKILL
    assert "no recomiendes tú ninguno" in SKILL
    assert "empate: elige tú" in SKILL


def test_cuota_del_dia_y_huecos_reutilizados():
    assert "Búsquedas usadas hoy" in SKILL
    assert "se retoma mañana" in SKILL
    assert "trovefy caza hueco" in SKILL


def test_cita_entre_comillas_simples():
    assert "--cita '<sus palabras literales>'" in SKILL
    assert "'\\''" in SKILL


def test_senales_de_la_oferta_y_salidas():
    assert "las tres señales de la oferta" in SKILL and "de cada país con sus cifras" not in SKILL
    assert "`Error:`" in SKILL


def test_ayuda_lista_auditar():
    assert "/trovefy:auditar" in (RAIZ / "ayuda/SKILL.md").read_text(encoding="utf-8")
