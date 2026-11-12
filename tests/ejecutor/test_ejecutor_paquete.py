import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from trovefy_ejecutor.config import rutas_por_defecto

RAIZ = Path(__file__).resolve().parents[2]
PAQ = RAIZ / "scripts/trovefy_ejecutor"


def test_pyproject_declara_paquete_y_entrada():
    d = tomllib.loads((RAIZ / "pyproject.toml").read_text())
    assert "scripts/trovefy_ejecutor" in d["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert d["project"]["scripts"]["trovefy-ejecutor"] == "trovefy_ejecutor.cli:main"


def test_solo_stdlib_y_yaml_y_nunca_trovefy():
    permitidos = set(sys.stdlib_module_names) | {"yaml", "trovefy_ejecutor"}
    for f in PAQ.rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            mods = (
                [a.name for a in n.names]
                if isinstance(n, ast.Import)
                else [n.module]
                if isinstance(n, ast.ImportFrom) and n.level == 0
                else []
            )
            for m in mods:
                assert m.split(".")[0] in permitidos, (f.name, m)


def test_modulos_importables_sin_yaml():
    # resolución 15: esquema, modelo, dinero y auditoria no cargan PyYAML al importarse
    codigo = (
        "import sys; sys.modules['yaml'] = None; "
        "import trovefy_ejecutor.esquema, trovefy_ejecutor.modelo, "
        "trovefy_ejecutor.dinero, trovefy_ejecutor.auditoria"
    )
    r = subprocess.run(
        [sys.executable, "-c", codigo],
        check=False,
        env={**os.environ, "PYTHONPATH": str(RAIZ / "scripts")},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_rutas_de_5_1():
    r = rutas_por_defecto({})
    assert str(r.limites) == "/home/trovefy-exec/.config/trovefy-ejecutor/limites.yaml"
    assert str(r.base) == "/home/trovefy-exec/.local/share/trovefy-ejecutor/estado.sqlite"
    assert str(r.spool) == "/var/spool/trovefy" and r.vault is None


def test_rutas_redirigibles(tmp_path):
    r = rutas_por_defecto({"TROVEFY_EJECUTOR_HOME": str(tmp_path), "TROVEFY_SPOOL": str(tmp_path / "s")})
    assert r.stop.is_relative_to(tmp_path) and r.spool == tmp_path / "s"
