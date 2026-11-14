from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]


def _skill() -> tuple[str, str]:
    t = (RAIZ / "skills/ver-anuncios/SKILL.md").read_text()
    return t.split("---")[1], t


def test_skill_solo_escribe_lotes_del_mcp_en_la_cache():
    cabecera, _ = _skill()
    assert "Write(~/.cache/trovefy/referencia/*/mcp/lote-*.json)" in cabecera
    assert "Write(~/.cache/trovefy/referencia/**)" not in cabecera
    assert "Write(data/referencia/analisis-*.json)" in cabecera


def test_skill_dice_que_anotar_borra_el_borrador():
    _, t = _skill()
    assert "borra el borrador" in t
