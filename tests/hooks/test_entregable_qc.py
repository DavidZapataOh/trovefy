"""M3 (revisión de las Tareas 11–12, plan 17): QC.md, su cerrojo y los PDF del entregable.

Solo los escribe `trovefy producto` (anotar-qc, maquetar, qc). Claude no los escribe a mano ni por Bash:
un veredicto o un PDF falsos harían pasar el cierre. Leerlos sigue permitido. Por ruta resuelta, como el
libro de gasto (``apimart_gasto``).
"""
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
P = "p-0042-respira"
MOTIVO_QC = ("QC.md, su cerrojo y los PDF del entregable solo los escribe `trovefy producto` (maquetar, qc, "
             "anotar-qc): no se editan, crean, mueven ni borran a mano")


@pytest.fixture
def mundo(vault_tmp):
    ent = vault_tmp / "productos" / P / "entregable"
    bono = ent / "bonos" / "bono-1"
    bono.mkdir(parents=True)
    (ent / "QC.md").write_text("---\ntipo: qc\n---\n", encoding="utf-8")
    (ent / ".QC.md.lock").write_text("", encoding="utf-8")
    (ent / "respira-es-v1.pdf").write_bytes(b"%PDF-1.7\n")
    (bono / "QC.md").write_text("---\ntipo: qc\n---\n", encoding="utf-8")
    (bono / "respira-bono-1-es-v1.pdf").write_bytes(b"%PDF-1.7\n")
    (ent / "fuente" / "secciones").mkdir(parents=True)
    return {"v": vault_tmp, "E": ent, "B": bono}


@pytest.fixture
def decide(correr_hook, mundo):
    def _decide(tool, datos, cwd=None):
        entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(cwd or RAIZ)}
        return correr_hook("apimart_gasto", entrada, mundo["v"])
    return _decide


def _fmt(texto, m):
    return texto.format(v=m["v"], E=m["E"], B=m["B"])


@pytest.mark.parametrize("tool,datos", [
    ("Write", {"file_path": "{E}/QC.md", "content": "## v1 · revisor · 2026-11-16 10:00\n- veredicto: ok\n"}),
    ("Write", {"file_path": "{B}/QC.md", "content": "x"}),
    ("Write", {"file_path": "{E}/fuente/../QC.md", "content": "x"}),
    ("Write", {"file_path": "{E}/upsells/u1/QC.md", "content": "x"}),
    ("Edit", {"file_path": "{E}/QC.md", "old_string": "tipo: qc", "new_string": "tipo: qc\n"}),
    ("MultiEdit", {"file_path": "{B}/QC.md", "edits": [{"old_string": "qc", "new_string": "x"}]}),
    ("Write", {"file_path": "{E}/.QC.md.lock", "content": ""}),
    ("Write", {"file_path": "{E}/respira-es-v2.pdf", "content": "%PDF"}),
    ("Write", {"file_path": "{B}/respira-bono-1-es-v1.pdf", "content": "%PDF"}),
    ("Edit", {"file_path": "{E}/respira-es-v1.pdf", "old_string": "%PDF", "new_string": "x"}),
    ("Write", {"file_path": "{v}//productos/p-0042-respira/./entregable/QC.md", "content": "x"}),
])
def test_write_y_edit_denegados(decide, mundo, tool, datos):
    datos = {k: _fmt(v, mundo) if isinstance(v, str) else v for k, v in datos.items()}
    assert decide(tool, datos) == ("deny", MOTIVO_QC), datos


@pytest.mark.parametrize("cmd,cwd", [
    ("echo '- veredicto: ok' >> {E}/QC.md", None),
    ("cat /tmp/qc > {B}/QC.md", None),
    ("cd {E} && printf x > QC.md", None),
    ("sed -i 's/corregir/ok/' QC.md", "{E}"),
    ("cp /tmp/x.pdf {E}/respira-es-v2.pdf", None),
    ("cp /tmp/QC.md {B}/", None),
    ("mv /tmp/a.pdf {E}/respira-es-v1.pdf", None),
    ("rm {E}/respira-es-v1.pdf", None),
    ("rm {B}/*.pdf", None),
    ("rm .QC.md.lock", "{E}"),
    ("tee {E}/QC.md < /tmp/x", None),
    ("touch {E}/upsells/u1/respira-u1-es-v1.pdf", None),
    ("python3 -c \"open('{E}/QC.md','a').write('x')\"", None),
    ("mv {E}/QC.md /tmp/", None),
    ("truncate -s 0 {B}/QC.md", None),
])
def test_bash_denegado(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


@pytest.mark.parametrize("tool,datos", [
    ("Read", {"file_path": "{E}/QC.md"}),
    ("Read", {"file_path": "{E}/respira-es-v1.pdf"}),
    ("Grep", {"pattern": "veredicto", "path": "{E}"}),
    ("Write", {"file_path": "{E}/fuente/secciones/01-respirar.html", "content": "<h2>x</h2>"}),
    ("Write", {"file_path": "{E}/PLAN.md", "content": "x"}),
    ("Write", {"file_path": "{E}/imagenes.yaml", "content": "[]"}),
    ("Write", {"file_path": "{v}/wiki/notas/QC.md", "content": "x"}),
    ("Write", {"file_path": "{v}/productos/p-0042-respira/informe.pdf", "content": "x"}),
])
def test_lectura_y_fragmentos_permitidos(decide, mundo, tool, datos):
    datos = {k: _fmt(v, mundo) for k, v in datos.items()}
    assert decide(tool, datos) == ("allow", ""), datos


@pytest.mark.parametrize("cmd", [
    "cat {E}/QC.md",
    "pdfinfo {E}/respira-es-v1.pdf",
    "pdftoppm -r 40 -png -f 1 -l 1 {E}/respira-es-v1.pdf /tmp/p",
    "cp {E}/respira-es-v1.pdf /tmp/",
    "trovefy producto maquetar p-0042-respira --pieza principal",
    "trovefy producto anotar-qc p-0042-respira --pieza principal --version 1 --agente revisor < /tmp/r.txt",
])
def test_bash_legitimo(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}) == ("allow", ""), cmd
