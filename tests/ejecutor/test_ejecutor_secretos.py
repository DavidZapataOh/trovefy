import os
import stat

import pytest
from trovefy_ejecutor.secretos import (
    SecretosInseguros,
    cargar_secretos,
    guardar_secreto,
)

TOKEN = "123456:" + "A" * 35
HMAC = "ab" * 32


def env(tmp_path, texto, modo=0o600):
    s = tmp_path / "secretos.env"
    s.write_text(texto)
    os.chmod(s, modo)
    return s


def test_cargar_y_guardar(tmp_path):
    s = env(tmp_path, "TELEGRAM_BOT_TOKEN=" + TOKEN + "\nHMAC_CLAVE=" + HMAC + "\n")
    guardar_secreto(s, "TELEGRAM_USER_ID", "42")
    x = cargar_secretos(s)
    assert x.telegram_user_id == 42 and x.hmac_clave == bytes.fromhex(HMAC) and x.meta_token is None
    assert "A" * 35 not in repr(x) and HMAC not in repr(x)
    assert stat.S_IMODE(s.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        guardar_secreto(s, "TELEGRAM_USER_ID", "99")
    guardar_secreto(s, "TELEGRAM_USER_ID", "99", sobrescribir=True)
    assert cargar_secretos(s).telegram_user_id == 99 and "TELEGRAM_BOT_TOKEN=" in s.read_text()
    assert stat.S_IMODE(s.stat().st_mode) == 0o600


def test_crea_archivo_0600(tmp_path):
    s = tmp_path / "nuevo.env"
    guardar_secreto(s, "META_TOKEN", "EAAx")
    assert stat.S_IMODE(s.stat().st_mode) == 0o600
    assert cargar_secretos(s).meta_token == "EAAx"


def test_ausente(tmp_path):
    with pytest.raises(FileNotFoundError):
        cargar_secretos(tmp_path / "no.env")


@pytest.mark.parametrize("modo", [0o640, 0o604, 0o644])
def test_permisos_inseguros(tmp_path, modo):
    s = env(tmp_path, "HMAC_CLAVE=" + HMAC + "\n", modo)
    with pytest.raises(SecretosInseguros) as e:
        cargar_secretos(s)
    assert HMAC not in str(e.value) and str(s) in str(e.value)
    with pytest.raises(SecretosInseguros):
        guardar_secreto(s, "META_TOKEN", "x")


def test_enlace_y_claves(tmp_path):
    s = env(tmp_path, "HMAC_CLAVE=" + HMAC + "\n")
    link = tmp_path / "l.env"
    link.symlink_to(s)
    with pytest.raises(SecretosInseguros):
        cargar_secretos(link)
    with pytest.raises(ValueError):
        guardar_secreto(s, "OTRA", "x")
    with pytest.raises(ValueError):
        guardar_secreto(s, "META_TOKEN", "EAAx\nHMAC_CLAVE=00")
    with pytest.raises(SecretosInseguros):
        cargar_secretos(env(tmp_path, "HMAC_CLAVE=abcd\n"))


def test_clave_desconocida_no_filtra_valor(tmp_path):
    s = env(tmp_path, "RARA=valorsecreto123\n")
    with pytest.raises(ValueError) as e:
        cargar_secretos(s)
    assert "RARA" in str(e.value) and "valorsecreto123" not in str(e.value)


def test_hmac_invalida_no_filtra(tmp_path):
    with pytest.raises(SecretosInseguros) as e:
        cargar_secretos(env(tmp_path, "HMAC_CLAVE=zz\n"))
    assert "zz" not in str(e.value).replace("HMAC_CLAVE demasiado corta", "")


def test_comentarios_y_vacias(tmp_path):
    s = env(tmp_path, "# c\n\nTELEGRAM_CHAT_ID=7\nCLAUDE_UID=1001\n")
    x = cargar_secretos(s)
    assert x.telegram_chat_id == 7 and x.claude_uid == 1001
