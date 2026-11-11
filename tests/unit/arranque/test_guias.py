import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[3] / "skills/arranque"
GUIAS = RAIZ / "references/pasos"
SECCIONES = ["**Objetivo**", "**Antes de empezar**", "**Pasos**", "**Errores típicos**", "**Cómo se verifica**"]


def test_guias_de_la_fase_0_nucleo():
    for nombre in ["00-entorno.md", "01-cerebro.md", "02-caza-sin-cuentas.md", "03-perfil.md", "04-business.md", "05-pagina.md", "06-cuenta-publicitaria.md", "07-dominio.md", "08-verificar-dominio.md", "16-apimart.md", "_plantilla.md"]:
        texto = (GUIAS / nombre).read_text()
        for s in SECCIONES:
            assert s in texto, (nombre, s)
        assert "trovefy arranque verificar" in texto


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
    raiz = RAIZ.parents[1] / "scripts/trovefy/arranque/verificadores"
    for nombre in ["entorno.py", "apimart.py", "cerebro.py"]:
        assert "`!" not in (raiz / nombre).read_text() and '"! ' not in (raiz / nombre).read_text(), nombre


def test_skill_tiene_frontmatter_y_permisos():
    t = (RAIZ / "SKILL.md").read_text()
    assert t.startswith("---\nname: arranque\n")
    assert "allowed-tools: Read, Bash(trovefy arranque *), Bash(trovefy cerebro *), Bash(trovefy navegador *)" in t
    assert "saltado por el usuario" in t


def _t(n):
    return (GUIAS / n).read_text()


def test_guia_01_abre_el_vault_en_obsidian():
    t = _t("01-cerebro.md")
    for x in ["Abrir carpeta como bóveda", "obsidian &", "/home/<tu-usuario>/trovefy-cerebro", "whoami", "EISDIR"]:
        assert x in t, x


def test_guia_16_lleva_de_cero_a_clave_funcionando():
    t = _t("16-apimart.md")
    for x in ["https://apimart.ai/", "https://apimart.ai/keys", "US$ 5", "Ctrl+Shift+V", "Ctrl+V", "touch ~/.config/trovefy/claude.env", "chmod 600"]:
        assert x in t, x
    assert "install -m" not in t


def test_guia_00_avisa_que_wsl_shutdown_cierra_claude_code():
    t = _t("00-entorno.md")
    assert "cierra Claude Code" in t and "cd ~/trovefy-cerebro" in t


def test_skill_prohibe_leer_env_y_cubre_hecho_y_bloqueado():
    t = (RAIZ / "SKILL.md").read_text()
    assert "Nunca leas ni muestres `~/.config/trovefy/*.env`; la clave solo la escribe el usuario." in t
    assert 'trovefy arranque bloqueado 02 --motivo "espera /trovefy:cazar (plan 07)"' in t
    assert "hecho" in t and "Playwright" in t
    assert "espera /trovefy:cazar" in _t("02-caza-sin-cuentas.md")
    assert "trovefy arranque hecho 00" in _t("00-entorno.md")


def test_guias_03_04_05_dicen_lo_esencial():
    assert "trovefy arranque checklist 03 --respuesta perfil_propio=si --respuesta dos_fa=si --respuesta sin_vpn=si" in _t("03-perfil.md")
    assert "Autenticación en dos pasos" in _t("03-perfil.md")
    for n in ["04-business.md", "05-pagina.md"]:
        assert "trovefy navegador abrir meta https://business.facebook.com/" in _t(n)
    assert "sin VPN" in _t("04-business.md") and "correo" in _t("04-business.md")
    assert "--dato url=" in _t("05-pagina.md") and "marca del primer producto" in _t("05-pagina.md")


def test_guia_06_avisa_antes_de_crear_nada():
    t = _t("06-cuenta-publicitaria.md")
    aviso = t.index("**Antes de crear nada: la moneda (USD) y la zona horaria no se pueden cambiar después.**")
    assert aviso < t.index("**Pasos**")
    assert "/trovefy:auditar" in t and "compras internacionales" in t
    assert "cuenta.limite_gasto_inicial_usd" in t and "US$ 250" in t and "Fase 1" in t
    assert "trovefy arranque hecho 06 --dato act_id=" in t


def test_guia_06_pide_pago_automatico():
    t = _t("06-cuenta-publicitaria.md")
    assert t.count("pago automático") >= 3 and "141820733085330" in t
    assert t.index("pago automático") < t.index("**Pasos**")


def test_guia_09_free_y_prueba_solo_si_hace_falta():
    t = _t("09-impultienda.md")
    for s in SECCIONES:
        assert s in t, s
    assert "trovefy arranque verificar 09" in t
    assert "Free" in t and "1 tienda" in t and "45 días" in t and "segunda tienda" in t


def test_guias_10_y_10b():
    t10, t10b = _t("10-whop.md"), _t("10b-hotmart.md")
    for t, n in ((t10, "10"), (t10b, "10b")):
        for s in SECCIONES:
            assert s in t, (n, s)
        assert f"trovefy arranque verificar {n}" in t
    aviso = t10.index("Antes de hacer el KYC, comprueba que Whop paga a Colombia")
    assert aviso < t10.index("**Pasos**") and "bloqueado" in t10 and "10b" in t10
    assert t10.index("trovefy arranque verificar 10") < t10.index("Set up Whop Payments")
    assert "checkout, el order bump y el upsell son de Hotmart" in t10b and "Cloudflare Pages" in t10b
    assert "US$ 50" in t10b and "HotPay Internacional" in t10b and "Lemon Squeezy" in t10b
    assert "Lemon Squeezy" not in _t("09-impultienda.md") + t10


def test_prerrequisitos_aceptan_patron_sin_confirmar():
    for n in ["05-pagina.md", "06-cuenta-publicitaria.md", "08-verificar-dominio.md", "09-impultienda.md", "10-whop.md"]:
        antes = _t(n).split("**Antes de empezar**")[1].split("**Pasos**")[0]
        assert "patrón sin confirmar" in antes and "verificado" in antes, n


def test_guias_con_patron_explican_confirmar():
    for n in ["04-business.md", "05-pagina.md", "06-cuenta-publicitaria.md", "08-verificar-dominio.md",
              "09-impultienda.md", "10-whop.md", "10b-hotmart.md"]:
        paso = n.split("-")[0]
        assert f"trovefy arranque confirmar {paso}" in _t(n), n


def test_skill_procedimiento_de_confirmacion_y_sin_plan_05_obsoleto():
    t = (RAIZ / "SKILL.md").read_text()
    assert "llega con el plan 05" not in t and "después del plan 05" not in t
    assert "trovefy arranque confirmar <paso> --respuesta si" in t
    assert "patrón sin confirmar" in t and "nunca responde por el usuario" in t
    assert "config/evidencia/provisional/" in t


def test_entorno_arreglo_de_playwright_con_cd():
    t = (RAIZ.parents[1] / "scripts/trovefy/arranque/verificadores/entorno.py").read_text()
    assert "plan 05" not in t
    assert "cd ~/trovefy/trovefy && uv run playwright install chromium" in t
