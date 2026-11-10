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


def test_cli_servicio_invalido(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovify.cli import main

    assert main(["navegador", "abrir", "../x", "http://127.0.0.1"]) == 2
    assert "Error" in capsys.readouterr().err


def test_cli_url_invalida(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovify.cli import main

    assert main(["navegador", "capturar", "meta", "no-es-url", "--png", "x.png"]) == 2


def test_cli_capturar_error_de_navegador_sin_traza(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import trovify.navegador as nav
    from trovify.cli import main

    def falla(*a, **k):
        raise NavegadorError("no se pudo abrir la página")

    monkeypatch.setattr(nav, "capturar", falla)
    assert main(["navegador", "capturar", "meta", "http://127.0.0.1/", "--png", "x.png"]) == 1
    err = capsys.readouterr().err
    assert "no se pudo abrir la página" in err and "Traceback" not in err


def test_lanzar_activa_sandbox(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import trovify.navegador as nav

    monkeypatch.setenv("HOME", str(tmp_path))
    p = MagicMock()
    nav._lanzar(p, "meta", True)
    kw = p.chromium.launch_persistent_context.call_args.kwargs
    assert kw["chromium_sandbox"] is True and kw["headless"] is False
    assert kw["user_data_dir"] == str(tmp_path / ".config/trovify/pw-meta")


def test_lanzar_error_en_espanol(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import trovify.navegador as nav

    monkeypatch.setenv("HOME", str(tmp_path))
    p = MagicMock()
    p.chromium.launch_persistent_context.side_effect = RuntimeError("boom")
    with pytest.raises(NavegadorError, match="RuntimeError"):
        nav._lanzar(p, "meta", True)


def test_base_privada_modos(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    perfil("meta")
    assert stat.S_IMODE((tmp_path / ".config/trovify").stat().st_mode) == 0o700


@pytest.mark.parametrize("url", [
    "https://whop.com/sign-in/?next=x",
    "https://app.impultienda.ar/auth/login",
    "https://app.impultienda.ar/auth",
    "https://app.hotmart.com/ingresar",
    "https://tienda.example.com/iniciar-sesion",
    "https://www.facebook.com/login.php",
])
def test_sesion_caducada_otras_rutas_de_login(url):
    assert sesion_caducada(url)


def test_sesion_caducada_no_confunde_rutas_parecidas():
    assert not sesion_caducada("https://blog.example.com/authors/ana")
    assert not sesion_caducada("https://app.impultienda.ar/dashboard/plan")
