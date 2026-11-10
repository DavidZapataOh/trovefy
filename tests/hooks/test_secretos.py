import json

TOKEN_META = "EAA" + "B" * 40
TOKEN_BOT = "123456789:" + "A" * 35


def test_write_con_token_en_el_vault_se_deniega(correr_hook, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": str(vault_tmp / "wiki/x.md"), "content": f"token {TOKEN_META}"}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_bash_con_token_de_bot_se_deniega(correr_hook, vault_tmp):
    e = {"tool_name": "Bash", "tool_input": {"command": f"echo bot{TOKEN_BOT} > notas.txt"}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_token_de_bot_sin_prefijo_se_deniega(correr_hook, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": str(vault_tmp / "wiki/a.md"), "content": f"x {TOKEN_BOT}"}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_env_permitido(correr_hook, vault_tmp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ruta = tmp_path / ".config/trovify/claude.env"
    e = {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": "APIMART_KEY=sk-" + "x" * 30}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "allow"


def test_env_con_punto_punto_no_escapa(correr_hook, vault_tmp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ruta = tmp_path / ".config/trovify/../../vault/wiki/otro.env"
    e = {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": "K=sk-" + "x" * 30}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_env_fuera_del_directorio_o_sin_extension_se_deniega(correr_hook, vault_tmp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for ruta in (vault_tmp / "wiki/x.env", tmp_path / ".config/trovify/notas.md"):
        e = {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": "K=sk-" + "x" * 30}}
        assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_bash_nunca_tiene_la_excepcion(correr_hook, vault_tmp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cmd = f"echo K={TOKEN_META} > {tmp_path}/.config/trovify/claude.env"
    e = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "deny"


def test_secreto_en_multiedit_y_notebook(correr_hook, vault_tmp):
    me = {"tool_name": "MultiEdit", "tool_input": {"file_path": str(vault_tmp / "wiki/a.md"), "edits": [{"old_string": "a", "new_string": TOKEN_META}]}}
    nb = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(vault_tmp / "wiki/a.ipynb"), "new_source": "access_token=abc"}}
    ed = {"tool_name": "Edit", "tool_input": {"file_path": str(vault_tmp / "wiki/a.md"), "old_string": "a", "new_string": TOKEN_META}}
    assert correr_hook("secretos", me, vault_tmp)[0] == "deny"
    assert correr_hook("secretos", nb, vault_tmp)[0] == "deny"
    assert correr_hook("secretos", ed, vault_tmp)[0] == "deny"


def test_el_motivo_nombra_el_patron_y_no_el_valor(correr_hook_crudo, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": str(vault_tmp / "wiki/a.md"), "content": TOKEN_META}}
    proc = correr_hook_crudo("secretos", e, vault_tmp)
    assert "Meta" in json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert TOKEN_META not in proc.stdout + proc.stderr


def test_texto_normal_pasa(correr_hook, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/a.md", "content": "ROAS 2,24 el 03-nov"}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "allow"


def test_herramienta_no_revisada_pasa(correr_hook, vault_tmp):
    e = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/a.md"}}
    assert correr_hook("secretos", e, vault_tmp)[0] == "allow"


def _w(ruta, contenido):
    return {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": contenido}}


def _b(cmd, cwd="/tmp"):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}


def test_sk_exige_limite_izquierdo(correr_hook, vault_tmp):
    for texto in ("git checkout -b task-refactor-authentication-flow", "risk-management-guidelines-v2"):
        assert correr_hook("secretos", _w(vault_tmp / "wiki/a.md", texto), vault_tmp)[0] == "allow", texto
    clave = "OPENAI_API_KEY=sk-proj-" + "a" * 30
    assert correr_hook("secretos", _w(vault_tmp / "wiki/a.md", clave), vault_tmp)[0] == "deny"
    assert correr_hook("secretos", _w(vault_tmp / "wiki/a.md", "x " + clave), vault_tmp)[0] == "deny"


def test_alcance_escritura_fuera_de_vault_repo_y_config(correr_hook, vault_tmp, tmp_path):
    clave = "OPENAI_API_KEY=sk-" + "a" * 30
    assert correr_hook("secretos", _w(tmp_path / "otro/.env", clave), vault_tmp)[0] == "allow"
    assert correr_hook("secretos", _w(vault_tmp / "wiki/.env", clave), vault_tmp)[0] == "deny"


def test_alcance_repo_por_claude_plugin_root(correr_hook, vault_tmp, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"CLAUDE_PLUGIN_ROOT": str(repo)}
    e = _w(repo / "x.py", "url = 'https://x/?access_token=abc'")
    assert correr_hook("secretos", e, vault_tmp, env)[0] == "deny"
    assert correr_hook("secretos", e, vault_tmp)[0] == "allow"  # sin la variable no hay repo


def test_bash_solo_meta_y_telegram_en_cualquier_cwd(correr_hook, vault_tmp):
    assert correr_hook("secretos", _b(f"echo {TOKEN_META}"), vault_tmp)[0] == "deny"
    assert correr_hook("secretos", _b(f"echo bot{TOKEN_BOT}", cwd=str(vault_tmp)), vault_tmp)[0] == "deny"
    assert correr_hook("secretos", _b("export K=sk-" + "a" * 30), vault_tmp)[0] == "allow"
    assert correr_hook("secretos", _b("curl 'https://x.test/?access_token=abc'"), vault_tmp)[0] == "allow"
