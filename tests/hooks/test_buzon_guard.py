import json
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def ev(tool, cwd="/", **inp):
    return {"tool_name": tool, "tool_input": inp, "cwd": cwd}


def noop(id_="P-20261112-001", **c):
    d = {"version": 1, "id": id_, "tipo": "noop", "creada": "2026-11-12T10:00:00-05:00",
         "origen": "/probar", "motivo": "prueba"}
    d.update(c)
    return d


@pytest.fixture
def spool(tmp_path):
    s = tmp_path / "spool"
    for sub in ("entrada", "procesadas", "estado"):
        (s / sub).mkdir(parents=True)
    return s


@pytest.fixture
def guardia(correr_hook, vault_tmp, spool):
    def _g(entrada, stop=False):
        if stop:
            (vault_tmp / ".trovefy/STOP").write_text("")
        return correr_hook("buzon_guard", entrada, vault_tmp, env_extra={"TROVEFY_SPOOL": str(spool)})
    return _g


def escribir(spool, nombre, contenido):
    return ev("Write", file_path=str(spool / "entrada" / nombre), content=contenido)


def test_write_nuevo_valido_se_permite(guardia, spool):
    e = escribir(spool, "P-20261112-001.json", json.dumps(noop()))
    assert guardia(e)[0] == "allow"


def test_herramientas_ajenas_se_permiten(guardia):
    assert guardia(ev("Write", file_path="/tmp/x.txt", content="x"))[0] == "allow"
    assert guardia(ev("Bash", command="ls -la"))[0] == "allow"
    assert guardia(ev("Read", file_path="/var/spool/trovefy/x"))[0] == "allow"


def test_no_sobrescribe_ni_edita_ni_borra(guardia, spool):
    (spool / "entrada/P-20261112-001.json").write_text("{}")
    d, m = guardia(escribir(spool, "P-20261112-001.json", json.dumps(noop())))
    assert d == "deny" and "solo archivos nuevos" in m
    p = str(spool / "entrada/P-20261112-001.json")
    assert guardia(ev("Edit", file_path=p, old_string="a", new_string="b"))[0] == "deny"
    assert guardia(ev("MultiEdit", file_path=p, edits=[]))[0] == "deny"
    assert guardia(ev("NotebookEdit", notebook_path=p, new_source="x"))[0] == "deny"
    assert guardia(ev("Bash", command=f"rm {p}"))[0] == "deny"
    assert guardia(ev("Bash", command=f"echo x > {p}"))[0] == "deny"
    assert guardia(ev("Bash", command=f"ls {spool}/entrada"))[0] == "allow"
    assert guardia(ev("Bash", command=f"cat {p}"))[0] == "allow"


def test_esquema_unidad_rango_e_id(guardia, spool):
    assert guardia(escribir(spool, "P-20261112-001.json", json.dumps(noop(extra=1))))[0] == "deny"
    op = {"entidad": "adset", "id": "1", "campo": "daily_budget", "de_esperado": 1, "a": 2,
          "unidad": "centavos", "moneda": "COP"}
    malo = noop(tipo="presupuesto", cuenta="act_0000000000000000", operaciones=[op])
    d, m = guardia(escribir(spool, "P-20261112-001.json", json.dumps(malo)))
    assert d == "deny" and "minima" in m
    d, m = guardia(escribir(spool, "P-20261112-850.json", json.dumps(noop("P-20261112-850"))))
    assert d == "deny" and "799" in m or d == "deny"
    d, m = guardia(escribir(spool, "P-20261112-002.json", json.dumps(noop("P-20261112-003"))))
    assert d == "deny" and "id" in m
    assert guardia(escribir(spool, "nota.json", json.dumps(noop())))[0] == "deny"
    assert guardia(escribir(spool, "P-20261112-001.json", "no json"))[0] == "deny"
    assert guardia(escribir(spool, "P-20261112-001.json", "[]"))[0] == "deny"


def test_procesadas_y_estado_son_de_solo_lectura(guardia, spool):
    for sub in ("procesadas", "estado"):
        e = ev("Write", file_path=str(spool / sub / "P-20261112-001.json"), content=json.dumps(noop()))
        assert guardia(e)[0] == "deny"
    assert guardia(ev("Write", file_path=str(spool / "otro.json"), content="{}"))[0] == "deny"


def test_enlace_simbolico_en_entrada(guardia, spool, tmp_path):
    (spool / "entrada/P-20261112-001.json").symlink_to(tmp_path / "fuera.json")
    e = escribir(spool, "P-20261112-001.json", json.dumps(noop()))
    assert guardia(e)[0] == "deny"


def test_bash_relativo_desde_el_spool(guardia, spool):
    assert guardia(ev("Bash", cwd=str(spool / "entrada"), command="rm P-20261112-001.json"))[0] == "deny"
    assert guardia(ev("Bash", cwd=str(spool / "entrada"), command="ls"))[0] == "allow"
    assert guardia(ev("Bash", command=f"cd {spool}/entrada && rm x"))[0] == "deny"


def test_stop_deniega_depositar(guardia, spool):
    e = escribir(spool, "P-20261112-001.json", json.dumps(noop()))
    d, m = guardia(e, stop=True)
    assert d == "deny" and "STOP activo: no se deposita nada" in m
    assert guardia(ev("Bash", command="trovefy buzon depositar x.json"), stop=True)[0] == "deny"
    assert guardia(ev("Bash", command=f"ls {spool}/entrada"), stop=True)[0] == "allow"


def test_depositar_sin_stop(guardia):
    assert guardia(ev("Bash", command="trovefy buzon depositar x.json"))[0] == "allow"


def test_json_de_hook_roto_deniega(correr_hook, vault_tmp, spool):
    assert correr_hook("buzon_guard", "{", vault_tmp, env_extra={"TROVEFY_SPOOL": str(spool)})[0] == "deny"


def test_sin_esquema_importable_deniega(spool, tmp_path):
    import os
    import shutil
    import subprocess

    copia = tmp_path / "plugin" / "hooks"
    copia.mkdir(parents=True)
    for n in ("buzon_guard.py", "_comun.py"):
        shutil.copy(RAIZ / "hooks" / n, copia / n)  # sin scripts/ al lado: el esquema no se puede importar
    e = escribir(spool, "P-20261112-001.json", json.dumps(noop()))
    proc = subprocess.run(["python3", "-S", str(copia / "buzon_guard.py")], input=json.dumps(e), capture_output=True,
                          text=True, check=False, timeout=30,
                          env={"PATH": os.environ.get("PATH", ""), "TROVEFY_SPOOL": str(spool),
                               "TROVEFY_VAULT": str(tmp_path / "v")})
    assert proc.returncode == 0 and "deny" in proc.stdout and "esquema" in proc.stdout
