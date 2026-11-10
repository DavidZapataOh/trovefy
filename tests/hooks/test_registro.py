import json
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def test_hooks_json_registra_los_cuatro_hooks():
    reg = json.loads((RAIZ / "hooks/hooks.json").read_text())
    comandos = json.dumps(reg)
    for h in ["meta_guard.py", "secretos.py", "raw_inmutable.py", "stop.py"]:
        assert h in comandos
        assert (RAIZ / "hooks" / h).exists()
    assert "${CLAUDE_PLUGIN_ROOT}" in comandos


def test_matchers_exactos():
    reg = json.loads((RAIZ / "hooks/hooks.json").read_text())
    esperado = {
        "meta_guard.py": "mcp__.*|Bash|WebFetch",
        "secretos.py": "Write|Edit|MultiEdit|NotebookEdit|Bash",
        "raw_inmutable.py": "Write|Edit|MultiEdit|Bash",
        "stop.py": "Write|Edit|MultiEdit|Bash",
    }
    obtenido = {}
    for grupo in reg["hooks"]["PreToolUse"]:
        for h in grupo["hooks"]:
            assert h["type"] == "command"
            nombre = h["command"].split("/hooks/")[1].rstrip('"')
            assert h["command"] == f'python3 "${{CLAUDE_PLUGIN_ROOT}}/hooks/{nombre}"'
            obtenido[nombre] = grupo["matcher"]
    assert obtenido == esperado
