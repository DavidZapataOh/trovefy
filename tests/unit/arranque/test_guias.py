import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "skills/arranque"
GUIAS = RAIZ / "references/pasos"
SECCIONES = ["**Objetivo**", "**Antes de empezar**", "**Pasos**", "**Errores típicos**", "**Cómo se verifica**"]


def test_guias_de_la_fase_0_nucleo():
    for nombre in ["00-entorno.md", "01-cerebro.md", "02-caza-sin-cuentas.md", "16-apimart.md", "_plantilla.md"]:
        texto = (GUIAS / nombre).read_text()
        for s in SECCIONES:
            assert s in texto, (nombre, s)
        assert "trovify arranque verificar" in texto


def test_guias_sin_practicas_prohibidas():
    for f in [*GUIAS.glob("*.md"), RAIZ / "SKILL.md"]:
        texto = f.read_text()
        assert "@latest" not in texto and "| bash" not in texto, f.name
        for linea in texto.splitlines():
            if linea.lstrip().startswith(("!", "1. !")) or "`! " in linea:
                assert "!!" not in linea and "&& !" not in linea, (f.name, linea)


def test_skill_tiene_frontmatter_y_permisos():
    t = (RAIZ / "SKILL.md").read_text()
    assert t.startswith("---\nname: arranque\n")
    assert "allowed-tools: Read, Bash(trovify arranque *), Bash(trovify cerebro *), Bash(trovify navegador *)" in t
    assert "saltado por el usuario" in t
