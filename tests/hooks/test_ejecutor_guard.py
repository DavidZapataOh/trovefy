"""M7 (revisión T6–10): Claude nunca cambia límites ni estado del ejecutor; eso lo hace el usuario en su terminal."""
import pytest

EJ = "/home/trovefy-exec/.local/bin/trovefy-ejecutor"


def _bash(comando: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": comando}}


@pytest.mark.parametrize("comando", [
    f"sudo -u trovefy-exec {EJ} permitir --dataset 1111111111111111",
    f"sudo -u trovefy-exec {EJ} comprobar-dataset 1111111111111111 --pagina 2222",
    "sudo -u trovefy-exec true",
    "sudo -n -u trovefy-exec ls",
    "sudo --user=trovefy-exec id",
    "sudo -iu trovefy-exec",
    "su - trovefy-exec -c 'trovefy-ejecutor estado'",
    "runuser -u trovefy-exec -- ls",
    "trovefy-ejecutor permitir --pagina 2222",
    "trovefy-ejecutor reanudar --si",
    "trovefy-ejecutor emparejar --reiniciar",
    "trovefy-ejecutor servir",
    "trovefy-ejecutor auditoria reparar",
    "trovefy-ejecutor comprobar-meta",
    "trovefy-ejecutor comprobar-dataset 1111111111111111",
    f"{EJ} permitir --dataset 1",
    "python3 -m trovefy_ejecutor permitir --dataset 1",
    "uv run python -m trovefy_ejecutor.cli reanudar --si",
    "ls && trovefy-ejecutor 'permitir' --dataset 1",
    "echo x | trovefy-ejecutor reanudar",
])
def test_deniega_cambios_del_ejecutor(correr_hook, vault_tmp, comando):
    decision, motivo = correr_hook("ejecutor_guard", _bash(comando), vault_tmp)
    assert decision == "deny", comando
    assert "terminal" in motivo


@pytest.mark.parametrize("comando", [
    "trovefy-ejecutor estado",
    "trovefy-ejecutor limites",
    "trovefy-ejecutor stop se acabó",
    "trovefy-ejecutor --help",
    "trovefy tracking ejecutor --producto p-0099-prueba-abc123 --pais ZZ",
    "uv run pytest -q tests/ejecutor/test_cli_permitir.py",
    "grep -rn permitir scripts/trovefy_ejecutor/cli.py",
    "ls -la",
])
def test_deja_pasar_lecturas_y_desarrollo(correr_hook, vault_tmp, comando):
    assert correr_hook("ejecutor_guard", _bash(comando), vault_tmp)[0] == "allow", comando


def test_solo_bash(correr_hook, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.md", "content": "sudo -u trovefy-exec permitir"}}
    assert correr_hook("ejecutor_guard", e, vault_tmp)[0] == "allow"


def test_entrada_rota_falla_cerrado(correr_hook_crudo, vault_tmp):
    proc = correr_hook_crudo("ejecutor_guard", "no es json", vault_tmp)
    assert proc.returncode == 2 or "deny" in proc.stdout
