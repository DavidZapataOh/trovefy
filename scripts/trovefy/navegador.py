"""Navegador Chromium (Playwright) con un perfil persistente por servicio.

El usuario inicia sesión él mismo en la ventana visible; los verificadores reutilizan el perfil
para leer IDs. Nunca se escriben contraseñas ni se leen códigos 2FA desde aquí.
"""

from __future__ import annotations

import fcntl
import os
import random
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_SERVICIO = re.compile(r"[a-z0-9-]+")
_RUTAS_LOGIN = ("/login", "/checkpoint", "/signin", "/sign-in", "/auth", "/ingresar", "/iniciar-sesion")
# la ruta de login va seguida de /, ., -, _ o del final: «/auth/login» sí, «/authors» no
_LOGIN = re.compile("(?:" + "|".join(re.escape(r) for r in _RUTAS_LOGIN) + r")(?=[/._-]|$)")


class NavegadorError(Exception):
    """Error del navegador con un mensaje en español, apto para mostrar al usuario."""


@dataclass
class Captura:
    url_final: str
    html: str
    texto: str
    png: Path | None


def _base() -> Path:
    return Path.home() / ".config" / "trovefy"


def _base_privada() -> Path:
    base = _base()
    base.parent.mkdir(parents=True, exist_ok=True)
    base.mkdir(mode=0o700, exist_ok=True)
    base.chmod(0o700)
    return base


def perfil(servicio: str) -> Path:
    """Directorio del perfil `~/.config/trovefy/pw-<servicio>/`, creado con modo 0700."""
    if not _SERVICIO.fullmatch(servicio):
        raise ValueError("el servicio solo admite minúsculas, dígitos y guiones (a-z, 0-9, -)")
    base = _base_privada()
    ruta = base / f"pw-{servicio}"
    ruta.mkdir(mode=0o700, exist_ok=True)
    ruta.chmod(0o700)
    return ruta


def sesion_caducada(url_final: str) -> bool:
    """True si la URL final es una pantalla de login o de comprobación de seguridad."""
    return bool(_LOGIN.search(urlparse(url_final).path.lower()))


@contextmanager
def _un_navegador_a_la_vez():
    base = _base_privada()
    fd = os.open(base / "navegador.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise NavegadorError("ya hay un navegador de Trovefy abierto; ciérralo y vuelve a intentarlo") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _viewport(viewport: tuple[int, int] | None) -> dict:
    return {} if viewport is None else {"viewport": {"width": int(viewport[0]), "height": int(viewport[1])}}


def _lanzar(p, servicio: str, visible: bool, viewport: tuple[int, int] | None = None):
    try:
        return p.chromium.launch_persistent_context(
            user_data_dir=str(perfil(servicio)), headless=not visible, chromium_sandbox=True, **_viewport(viewport)
        )
    except Exception as exc:
        raise _sin_chromium(exc) from exc


def _sin_chromium(exc: Exception) -> NavegadorError:
    return NavegadorError(
        f"no se pudo iniciar Chromium ({type(exc).__name__}); comprueba que está instalado "
        "(en una terminal de Ubuntu aparte: cd ~/trovefy/trovefy && uv run playwright install chromium) y que tiene sus librerías de sistema"
    )


@contextmanager
def sesion(
    servicio: str,
    visible: bool = True,
    perfil_persistente: bool = True,
    viewport: tuple[int, int] | None = None,
) -> Iterator:
    """Página viva de Playwright con el perfil del servicio, bajo el mismo candado que `capturar`.

    Con `perfil_persistente=False` usa un contexto efímero sin perfil (vista de comprador, QA): no hay sesión
    iniciada ni se guarda nada. Cierra el contexto (y el navegador) al salir, también si algo falla dentro.
    La página no hace clics por su cuenta: quien escribe o pulsa es `trovefy.tienda.conductor.Conductor`.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    if perfil_persistente:
        perfil(servicio)  # valida el nombre antes de arrancar nada
    elif not _SERVICIO.fullmatch(servicio):
        raise ValueError("el servicio solo admite minúsculas, dígitos y guiones (a-z, 0-9, -)")
    with _un_navegador_a_la_vez(), sync_playwright() as p:
        navegador = None
        if perfil_persistente:
            ctx = _lanzar(p, servicio, visible, viewport)
        else:
            try:
                navegador = p.chromium.launch(headless=not visible, chromium_sandbox=True)
                ctx = navegador.new_context(**_viewport(viewport))
            except Exception as exc:
                if navegador is not None:
                    navegador.close()
                raise _sin_chromium(exc) from exc
        try:
            yield ctx.pages[0] if ctx.pages else ctx.new_page()
        finally:
            for cerrar in (ctx.close, navegador.close if navegador is not None else None):
                try:
                    if cerrar is not None:
                        cerrar()
                except PlaywrightError:
                    pass  # el usuario ya cerró la ventana


# Última navegación por dominio registrable (reloj monótono).
_ULTIMA_NAVEGACION: dict[str, float] = {}

# Sufijos públicos de dos niveles que usan los servicios de Trovefy (aproximación sin la Public Suffix List,
# que no está entre las dependencias): con ellos «x.impultienda.com.ar» cuenta como «impultienda.com.ar».
_SUFIJOS_DOBLES = frozenset({
    "com.ar", "net.ar", "org.ar", "gob.ar", "com.br", "net.br", "org.br", "com.mx", "org.mx", "com.co", "net.co",
    "com.pe", "com.uy", "com.py", "com.bo", "com.ec", "com.ve", "com.es", "co.uk", "org.uk", "com.au", "co.jp",
})
_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")


def dominio_registrable(host: str) -> str:
    """El dominio que se registra («app.impultienda.ar» → «impultienda.ar»); una IP o un nombre suelto, tal cual."""
    h = host.strip().lower().rstrip(".")
    if _IPV4.fullmatch(h) or ":" in h:
        return h
    partes = h.split(".")
    n = 3 if len(partes) >= 3 and ".".join(partes[-2:]) in _SUFIJOS_DOBLES else 2
    return ".".join(partes[-n:])


def esperar_entre_navegaciones(
    dominio: str,
    ahora: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
    minimo_s: float = 5.0,
    maximo_s: float = 8.0,
    azar: Callable[[float, float], float] = random.uniform,
) -> None:
    """Duerme lo que falte para que pasen entre `minimo_s` y `maximo_s` (al azar) desde la última navegación
    al mismo dominio registrable (`dominio_registrable`), y la anota.

    Contrato 8 del plan 19: 5–8 s entre navegaciones del mismo dominio, para no parecer un robot. `azar` se
    inyecta en los tests; su resultado se acota a [`minimo_s`, `maximo_s`].
    """
    clave = dominio_registrable(dominio)
    anterior = _ULTIMA_NAVEGACION.get(clave)
    if anterior is not None:
        intervalo = min(maximo_s, max(minimo_s, azar(minimo_s, maximo_s)))
        falta = intervalo - (ahora() - anterior)
        if falta > 0:
            dormir(falta)
    _ULTIMA_NAVEGACION[clave] = ahora()


def capturar(
    servicio: str,
    url: str,
    esperar_ms: int = 3000,
    visible: bool = True,
    captura_png: Path | None = None,
) -> Captura:
    """Abre `url` con el perfil del servicio y devuelve URL final, HTML y texto de la página."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    perfil(servicio)  # valida el nombre antes de arrancar nada
    with _un_navegador_a_la_vez(), sync_playwright() as p:
        ctx = _lanzar(p, servicio, visible)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="load", timeout=30_000)
                page.wait_for_timeout(esperar_ms)
                png = None
                if captura_png is not None:
                    captura_png = Path(captura_png)
                    captura_png.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(captura_png))
                    captura_png.chmod(0o600)
                    png = captura_png
                return Captura(page.url, page.content(), page.inner_text("body"), png)
            except PlaywrightError as exc:
                raise NavegadorError(f"no se pudo cargar la página ({type(exc).__name__}); revisa la URL y tu conexión") from exc
        finally:
            ctx.close()


def abrir(servicio: str, url: str, cierre_auto_ms: int | None = None) -> None:
    """Abre una ventana visible y espera a que el usuario la cierre (o a `cierre_auto_ms`)."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    perfil(servicio)
    with _un_navegador_a_la_vez(), sync_playwright() as p:
        ctx = _lanzar(p, servicio, True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightError as exc:
                raise NavegadorError(f"no se pudo cargar la página ({type(exc).__name__}); revisa la URL y tu conexión") from exc
            try:
                ctx.wait_for_event("close", timeout=cierre_auto_ms or 0)
            except (PlaywrightTimeout, KeyboardInterrupt):
                pass
        finally:
            try:
                ctx.close()
            except PlaywrightError:
                pass  # el usuario ya cerró la ventana
