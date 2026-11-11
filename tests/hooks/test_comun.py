def test_entrada_ilegible_deniega(correr_hook, vault_tmp):
    for mala in ["", "{no es json", '"una cadena"', '{"tool_name": "Write", "tool_input": 3}']:
        decision, motivo = correr_hook("meta_guard", mala, vault_tmp)
        assert decision == "deny" and "ilegible" in motivo


def test_hook_que_explota_deniega(correr_hook, vault_tmp):
    # _prueba_explota.py es un hook de prueba cuyo decidir() lanza RuntimeError
    decision, motivo = correr_hook("_prueba_explota", {"tool_name": "Read", "tool_input": {}}, vault_tmp)
    assert decision == "deny" and "fallo interno" in motivo


import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "hooks"))
import _comun


def _entrada(modo):
    return {"tool_name": modo, "tool_input": {}}


@pytest.mark.parametrize("modo", ["salir0", "salir1", "interrupcion"])
def test_baseexception_en_decidir_deniega(correr_hook, vault_tmp, modo):
    decision, motivo = correr_hook("_prueba_modos", _entrada(modo), vault_tmp)
    assert decision == "deny" and "fallo interno" in motivo


def test_fallo_interno_escribe_diagnostico_en_stderr(correr_hook_crudo, vault_tmp):
    proc = correr_hook_crudo("_prueba_modos", _entrada("salir0"), vault_tmp)
    assert proc.returncode == 0 and "SystemExit" in proc.stderr


@pytest.mark.parametrize("modo", ["decision_invalida", "motivo_no_str"])
def test_decision_invalida_deniega(correr_hook, vault_tmp, modo):
    decision, motivo = correr_hook("_prueba_modos", _entrada(modo), vault_tmp)
    assert decision == "deny" and "fallo interno" in motivo


def test_allow_limpio(correr_hook_crudo, vault_tmp):
    proc = correr_hook_crudo("_prueba_modos", _entrada("allow"), vault_tmp)
    assert proc.returncode == 0 and proc.stdout == ""


def test_deny_limpio(correr_hook, vault_tmp):
    assert correr_hook("_prueba_modos", _entrada("deny"), vault_tmp) == ("deny", "no permitido")


def test_fallo_al_emitir_sale_con_codigo_2(correr_hook_crudo, vault_tmp):
    proc = correr_hook_crudo("_prueba_modos", _entrada("stdout_cerrado"), vault_tmp)
    assert proc.returncode == 2
    assert "no se pudo emitir" in proc.stderr
    assert proc.stdout == ""


def test_deny_fijo_es_json_valido():
    salida = json.loads(_comun._DENY_FIJO)["hookSpecificOutput"]
    assert salida["permissionDecision"] == "deny"


def test_resolver_punto_punto_y_relativa(tmp_path):
    (tmp_path / "a").mkdir()
    assert _comun.resolver("a/../b.txt", str(tmp_path)) == (tmp_path / "b.txt").resolve()
    assert _comun.resolver(str(tmp_path / "a" / ".." / "c"), None) == (tmp_path / "c").resolve()


def test_resolver_enlace_simbolico(tmp_path):
    destino = tmp_path / "real"
    destino.mkdir()
    (tmp_path / "enlace").symlink_to(destino)
    assert _comun.resolver("enlace/x.md", str(tmp_path)) == destino.resolve() / "x.md"


def test_stop_activo(vault_tmp):
    assert not _comun.stop_activo(vault_tmp)
    (vault_tmp / ".trovefy" / "STOP").write_text("", encoding="utf-8")
    assert _comun.stop_activo(vault_tmp)


def test_herramienta():
    assert _comun.herramienta({"tool_name": "Read", "tool_input": {"a": 1}}) == ("Read", {"a": 1})
    for mala in [{"tool_name": "Read", "tool_input": 3}, {"tool_input": {}}, {"tool_name": 5, "tool_input": {}}]:
        with pytest.raises(_comun.EntradaIlegible):
            _comun.herramienta(mala)
