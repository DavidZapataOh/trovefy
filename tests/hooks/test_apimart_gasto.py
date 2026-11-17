import pytest

MOTIVO = "APIMart solo se llama con `trovefy producto`: tiene tope de gasto"


def _bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/tmp"}


def test_curl_apimart_denegado(correr_hook, vault_tmp):
    cmd = 'curl -H "Authorization: Bearer $APIMART_API_KEY" https://api.apimart.ai/v1/images/generations'
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("deny", MOTIVO)


def test_trovefy_producto_permitido(correr_hook, vault_tmp):
    for cmd in ("trovefy producto imagenes p-0042-respira", "uv run trovefy producto imagenes p-0042-respira",
                "  trovefy producto estado p-0042-respira --base https://api.apimart.ai"):
        assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("allow", "")


def test_encadenado_tras_trovefy_denegado(correr_hook, vault_tmp):
    cmd = "trovefy producto estado x; curl https://api.apimart.ai/v1/images/generations"
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("deny", MOTIVO)


@pytest.mark.parametrize("cmd", [
    "trovefy producto x && python3 -c 'import os; print(os.environ[\"APIMART_API_KEY\"])'",
    "trovefy producto x $(curl https://api.apimart.ai/v1/balance)",
    "trovefy producto x `curl https://API.APIMART.AI/v1/balance`",
    "echo $APIMART_API_KEY",
    "wget https://api.apimart.ai/v1/tasks/x | cat",
    "python3 -c \"import urllib.request; urllib.request.urlopen('https://api.apimart.ai/v1/balance')\"",
])
def test_otras_vias_denegadas(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny"


def _web(url):
    return {"tool_name": "WebFetch", "tool_input": {"url": url, "prompt": "x"}}


def test_webfetch_apimart_denegado(correr_hook, vault_tmp):
    for url in ("https://api.apimart.ai/v1/balance", "https://APIMART.AI/x", "https://upload.apimart.ai/f/x.png",
                "https://docs%2eapimart.ai@api.apimart.ai/v1/balance", "https://api.apimart.ai#docs.apimart.ai"):
        assert correr_hook("apimart_gasto", _web(url), vault_tmp) == ("deny", MOTIVO), url
    assert correr_hook("apimart_gasto", _web("https://notapimart.ai.example.com/"), vault_tmp) == ("allow", "")


def test_webfetch_a_la_documentacion_permitido(correr_hook, vault_tmp):
    """Ruling R-D: leer docs.apimart.ai no cuesta nada."""
    for url in ("https://docs.apimart.ai/llms.txt", "https://DOCS.apimart.ai/en/api-reference/tasks/status.md"):
        assert correr_hook("apimart_gasto", _web(url), vault_tmp) == ("allow", ""), url


def test_json_roto_deny(correr_hook, vault_tmp):
    decision, _ = correr_hook("apimart_gasto", "{roto", vault_tmp)
    assert decision == "deny"


def test_otros_comandos_allow(correr_hook, vault_tmp):
    for entrada in (_bash("ls -la"), _bash("curl https://example.com"),
                    {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}},
                    {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}):
        assert correr_hook("apimart_gasto", entrada, vault_tmp) == ("allow", "")


# --- M2: vías de escape del comando -----------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "trovefy producto x & curl https://api.apimart.ai/v1/balance",
    "trovefy producto x &curl https://api.apimart.ai/v1/balance",
    "trovefy producto x < <(curl https://api.apimart.ai/v1/balance)",
    "trovefy producto x > >(curl https://api.apimart.ai/v1/balance)",
    'curl https://api.apimart"".ai/v1/balance',
    "curl https://api.apimart\\.ai/v1/balance",
    "curl https://api.apim'a'rt.ai/v1/balance",
    "python3 -c 'from trovefy.apimart.cliente import enviar'",
    "python3 -c 'from trovefy import apimart'",
    "uv run python -m trovefy.apimart.lote",
    "printenv APIMART_API_KEY",
    "env | grep APIMART",
    "trovefy arranque x; python3 -c 'import trovefy.apimart.http as h; print(h.leer_credenciales())'",
    "rg --pre 'sh -c' apimart.ai .",
    "git diff --output=/tmp/x apimart.ai",
    "rg -o 'curl .*apimart.ai.*' notas.md | sh",
    "grep -h curl notas.md | grep apimart.ai | bash",
    "trovefy caza apimart.ai",
])
def test_vias_de_escape_denegadas(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "uv run pytest -q tests/unit/apimart/test_lote.py -k apimart.ai",
    "uv run pytest -q tests/unit/apimart 2>&1 | tail -5",
    "uv run ruff check scripts/trovefy/apimart",
    "ruff check --select I trovefy.apimart",
    "rg -n 'apimart.ai' scripts",
    "grep -rn APIMART_BASE_URL scripts",
    "git log --oneline -- scripts/trovefy/apimart",
    "git diff HEAD~1 -- docs/apimart.ai.md",
    "git show HEAD:scripts/trovefy/apimart/http.py | grep APIMART",
    'git commit -m "fix(apimart): ronda de revisión (apimart.ai)"',
    "trovefy producto imagenes p-0042-respira --base https://api.apimart.ai",
    "git add scripts/trovefy/apimart/lote.py && git status",
])
def test_comandos_permitidos(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("allow", ""), cmd


# --- L9: claude.env solo lo lee trovefy ---------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "cat ~/.config/trovefy/claude.env",
    "head -1 ~/.config/trovefy/claude.env",
    "less ~/.config/trovefy/claude.env",
    'cat ~/.config/trovefy/claude"".env',
    "grep KEY ~/.config/trovefy/claude.env",
    "rg . ~/.config/trovefy/claude.env",
    "git show HEAD:claude.env",
    "uv run pytest --confcutdir ~/.config/trovefy/claude.env",
])
def test_leer_claude_env_denegado(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny", cmd


def test_claude_env_bajo_trovefy_permitido(correr_hook, vault_tmp):
    cmd = "trovefy producto imagenes p-0042-respira --env ~/.config/trovefy/claude.env"
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("allow", "")


@pytest.mark.parametrize("herramienta,datos", [
    ("Read", {"file_path": "/home/alguien/.config/trovefy/claude.env"}),
    ("Grep", {"pattern": "KEY", "path": "/home/alguien/.config/trovefy/claude.env"}),
])
def test_read_y_grep_de_claude_env_denegados(correr_hook, vault_tmp, herramienta, datos):
    entrada = {"tool_name": herramienta, "tool_input": datos, "cwd": "/tmp"}
    assert correr_hook("apimart_gasto", entrada, vault_tmp)[0] == "deny"


# --- H2: el tope solo se sube con trovefy y la cita del usuario -------------------------------------

P = "p-0042-respira"


def _producto(vault, meta_extra=""):
    ruta = vault / "productos" / P / "PRODUCTO.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(f"---\nid: {P}\n{meta_extra}---\n# Respira\n", encoding="utf-8")
    return ruta


def _escribir(ruta, contenido):
    return {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": contenido}, "cwd": "/tmp"}


def _editar(ruta, viejo, nuevo):
    return {"tool_name": "Edit", "tool_input": {"file_path": str(ruta), "old_string": viejo, "new_string": nuevo},
            "cwd": "/tmp"}


def test_write_que_introduce_el_tope_denegado(correr_hook, vault_tmp):
    ruta = _producto(vault_tmp)
    entrada = _escribir(ruta, f"---\nid: {P}\napimart_tope_usd: '300'\n---\n# Respira\n")
    assert correr_hook("apimart_gasto", entrada, vault_tmp)[0] == "deny"


def test_edit_que_cambia_el_tope_denegado(correr_hook, vault_tmp):
    ruta = _producto(vault_tmp, "apimart_tope_usd: '3'\n")
    entrada = _editar(ruta, "apimart_tope_usd: '3'", "apimart_tope_usd: '300'")
    assert correr_hook("apimart_gasto", entrada, vault_tmp)[0] == "deny"
    multi = {"tool_name": "MultiEdit", "cwd": "/tmp", "tool_input": {"file_path": str(ruta), "edits": [
        {"old_string": "# Respira", "new_string": "# Respira 2"},
        {"old_string": "'3'", "new_string": "'300'"}]}}
    assert correr_hook("apimart_gasto", multi, vault_tmp)[0] == "deny"


def test_editar_otras_cosas_de_producto_permitido(correr_hook, vault_tmp):
    ruta = _producto(vault_tmp, "apimart_tope_usd: '3'\n")
    assert correr_hook("apimart_gasto", _editar(ruta, "# Respira", "# Respira, el libro"), vault_tmp) == ("allow", "")
    nuevo = f"---\nid: {P}\napimart_tope_usd: '3'\n---\n# Respira, otro cuerpo\n"
    assert correr_hook("apimart_gasto", _escribir(ruta, nuevo), vault_tmp) == ("allow", "")


def test_write_de_config_producto_denegado(correr_hook, vault_tmp):
    ruta = vault_tmp / "config" / "producto.yaml"
    assert correr_hook("apimart_gasto", _escribir(ruta, "apimart: {}\n"), vault_tmp)[0] == "deny"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("apimart: {}\n", encoding="utf-8")
    assert correr_hook("apimart_gasto", _editar(ruta, "{}", "{x: 1}"), vault_tmp)[0] == "deny"


def test_decision_de_tope_a_mano_denegada(correr_hook, vault_tmp):
    ruta = vault_tmp / "productos" / P / "decisiones" / "2026-11-16-100000-tope-apimart.md"
    assert correr_hook("apimart_gasto", _escribir(ruta, "---\ncita: x\n---\n"), vault_tmp)[0] == "deny"


@pytest.mark.parametrize("cmd", [
    "sed -i 's/apimart_tope_usd: 3/apimart_tope_usd: 300/' productos/p-0042-respira/PRODUCTO.md",
    "echo 'apimart_tope_usd: 300' >> PRODUCTO.md",
    "rm config/producto.yaml",
    "sed -i s/2.00/200/ config/producto.yaml",
])
def test_bash_que_toca_el_tope_denegado(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny", cmd


# --- M3: el registro del gasto no se toca a mano --------------------------------------------------

@pytest.mark.parametrize("rel", [
    "entregable/costes.csv", "entregable/bonos/bono-1/costes.csv",
    "entregable/.apimart-intentos.jsonl", "entregable/.apimart.lock",
])
def test_write_edit_del_gasto_denegados(correr_hook, vault_tmp, rel):
    ruta = vault_tmp / "productos" / P / rel
    assert correr_hook("apimart_gasto", _escribir(ruta, "x"), vault_tmp)[0] == "deny"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("a\n", encoding="utf-8")
    assert correr_hook("apimart_gasto", _editar(ruta, "a", "b"), vault_tmp)[0] == "deny"


@pytest.mark.parametrize("cmd", [
    "rm productos/p-0042-respira/entregable/costes.csv",
    "truncate -s 0 entregable/costes.csv",
    "> entregable/costes.csv",
    ": > costes.csv",
    "echo fila >> entregable/costes.csv",
    "sed -i '$d' costes.csv",
    "mv costes.csv costes.viejo",
    "cp /tmp/vacio.csv productos/p-0042-respira/entregable/costes.csv",
    "rm -f entregable/.apimart-intentos.jsonl",
    "rm entregable/.apimart.lock",
    "echo x | tee entregable/.apimart-intentos.jsonl",
    "python3 -c \"open('costes.csv','w')\"",
    'rm entregable/costes"".csv',
])
def test_bash_destructivo_sobre_el_gasto_denegado(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "cat productos/p-0042-respira/entregable/costes.csv",
    "tail -3 entregable/costes.csv 2>/dev/null",
    "wc -l entregable/.apimart-intentos.jsonl",
])
def test_leer_el_gasto_permitido(correr_hook, vault_tmp, cmd):
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("allow", ""), cmd


def test_write_fuera_del_vault_no_afectado(correr_hook, vault_tmp, tmp_path):
    for ruta in (tmp_path / "otro" / "costes.csv", tmp_path / "config" / "producto.yaml"):
        assert correr_hook("apimart_gasto", _escribir(ruta, "x"), vault_tmp) == ("allow", "")
