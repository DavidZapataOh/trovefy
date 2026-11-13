"""``borrar_secretos`` (plan 12, tarea 7): quita claves sin tocar el resto ni dejar temporales."""
from __future__ import annotations

import os

import pytest
from trovefy_ejecutor import secretos as mod
from trovefy_ejecutor.secretos import (
    SecretosInseguros,
    borrar_secretos,
    cargar_secretos,
)


@pytest.fixture
def env(tmp_path):
    f = tmp_path / "secretos.env"
    f.write_text("# nota\nMETA_TOKEN=a1\nTELEGRAM_USER_ID=7\nTELEGRAM_CHAT_ID=7\n# fin\n")
    os.chmod(f, 0o600)
    return f


def _temporales(f):
    return [p.name for p in f.parent.iterdir() if p.name.endswith(".tmp")]


def test_borra_y_conserva_el_resto(env):
    borrar_secretos(env, ("TELEGRAM_USER_ID", "TELEGRAM_CHAT_ID", "HMAC_CLAVE"))  # HMAC ausente: se ignora
    assert env.read_text() == "# nota\nMETA_TOKEN=a1\n# fin\n"
    assert (env.stat().st_mode & 0o777) == 0o600
    s = cargar_secretos(env)
    assert s.meta_token == "a1" and s.telegram_user_id is None
    assert _temporales(env) == []


def test_clave_desconocida_no_toca(env):
    antes = env.read_bytes()
    with pytest.raises(ValueError, match="desconocida"):
        borrar_secretos(env, ("TELEGRAM_USER_ID", "NO_EXISTE"))
    assert env.read_bytes() == antes


def test_permisos_laxos(env):
    os.chmod(env, 0o644)
    antes = env.read_bytes()
    with pytest.raises(SecretosInseguros):
        borrar_secretos(env, ("TELEGRAM_USER_ID",))
    assert env.read_bytes() == antes and _temporales(env) == []


def test_archivo_ausente(tmp_path):
    f = tmp_path / "secretos.env"
    with pytest.raises(FileNotFoundError):
        borrar_secretos(f, ("TELEGRAM_USER_ID",))
    assert not f.exists()


def test_fallo_al_escribir_deja_el_original(env, monkeypatch):
    antes = env.read_bytes()

    def mal(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(mod.os, "replace", mal)
    with pytest.raises(OSError):
        borrar_secretos(env, ("TELEGRAM_USER_ID",))
    assert env.read_bytes() == antes and _temporales(env) == []
