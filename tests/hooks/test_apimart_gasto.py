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


def test_webfetch_apimart_denegado(correr_hook, vault_tmp):
    for url in ("https://api.apimart.ai/v1/balance", "https://APIMART.AI/x", "https://docs.apimart.ai/llms.txt"):
        entrada = {"tool_name": "WebFetch", "tool_input": {"url": url, "prompt": "x"}}
        assert correr_hook("apimart_gasto", entrada, vault_tmp) == ("deny", MOTIVO)
    entrada = {"tool_name": "WebFetch", "tool_input": {"url": "https://notapimart.ai.example.com/", "prompt": "x"}}
    assert correr_hook("apimart_gasto", entrada, vault_tmp) == ("allow", "")


def test_json_roto_deny(correr_hook, vault_tmp):
    decision, _ = correr_hook("apimart_gasto", "{roto", vault_tmp)
    assert decision == "deny"


def test_otros_comandos_allow(correr_hook, vault_tmp):
    for entrada in (_bash("ls -la"), _bash("curl https://example.com"),
                    {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}},
                    {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}):
        assert correr_hook("apimart_gasto", entrada, vault_tmp) == ("allow", "")
