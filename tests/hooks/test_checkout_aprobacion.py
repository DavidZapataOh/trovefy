"""Revisión de la Tarea 11 del plan 19: la aprobación de un plan del MCP no se puede falsificar y una escritura
aprobada no se repite (C1, H1, H2, M1 y el nombre del conector). Son las sondas del revisor (`sonda_hooks.py` y
`sonda_guarda.py`) convertidas en tests, con procesos reales del python3 del sistema; nunca se llama al MCP."""

import json
import os
from pathlib import Path

import pytest
from plan_aprobado import P, plan_aprobado
from trovefy.checkout.mensajes import registrar_mensaje
from trovefy.tienda import mcp

RAIZ = Path(__file__).resolve().parents[2]
STORE = "00000000-0000-4000-8000-000000000000"
FIJAR = {"store_id": STORE, "item_id": "i-1", "precio": 13.9}
POR_PAIS = {"store_id": STORE, "item_id": "i-1", "market_id": "m-1", "precio": 13.9}
HOOKS = ("meta_guard", "secretos", "raw_inmutable", "stop", "buzon_guard", "ejecutor_guard", "apimart_gasto")


@pytest.fixture
def home(tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    return casa


def _entrada(corto: str, args: dict, nombre: str | None = None) -> dict:
    return {"tool_name": nombre or f"mcp__impultienda__impultienda_{corto}", "tool_input": args, "cwd": str(RAIZ)}


def _guarda(correr_hook, entrada, vault, home):
    return correr_hook("impultienda_guard", entrada, vault, {"HOME": str(home)})


def _algun_hook_deniega(correr_hook, tool: str, datos: dict, vault: Path, home: Path) -> list[str]:
    entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(RAIZ), "hook_event_name": "PreToolUse"}
    return [h for h in HOOKS if correr_hook(h, entrada, vault, {"HOME": str(home)})[0] == "deny"]


# --- C1: los archivos del plan, la aprobación y el estado solo los escribe `trovefy checkout …` ------------------


def _carpeta(vault: Path) -> Path:
    c = vault / "productos" / P / "checkout" / "ZZ"
    c.mkdir(parents=True, exist_ok=True)
    return c


@pytest.mark.parametrize("nombre", ["APROBACION.md", "PLAN-MCP.json", "MCP-ESTADO.json", "COMPROBACION.md",
                                    "CHECKOUT.md", "mcp/etapa-1/APROBACION.md", "mcp/etapa-2/PLAN-MCP.json"])
def test_write_edit_bash_no_escriben_los_archivos_del_checkout(correr_hook, vault_tmp, home, nombre):
    ruta = _carpeta(vault_tmp) / nombre
    for tool, datos in (
        ("Write", {"file_path": str(ruta), "content": "---\nplan_huella: " + "a" * 64 + "\ncita: \"sí\"\n---\n"}),
        ("Edit", {"file_path": str(ruta), "old_string": "a", "new_string": "b"}),
        ("MultiEdit", {"file_path": str(ruta), "edits": [{"old_string": "a", "new_string": "b"}]}),
        ("NotebookEdit", {"notebook_path": str(ruta), "new_source": "x"}),
        ("Bash", {"command": f"printf x > {ruta}"}),
        ("Bash", {"command": f"cp /tmp/x {ruta}"}),
        ("Bash", {"command": f"python3 -c \"open('{ruta}', 'w').write('x')\""}),
        ("Bash", {"command": f"sed -i s/a/b/ {ruta}"}),
        ("Bash", {"command": f"rm -f {ruta}"}),
    ):
        entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(RAIZ)}
        decision, motivo = correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})
        assert decision == "deny" and "trovefy checkout" in motivo, (tool, datos)


def test_borrar_la_carpeta_del_pais_en_bloque_se_deniega(correr_hook, vault_tmp, home):
    c = _carpeta(vault_tmp)
    for comando in (f"rm -rf {c}", f"mv {c} /tmp/otro", f"rm -rf {c}/mcp"):
        entrada = {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(RAIZ)}
        assert correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})[0] == "deny", comando


def test_leer_y_las_respuestas_de_la_cache_siguen(correr_hook, vault_tmp, home):
    c = _carpeta(vault_tmp)
    cache = home / ".cache" / "trovefy" / "checkout" / P / "ZZ" / "etapa-1.json"
    for tool, datos in (("Read", {"file_path": str(c / "PLAN-MCP.json")}),
                        ("Bash", {"command": f"cat {c}/PLAN-MCP.md"}),
                        ("Write", {"file_path": str(cache), "content": "{}"}),
                        ("Write", {"file_path": str(c / "upsells" / "u1.md"), "content": "## x\n"})):
        entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(RAIZ)}
        assert correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})[0] == "allow", (tool, datos)


def test_sonda_de_hooks(correr_hook, vault_tmp, home):
    """La sonda del revisor: cada caso lo deniega al menos un hook (salvo la respuesta en la caché)."""
    c = _carpeta(vault_tmp)
    aprobar = "uv run trovefy checkout aprobar --producto p-0099-prueba-abc123 --pais ZZ --cita 'sí'"
    casos = [
        ("Write", {"file_path": str(home / ".config/trovefy/mensajes-usuario.json"), "content": "[]"}),
        ("Bash", {"command": "uv run python -c 'from trovefy.checkout.mensajes import registrar_mensaje'"}),
        ("Write", {"file_path": str(c / "APROBACION.md"), "content": "---\nplan_huella: " + "a" * 64 + "\n---\n"}),
        ("Write", {"file_path": str(c / "PLAN-MCP.json"), "content": "{}"}),
        ("Write", {"file_path": str(c / "MCP-ESTADO.json"), "content": "{}"}),
        ("Edit", {"file_path": str(c / "PLAN-MCP.json"), "old_string": "a", "new_string": "b"}),
        ("Bash", {"command": f"printf x > {c}/APROBACION.md"}),
        ("Bash", {"command": f"script -qec \"{aprobar}\" /dev/null"}),
        ("Bash", {"command": aprobar}),
        ("Write", {"file_path": str(c / "COMPROBACION.md"), "content": "---\nestado: completo\n---\n"}),
    ]
    for tool, datos in casos:
        assert _algun_hook_deniega(correr_hook, tool, datos, vault_tmp, home), (tool, datos)
    cache = home / ".cache/trovefy/checkout/p-0099-prueba-abc123/ZZ/etapa-1.json"
    assert not _algun_hook_deniega(correr_hook, "Write", {"file_path": str(cache), "content": "{}"}, vault_tmp, home)


# --- H2: `trovefy checkout aprobar` lo ejecuta el usuario en su terminal, nunca Claude ---------------------------


@pytest.mark.parametrize("comando", [
    "trovefy checkout aprobar --producto p-0099-prueba-abc123 --pais ZZ --cita 'sí, aplica la etapa 1 (abcd)'",
    "uv run trovefy checkout aprobar --producto p --pais ZZ --cita x",
    "cd /home && uv run trovefy checkout aprobar --producto p --pais ZZ --cita x",
    "python -m trovefy checkout aprobar --producto p --pais ZZ --cita x",
    "uv run python -m trovefy checkout aprobar --producto p --pais ZZ --cita x",
    "script -qec \"uv run trovefy checkout aprobar --producto p --pais ZZ --cita x\" /dev/null",
    "script -q -c 'trovefy checkout aprobar --cita x' /dev/null",
    "unbuffer trovefy checkout aprobar --cita x",
    "expect -c 'spawn trovefy checkout aprobar --cita x; interact'",
    "python3 -c \"import pty; pty.spawn(['trovefy', 'checkout', 'aprobar', '--cita', 'x'])\"",
    "uv run python -c 'from trovefy.checkout.mcp_cli import aprobar'",
    "uv run python -c 'from trovefy.checkout import mcp_cli; mcp_cli.hay_terminal = lambda: True'",
    "echo x | trovefy checkout aprobar --cita x",
])
def test_claude_no_ejecuta_aprobar(correr_hook, vault_tmp, home, comando):
    entrada = {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(RAIZ)}
    decision, motivo = correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})
    assert decision == "deny" and "terminal" in motivo, comando


@pytest.mark.parametrize("comando", [
    "uv run trovefy checkout plan --producto p-0099-prueba-abc123 --pais ZZ",
    "uv run trovefy checkout releer --producto p-0099-prueba-abc123 --pais ZZ --respuesta x.json",
    "uv run pytest tests/unit/checkout -q -k aprobar",
    "grep -rn 'checkout aprobar' skills",
    "git commit -m 'fix(checkout): aprobación imposible de falsificar'",
])
def test_lo_demas_del_checkout_sigue(correr_hook, vault_tmp, home, comando):
    entrada = {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(RAIZ)}
    assert correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})[0] == "allow", comando


# --- C1/H1 en la guarda: un par plan + aprobación escrito a mano no vale -----------------------------------------


def test_par_falsificado_denegado_de_punta_a_punta(correr_hook, vault_tmp, home):
    """`sonda_guarda.py`: PLAN-MCP.json y APROBACION.md escritos a mano (con la huella de antes y luego con la de
    ahora) no abren la guarda: falta el mensaje del usuario en el registro."""
    ops = [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}]
    c = _carpeta(vault_tmp)
    hu = mcp.huella_plan(ops)
    (c / "PLAN-MCP.json").write_text(json.dumps({"operaciones": ops, "huella": hu}), encoding="utf-8")
    (c / "APROBACION.md").write_text(f"---\nplan_huella: {hu}\ncita: \"x\"\n---\n", encoding="utf-8")
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"
    # Con la huella y la frase de ahora, pero sin el mensaje del usuario en el registro.
    plan_aprobado(vault_tmp, ops, registrar=False)
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"
    # Aunque el usuario escribiera la frase, si nadie la usó para aprobar (sin la marca del registro), tampoco.
    plan = json.loads((c / "PLAN-MCP.json").read_text(encoding="utf-8"))
    registrar_mensaje(mcp.frase_aprobacion(1, plan["huella"]), ahora=1.8e9)
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"


def test_registro_ilegible_falla_cerrado(correr_hook, vault_tmp, home):
    ops = [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}]
    plan_aprobado(vault_tmp, ops)
    registro = home / ".config" / "trovefy" / "mensajes-usuario.json"
    registro.write_text("{roto", encoding="utf-8")
    decision, motivo = _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)
    assert decision == "deny" and "mensaje" in motivo


@pytest.mark.parametrize("cambio", ["creado", "etapa", "producto", "pais", "operaciones"])
def test_la_huella_cubre_creado_etapa_producto_y_pais(correr_hook, vault_tmp, home, cambio):
    ops = [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}]
    c, plan = plan_aprobado(vault_tmp, ops)
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "allow"
    nuevo = dict(plan)
    nuevo[cambio] = {"creado": "2026-11-18T12:00:00-05:00", "etapa": 2, "producto": "p-0098-otro-abc123",
                     "pais": "YY", "operaciones": ops + ops}[cambio]
    # La huella vieja ya no casa con el plan cambiado; recalcularla cambia la frase y el registro no la tiene.
    (c / "PLAN-MCP.json").write_text(json.dumps(nuevo), encoding="utf-8")
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"
    nuevo["huella"] = mcp.huella_del_plan(nuevo)
    (c / "PLAN-MCP.json").write_text(json.dumps(nuevo), encoding="utf-8")
    texto = (c / "APROBACION.md").read_text(encoding="utf-8").replace(plan["huella"], nuevo["huella"])
    (c / "APROBACION.md").write_text(texto, encoding="utf-8")
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"


def test_huella_misma_funcion_en_cli_y_guarda():
    from trovefy.checkout import mcp_cli
    assert mcp_cli.huella_del_plan is mcp.huella_del_plan
    base = {"operaciones": [], "creado": "x", "etapa": 1, "producto": P, "pais": "ZZ"}
    assert len({mcp.huella_del_plan({**base, k: v}) for k, v in
                [("creado", "y"), ("etapa", 2), ("producto", "q"), ("pais", "YY"), ("operaciones", [{}])]}
               | {mcp.huella_del_plan(base)}) == 6


# --- M1: una escritura aprobada no se repite en la misma etapa ---------------------------------------------------


def test_escritura_repetida_en_la_etapa_se_deniega(correr_hook, vault_tmp, home):
    plan_aprobado(vault_tmp, [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}])
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "allow"
    decision, motivo = _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)
    assert decision == "deny" and "ya" in motivo
    # El registro vive en ~/.config/trovefy (Claude no lo lee ni lo escribe) y no guarda argumentos en claro.
    registro = home / ".config" / "trovefy" / mcp.ESCRITURAS
    assert registro.is_file() and "13.9" not in registro.read_text(encoding="utf-8")
    assert oct(registro.stat().st_mode & 0o777) == oct(0o600)


def test_dos_pasos_la_vista_previa_una_vez_y_la_confirmacion_si(correr_hook, vault_tmp, home):
    plan_aprobado(vault_tmp, [{"herramienta": "impultienda_precio_por_pais", "argumentos": POR_PAIS}])
    assert _guarda(correr_hook, _entrada("precio_por_pais", POR_PAIS), vault_tmp, home)[0] == "allow"
    assert _guarda(correr_hook, _entrada("precio_por_pais", POR_PAIS), vault_tmp, home)[0] == "deny"
    confirmar = {**POR_PAIS, "confirmar": True, "token": "0123456789abcdef"}
    assert _guarda(correr_hook, _entrada("precio_por_pais", confirmar), vault_tmp, home)[0] == "allow"
    assert _guarda(correr_hook, _entrada("precio_por_pais", confirmar), vault_tmp, home)[0] == "allow"


def test_registro_de_escrituras_ilegible_falla_cerrado(correr_hook, vault_tmp, home):
    plan_aprobado(vault_tmp, [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}])
    registro = home / ".config" / "trovefy" / mcp.ESCRITURAS
    registro.write_text("{roto", encoding="utf-8")
    assert _guarda(correr_hook, _entrada("fijar_precio", FIJAR), vault_tmp, home)[0] == "deny"


def test_claude_no_toca_el_registro_de_escrituras(correr_hook, vault_tmp, home):
    ruta = home / ".config" / "trovefy" / mcp.ESCRITURAS
    for tool, datos in (("Write", {"file_path": str(ruta), "content": "[]"}), ("Read", {"file_path": str(ruta)}),
                        ("Bash", {"command": f"rm {ruta}"})):
        entrada = {"tool_name": tool, "tool_input": datos, "cwd": str(RAIZ)}
        assert correr_hook("apimart_gasto", entrada, vault_tmp, {"HOME": str(home)})[0] == "deny", tool


# --- el nombre del conector -------------------------------------------------------------------------------------


@pytest.mark.parametrize("nombre", ["mcp__claude_ai_Impultienda__impultienda_fijar_precio",
                                    "mcp__claude_ai_impultienda__impultienda_listar_tiendas",
                                    "mcp__IMPULTIENDA__impultienda_listar_tiendas",
                                    "mcp__otro__impultienda_listar_tiendas"])
def test_otro_nombre_con_impultienda_se_deniega(correr_hook, vault_tmp, home, nombre):
    decision, motivo = _guarda(correr_hook, _entrada("", {}, nombre), vault_tmp, home)
    assert decision == "deny" and "mcp__impultienda__" in motivo


def test_hooks_json_lleva_la_guarda_a_cualquier_impultienda():
    import re
    reg = json.loads((RAIZ / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    grupos = [g for g in reg["hooks"]["PreToolUse"]
              if any("impultienda_guard.py" in h["command"] for h in g["hooks"])]
    assert len(grupos) == 1  # una sola vez: la guarda anota cada escritura (M1)
    patron = re.compile(grupos[0]["matcher"])
    for nombre in ("mcp__impultienda__impultienda_fijar_precio", "mcp__claude_ai_Impultienda__x",
                   "mcp__claude_ai_IMPULTIENDA__x"):
        assert patron.fullmatch(nombre), nombre
    assert not patron.fullmatch("mcp__otro__listar")


def test_home_aislado(home):
    assert Path.home() == home and os.environ["HOME"] == str(home)
