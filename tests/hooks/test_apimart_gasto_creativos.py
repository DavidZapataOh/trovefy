"""Hook apimart_gasto y las tandas de creativos (plan 21, Tarea 4)."""

import pytest


def _bash(cmd, cwd="/tmp"):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}


def _write(ruta):
    return {"tool_name": "Write", "tool_input": {"file_path": str(ruta), "content": "x"}}


TANDA = "productos/p-0099-prueba-abc123/creativos/ZZ/t1"


def test_trovefy_creativos_puede_llamar_apimart(correr_hook, vault_tmp):
    for cmd in (("trovefy creativos escenas --producto p-0099-prueba-abc123 --pais ZZ --tanda t1 --base "
                 "https://api.apimart.ai"), "uv run trovefy creativos voz --base https://api.apimart.ai"):
        assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp) == ("allow", ""), cmd


def test_libro_creativos_protegido(correr_hook, vault_tmp):
    libro = "costes" + ".csv"
    decision, _ = correr_hook("apimart_gasto", _bash(f"echo x > {vault_tmp}/{TANDA}/{libro}"), vault_tmp)
    assert decision == "deny"
    assert correr_hook("apimart_gasto", _write(vault_tmp / TANDA / libro), vault_tmp)[0] == "deny"
    assert correr_hook("apimart_gasto", _write(vault_tmp / TANDA / ".apimart-intentos.jsonl"), vault_tmp)[0] == "deny"


@pytest.mark.parametrize("nombre", ["QA.md", "manifest.csv", "TANDA.md", "medios.json"])
def test_qa_y_manifest_creativos_protegidos(correr_hook, vault_tmp, nombre):
    assert correr_hook("apimart_gasto", _write(vault_tmp / TANDA / nombre), vault_tmp)[0] == "deny"
    cmd = f"echo x > {vault_tmp}/{TANDA}/{nombre}"
    assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny"


def test_claude_escribe_brief_escenas_y_guiones(correr_hook, vault_tmp):
    for rel in ("brief.yaml", "escenas.yaml", "guiones/AD01.yaml"):
        assert correr_hook("apimart_gasto", _write(vault_tmp / TANDA / rel), vault_tmp) == ("allow", ""), rel


def test_rm_r_tanda_denegado(correr_hook, vault_tmp):
    (vault_tmp / TANDA).mkdir(parents=True)
    for cmd in (f"rm -r {vault_tmp}/{TANDA}", f"mv {vault_tmp}/productos/p-0099-prueba-abc123/creativos /tmp/x",
                f"rm -rf {vault_tmp}/productos/p-0099-prueba-abc123"):
        assert correr_hook("apimart_gasto", _bash(cmd), vault_tmp)[0] == "deny", cmd


def test_tope_y_config_de_creativos_protegidos(correr_hook, vault_tmp):
    decision = vault_tmp / "productos/p-0099-prueba-abc123/decisiones/2026-11-20-100000-tope-creativos-ZZ-t1.md"
    assert correr_hook("apimart_gasto", _write(decision), vault_tmp)[0] == "deny"
    assert correr_hook("apimart_gasto", _write(vault_tmp / "config/creativos.yaml"), vault_tmp)[0] == "deny"
