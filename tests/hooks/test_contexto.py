import json
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parents[2] / "hooks/contexto.py"


def correr(vault, entrada=None):
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(entrada or {"hook_event_name": "SessionStart", "cwd": "/"}),
        capture_output=True,
        check=False,
        text=True,
        env={"TROVIFY_VAULT": str(vault), "PATH": "/usr/bin:/bin"},
    )
    return r


def ctx_de(r):
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_contexto_con_stop_y_producto(tmp_path):
    (tmp_path / ".trovify").mkdir()
    (tmp_path / ".trovify/STOP").write_text("")
    (tmp_path / "index.md").write_text("# Índice\n- [[wiki/reglas/R-001-vara-de-caza]]\n")
    p = tmp_path / "productos/p-0001-trusa"
    p.mkdir(parents=True)
    (p / "PRODUCTO.md").write_text("---\nestado: TEST\n---\n")
    r = correr(tmp_path)
    ctx = ctx_de(r)
    assert r.returncode == 0 and "STOP activo" in ctx and "p-0001-trusa" in ctx and "R-001" in ctx
    assert json.loads(r.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_contexto_sin_vault(tmp_path):
    r = correr(tmp_path / "no-existe")
    assert r.returncode == 0 and r.stdout.strip() == "" and r.stderr == ""


def test_sin_stop_ni_propuestas(tmp_path):
    (tmp_path / "index.md").write_text("# I\n")
    ctx = ctx_de(correr(tmp_path))
    assert "STOP activo" not in ctx


def test_propuestas_pendientes_y_estado_anidado(tmp_path):
    (tmp_path / "propuestas").mkdir()
    (tmp_path / "propuestas/a.md").write_text("---\nestado: pendiente\n---\n")
    (tmp_path / "propuestas/b.md").write_text("---\nestado: aprobada\n---\n")
    for nombre, fm in {
        "p-1-viva": "paises:\n  CO:\n    estado: ESCALA\n",
        "p-2-muerta": "estado: MUERTO\n",
        "p-3-fuera": "x: 1\n---\nestado: TEST\n",
    }.items():
        d = tmp_path / "productos" / nombre
        d.mkdir(parents=True)
        (d / "PRODUCTO.md").write_text("---\n" + fm + ("" if "---" in fm else "---\n"))
    ctx = ctx_de(correr(tmp_path))
    assert "a.md" in ctx and "b.md" not in ctx
    assert "p-1-viva" in ctx and "p-2-muerta" not in ctx and "p-3-fuera" not in ctx


def test_ultimo_traspaso(tmp_path):
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "sesiones/2026-01-01-a.md").write_text("x")
    (tmp_path / "sesiones/2026-02-01-b.md").write_text("x")
    ctx = ctx_de(correr(tmp_path))
    assert "2026-02-01-b.md" in ctx and "2026-01-01-a.md" not in ctx


def test_indice_limitado_a_40_lineas_y_total_acotado(tmp_path):
    (tmp_path / "index.md").write_text("\n".join(f"L{i:03d} " + "x" * 30 for i in range(500)))
    ctx = ctx_de(correr(tmp_path))
    assert "L039" in ctx and "L040" not in ctx


def test_contexto_total_acotado_y_no_tapa_stop(tmp_path):
    (tmp_path / ".trovify").mkdir()
    (tmp_path / ".trovify/STOP").write_text("")
    (tmp_path / "index.md").write_text("\n".join("y" * 5000 for _ in range(100)))
    (tmp_path / "propuestas").mkdir()
    for i in range(300):
        (tmp_path / f"propuestas/prop-{i:03d}-{"z" * 50}.md").write_text("---\nestado: pendiente\n---\n")
    ctx = ctx_de(correr(tmp_path))
    assert len(ctx) <= 4000 and "STOP activo" in ctx


def test_nunca_falla_con_entrada_basura(tmp_path):
    (tmp_path / "index.md").write_bytes(b"\xff\xfe\x00bad")
    r = subprocess.run(
        [sys.executable, str(HOOK)], input="no json", capture_output=True, text=True, check=False,
        env={"TROVIFY_VAULT": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert r.returncode == 0 and "Traceback" not in r.stderr


def test_registrado_en_session_start():
    raiz = HOOK.parents[1]
    reg = json.loads((raiz / "hooks/hooks.json").read_text())
    cmds = [h["command"] for g in reg["hooks"]["SessionStart"] for h in g["hooks"]]
    assert cmds == ['python3 "${CLAUDE_PLUGIN_ROOT}/hooks/contexto.py"']


def test_indice_enorme_rapido(tmp_path):
    import time

    with (tmp_path / "index.md").open("w") as f:
        for i in range(50000):
            f.write(f"L{i:05d} {'x' * 20}\n")
    t = time.monotonic()
    ctx = ctx_de(correr(tmp_path))
    assert "L00039" in ctx and "L00040" not in ctx
    assert time.monotonic() - t < 2


def test_producto_con_cuerpo_enorme_detecta_estado(tmp_path):
    d = tmp_path / "productos/p-9-grande"
    d.mkdir(parents=True)
    with (d / "PRODUCTO.md").open("w") as f:
        f.write("---\nestado: ESCALA\n---\n")
        f.write("cuerpo\n" * 100000)
    assert "p-9-grande" in ctx_de(correr(tmp_path))


def test_nombres_largos_no_tapan_ultimas_secciones(tmp_path):
    (tmp_path / "index.md").write_text("\n".join("i" * 200 for _ in range(40)))
    (tmp_path / "propuestas").mkdir()
    for i in range(20):
        n = f"prop-{i:02d}-{'z' * 200}.md"
        (tmp_path / "propuestas" / n).write_text("---\nestado: pendiente\n---\n")
    d = tmp_path / "productos/p-1-ultimo"
    d.mkdir(parents=True)
    (d / "PRODUCTO.md").write_text("---\nestado: TEST\n---\n")
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "sesiones/2026-03-03-fin.md").write_text("x")
    ctx = ctx_de(correr(tmp_path))
    assert "p-1-ultimo" in ctx and "2026-03-03-fin.md" in ctx and len(ctx) <= 4000


def test_timeout_en_hooks_json():
    reg = json.loads((HOOK.parents[1] / "hooks/hooks.json").read_text())
    assert reg["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 5
