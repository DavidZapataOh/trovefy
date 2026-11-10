"""Fixtures comunes para probar los hooks de Claude Code como procesos reales."""
import json
import os
import pathlib
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def vault_tmp(tmp_path):
    vault = tmp_path / "vault"
    for sub in ("raw", "wiki", ".trovify"):
        (vault / sub).mkdir(parents=True)
    (vault / "log.md").write_text("# Log\n", encoding="utf-8")
    return vault


@pytest.fixture
def correr_hook_crudo():
    """Ejecuta el hook y devuelve el CompletedProcess sin interpretar."""

    def _correr(nombre, entrada, vault, env_extra=None):
        script = RAIZ / "hooks" / f"{nombre}.py"
        if not script.exists():
            script = RAIZ / "tests" / "hooks" / f"{nombre}.py"
        assert script.exists(), f"no existe el hook {nombre}"
        cuerpo = entrada if isinstance(entrada, str) else json.dumps(entrada)
        entorno = {
            "TROVIFY_VAULT": str(vault),
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ.get("PATH", ""),
            **(env_extra or {}),
        }
        return subprocess.run(
            ["python3", str(script)],
            input=cuerpo, capture_output=True, text=True,
            env=entorno, cwd=RAIZ, timeout=30, check=False,
        )

    return _correr


@pytest.fixture
def correr_hook(correr_hook_crudo):
    def _correr(nombre, entrada, vault, env_extra=None):
        proc = correr_hook_crudo(nombre, entrada, vault, env_extra)
        assert proc.returncode == 0, f"código {proc.returncode}: {proc.stderr}"
        if not proc.stdout.strip():
            return ("allow", "")
        salida = json.loads(proc.stdout)["hookSpecificOutput"]
        assert salida["permissionDecision"] == "deny", salida
        return ("deny", salida["permissionDecisionReason"])

    return _correr
