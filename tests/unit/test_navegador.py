import stat

import pytest
from trovefy.navegador import NavegadorError, perfil, sesion_caducada


def test_perfil_privado(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = perfil("meta")
    assert p == tmp_path / ".config/trovefy/pw-meta" and stat.S_IMODE(p.stat().st_mode) == 0o700
    with pytest.raises(ValueError):
        perfil("../otro")


def test_perfil_existente_se_endurece(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".config/trovefy/pw-meta"
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
    from trovefy.cli import main

    assert main(["navegador", "abrir", "../x", "http://127.0.0.1"]) == 2
    assert "Error" in capsys.readouterr().err


def test_cli_url_invalida(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from trovefy.cli import main

    assert main(["navegador", "capturar", "meta", "no-es-url", "--png", "x.png"]) == 2


def test_cli_capturar_error_de_navegador_sin_traza(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import trovefy.navegador as nav
    from trovefy.cli import main

    def falla(*a, **k):
        raise NavegadorError("no se pudo abrir la página")

    monkeypatch.setattr(nav, "capturar", falla)
    assert main(["navegador", "capturar", "meta", "http://127.0.0.1/", "--png", "x.png"]) == 1
    err = capsys.readouterr().err
    assert "no se pudo abrir la página" in err and "Traceback" not in err


def test_lanzar_activa_sandbox(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import trovefy.navegador as nav

    monkeypatch.setenv("HOME", str(tmp_path))
    p = MagicMock()
    nav._lanzar(p, "meta", True)
    kw = p.chromium.launch_persistent_context.call_args.kwargs
    assert kw["chromium_sandbox"] is True and kw["headless"] is False
    assert kw["user_data_dir"] == str(tmp_path / ".config/trovefy/pw-meta")


def test_lanzar_error_en_espanol(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import trovefy.navegador as nav

    monkeypatch.setenv("HOME", str(tmp_path))
    p = MagicMock()
    p.chromium.launch_persistent_context.side_effect = RuntimeError("boom")
    with pytest.raises(NavegadorError, match="RuntimeError"):
        nav._lanzar(p, "meta", True)


def test_base_privada_modos(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    perfil("meta")
    assert stat.S_IMODE((tmp_path / ".config/trovefy").stat().st_mode) == 0o700


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


class _PlaywrightFalso:
    """`sync_playwright()` falso: devuelve un MagicMock como `p` y anota si se cerró."""

    def __init__(self):
        from unittest.mock import MagicMock

        self.p = MagicMock()
        self.ctx = self.p.chromium.launch_persistent_context.return_value
        self.ctx.pages = []
        self.navegador = self.p.chromium.launch.return_value
        self.efimero = self.navegador.new_context.return_value
        self.efimero.pages = []

    def __call__(self):
        return self

    def __enter__(self):
        return self.p

    def __exit__(self, *_a):
        return None


@pytest.fixture
def pw_falso(tmp_path, monkeypatch):
    import playwright.sync_api

    monkeypatch.setenv("HOME", str(tmp_path))
    falso = _PlaywrightFalso()
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", falso)
    return falso


def test_sesion_con_perfil_y_viewport(pw_falso, tmp_path):
    from trovefy.navegador import sesion

    with sesion("impultienda", visible=True, viewport=(390, 844)) as page:
        assert page is pw_falso.ctx.new_page.return_value
        pw_falso.ctx.close.assert_not_called()
    kw = pw_falso.p.chromium.launch_persistent_context.call_args.kwargs
    assert kw["user_data_dir"] == str(tmp_path / ".config/trovefy/pw-impultienda")
    assert kw["headless"] is False and kw["chromium_sandbox"] is True
    assert kw["viewport"] == {"width": 390, "height": 844}
    pw_falso.ctx.close.assert_called_once()


def test_sesion_sin_perfil_es_efimera(pw_falso, tmp_path):
    from trovefy.navegador import sesion

    with sesion("comprador", visible=False, perfil_persistente=False) as page:
        assert page is pw_falso.efimero.new_page.return_value
    pw_falso.p.chromium.launch_persistent_context.assert_not_called()
    assert pw_falso.p.chromium.launch.call_args.kwargs == {"headless": True, "chromium_sandbox": True}
    assert pw_falso.navegador.new_context.call_args.kwargs == {}
    pw_falso.efimero.close.assert_called_once()
    pw_falso.navegador.close.assert_called_once()
    assert not (tmp_path / ".config/trovefy/pw-comprador").exists()


def test_sesion_cierra_aunque_falle_y_suelta_el_candado(pw_falso):
    from trovefy.navegador import sesion

    with pytest.raises(RuntimeError), sesion("impultienda"):
        raise RuntimeError("parada")
    pw_falso.ctx.close.assert_called_once()
    with sesion("impultienda"):  # el candado quedó libre
        pass


def test_sesion_un_navegador_a_la_vez(pw_falso):
    from trovefy.navegador import sesion

    with sesion("impultienda"), pytest.raises(NavegadorError, match="ya hay un navegador"), sesion("meta"):
        pass


def test_sesion_rechaza_servicio_invalido(pw_falso):
    from trovefy.navegador import sesion

    with pytest.raises(ValueError), sesion("../x", perfil_persistente=False):
        pass


def test_sesion_efimera_admite_opciones_de_contexto_internas(pw_falso):
    """Plan 18 (QA): `_contexto` solo en la ruta efímera (service workers bloqueados, móvil con DPR 2)."""
    from trovefy.navegador import sesion

    opciones = {"service_workers": "block", "is_mobile": True, "device_scale_factor": 2}
    with sesion("qa-landing", visible=False, perfil_persistente=False, viewport=(390, 844), _contexto=opciones):
        pass
    assert pw_falso.navegador.new_context.call_args.kwargs == {
        "viewport": {"width": 390, "height": 844}, **opciones}
    with pytest.raises(ValueError, match="efímer"), sesion("impultienda", _contexto={"is_mobile": True}):
        pass
    pw_falso.p.chromium.launch_persistent_context.assert_not_called()
