"""Conductor de navegador: el único componente de Trovefy que escribe o pulsa en una pantalla, y se para.

Todo sale del mapa (`trovefy.mapa`): el conductor no conoce Impultienda ni Hotmart. Antes de cada acción
comprueba que la pantalla no es `prohibida`, que el control no es `secreto`, que la pantalla está confirmada
(su propio `capturado`), que la sesión no caducó, que el origen (esquema, host y puerto) está permitido, que
la URL actual no es de cobros y que la firma sigue en la página; después, que el control casa con exactamente
un elemento. Si algo no casa lanza una `Parada` (motivo en español) y no toca nada más: tras una parada de
pantalla hay que volver a `ir()` antes de leer, escribir o capturar otra vez.

Comprobar y actuar no son atómicos (la página puede navegar entre medias: H-1 de la revisión). Por eso:

1. tras las comprobaciones se **fija** el elemento (`element_handle`): las acciones van a ese elemento
   concreto y, si la página navega, fallan en vez de caer en un campo de otra pantalla con la misma etiqueta;
2. con el elemento fijado se vuelven a comprobar firma, sesión, origen y zona de cobro (la URL, la última);
3. se actúa con un tiempo corto (la página entera tiene un tiempo por defecto de pocos segundos);
4. después de cada acción se mira otra vez el origen y las palabras prohibidas de la URL: si cambiaron,
   `Parada` (la acción sí se hizo; lo siguiente no);
5. si Playwright falla a mitad de una acción, `AccionIncierta`: no sé si se aplicó, y no sigo.

Espera entre navegaciones: 5–8 s al azar por dominio registrable, en `ir()` y también tras un `pulsar` que
navega. Lo segundo es *best effort*: solo se ve la navegación que ya empezó cuando `click` devuelve (Playwright
espera a las que el clic inicia); una redirección diferida (un `setTimeout`) no se detecta aquí, pero la
siguiente acción la descubre por la firma o el origen y se para.

Los controles `secreto` (token CAPI) nunca se leen: `configurado()` solo dice si tienen valor, el valor no sale
del navegador, y las capturas los enmascaran junto con todos los campos (`input`, `textarea`, editables).

**Quien llama** debe pasar por `trovefy.secretos.buscar_secreto` todo texto que devuelvan `ir()` y `leer()` antes
de guardarlo, mostrarlo o mandarlo a otro sitio: el texto visible de una pantalla puede llevar un token.
"""

from __future__ import annotations

import contextlib
import os
import random
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from trovefy.mapa import (
    Control,
    FirmaAusente,
    capturado_de,
    control,
    controles_de,
    leer_pantalla,
    origen,
    origenes_de,
    palabra_prohibida,
    prohibida,
)
from trovefy.navegador import (
    NavegadorError,
    esperar_entre_navegaciones,
    sesion_caducada,
)


class Parada(Exception):
    """El conductor se detuvo sin tocar nada más. `pantalla` y `motivo` (en español, apto para el usuario)."""

    def __init__(self, pantalla: str, motivo: str):
        super().__init__(f"{pantalla}: {motivo}")
        self.pantalla = pantalla
        self.motivo = motivo


class FirmaNoCasa(Parada):
    """La página no es la pantalla esperada (o cambió desde la última comprobación)."""


class SelectorAusente(Parada):
    """El control no casa con exactamente un elemento: nunca se pulsa a ciegas."""


class HostNoPermitido(Parada):
    """La URL (pedida o actual) está fuera de los orígenes del mapa (esquema, host y puerto)."""


class ZonaProhibida(Parada):
    """Pantalla de cobros, pasarelas, retiros, tarjetas, bancos o contraseñas: no se escribe ni se captura."""


class SesionCaducada(Parada):
    """La página acabó en una pantalla de login o de comprobación de seguridad."""


class MapaSinConfirmar(Parada):
    """La pantalla no tiene su propio `capturado`: se puede leer, no escribir."""


class ControlSecreto(Parada):
    """El control es secreto: no se lee ni se escribe su valor (solo `configurado`)."""


class AccionIncierta(Parada):
    """Playwright falló a mitad de una acción (o de una lectura): no sé si se aplicó."""


_VALOR_URL = re.compile(r"[A-Za-z0-9._~-]+")
_CON_VALOR = ("texto", "numero", "precio", "area")
_JS_TIENE_VALOR = "e => (e.value || '').trim().length > 0"
_JS_OPCION = "e => e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : null"
_INTENTOS_FIRMA = 4  # la página puede tardar en pintar el panel: hasta 3 s más antes de parar (solo en ir/_en)
_PAUSA_FIRMA_S = 1.0
_TIMEOUT_PAGINA_MS = 5_000  # por defecto para toda la página: nada se queda reintentando mucho rato
_TIMEOUT_FIJAR_MS = 2_000
_TIMEOUT_ACCION_MS = 3_000
_TIMEOUT_CAPTURA_MS = 10_000
_CSS_CAMPOS = "input, textarea, [contenteditable]"  # se tapan siempre en las capturas (input incluye contraseñas)
_PARADAS_DE_PANTALLA = (FirmaNoCasa, SelectorAusente, HostNoPermitido, SesionCaducada, ZonaProhibida, AccionIncierta)


def _donde(url: str) -> str:
    """Esquema, host y puerto de `url` para un mensaje (sin ruta ni consulta, que pueden llevar datos)."""
    try:
        u = urlparse(url)
        puerto = f":{u.port}" if u.port else ""
    except ValueError:
        return "una dirección que no entiendo"
    return f"{u.scheme}://{u.hostname or ''}{puerto}" if u.hostname else (u.scheme or url[:20])


class Conductor:
    """Conduce una página de Playwright (`trovefy.navegador.sesion`) siguiendo el mapa de un servicio.

    Fija el tiempo por defecto de la página a unos segundos (`page.set_default_timeout`).
    """

    def __init__(
        self,
        page,
        mapa: dict,
        servicio: str,
        dormir: Callable[[float], None] = time.sleep,
        ahora: Callable[[], float] = time.monotonic,
        azar: Callable[[float, float], float] = random.uniform,
    ):
        self.page = page
        self.mapa = mapa
        self.servicio = servicio
        self._dormir = dormir
        self._ahora = ahora
        self._azar = azar
        self._origenes = origenes_de(mapa)
        self._secretos = [c for nombre in mapa["pantallas"] for c in controles_de(mapa, nombre) if c.secreto]
        self._actual: str | None = None
        page.set_default_timeout(_TIMEOUT_PAGINA_MS)

    # --- comprobaciones -------------------------------------------------------------------------

    def _parar(self, parada: Parada) -> Parada:
        if isinstance(parada, _PARADAS_DE_PANTALLA):
            self._actual = None
        return parada

    def _pantalla(self, pantalla: str) -> dict:
        try:
            return self.mapa["pantallas"][pantalla]
        except KeyError:
            raise KeyError(f"no hay pantalla «{pantalla}» en el mapa") from None

    def _esperar(self, url: str) -> None:
        esperar_entre_navegaciones(urlparse(url).hostname or "", ahora=self._ahora, dormir=self._dormir, azar=self._azar)

    def _comprobar_url(self, pantalla: str, zona: bool) -> None:
        """Sesión, origen y (si `zona`) palabras prohibidas, sobre una sola lectura de la URL actual."""
        url = self.page.url
        if sesion_caducada(url):
            inicio = urlparse(self._pantalla(pantalla)["url"])
            raise self._parar(SesionCaducada(
                pantalla,
                f"la sesión de {self.servicio} caducó (la página acabó en el login). Inicia sesión con "
                f"`trovefy navegador abrir {self.servicio} {inicio.scheme}://{inicio.netloc}/` y vuelve a lanzar. "
                "No he tocado nada más.",
            ))
        if origen(url) not in self._origenes:
            raise self._parar(HostNoPermitido(
                pantalla, f"la página está en «{_donde(url)}», que no es de {self.servicio} según el mapa; no toco nada."
            ))
        if zona:
            palabra = palabra_prohibida(url)
            if palabra:
                raise self._parar(ZonaProhibida(
                    pantalla, f"la página actual parece de cobros o datos sensibles («{palabra}»): aquí nunca escribo."
                ))

    def _texto(self) -> str | None:
        from playwright.sync_api import Error as PlaywrightError

        try:
            return self.page.inner_text("body")
        except PlaywrightError:  # la página navegaba o se cerró mientras se leía (también TimeoutError)
            return None

    def _firma_no_casa(self, pantalla: str, texto: str | None) -> FirmaNoCasa:
        faltan = [t for t in self._pantalla(pantalla)["firma"] if texto is None or t not in texto]
        return self._parar(FirmaNoCasa(
            pantalla,
            f"la pantalla no casa con el mapa (falta: {', '.join(f'«{t}»' for t in faltan)}). "
            "Puede que haya cambiado: no toco nada. Abre tú la pantalla y avisa.",
        ))

    def _texto_con_firma(self, pantalla: str, intentos: int = _INTENTOS_FIRMA) -> str:
        p = self._pantalla(pantalla)
        texto = None
        for intento in range(intentos):
            texto = self._texto()
            if texto is not None:
                try:
                    leer_pantalla(p, texto)
                    return texto
                except FirmaAusente:
                    pass
            if intento + 1 < intentos:
                self._dormir(_PAUSA_FIRMA_S)
        raise self._firma_no_casa(pantalla, texto)

    def _en(self, pantalla: str, zona: bool) -> None:
        """Sigo en `pantalla`, con sesión, origen permitido, (si `zona`) URL sin cobros y firma vigente."""
        if self._actual != pantalla:
            raise self._parar(FirmaNoCasa(
                pantalla, f"no estoy en «{pantalla}» (o la última comprobación falló): primero hay que ir a ella."
            ))
        self._comprobar_url(pantalla, zona)
        self._texto_con_firma(pantalla)

    def _recomprobar(self, pantalla: str, zona: bool) -> None:
        """Con el elemento ya fijado: firma (una sola lectura, sin esperas) y, la última, la URL."""
        self._texto_con_firma(pantalla, intentos=1)
        self._comprobar_url(pantalla, zona)

    def _tras_accion(self, pantalla: str, que: str) -> None:
        """Después de actuar: si la URL salió de los orígenes o es de cobros, paro (lo anterior sí se hizo)."""
        url = self.page.url
        if origen(url) not in self._origenes:
            raise self._parar(HostNoPermitido(
                pantalla, f"después de {que}, la página fue a «{_donde(url)}», fuera de {self.servicio}: "
                "lo anterior sí se hizo; no sigo. Revisa la pantalla tú.",
            ))
        palabra = palabra_prohibida(url)
        if palabra:
            raise self._parar(ZonaProhibida(
                pantalla, f"después de {que}, la página fue a una zona de cobros o datos sensibles («{palabra}»): "
                "lo anterior sí se hizo; no sigo. Revisa la pantalla tú.",
            ))

    def _localizador(self, c: Control):
        if c.rol:
            return self.page.get_by_role(c.rol, name=c.etiqueta, exact=True)
        if c.etiqueta:
            return self.page.get_by_label(c.etiqueta, exact=True)
        return self.page.locator(c.css)

    def _uno(self, c: Control):
        loc = self._localizador(c)
        n = loc.count()
        if n == 1:
            return loc
        donde = f"etiqueta «{c.etiqueta}»" if c.etiqueta else f"selector «{c.css}»"
        if n == 0:
            motivo = f"no encuentro el control «{c.nombre}» ({donde}): la pantalla cambió; no toco nada."
        else:
            motivo = f"el control «{c.nombre}» ({donde}) casa con {n} elementos: no pulso a ciegas."
        raise self._parar(SelectorAusente(c.pantalla, motivo))

    def _fijar(self, c: Control, zona: bool):
        """El elemento concreto del control, fijado y con todo comprobado otra vez después de fijarlo."""
        loc = self._uno(c)
        try:
            h = loc.element_handle(timeout=_TIMEOUT_FIJAR_MS)
        except Exception as exc:
            raise self._parar(SelectorAusente(
                c.pantalla, f"no he podido fijar el control «{c.nombre}» ({type(exc).__name__}): la pantalla cambió; "
                "no he tocado nada.",
            )) from exc
        if h is None:
            raise self._parar(SelectorAusente(c.pantalla, f"el control «{c.nombre}» desapareció: no he tocado nada."))
        self._recomprobar(c.pantalla, zona)
        return h

    def _actuar(self, c: Control, verbo: str, accion: Callable[[], object], escribe: bool = True):
        """Ejecuta una llamada de Playwright; si falla, `AccionIncierta` y nada más hasta un nuevo `ir()`."""
        try:
            return accion()
        except Parada:
            raise
        except Exception as exc:
            self._actual = None
            if escribe:
                motivo = (f"Playwright falló al {verbo} «{c.nombre}» ({type(exc).__name__}): no sé si se aplicó. "
                          "Revisa la pantalla tú antes de seguir; no toco nada más.")
            else:
                motivo = (f"no he podido {verbo} «{c.nombre}» ({type(exc).__name__}): la pantalla cambió mientras "
                          "leía. No he escrito nada; no sigo.")
            raise AccionIncierta(c.pantalla, motivo) from exc

    def _para_escribir(self, pantalla: str, nombre: str) -> Control:
        c = control(self.mapa, pantalla, nombre)
        if prohibida(self.mapa, pantalla):
            raise self._parar(ZonaProhibida(
                pantalla, "pantalla prohibida (cobros, pasarelas, retiros, tarjetas, bancos o contraseñas): solo se lee."
            ))
        if c.secreto:
            raise ControlSecreto(pantalla, f"«{nombre}» es secreto: lo pega el usuario en la ventana visible, nunca Trovefy.")
        if capturado_de(self.mapa, pantalla) is None:
            raise MapaSinConfirmar(pantalla, f"no medido: mapa sin confirmar ({pantalla})")
        return c

    # --- API ------------------------------------------------------------------------------------

    def ir(self, pantalla: str, **valores_url: str) -> str:
        """Navega a la pantalla (respetando la espera por dominio) y devuelve el texto visible si casa.

        El texto puede llevar datos sensibles: pásalo por `trovefy.secretos.buscar_secreto` antes de guardarlo.
        """
        p = self._pantalla(pantalla)
        self._actual = None
        for clave, valor in valores_url.items():
            if not _VALOR_URL.fullmatch(str(valor)):
                raise ValueError(f"valor no válido para «{clave}» en la URL de «{pantalla}»: solo letras, dígitos, . _ ~ -")
        url = p["url"].format(**valores_url)
        if origen(url) not in self._origenes:
            raise self._parar(HostNoPermitido(
                pantalla, f"la URL de «{pantalla}» va a «{_donde(url)}», fuera de los orígenes del mapa (https)."
            ))
        self._esperar(url)
        try:
            self.page.goto(url, wait_until="load", timeout=30_000)
        except Exception as exc:  # errores de Playwright: red, tiempo, página cerrada
            raise NavegadorError(f"no se pudo cargar «{pantalla}» ({type(exc).__name__}); revisa tu conexión") from exc
        self._comprobar_url(pantalla, zona=False)
        texto = self._texto_con_firma(pantalla)
        self._actual = pantalla
        return texto

    def leer(self, pantalla: str, nombre: str) -> str | bool | None:
        """Valor actual del control, leído del DOM (`None` para un archivo: no se puede releer).

        Pasa el valor por `trovefy.secretos.buscar_secreto` antes de guardarlo o mostrarlo.
        """
        c = control(self.mapa, pantalla, nombre)
        if c.secreto:
            raise ControlSecreto(pantalla, f"«{nombre}» es secreto: no se lee; usa configurado() para saber si tiene valor.")
        if c.tipo == "boton":
            raise TypeError(f"«{nombre}» es un botón: no tiene valor que leer")
        self._en(pantalla, zona=False)
        h = self._fijar(c, zona=False)

        def valor():
            if c.tipo in _CON_VALOR:
                return h.input_value(timeout=_TIMEOUT_ACCION_MS)
            if c.tipo == "select":
                return h.evaluate(_JS_OPCION)
            if c.tipo == "interruptor":
                return h.is_checked()
            return None  # archivo

        return self._actuar(c, "leer", valor, escribe=False)

    def configurado(self, pantalla: str, nombre: str) -> bool:
        """True si el control tiene valor no vacío. El valor nunca sale del navegador."""
        c = control(self.mapa, pantalla, nombre)
        if c.tipo == "boton":
            raise TypeError(f"«{nombre}» es un botón: no tiene valor")
        self._en(pantalla, zona=False)
        h = self._fijar(c, zona=False)

        def tiene_valor() -> bool:
            if c.tipo == "interruptor":
                return bool(h.is_checked())
            if c.tipo == "select":
                return h.evaluate(_JS_OPCION) is not None
            return bool(h.evaluate(_JS_TIENE_VALOR))

        return self._actuar(c, "comprobar", tiene_valor, escribe=False)

    def poner(self, pantalla: str, nombre: str, valor: str | bool | Path) -> None:
        """Escribe `valor` en el control, solo si todas las comprobaciones pasan (antes y después de fijarlo)."""
        c = self._para_escribir(pantalla, nombre)
        valor = _validar_valor(c, valor)
        self._en(pantalla, zona=True)
        h = self._fijar(c, zona=True)
        t = _TIMEOUT_ACCION_MS
        if c.tipo in _CON_VALOR:
            self._actuar(c, "escribir en", lambda: h.fill(valor, timeout=t))
        elif c.tipo == "select":
            self._actuar(c, "elegir en", lambda: h.select_option(label=valor, timeout=t))
        elif c.tipo == "interruptor":
            self._actuar(c, "cambiar", lambda: h.check(timeout=t) if valor else h.uncheck(timeout=t))
        else:  # archivo
            self._actuar(c, "subir el archivo a", lambda: h.set_input_files(valor, timeout=t))
        self._tras_accion(pantalla, f"escribir en «{nombre}»")

    def pulsar(self, pantalla: str, nombre: str) -> None:
        """Pulsa un control `boton`, con las mismas guardas que `poner`; si navega, respeta la espera."""
        c = self._para_escribir(pantalla, nombre)
        if c.tipo != "boton":
            raise TypeError(f"«{nombre}» es de tipo {c.tipo}: solo se pulsan botones (usa poner())")
        self._en(pantalla, zona=True)
        h = self._fijar(c, zona=True)
        antes = urldefrag(self.page.url).url
        self._actuar(c, "pulsar", lambda: h.click(timeout=_TIMEOUT_ACCION_MS))
        self._tras_accion(pantalla, f"pulsar «{nombre}»")
        despues = self.page.url
        if urldefrag(despues).url != antes:
            self._esperar(despues)

    def capturar(self, ruta: Path) -> Path:
        """Captura de la pantalla actual (archivo nuevo 0600, sin seguir enlaces) con secretos y campos tapados.

        Para (`Parada`) si no hay pantalla comprobada, si es `prohibida`, si la URL no es de un origen del mapa o
        es de cobros, si la firma no casa, si un control secreto de la pantalla no casa con un solo elemento (no
        se podría tapar) o si la página se fue a otro sitio durante la captura (entonces no se guarda nada).
        """
        pantalla = self._actual
        if pantalla is None:
            raise Parada("captura", "no estoy en ninguna pantalla comprobada: primero hay que ir() a una; no capturo.")
        if prohibida(self.mapa, pantalla):
            raise ZonaProhibida(pantalla, "pantalla prohibida (cobros, pasarelas, retiros, tarjetas, bancos o "
                                          "contraseñas): no se captura.")
        self._en(pantalla, zona=True)
        for c in controles_de(self.mapa, pantalla):
            if c.secreto:
                self._uno(c)
        mascaras = [self._localizador(c) for c in self._secretos]
        mascaras.append(self.page.locator(_CSS_CAMPOS))
        try:
            datos = self.page.screenshot(mask=mascaras, timeout=_TIMEOUT_CAPTURA_MS)
        except Exception as exc:
            raise self._parar(AccionIncierta(
                pantalla, f"no he podido hacer la captura ({type(exc).__name__}); no se ha guardado nada."
            )) from exc
        self._tras_accion(pantalla, "capturar")
        return _guardar_privado(Path(ruta), datos)


def _guardar_privado(ruta: Path, datos: bytes) -> Path:
    """Escribe `datos` en un temporal nuevo (0600, O_EXCL) y lo renombra a `ruta`: nunca sigue un enlace."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(datos)
        os.replace(tmp, ruta)  # sustituye el propio enlace si lo hubiera, no su destino
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    return ruta


def _validar_valor(c: Control, valor):
    """El valor listo para Playwright, o `TypeError`/`FileNotFoundError` antes de tocar nada."""
    if c.tipo == "boton":
        raise TypeError(f"«{c.nombre}» es un botón: se pulsa con pulsar(), no se pone")
    if c.tipo == "interruptor":
        if not isinstance(valor, bool):
            raise TypeError(f"«{c.nombre}» es un interruptor: el valor debe ser True o False")
        return valor
    if c.tipo == "archivo":
        if not isinstance(valor, Path):
            raise TypeError(f"«{c.nombre}» es un archivo: el valor debe ser una ruta (Path)")
        if not valor.is_file():
            raise FileNotFoundError(f"no existe el archivo para «{c.nombre}»: {valor}")
        return str(valor)
    if not isinstance(valor, str):  # nunca float ni bool: precios como texto (Decimal → str antes)
        raise TypeError(f"«{c.nombre}» es de tipo {c.tipo}: el valor debe ser texto")
    return valor
