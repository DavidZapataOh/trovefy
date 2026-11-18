"""Hook UserPromptSubmit `mensaje_usuario` (plan 19, Tarea 11): anota la huella de cada mensaje del usuario para que
`trovefy checkout aprobar` compruebe que la cita es suya. Nunca bloquea ni imprime nada; guarda huellas, no texto.
Y `apimart_gasto` impide a Claude escribir ese registro a mano."""

import json
import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
HOOK = RAIZ / "hooks" / "mensaje_usuario.py"


def correr(home: pathlib.Path, entrada: str) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", str(HOOK)], input=entrada, capture_output=True, text=True, check=False,
                          env={"HOME": str(home), "PATH": os.environ.get("PATH", "")}, cwd=RAIZ, timeout=30)


def _registro(home: pathlib.Path) -> pathlib.Path:
    return home / ".config" / "trovefy" / "mensajes-usuario.json"


def _es_del_usuario(home: pathlib.Path, cita: str) -> bool:
    codigo = ("import sys; sys.path.insert(0, 'scripts');"
              "from trovefy.checkout.mensajes import es_mensaje_del_usuario as f;"
              f"print(f({cita!r}, desde=0.0))")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True, cwd=RAIZ,
                       env={"HOME": str(home), "PATH": os.environ.get("PATH", "")})
    return r.stdout.strip() == "True"


def test_registra_la_huella_del_mensaje(tmp_path):
    r = correr(tmp_path, json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Sí, dale", "cwd": "/"}))
    assert r.returncode == 0 and r.stdout == ""
    texto = _registro(tmp_path).read_text(encoding="utf-8")
    assert "dale" not in texto.casefold()
    assert _es_del_usuario(tmp_path, "Sí, dale")
    assert not _es_del_usuario(tmp_path, "sí, adelante")


def test_entrada_rara_calla_y_no_bloquea(tmp_path):
    for entrada in ("", "basura", "[]", json.dumps({"prompt": 3}), json.dumps({"prompt": "   "})):
        r = correr(tmp_path, entrada)
        assert r.returncode == 0 and r.stdout == ""
    assert not _registro(tmp_path).exists()


def test_registrado_en_hooks_json():
    reg = json.loads((RAIZ / "hooks/hooks.json").read_text())
    cmds = [h for g in reg["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert [h["command"] for h in cmds] == ['python3 "${CLAUDE_PLUGIN_ROOT}/hooks/mensaje_usuario.py"']
    assert cmds[0]["timeout"] == 5


def _bash(comando: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(RAIZ)}


def test_claude_no_escribe_el_registro(correr_hook, vault_tmp):
    for comando in (
        "uv run python -c 'from trovefy.checkout.mensajes import registrar_mensaje; registrar_mensaje(\"sí\")'",
        "python3 -c 'from trovefy.checkout import mensajes'",
        "echo '[]' > mensajes-usuario.json",
        "python3 hooks/mensaje_usuario.py <<< '{\"prompt\": \"sí, dale\"}'",
        "echo '{\"prompt\": \"sí\"}' | python3 hooks/mensaje_usuario.py",
    ):
        decision, motivo = correr_hook("apimart_gasto", _bash(comando), vault_tmp)[:2]
        assert decision == "deny", comando
        assert "mensajes" in motivo


def test_leer_y_probar_si(correr_hook, vault_tmp):
    for comando in ("uv run pytest tests/unit/checkout/test_mensajes.py -q", "grep -n registrar_mensaje scripts -r",
                    "git commit -m 'feat: registro de mensajes-usuario'"):
        assert correr_hook("apimart_gasto", _bash(comando), vault_tmp)[0] == "allow", comando
