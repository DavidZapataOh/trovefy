import json
import pathlib
import subprocess
import sys
from datetime import date

HOOK = pathlib.Path(__file__).resolve().parents[2] / "hooks/cierre_sesion.py"
HOY = date.today().isoformat()
LINEA = f"- {HOY} 10:00 COT · cazar · x ·  · tokens: —\n"


def correr(vault, entrada='{"hook_event_name": "Stop"}'):
    r = subprocess.run([sys.executable, str(HOOK)], check=False, input=entrada, capture_output=True, text=True,
                       env={"TROVIFY_VAULT": str(vault), "PATH": "/usr/bin:/bin"})
    return r.returncode, r.stdout + r.stderr


def test_recuerda_cerrar_si_hubo_trabajo(tmp_path):
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "log.md").write_text(LINEA)
    code, salida = correr(tmp_path)
    assert code == 0 and "/trovify:cerrar" in salida
    assert "systemMessage" in json.loads(salida)


def test_no_molesta_si_ya_se_cerro(tmp_path):
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "log.md").write_text(LINEA)
    (tmp_path / f"sesiones/{HOY}-1800.md").write_text("x")
    assert "/trovify:cerrar" not in correr(tmp_path)[1]


def test_silencioso_sin_trabajo_hoy_o_sin_vault(tmp_path):
    (tmp_path / "log.md").write_text("- 2020-01-01 10:00 COT · x\n")
    assert correr(tmp_path) == (0, "")
    assert correr(tmp_path / "no-existe") == (0, "")
    assert correr(tmp_path, "basura")[0] == 0


def test_solo_lee_la_cola_del_log(tmp_path):
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "log.md").write_text("- 2020-01-01 relleno\n" * 20000 + LINEA)
    assert "/trovify:cerrar" in correr(tmp_path)[1]
