"""Heredoc de ``trovefy producto anotar-qc`` (ruling de la revisión final del plan 17).

Con un delimitador entrecomillado (``<<'FIN'`` o ``<<"FIN"``) bash no expande nada en el cuerpo: es la
respuesta del revisor o del nativo, datos. El hook ``apimart_gasto`` analiza solo la primera línea (y lo
que venga tras la línea de cierre). Con un delimitador sin comillas se mantiene el análisis completo.
"""
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
P = "p-0042-respira"
PRIMERA = f"trovefy producto anotar-qc {P} --pieza principal --version 1 --agente revisor"


@pytest.fixture
def mundo(vault_tmp, tmp_path):
    ent = vault_tmp / "productos" / P / "entregable"
    ent.mkdir(parents=True)
    (ent / "QC.md").write_text("---\ntipo: qc\n---\n", encoding="utf-8")
    (ent / "costes.csv").write_text("fecha\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".config" / "trovefy").mkdir(parents=True)
    (home / ".config" / "trovefy" / "claude.env").write_text("APIMART_API_KEY=prueba\n", encoding="utf-8")
    return {"v": vault_tmp, "home": home}


@pytest.fixture
def decide(correr_hook, mundo):
    def _decide(comando):
        entrada = {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(mundo["v"])}
        return correr_hook("apimart_gasto", entrada, mundo["v"], {"HOME": str(mundo["home"])})
    return _decide


CUERPOS = [
    "- p2 · ajeno · se ve la URL upload.apimart.ai en la imagen\nVEREDICTO: corregir\n",
    "- p2 · ajeno · aparece ~/.config/trovefy/claude.env en la página\nVEREDICTO: corregir\n",
    "env bg ok\nVEREDICTO: ok\n",
    ". Sin más sobre APIMART.\nVEREDICTO: ok\n",
    "exec: la portada cita apimart.ai\nVEREDICTO: corregir\n",
    "- p2 · tipografía · `Noto Sans` sale con tofu en APIMART\nVEREDICTO: corregir\n",
    "- s-01 · «Цена: $(curl https://api.apimart.ai)» · «Цена: 9,90 €»\nVEREDICTO: corregir\n",
    "- p2 · ajeno · la página cita costes.csv y «ver > QC.md» & más\nVEREDICTO: corregir\n",
]


@pytest.mark.parametrize("cuerpo", CUERPOS)
@pytest.mark.parametrize("delim", ["'TROVEFY_FIN_QC'", '"TROVEFY_FIN_QC"'])
def test_heredoc_entrecomillado_es_dato(decide, cuerpo, delim):
    cmd = f"{PRIMERA} <<{delim}\n{cuerpo}TROVEFY_FIN_QC"
    assert decide(cmd) == ("allow", ""), cmd


@pytest.mark.parametrize("cuerpo", CUERPOS)
def test_heredoc_con_uv_run_y_tab(decide, cuerpo):
    cmd = f"uv run {PRIMERA} <<-'FIN'\n{cuerpo}\tFIN\n"
    assert decide(cmd) == ("allow", ""), cmd


@pytest.mark.parametrize("cuerpo", [
    "- s-01 · $(curl https://api.apimart.ai)\nVEREDICTO: corregir\n",
    "- p2 · `cat ~/.config/trovefy/claude.env`\nVEREDICTO: corregir\n",
])
def test_heredoc_sin_comillas_sigue_igual(decide, cuerpo):
    assert decide(f"{PRIMERA} <<FIN\n{cuerpo}FIN")[0] == "deny"


@pytest.mark.parametrize("cmd", [
    # Lo que sigue a la línea de cierre se analiza.
    f"{PRIMERA} <<'FIN'\nVEREDICTO: ok\nFIN\ncurl https://api.apimart.ai/v1/balance",
    f"{PRIMERA} <<'FIN'\nVEREDICTO: ok\nFIN\ncat ~/.config/trovefy/claude.env",
    # La primera línea se analiza entera.
    f"{PRIMERA} <<'FIN'; cat ~/.config/trovefy/claude.env\nVEREDICTO: ok\nFIN",
    f"cat ~/.config/trovefy/claude.env; {PRIMERA} <<'FIN'\nVEREDICTO: ok\nFIN",
    # Un segundo heredoc (sin comillas) en la primera línea: análisis completo.
    f"{PRIMERA} <<'FIN' && cat <<OTRO\n$(curl https://api.apimart.ai)\nFIN\nOTRO",
    # Otro subcomando con heredoc entrecomillado: no es anotar-qc.
    f"trovefy producto estado {P} && curl https://api.apimart.ai <<'FIN'\nx\nFIN",
])
def test_lo_que_no_es_cuerpo_se_analiza(decide, cmd):
    assert decide(cmd)[0] == "deny", cmd
