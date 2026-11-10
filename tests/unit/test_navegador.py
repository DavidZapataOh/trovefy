import stat

import pytest
from trovify.navegador import NavegadorError, perfil, sesion_caducada


def test_perfil_privado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = perfil("meta")
    assert p == tmp_path / ".config/trovify/pw-meta" and stat.S_IMODE(p.stat().st_mode) == 0o700
    with pytest.raises(ValueError):
        perfil("../otro")


def test_perfil_existente_se_endurece(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".config/trovify/pw-meta"
    d.mkdir(parents=True, mode=0o755)
    d.chmod(0o755)
    assert stat.S_IMODE(perfil("meta").stat().st_mode) == 0o700


@pytest.mark.parametrize("malo", ["", "Meta", "a b", "a/b", "..", "a_b"])
def test_perfil_rechaza_nombres_invalidos(malo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError):
        perfil(malo)


def test_sesion_caducada_no_medido():
    assert sesion_caducada("https://www.facebook.com/login/?next=https%3A%2F%2Fbusiness.facebook.com")
    assert sesion_caducada("https://www.facebook.com/checkpoint/1501092823525282/")
    assert sesion_caducada("https://accounts.example.com/signin")
    assert not sesion_caducada("https://business.facebook.com/settings/?business_id=123")


def test_cli_servicio_invalido(capsys):
    from trovify.cli import main

    assert main(["navegador", "abrir", "../x", "http://127.0.0.1"]) == 2
    assert "Error" in capsys.readouterr().err


def test_cli_url_invalida(capsys):
    from trovify.cli import main

    assert main(["navegador", "capturar", "meta", "no-es-url", "--png", "x.png"]) == 2


def test_cli_capturar_error_de_navegador_sin_traza(monkeypatch, capsys):
    import trovify.navegador as nav
    from trovify.cli import main

    def falla(*a, **k):
        raise NavegadorError("no se pudo abrir la página")

    monkeypatch.setattr(nav, "capturar", falla)
    assert main(["navegador", "capturar", "meta", "http://127.0.0.1/", "--png", "x.png"]) == 1
    err = capsys.readouterr().err
    assert "no se pudo abrir la página" in err and "Traceback" not in err
