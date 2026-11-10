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


def _t(n):
    return (GUIAS / n).read_text()


def test_guia_01_abre_el_vault_en_obsidian():
    t = _t("01-cerebro.md")
    for x in ["Abrir carpeta como bóveda", r"\\wsl.localhost\Ubuntu\home\<tu-usuario>\trovify-cerebro", "whoami"]:
        assert x in t, x


def test_guia_16_lleva_de_cero_a_clave_funcionando():
    t = _t("16-apimart.md")
    for x in ["https://apimart.ai/", "https://apimart.ai/keys", "US$ 5", "Ctrl+Shift+V", "Ctrl+V", "touch ~/.config/trovify/claude.env", "chmod 600"]:
        assert x in t, x
    assert "install -m" not in t


def test_guia_00_avisa_que_wsl_shutdown_cierra_claude_code():
    t = _t("00-entorno.md")
    assert "cierra Claude Code" in t and "cd ~/trovify-cerebro" in t


def test_skill_prohibe_leer_env_y_cubre_hecho_y_bloqueado():
    t = (RAIZ / "SKILL.md").read_text()
    assert "Nunca leas ni muestres `~/.config/trovify/*.env`; la clave solo la escribe el usuario." in t
    assert 'trovify arranque bloqueado 02 --motivo "espera /trovify:cazar (plan 07)"' in t
    assert "hecho" in t and "Playwright" in t
    assert "espera /trovify:cazar" in _t("02-caza-sin-cuentas.md")
    assert "trovify arranque hecho 00" in _t("00-entorno.md")
