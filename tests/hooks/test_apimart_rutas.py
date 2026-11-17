"""Segunda ronda de apimart_gasto: protección por ruta resuelta (rulings de progress.md, plan 17).

Cada caso de denegación sale de un rodeo que encontró la revisión (probe.py, e2e.py, st.py). Los
hooks se ejecutan como procesos reales con ``python3`` (sin PyYAML: rama de reserva del hook) y,
para la comparación del tope, también en el proceso de pytest (con PyYAML).
"""
import importlib.util
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
P = "p-0042-respira"
PRODUCTO = f"---\nid: {P}\napimart_tope_usd: '2.00'\ntitulo: X\n---\nCuerpo\n"
DECISION = "2026-11-14-100000-tope-apimart.md"


@pytest.fixture
def mundo(vault_tmp, tmp_path):
    """Vault con un producto, su libro de gasto, una decisión de tope, config y STOP; HOME de prueba."""
    prod = vault_tmp / "productos" / P
    (prod / "entregable").mkdir(parents=True)
    (prod / "decisiones").mkdir()
    (prod / "PRODUCTO.md").write_text(PRODUCTO, encoding="utf-8")
    (prod / "entregable" / "costes.csv").write_text("fecha\n", encoding="utf-8")
    (prod / "entregable" / ".apimart-intentos.jsonl").write_text("{}\n", encoding="utf-8")
    (prod / "decisiones" / DECISION).write_text("---\ncita: x\n---\n", encoding="utf-8")
    (vault_tmp / "config").mkdir()
    (vault_tmp / "config" / "producto.yaml").write_text("apimart: {}\n", encoding="utf-8")
    (vault_tmp / ".trovefy" / "STOP").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".config" / "trovefy").mkdir(parents=True)
    (home / ".config" / "trovefy" / "claude.env").write_text("APIMART_API_KEY=prueba\n", encoding="utf-8")
    return {"v": vault_tmp, "P": prod, "home": home}


@pytest.fixture
def decide(correr_hook, mundo):
    def _decide(tool, datos, cwd=None):
        entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(cwd or RAIZ)}
        return correr_hook("apimart_gasto", entrada, mundo["v"], {"HOME": str(mundo["home"])})
    return _decide


def _fmt(cmd, m):
    return cmd.format(v=m["v"], P=m["P"], home=m["home"])


# --- H-A: decisiones de tope y PRODUCTO.md por Bash ---------------------------------------------------

@pytest.mark.parametrize("cmd", [
    ("cat > {P}/decisiones/2099-01-01-000000-tope-apimart.md <<'X'\n---\nproducto: p-0042-respira\n"
     "tope_nuevo_usd: '50'\ncita: ok\n---\nX"),
    "cp /tmp/d.md {P}/decisiones/2099-01-01-000000-tope-apimart.md",
    "mv /tmp/d.md {P}/decisiones/2099-01-01-000000-tope-apimart.md",
    "echo x | tee {P}/decisiones/2099-01-01-000000-tope-apimart.md",
    "cd {P}/decisiones && echo x > 2099-01-01-000000-tope-apimart.md",
    "cd {P} && cat /tmp/d > decisiones/2099-01-01-000000-tope-apimart.md",
    "sed -i s/50/500/ {P}/decisiones/" + DECISION,
    "cp /tmp/d.md {P}/decisiones/*-tope-apimart.md",
    "cp /tmp/2099-01-01-000000-tope-apimart.md {P}/decisiones/",
    "rm {P}/decisiones/*.md",
    "rm -rf {P}/decisiones",
    "python3 -c \"open('{P}/decisiones/2099-01-01-000000-tope-apimart.md','w')\"",
    "cp /tmp/d.md {v}//productos/p-0042-respira/./decisiones/2099-01-01-000000-tope-apimart.md",
])
def test_bash_no_crea_decisiones_de_tope(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)})[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "sed -i 's/2.00/50.00/' {P}/PRODUCTO.md",
    "sed -i 's/tope_usd: .2.00./tope_usd: 50/' {P}/PRODUCTO.md",
    "sed -i 's/apimart_tope_usd: .*/apimart_tope_usd: 50/' {P}/PRODUCTO.md",
    "cd {P} && sed -i '3s/.*/x/' PRODUCTO.md",
    "sed -i 's/titulo: X/apim\\x61rt_t\\x6fpe_usd: 50/' {P}/PRODUCTO.md",
    "echo 'apimart_tope_usd: 50' >> {P}/PRODUCTO.md",
    "cat /tmp/x > {P}/PRODUCTO.md",
    "cp /tmp/x {P}/PRODUCTO.md",
    "printf 'x' | tee {P}/PRODUCTO.md",
    "perl -pi -e 's/2/50/' {P}/PRODUCTO.md",
    "python3 -c \"import pathlib; pathlib.Path('{P}/PRODUCTO.md').write_text('x')\"",
    "sed -i 's/2.00/50/' {P}/PRODUC*.md",
])
def test_bash_no_cambia_el_tope_de_producto(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)})[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "sed -i 's/titulo: X/titulo: Y/' {P}/PRODUCTO.md",
    "cat {P}/PRODUCTO.md",
    "grep -n tope {P}/PRODUCTO.md",
    "echo 'Nota al final' >> {P}/PRODUCTO.md",
    "cat {P}/PRODUCTO.md > /tmp/copia.md",
])
def test_bash_legitimo_sobre_producto(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}) == ("allow", ""), cmd


# --- H-A: el tope de PRODUCTO.md se compara ya parseado ------------------------------------------------

def _w(m, contenido):
    return {"file_path": str(m["P"] / "PRODUCTO.md"), "content": contenido}


CAMBIOS_DEL_TOPE = [
    f"---\nid: {P}\napimart_tope_usd: '50'\n---\n",
    f"---\nid: {P}\napimart_tope_usd:  '2.00'\napimart_tope_usd: '50'\n---\n",
    f"---\nid: {P}\n\"apimart_tope_usd\": '50'\napimart_tope_usd: '2.00'\n---\n",
    f"---\nid: {P}\n'apimart_tope_usd': '50'\ntitulo: X\n---\n",
    f"---\nid: {P}\n? apimart_tope_usd\n: '50'\n---\napimart_tope_usd: '2.00'\n",
    f"---\n{{id: {P}, apimart_tope_usd: '50'}}\n---\napimart_tope_usd: '2.00'\n",
    f"---\nid: {P}\n<<: {{apimart_tope_usd: '50'}}\n---\n",
    f"---\nid: {P}\n\"apimart\\x5ftope_usd\": '50'\n---\n",
    f"---\nid: {P}\ntitulo: X\n---\n",  # quitar la clave también cambia el tope
    f"---\nid: {P}\napimart_tope_usd: |\n  50\n---\n",
]
MISMO_TOPE = [
    f"---\nid: {P}\napimart_tope_usd: '2.00'\ntitulo: Y\n---\nOtro cuerpo\n",
    f"---\nid: {P}\napimart_tope_usd: \"2.00\"\ntitulo: X\n---\nCuerpo\n",
    f"---\nid: {P}\napimart_tope_usd: 2.00\ntitulo: X\n---\nCuerpo\n",
    f"---\nid: {P}\napimart_tope_usd: '2.00'  # sin cambios\ntitulo: X\nnueva: 1\n---\nCuerpo\n",
]


@pytest.mark.parametrize("contenido", CAMBIOS_DEL_TOPE)
def test_write_que_cambia_el_tope_parseado(decide, mundo, contenido):
    assert decide("Write", _w(mundo, contenido))[0] == "deny", contenido


@pytest.mark.parametrize("contenido", MISMO_TOPE)
def test_write_con_el_mismo_tope_permitido(decide, mundo, contenido):
    assert decide("Write", _w(mundo, contenido)) == ("allow", ""), contenido


def test_edit_y_multiedit_de_producto(decide, mundo):
    ruta = str(mundo["P"] / "PRODUCTO.md")
    assert decide("Edit", {"file_path": ruta, "old_string": "titulo: X", "new_string": "titulo: Z"}) == ("allow", "")
    assert decide("Edit", {"file_path": ruta, "old_string": "titulo: X",
                           "new_string": "titulo: Z\n\"apimart_tope_usd\": '50'"})[0] == "deny"
    assert decide("Edit", {"file_path": ruta, "old_string": "'2.00'", "new_string": "\"2.00\""}) == ("allow", "")
    assert decide("MultiEdit", {"file_path": ruta, "edits": [
        {"old_string": "titulo: X", "new_string": "titulo: Y"}]}) == ("allow", "")
    assert decide("MultiEdit", {"file_path": ruta, "edits": [
        {"old_string": "id: p", "new_string": "{id: p"},
        {"old_string": "titulo: X", "new_string": "apimart_tope_usd: '9'}"}]})[0] == "deny"


@pytest.fixture
def hook_en_proceso(mundo, monkeypatch):
    """El hook importado en el proceso de pytest, donde sí hay PyYAML."""
    monkeypatch.setenv("TROVEFY_VAULT", str(mundo["v"]))
    monkeypatch.setenv("HOME", str(mundo["home"]))
    hooks = str(RAIZ / "hooks")
    sys.path.insert(0, hooks)
    try:
        spec = importlib.util.spec_from_file_location("_apimart_gasto_prueba", RAIZ / "hooks" / "apimart_gasto.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(hooks)
    return mod


@pytest.mark.parametrize("contenido", CAMBIOS_DEL_TOPE)
def test_cambio_del_tope_con_pyyaml(hook_en_proceso, mundo, contenido):
    assert hook_en_proceso.yaml is not None
    entrada = {"tool_name": "Write", "tool_input": _w(mundo, contenido), "cwd": str(RAIZ)}
    assert hook_en_proceso.decidir(entrada)[0] == "deny", contenido


@pytest.mark.parametrize("contenido", [*MISMO_TOPE, f"---\n{{id: {P}, apimart_tope_usd: '2.00'}}\n---\n"])
def test_mismo_tope_con_pyyaml(hook_en_proceso, mundo, contenido):
    entrada = {"tool_name": "Write", "tool_input": _w(mundo, contenido), "cwd": str(RAIZ)}
    assert hook_en_proceso.decidir(entrada) == ("allow", ""), contenido


def test_flujo_sin_pyyaml_falla_cerrado(hook_en_proceso, mundo, monkeypatch):
    monkeypatch.setattr(hook_en_proceso, "yaml", None)
    flujo = f"---\n{{id: {P}, apimart_tope_usd: '2.00'}}\n---\n"
    entrada = {"tool_name": "Write", "tool_input": _w(mundo, flujo), "cwd": str(RAIZ)}
    assert hook_en_proceso.decidir(entrada)[0] == "deny"


# --- H-B: config/producto.yaml por ruta ------------------------------------------------------------------

@pytest.mark.parametrize("cmd,cwd", [
    ("cd {v}/config && sed -i 's/2.00/50.00/' producto.yaml", None),
    ("sed -i 's/2.00/50.00/' {v}/config//producto.yaml", None),
    ("sed -i s/2/5/ producto.yaml", "{v}/config"),
    ("cd config && sed -i s/2/5/ producto.yaml", "{v}"),
    ("rm -rf {v}/config", None),
    ("echo x > {v}/config/produc?o.yaml", None),
    ("cp /tmp/producto.yaml {v}/config/", None),
])
def test_bash_config_producto_por_ruta(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


# --- I-1 del plan 18: config/pantallas-confirmadas.yaml solo lo escribe `trovefy landing capturar` -------

PANTALLAS = "{v}/config/pantallas-confirmadas.yaml"


@pytest.mark.parametrize("tool,datos", [
    ("Write", {"file_path": PANTALLAS, "content": "impultienda: {}\n"}),
    ("Edit", {"file_path": PANTALLAS, "old_string": "no", "new_string": "sí"}),
    ("MultiEdit", {"file_path": PANTALLAS, "edits": [{"old_string": "no", "new_string": "sí"}]}),
    ("Write", {"file_path": "{v}/config/../config/pantallas-confirmadas.yaml", "content": "x"}),
])
def test_pantallas_confirmadas_write_edit(decide, mundo, tool, datos):
    datos = {k: (_fmt(x, mundo) if k == "file_path" else x) for k, x in datos.items()}
    decision, motivo = decide(tool, datos)
    assert decision == "deny" and "trovefy landing capturar" in motivo


def test_pantallas_confirmadas_write_relativo_desde_el_vault(decide, mundo):
    decision, _ = decide("Write", {"file_path": "config/pantallas-confirmadas.yaml", "content": "x"}, mundo["v"])
    assert decision == "deny"


@pytest.mark.parametrize("cmd,cwd", [
    ("echo 'impultienda: {{}}' > {v}/config/pantallas-confirmadas.yaml", None),
    ("printf x >> {v}/config/pantallas-confirmadas.yaml", None),
    ("cp /tmp/p.yaml {v}/config/pantallas-confirmadas.yaml", None),
    ("cp /tmp/pantallas-confirmadas.yaml {v}/config/", None),
    ("mv /tmp/p.yaml {v}/config/pantallas-confirmadas.yaml", None),
    ("sed -i s/no/si/ {v}/config/pantallas-confirmadas.yaml", None),
    ("echo x | tee {v}/config/pantallas-confirmadas.yaml", None),
    ("cd {v}/config && echo x > pantallas-confirmadas.yaml", None),
    ("sed -i s/no/si/ pantallas-confirmadas.yaml", "{v}/config"),
    ("python3 -c 'print(1)' > {v}/config/pantallas-confirmadas.yaml", None),
    ("python3 -c \"open('{v}/config/pantallas-confirmadas.yaml','w').write('x')\"", None),
    ("echo x > {v}/config/pantallas-confirmad?s.yaml", None),
    ("rm {v}/config/pantallas-confirmadas.yaml", None),
])
def test_pantallas_confirmadas_bash(decide, mundo, cmd, cwd):
    decision, motivo = decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))
    assert decision == "deny", cmd
    assert "trovefy landing capturar" in motivo or "producto.yaml" in motivo, (cmd, motivo)


def test_pantallas_confirmadas_leer_pasa(decide, mundo):
    assert decide("Bash", {"command": _fmt("cat {v}/config/pantallas-confirmadas.yaml", mundo)}) == ("allow", "")


# --- F1-1 (segunda ronda): la confirmación vive en ~/.config/trovefy y la lanza solo el usuario -------------

CONF_PANTALLAS = "{home}/.config/trovefy/pantallas-confirmadas.yaml"


@pytest.mark.parametrize("tool,datos", [
    ("Write", {"file_path": CONF_PANTALLAS, "content": "impultienda: {}\n"}),
    ("Edit", {"file_path": CONF_PANTALLAS, "old_string": "no", "new_string": "sí"}),
    ("MultiEdit", {"file_path": CONF_PANTALLAS, "edits": [{"old_string": "no", "new_string": "sí"}]}),
    ("NotebookEdit", {"notebook_path": CONF_PANTALLAS, "new_source": "x"}),
    ("Write", {"file_path": "{home}/.config/./trovefy/otra.yaml", "content": "x"}),
])
def test_config_de_trovefy_no_se_escribe_con_write_edit(decide, mundo, tool, datos):
    datos = {k: (_fmt(x, mundo) if k in ("file_path", "notebook_path") else x) for k, x in datos.items()}
    assert decide(tool, datos)[0] == "deny", datos


@pytest.mark.parametrize("cmd", [
    "cp /tmp/p ~/.config/trovefy/pantallas-confirmadas.yaml",
    "printf x >| ~/.config/trovefy/pantallas-confirmadas.yaml",
    "echo x >|{home}/.config/trovefy/pantallas-confirmadas.yaml",
    "cp -t ~/.config/trovefy /tmp/pantallas-confirmadas.yaml",
    "curl -so ~/.config/trovefy/pantallas-confirmadas.yaml file:///tmp/p",
    "cp /tmp/p ~/.config/{{trovefy,x}}/pantallas-confirmadas.yaml",
    "trovefy ayuda > ~/.config/trovefy/pantallas-confirmadas.yaml",
    "uv run trovefy x 2> {home}/.config/trovefy/pantallas-confirmadas.yaml",
])
def test_config_de_trovefy_no_se_escribe_por_bash(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)})[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "trovefy landing capturar",
    "uv run trovefy landing capturar --url https://app.impultienda.ar/x",
    "uv run trovefy landing capturar < /dev/tty",
    "cd {v} && script -qc 'trovefy landing capturar' /dev/null",
    "printf '\\nsí\\n' | script -qec 'uv run trovefy landing capturar' /dev/null",
    "uv run python -m trovefy.landing_cli capturar",
    "uv run python -c 'from trovefy.tienda.confirmacion import confirmar_pantalla as c; c()'",
    "uv run python -c 'from trovefy.tienda import confirmacion'",
    "uv run python -c 'import trovefy.landing.panel as p; p.capturar_pantalla(v)'",
    "python3 -c \"import trovefy.tienda.confirmacion\"",
    "uv run trovefy 'land''ing' capturar",
])
def test_capturar_y_confirmar_solo_los_lanza_el_usuario(decide, mundo, cmd):
    decision, motivo = decide("Bash", {"command": _fmt(cmd, mundo)})
    assert decision == "deny" and "terminal" in motivo, (cmd, motivo)


@pytest.mark.parametrize("cmd", [
    "TROVEFY_VAULT=/tmp/fake uv run trovefy landing sonda --producto p --pais BG --tienda https://x",
    "TROVEFY_VAULT=/tmp/fake trovefy landing publicar --producto p --pais BG",
    "env TROVEFY_VAULT=/tmp/fake trovefy landing sonda --producto p --pais BG --tienda https://x",
    "export TROVEFY_VAULT=/tmp/fake; uv run trovefy landing publicar --producto p --pais BG",
])
def test_sonda_y_publicar_con_otro_vault_se_niegan(decide, cmd):
    assert decide("Bash", {"command": cmd})[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "trovefy landing sonda --producto p --pais BG --tienda https://x",
    "TROVEFY_VAULT=/tmp/x uv run pytest -q tests/unit/landing",
    "uv run pytest -q tests/unit/tienda/test_confirmacion.py",
    "rg -n confirmar_pantalla scripts tests",
    "grep -rn capturar_pantalla scripts",
    "git log --oneline -3",
])
def test_lo_legitimo_alrededor_de_la_confirmacion_pasa(decide, cmd):
    assert decide("Bash", {"command": cmd}) == ("allow", ""), cmd


def test_segundo_vault_no_trae_confirmacion(decide, mundo, tmp_path):
    """Copiar el vault a otro sitio y escribir allí una confirmación no sirve: ni se escribe en la config ni
    se lanza la sonda con ese vault."""
    otro = tmp_path / "fake"
    assert decide("Bash", {"command": f"cp -r {mundo['v']} {otro}"}) == ("allow", "")
    assert decide("Bash", {"command": f"TROVEFY_VAULT={otro} trovefy landing sonda --producto p --pais BG "
                                      "--tienda https://x"})[0] == "deny"
    assert decide("Write", {"file_path": str(mundo["home"] / ".config/trovefy/pantallas-confirmadas.yaml"),
                            "content": "x"})[0] == "deny"


# --- F1-4: la evidencia de la sonda solo la escribe la sonda ---------------------------------------------

EV_SONDA = "{v}/config/evidencia/p05-impultienda-2026-11-17.json"


@pytest.mark.parametrize("tool,datos", [
    ("Write", {"file_path": EV_SONDA, "content": "{}"}),
    ("Edit", {"file_path": EV_SONDA, "old_string": "false", "new_string": "true"}),
    ("Write", {"file_path": "{v}/config/evidencia/p05-impultienda-2099-01-01.json", "content": "{}"}),
    ("Write", {"file_path": "{v}/config/evidencia/p05-diseno-contenido-2026-11-17.png", "content": "x"}),
])
def test_evidencia_de_la_sonda_no_se_escribe_con_write(decide, mundo, tool, datos):
    datos = {k: (_fmt(x, mundo) if k == "file_path" else x) for k, x in datos.items()}
    assert decide(tool, datos)[0] == "deny", datos


@pytest.mark.parametrize("cmd,cwd", [
    ("echo '{{}}' > " + EV_SONDA, None),
    ("cp /tmp/e.json " + EV_SONDA, None),
    ("cp /tmp/p05-impultienda-2026-11-17.json {v}/config/evidencia/", None),
    ("cp /tmp/e.json p05-impultienda-2026-11-18.json", "{v}/config/evidencia"),
    ("sed -i s/false/true/ " + EV_SONDA, None),
    ("rm -rf {v}/config/evidencia", None),
])
def test_evidencia_de_la_sonda_no_se_escribe_por_bash(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


def test_evidencia_de_la_sonda_se_lee(decide, mundo):
    assert decide("Bash", {"command": _fmt("cat {v}/config/evidencia/p05-impultienda-*.json", mundo)}) == \
        ("allow", "")
    assert decide("Read", {"file_path": _fmt(EV_SONDA, mundo)}) == ("allow", "")


# --- F1-2: huecos del hook (también para config/producto.yaml) ------------------------------------------

@pytest.mark.parametrize("cmd,cwd", [
    ("printf x >| {v}/config/producto.yaml", None),
    ("printf a >| config/producto.yaml", "{v}"),
    ("cp -t {v}/config /tmp/producto.yaml", None),
    ("cp -t config /tmp/producto.yaml", "{v}"),
    ("mv -t {v}/config /tmp/producto.yaml", None),
    ("install -t {v}/config /tmp/producto.yaml", None),
    ("ln -s -t {v}/config /tmp/producto.yaml", None),
    ("cp --target-directory={v}/config /tmp/producto.yaml", None),
    ("curl -so {v}/config/producto.yaml file:///tmp/p", None),
    ("curl --output {v}/config/producto.yaml file:///tmp/p", None),
    ("curl -O file:///tmp/producto.yaml", "{v}/config"),
    ("wget -qO {v}/config/producto.yaml http://x", None),
    ("wget --output-document={v}/config/producto.yaml http://x", None),
    ("wget http://x/producto.yaml", "{v}/config"),
    ("awk 'BEGIN{{print 1 > \"{v}/config/producto.yaml\"}}'", None),
    ("cd {v} && awk 'BEGIN{{print \"x\" > \"config/producto.yaml\"}}'", None),
    ("cp /tmp/p {v}/config/producto.{{yaml,x}}", None),
    ("cp /tmp/p {v}/{{config,x}}/producto.yaml", None),
    ("cp /tmp/p {v}/config/pantallas-confirmadas.{{yaml,x}}", None),
])
def test_huecos_del_hook_cerrados(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "awk '{{print $1}}' {v}/config/producto.yaml",
    "cp -t /tmp/salida {v}/config/producto.yaml",
    "curl -so /tmp/x.json https://example.test/x",
    "mkdir -p /tmp/{{a,b}}",
    "echo x >| /tmp/nota.txt",
])
def test_lo_legitimo_cerca_de_los_huecos_pasa(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}) == ("allow", ""), cmd


def test_config_del_repo_se_puede_editar(decide):
    cmd = "sed -i 's/2.00/2.50/' templates/cerebro/config/producto.yaml"
    assert decide("Bash", {"command": cmd}) == ("allow", "")


# --- H-C: el libro de gasto por ruta, carpetas incluidas ---------------------------------------------------

@pytest.mark.parametrize("cmd,cwd", [
    ("rm -rf {P}/entregable", None),
    ("rm -r {P}", None),
    ("mv {P}/entregable /tmp/", None),
    ("mv {P}/entregable/costes* /tmp/", None),
    ("cd {P}/entregable && : > cost?s.csv", None),
    ("rm -f .apimart-*", "{P}/entregable"),
    ("rm .apimart.lock", "{P}/entregable"),
    ("rm -rf productos", "{v}"),
    ("git checkout -- productos/p-0042-respira/entregable/costes.csv", "{v}"),
    ("git -C {v} checkout HEAD~3 -- productos/p-0042-respira/entregable/costes.csv", None),
    ("git -C {v} stash", None),
    ("git stash", "{v}"),
    ("cd {v} && git reset --hard", None),
    ("git -C {v} clean -fdx", None),
    ("git -C {v} restore .", None),
    ("cp -r /tmp/viejo/entregable {P}/", None),
    ("find {P} -name costes.csv -delete", None),
])
def test_bash_libro_de_gasto_por_ruta(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


@pytest.mark.parametrize("cmd,cwd", [
    ("cat {P}/entregable/costes.csv", None),
    ("tail -3 {P}/entregable/costes.csv", None),
    ("tail -3 costes.csv", "{P}/entregable"),
    ("rm {P}/entregable/principal/borrador.png", None),
    ("git status", "{v}"),
    ("git log --oneline -5", "{v}"),
    ("git stash push -m x -- scripts/trovefy/apimart", None),
    ("git checkout scripts/trovefy/apimart/lote.py", None),
])
def test_bash_legitimo_cerca_del_libro(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo)) == ("allow", ""), cmd


# --- M-A: ~/.config/trovefy ------------------------------------------------------------------------------

@pytest.mark.parametrize("tool,datos", [
    ("Read", {"file_path": "{home}/.config/trovefy/claude.env"}),
    ("Read", {"file_path": "{home}/.config/trovefy/meta.env"}),
    ("Read", {"file_path": "{home}/.config/./trovefy/x"}),
    ("Grep", {"pattern": "KEY", "path": "{home}/.config/trovefy"}),
    ("Grep", {"pattern": "KEY", "path": "{home}/.config", "glob": "claude.env"}),
    ("Grep", {"pattern": "KEY", "path": "{home}/.config", "glob": "**/*.env"}),
    ("Grep", {"pattern": "KEY", "path": "{home}/.config"}),
])
def test_read_grep_de_la_config_de_trovefy(decide, mundo, tool, datos):
    datos = {k: _fmt(v, mundo) for k, v in datos.items()}
    assert decide(tool, datos)[0] == "deny", datos


@pytest.mark.parametrize("cmd,cwd", [
    ("cat ~/.config/trovefy/claude.env", None),
    ("cat ~/.config/trovefy/claude.en?", None),
    ("cat $HOME/.config/trovefy/meta.env", None),
    ("head {home}/.config/trov*/*", None),
    ("grep -r KEY ~/.config/", None),
    ("grep -r KEY ~/.config/trovefy/", None),
    ("tail -1 meta.env", "{home}/.config/trovefy"),
    ("cd ~/.config/trovefy && less meta.env", None),
    ("rg KEY {home}/.config", None),
    ("trovefy producto x; cat ~/.config/trovefy/meta.env", None),
])
def test_bash_de_la_config_de_trovefy(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


def test_trovefy_puede_leer_su_config(decide):
    for cmd in ("trovefy producto imagenes p-0042-respira --env ~/.config/trovefy/claude.env",
                "uv run trovefy arranque verificar --env ~/.config/trovefy/meta.env"):
        assert decide("Bash", {"command": cmd}) == ("allow", ""), cmd


# --- M-B: STOP lo quita el usuario ------------------------------------------------------------------------

@pytest.mark.parametrize("cmd,cwd", [
    ("rm {v}/.trovefy/STOP", None),
    ("mv {v}/.trovefy/STOP /tmp/", None),
    ("rm STOP", "{v}/.trovefy"),
    ("rm -rf {v}/.trovefy", None),
    ("unlink {v}/.trovefy/ST?P", None),
    ("cd {v} && rm .trovefy/STOP", None),
])
def test_stop_no_se_borra(decide, mundo, cmd, cwd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}, cwd and _fmt(cwd, mundo))[0] == "deny", cmd


def test_stop_no_se_borra_con_la_grafia_del_home(correr_hook, mundo):
    """El vault por defecto (~/trovefy-cerebro) escrito con ~."""
    v = mundo["home"] / "trovefy-cerebro"
    (v / ".trovefy").mkdir(parents=True)
    entrada = {"tool_name": "Bash", "tool_input": {"command": "rm -f ~/trovefy-cerebro/.trovefy/STOP"}, "cwd": "/tmp"}
    assert correr_hook("apimart_gasto", entrada, v, {"HOME": str(mundo["home"])})[0] == "deny"


@pytest.mark.parametrize("cmd", [
    "touch {v}/.trovefy/STOP",
    "echo 'para todo' > {v}/.trovefy/STOP",
    "ls -la {v}/.trovefy",
])
def test_crear_stop_permitido(decide, mundo, cmd):
    assert decide("Bash", {"command": _fmt(cmd, mundo)}) == ("allow", ""), cmd


def test_write_de_stop_permitido(decide, mundo):
    assert decide("Write", {"file_path": str(mundo["v"] / ".trovefy" / "STOP"), "content": "x"}) == ("allow", "")


# --- L-B y trabajo legítimo ----------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "trovefy producto imagenes p-0042-respira",
    "uv run trovefy producto imagenes p-0042-respira --reanudar",
    "uv run pytest -q",
    "uv run pytest -q tests/unit/apimart 2>&1 | tail -5",
    "uv run pytest -q tests/unit/apimart > /tmp/x.log 2>&1",
    "uv run ruff check .",
    "uv run ruff check scripts/trovefy/apimart hooks",
    "git add hooks/apimart_gasto.py tests/hooks/test_apimart_rutas.py",
    'git commit -m "fix(hooks): el hook protege claude.env y apimart_tope_usd"',
    "git status --short",
    "git diff HEAD -- scripts/trovefy/apimart/gasto.py | head",
    "git log --oneline -5",
    "git show HEAD --stat",
    "rg claude.env",
    "rg -n claude.env hooks tests",
    "grep -rn claude.env scripts",
    "sed -i 's/viejo/nuevo/' scripts/trovefy/apimart/lote.py",
    "cat scripts/trovefy/apimart/gasto.py",
    "echo hola > /tmp/nota.txt",
])
def test_trabajo_legitimo(decide, cmd):
    assert decide("Bash", {"command": cmd}) == ("allow", ""), cmd


def test_editar_archivos_del_repo(decide):
    for ruta in ("scripts/trovefy/apimart/lote.py", "templates/cerebro/config/producto.yaml"):
        assert decide("Write", {"file_path": str(RAIZ / ruta), "content": "x"}) == ("allow", ""), ruta


def test_cat_de_la_clave_real_sigue_denegado(decide):
    for cmd in ("cat claude.env", "grep KEY ~/.config/trovefy/claude.env"):
        assert decide("Bash", {"command": cmd})[0] == "deny", cmd
