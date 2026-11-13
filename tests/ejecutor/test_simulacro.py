"""Simulacro de extremo a extremo (plan 12, Tarea 6) e integración con el Telegram falso (cliente real)."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timedelta

import yaml
from ejecutor.conftest import datos_limites
from ejecutor.falsos.telegram_falso import TOKEN_PRUEBA, TelegramFalso
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor.callbacks import firmar
from trovefy_ejecutor.config import RutasEjecutor
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.secretos import Secretos
from trovefy_ejecutor.servicio import Ejecutor
from trovefy_ejecutor.simulado import GraphSimulado, simulacro
from trovefy_ejecutor.telegram import ClienteTelegram

NOMBRES = ["noop → Aceptar → registro", "presupuesto → Rechazar con motivo", "doble toque", "toque tardío",
           "STOP activo", "callback falsificado", "crear_estructura_pausada",
           "STOP y luego /pausar_todo responde", "reinicio en ejecutando no reescribe"]


def test_simulacro_completo(tmp_path):
    _ejecutar._EMITIDOS.clear()
    lineas: list[str] = []
    pasos = simulacro(tmp_path, lineas.append)
    assert [n for n, _ in pasos] == NOMBRES
    assert all(ok for _, ok in pasos), lineas
    assert [bool(re.match(r"(OK|FALLO)\b", ln)) for ln in lineas if ln.split(" ")[0] in ("OK", "FALLO")]
    assert sum(ln.startswith("OK") for ln in lineas) == len(NOMBRES)
    assert not any(re.search(r"bot\d+:|EAA|\d{6}:[A-Za-z0-9_-]{35}", ln) for ln in lineas)


def test_simulacro_no_deja_secretos_ni_toca_fuera_de_raiz(tmp_path):
    _ejecutar._EMITIDOS.clear()
    raiz = tmp_path / "sim"
    lineas: list[str] = []
    simulacro(raiz, lineas.append)
    env = raiz / "secretos.env"
    assert env.exists() and stat.S_IMODE(env.stat().st_mode) == 0o600
    clave = re.search(r"HMAC_CLAVE=([0-9a-f]+)", env.read_text()).group(1)
    assert len(clave) >= 64 and not any(clave in ln for ln in lineas)
    for f in raiz.rglob("*"):
        if f.is_file() and f.name != "secretos.env":
            assert clave not in f.read_text(errors="ignore"), f
    assert [p.name for p in tmp_path.iterdir()] == ["sim"]


def test_simulacro_repetido_en_otra_raiz_da_lo_mismo(tmp_path):
    _ejecutar._EMITIDOS.clear()
    a = simulacro(tmp_path / "a", lambda _l: None)
    _ejecutar._EMITIDOS.clear()
    b = simulacro(tmp_path / "b", lambda _l: None)
    assert a == b and all(ok for _, ok in a)


def test_simulado_no_importa_de_tests():
    from pathlib import Path

    import trovefy_ejecutor.simulado as s
    fuente = Path(s.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(tests|ejecutor\.|ejecutor\s)", fuente, re.MULTILINE)


# -- integración: ClienteTelegram real contra TelegramFalso ----------------------------------------
def _ejecutor_con(cliente, tmp_path):
    _ejecutar._EMITIDOS.clear()
    rutas = RutasEjecutor(secretos=tmp_path / "secretos.env", limites=tmp_path / "limites.yaml",
                          base=tmp_path / "datos" / "estado.sqlite", auditoria=tmp_path / "datos" / "auditoria.jsonl",
                          stop=tmp_path / "datos" / "STOP", spool=tmp_path / "spool", vault=tmp_path / "vault")
    d = datos_limites(1)
    rutas.limites.write_text(yaml.safe_dump(d))
    os.chmod(rutas.limites, 0o600)
    (tmp_path / "vault").mkdir()
    secretos = Secretos(meta_token="EAAno-se-usa", telegram_bot_token=TOKEN_PRUEBA, hmac_clave=b"h" * 32,
                        telegram_user_id=42, telegram_chat_id=42, claude_uid=os.geteuid())
    return Ejecutor(rutas, cliente, GraphSimulado(), secretos, reloj=lambda: datetime.now(ZONA_COT),
                    modo="simulado")


def test_noop_con_cliente_real_y_telegram_falso(tmp_path):
    with TelegramFalso() as tg:
        ej = _ejecutor_con(ClienteTelegram(TOKEN_PRUEBA, base=tg.base), tmp_path)
        try:
            ahora = datetime.now(ZONA_COT)
            id = f"P-{ahora:%Y%m%d}-001"
            d = {"version": 1, "id": id, "tipo": "noop", "creada": (ahora - timedelta(minutes=1)).isoformat(),
                 "origen": "/probar", "motivo": "Prueba", "prioridad": "alta", "expira_en_min": 30}
            ruta = ej.rutas.spool / "entrada" / f"{id}.json"
            ruta.write_text(json.dumps(d), encoding="utf-8")
            os.utime(ruta, (ahora.timestamp() - 60,) * 2)
            ej.ciclo()
            (mid,) = list(tg.mensajes)
            tg.meter_toque(firmar(id, "A", 42, ej.secretos.hmac_clave), 42, 42, mid)
            ej.ciclo()
            assert ej.almacen.obtener(id).estado == "ejecutada"
            assert any(ll.metodo == "answerCallbackQuery" for ll in tg.llamadas)
        finally:
            ej.almacen.cerrar()
            _ejecutar._EMITIDOS.clear()
