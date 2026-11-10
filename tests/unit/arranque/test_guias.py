import pathlib
import re

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
            for cmd in re.findall(r"`([^`]+)`", linea):
                if cmd == "!":  # mención del propio símbolo
                    continue
                assert "!" not in cmd, (f.name, cmd)  # ni `!` inicial ni negación dentro de un comando
            if "sudo" in linea or "nano" in linea:
                assert not linea.lstrip(" 0123456789.-").startswith("!"), (f.name, linea)
                assert "`!" not in linea.replace("`!`", ""), (f.name, linea)


def test_verificadores_sin_exclamacion_en_arreglos():
    raiz = RAIZ.parents[1] / "scripts/trovify/arranque/verificadores"
    for nombre in ["entorno.py", "apimart.py", "cerebro.py"]:
        assert "`!" not in (raiz / nombre).read_text() and '"! ' not in (raiz / nombre).read_text(), nombre


def test_skill_tiene_frontmatter_y_permisos():
    t = (RAIZ / "SKILL.md").read_text()
    assert t.startswith("---\nname: arranque\n")
    assert "allowed-tools: Read, Bash(trovify arranque *), Bash(trovify cerebro *), Bash(trovify navegador *)" in t
    assert "saltado por el usuario" in t
