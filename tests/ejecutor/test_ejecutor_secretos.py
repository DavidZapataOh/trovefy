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
    assert (
        x.telegram_user_id == 42
        and x.hmac_clave == bytes.fromhex(HMAC)
        and x.meta_token is None
    )
    assert "A" * 35 not in repr(x) and HMAC not in repr(x)
    assert stat.S_IMODE(s.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        guardar_secreto(s, "TELEGRAM_USER_ID", "99")
    guardar_secreto(s, "TELEGRAM_USER_ID", "99", sobrescribir=True)
    assert (
        cargar_secretos(s).telegram_user_id == 99
        and "TELEGRAM_BOT_TOKEN=" in s.read_text()
    )
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


SECRETO = "valorSinteticoXyz987654321"


@pytest.mark.parametrize(
    "texto",
    [
        SECRETO + "\n",
        "clave-rara-" + "x" * 60 + "=" + SECRETO + "\n",
        "minus=" + SECRETO + "\n",
        "export META_TOKEN=" + SECRETO + "\n",
        'META_TOKEN="' + SECRETO + '"\n',
        "META_TOKEN='" + SECRETO + "'\n",
        "META_TOKEN=" + SECRETO + "\nMETA_TOKEN=" + SECRETO + "\n",
        "TELEGRAM_USER_ID=" + SECRETO + "\n",
        "TELEGRAM_USER_ID=-5\n",
        "TELEGRAM_USER_ID=1_0\n",
        "TELEGRAM_USER_ID=٣٢\n",
    ],
)
def test_parseo_estricto_sin_eco(tmp_path, texto):
    s = env(tmp_path, texto)
    with pytest.raises(ValueError) as e:
        cargar_secretos(s)
    assert SECRETO not in str(e.value) and "x" * 20 not in str(e.value)


@pytest.mark.parametrize(
    "valor",
    ["a HMAC_CLAVE=00", "a\x0bb", "a\x85b", "a\x1cb", "a\x00b", " a", "a ", "a b"],
)
def test_valor_con_separadores_rechazado(tmp_path, valor):
    s = env(tmp_path, "CLAUDE_UID=1\n")
    with pytest.raises(ValueError):
        guardar_secreto(s, "META_TOKEN", valor)
    assert s.read_text() == "CLAUDE_UID=1\n"


def test_lectura_por_descriptor_y_cerrojo(tmp_path):
    s = env(tmp_path, "CLAUDE_UID=1\n")
    guardar_secreto(s, "META_TOKEN", "tokenSintetico1")
    assert (tmp_path / "secretos.env.lock").exists()
    assert not list(tmp_path.glob(".*.tmp"))
    assert cargar_secretos(s).meta_token == "tokenSintetico1"


@pytest.mark.parametrize(
    "valor",
    [
        "valorSinteticoQ1\rHMAC_CLAVE=00",
        "valorSinteticoQ1\x00",
        "valorSinteticoQ1\x1b[0m",
        "valorSinteticoQ1 ",
    ],
)
def test_lectura_rechaza_control_sin_eco(tmp_path, valor):
    s = tmp_path / "secretos.env"
    s.write_bytes(("META_TOKEN=" + valor + "\n").encode())
    os.chmod(s, 0o600)
    with pytest.raises(ValueError) as e:
        cargar_secretos(s)
    assert "valorSinteticoQ1" not in str(e.value) and "META_TOKEN" in str(e.value)


def test_crlf_se_admite(tmp_path):
    s = tmp_path / "secretos.env"
    s.write_bytes(b"CLAUDE_UID=5\r\nTELEGRAM_CHAT_ID=6\r\n")
    os.chmod(s, 0o600)
    x = cargar_secretos(s)
    assert x.claude_uid == 5 and x.telegram_chat_id == 6
