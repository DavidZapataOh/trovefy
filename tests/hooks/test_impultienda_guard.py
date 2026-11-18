"""Hook PreToolUse `impultienda_guard` (H-1): el conector de Impultienda solo con el catálogo, las restricciones por
herramienta y, para escribir, un plan aprobado. Procesos reales con el python3 del sistema; nunca llama al MCP."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from plan_aprobado import plan_aprobado

RAIZ = Path(__file__).resolve().parents[2]
P = "p-0099-prueba-abc123"
STORE = "00000000-0000-4000-8000-000000000000"
FIJAR = {"store_id": STORE, "item_id": "i-1", "precio": 13.9}


def _entrada(corto: str, args: dict) -> dict:
    return {"tool_name": f"mcp__impultienda__impultienda_{corto}", "tool_input": args, "cwd": str(RAIZ)}


@pytest.fixture(autouse=True)
def _home_aislado(tmp_path, monkeypatch):
    """El registro de mensajes y el de escrituras viven en el HOME: nunca el real (correr_hook pasa este HOME)."""
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))


def _aprobar(vault: Path, ops: list[dict], pais: str = "ZZ") -> None:
    """Como lo deja `trovefy checkout aprobar`: huella del plan, su frase y el mensaje del usuario en el registro."""
    plan_aprobado(vault, ops, pais=pais, producto=P)


def test_lectura_pasa(correr_hook, vault_tmp):
    assert correr_hook("impultienda_guard", _entrada("listar_ventas", {"store_id": STORE}), vault_tmp)[0] == "allow"


def test_faq_por_ruling_pasa(correr_hook, vault_tmp):
    assert correr_hook("impultienda_guard", _entrada("faq", {"consulta": "entrega"}), vault_tmp)[0] == "allow"


def test_configurar_checkout_por_ruling(correr_hook, vault_tmp):
    args = {"store_id": STORE, "pedir_telefono": True, "texto_boton_pagar": "Купи", "color_boton_pagar": "#112233"}
    # Sin aprobación, no; aprobada, sí; con otro texto o una clave fuera del esquema, no.
    assert correr_hook("impultienda_guard", _entrada("configurar_checkout", args), vault_tmp)[0] == "deny"
    _aprobar(vault_tmp, [{"herramienta": "impultienda_configurar_checkout", "argumentos": args}])
    assert correr_hook("impultienda_guard", _entrada("configurar_checkout", args), vault_tmp)[0] == "allow"
    otro = {**args, "texto_boton_pagar": "Pagar ya"}
    assert correr_hook("impultienda_guard", _entrada("configurar_checkout", otro), vault_tmp)[0] == "deny"
    decision, motivo = correr_hook("impultienda_guard",
                                   _entrada("configurar_checkout", {**args, "metodo_pago": "x"}), vault_tmp)
    assert decision == "deny" and "metodo_pago" in motivo


@pytest.mark.parametrize("corto", ["conectar_pasarela", "configurar_tracking", "ver_pago", "no_existe",
                                    "ver_cobros_plan"])
def test_prohibida_o_desconocida_se_deniega(correr_hook, vault_tmp, corto):
    decision, motivo = correr_hook("impultienda_guard", _entrada(corto, {"store_id": STORE}), vault_tmp)
    assert decision == "deny" and motivo


def test_nombre_raro_se_deniega(correr_hook, vault_tmp):
    entrada = {"tool_name": "mcp__impultienda__IMPULTIENDA_listar_ventas", "tool_input": {}, "cwd": str(RAIZ)}
    assert correr_hook("impultienda_guard", entrada, vault_tmp)[0] == "deny"
    entrada["tool_name"] = "mcp__Impultienda__impultienda_conectar_pasarela"
    assert correr_hook("impultienda_guard", entrada, vault_tmp)[0] == "deny"


def test_otro_servidor_no_es_cosa_suya(correr_hook, vault_tmp):
    entrada = {"tool_name": "mcp__otro__listar", "tool_input": {"x": 1}, "cwd": str(RAIZ)}
    assert correr_hook("impultienda_guard", entrada, vault_tmp)[0] == "allow"


def test_clave_desconocida_se_deniega(correr_hook, vault_tmp):
    decision, motivo = correr_hook("impultienda_guard",
                                   _entrada("listar_ventas", {"store_id": STORE, "pasarela": "x"}), vault_tmp)
    assert decision == "deny" and "pasarela" in motivo


def test_escritura_sin_aprobacion_se_deniega(correr_hook, vault_tmp):
    decision, motivo = correr_hook("impultienda_guard", _entrada("fijar_precio", FIJAR), vault_tmp)
    assert decision == "deny" and "APROBACION" in motivo


def test_escritura_aprobada_pasa_y_otra_no(correr_hook, vault_tmp):
    _aprobar(vault_tmp, [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}])
    assert correr_hook("impultienda_guard", _entrada("fijar_precio", FIJAR), vault_tmp)[0] == "allow"
    assert correr_hook("impultienda_guard", _entrada("fijar_precio", {**FIJAR, "precio": 1}), vault_tmp)[0] == "deny"
    assert correr_hook("impultienda_guard", _entrada("crear_embudo", {"store_id": STORE, "nombre": "x"}),
                       vault_tmp)[0] == "deny"


def test_escritura_aprobada_con_stop_se_deniega(correr_hook, vault_tmp):
    _aprobar(vault_tmp, [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}])
    (vault_tmp / ".trovefy" / "STOP").write_text("", encoding="utf-8")
    decision, motivo = correr_hook("impultienda_guard", _entrada("fijar_precio", FIJAR), vault_tmp)
    assert decision == "deny" and "STOP" in motivo


def test_valores_prohibidos_aunque_esten_aprobados(correr_hook, vault_tmp):
    diseno = {"store_id": STORE, "minutos_timer_bump": 0, "estilo_bump": "escasez"}
    bloques = {"store_id": STORE, "posicion": "arriba", "bloques": [{"tipo": "countdown", "minutos": 10}]}
    pago = {"store_id": STORE, "minutos_timer_bump": 0, "pago_expres_arriba": True}
    sin_timer = {"store_id": STORE, "plantilla": "kiwify"}
    _aprobar(vault_tmp, [{"herramienta": "impultienda_disenar_checkout", "argumentos": diseno},
                         {"herramienta": "impultienda_bloques_checkout", "argumentos": bloques},
                         {"herramienta": "impultienda_disenar_checkout", "argumentos": pago},
                         {"herramienta": "impultienda_disenar_checkout", "argumentos": sin_timer}])
    for corto, args, que in [("disenar_checkout", diseno, "escasez"), ("bloques_checkout", bloques, "countdown"),
                             ("disenar_checkout", pago, "pago_expres_arriba"),
                             ("disenar_checkout", sin_timer, "minutos_timer_bump")]:
        decision, motivo = correr_hook("impultienda_guard", _entrada(corto, args), vault_tmp)
        assert decision == "deny" and que in motivo, (corto, motivo)


def test_disenar_checkout_bien_aprobado_pasa(correr_hook, vault_tmp):
    args = {"store_id": STORE, "minutos_timer_bump": 0, "plantilla": "kiwify", "estilo_bump": "classic"}
    _aprobar(vault_tmp, [{"herramienta": "impultienda_disenar_checkout", "argumentos": args}])
    assert correr_hook("impultienda_guard", _entrada("disenar_checkout", args), vault_tmp)[0] == "allow"


def test_titulo_con_meta_descripcion_por_ruling(correr_hook, vault_tmp):
    args = {"store_id": STORE, "titulo": "Somatix", "meta_descripcion": "Descripción"}
    _aprobar(vault_tmp, [{"herramienta": "impultienda_cambiar_titulo_pagina", "argumentos": args}])
    assert correr_hook("impultienda_guard", _entrada("cambiar_titulo_pagina", args), vault_tmp)[0] == "allow"


def test_dos_pasos_con_token(correr_hook, vault_tmp):
    args = {"store_id": STORE, "item_id": "i", "market_id": "m", "precio": 13.9}
    _aprobar(vault_tmp, [{"herramienta": "impultienda_precio_por_pais", "argumentos": args}])
    assert correr_hook("impultienda_guard", _entrada("precio_por_pais", args), vault_tmp)[0] == "allow"
    confirmar = {**args, "confirmar": True, "token": "0123456789abcdef"}
    assert correr_hook("impultienda_guard", _entrada("precio_por_pais", confirmar), vault_tmp)[0] == "allow"


def test_entrada_ilegible_se_deniega(correr_hook, vault_tmp):
    assert correr_hook("impultienda_guard", "{no json", vault_tmp)[0] == "deny"


def _copia_plugin(tmp_path: Path) -> Path:
    raiz = tmp_path / "plugin"
    (raiz / "hooks").mkdir(parents=True)
    for nombre in ("_comun.py", "impultienda_guard.py"):
        shutil.copy(RAIZ / "hooks" / nombre, raiz / "hooks" / nombre)
    destino = raiz / "scripts" / "trovefy"
    (destino / "tienda").mkdir(parents=True)
    (destino / "checkout").mkdir()
    for rel in ("__init__.py", "fichas.py", "tienda/__init__.py", "tienda/mcp.py", "checkout/__init__.py",
                "checkout/mensajes.py"):
        shutil.copy(RAIZ / "scripts" / "trovefy" / rel, destino / rel)
    (raiz / "config").mkdir()
    return raiz


def _correr(raiz: Path, entrada: dict, vault: Path) -> tuple[str, str]:
    proc = subprocess.run(["python3", "-s", "-E", str(raiz / "hooks" / "impultienda_guard.py")],
                          input=json.dumps(entrada), capture_output=True, text=True, timeout=30, check=False,
                          env={"TROVEFY_VAULT": str(vault), "PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"]})
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow", ""
    salida = json.loads(proc.stdout)["hookSpecificOutput"]
    return salida["permissionDecision"], salida["permissionDecisionReason"]


def test_solo_biblioteca_estandar_y_falla_cerrado(tmp_path, vault_tmp):
    raiz = _copia_plugin(tmp_path)
    shutil.copy(RAIZ / "config" / "impultienda_tools.json", raiz / "config" / "impultienda_tools.json")
    # Sin yaml ni el resto del paquete: la lectura pasa con el catálogo real.
    assert _correr(raiz, _entrada("listar_ventas", {"store_id": STORE}), vault_tmp)[0] == "allow"
    # Y una escritura aprobada también (registro de mensajes y de escrituras con la biblioteca estándar), una vez.
    _aprobar(vault_tmp, [{"herramienta": "impultienda_fijar_precio", "argumentos": FIJAR}])
    assert _correr(raiz, _entrada("fijar_precio", FIJAR), vault_tmp)[0] == "allow"
    assert _correr(raiz, _entrada("fijar_precio", FIJAR), vault_tmp)[0] == "deny"
    # Catálogo roto o mal clasificado: todo se deniega.
    (raiz / "config" / "impultienda_tools.json").write_text("{roto", encoding="utf-8")
    decision, motivo = _correr(raiz, _entrada("listar_ventas", {"store_id": STORE}), vault_tmp)
    assert decision == "deny" and motivo
    doc = json.loads((RAIZ / "config" / "impultienda_tools.json").read_text(encoding="utf-8"))
    for h in doc["herramientas"]:
        if h["nombre"] == "impultienda_conectar_pasarela":
            h["clase"] = "escritura"
    (raiz / "config" / "impultienda_tools.json").write_text(json.dumps(doc), encoding="utf-8")
    assert _correr(raiz, _entrada("listar_ventas", {"store_id": STORE}), vault_tmp)[0] == "deny"
