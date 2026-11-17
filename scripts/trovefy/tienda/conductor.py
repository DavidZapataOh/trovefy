"""Conductor de navegador: el único componente de Trovefy que escribe o pulsa en una pantalla, y se para.

Todo sale del mapa (`trovefy.mapa`): el conductor no conoce Impultienda ni Hotmart. Antes de cada acción
comprueba, en este orden, que la pantalla no es `prohibida`, que el control no es `secreto`, que la
pantalla está confirmada (`capturado`), que la sesión no caducó, que el host está permitido, que la URL
actual no es de cobros y que la firma sigue en la página; después, que el control casa con exactamente
un elemento. Si algo no casa lanza una `Parada` (motivo en español) y no toca nada más: tras una parada
de pantalla hay que volver a `ir()` antes de leer o escribir otra vez.

Los controles `secreto` (token CAPI) nunca se leen: `configurado()` solo dice si tienen valor, el valor
no sale del navegador, y las capturas los enmascaran.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from trovefy.mapa import (
    Control,
    FirmaAusente,
    capturado_de,
    control,
    controles_de,
    hosts_de,
    leer_pantalla,
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
    """La URL (pedida o final) está fuera de los `hosts` del mapa."""


class ZonaProhibida(Parada):
    """Pantalla de cobros, pasarelas, retiros, tarjetas, bancos o contraseñas: no se escribe."""


class SesionCaducada(Parada):
    """La página acabó en una pantalla de login o de comprobación de seguridad."""


class MapaSinConfirmar(Parada):
    """La pantalla tiene `capturado: null`: se puede leer, no escribir."""


class ControlSecreto(Parada):
    """El control es secreto: no se lee ni se escribe su valor (solo `configurado`)."""


_VALOR_URL = re.compile(r"[A-Za-z0-9._~-]+")
_CON_VALOR = ("texto", "numero", "precio", "area")
_JS_TIENE_VALOR = "e => (e.value || '').trim().length > 0"
_JS_OPCION = "e => e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : null"
_INTENTOS_FIRMA = 4  # la página puede tardar en pintar el panel: hasta 3 s más antes de parar
_PAUSA_FIRMA_S = 1.0
_PARADAS_DE_PANTALLA = (FirmaNoCasa, SelectorAusente, HostNoPermitido, SesionCaducada, ZonaProhibida)


class Conductor:
    """Conduce una página de Playwright (`trovefy.navegador.sesion`) siguiendo el mapa de un servicio."""

    def __init__(
        self,
        page,
        mapa: dict,
        servicio: str,
        dormir: Callable[[float], None] = time.sleep,
        ahora: Callable[[], float] = time.monotonic,
    ):
        self.page = page
        self.mapa = mapa
        self.servicio = servicio
        self._dormir = dormir
        self._ahora = ahora
        self._hosts = hosts_de(mapa)
        self._actual: str | None = None

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

    def _comprobar_url(self, pantalla: str) -> None:
        url = self.page.url
        if sesion_caducada(url):
            inicio = urlparse(self._pantalla(pantalla)["url"])
            raise self._parar(SesionCaducada(
                pantalla,
                f"la sesión de {self.servicio} caducó (la página acabó en el login). Inicia sesión con "
                f"`trovefy navegador abrir {self.servicio} {inicio.scheme}://{inicio.netloc}/` y vuelve a lanzar. "
                "No he tocado nada más.",
            ))
        host = (urlparse(url).hostname or "").lower()
        if host not in self._hosts:
            raise self._parar(HostNoPermitido(
                pantalla, f"la página está en «{host or url}», que no es de {self.servicio} según el mapa; no toco nada."
            ))

    def _texto_con_firma(self, pantalla: str) -> str:
        p = self._pantalla(pantalla)
        for intento in range(_INTENTOS_FIRMA):
            texto = self.page.inner_text("body")
            try:
                leer_pantalla(p, texto)
                return texto
            except FirmaAusente:
                if intento + 1 < _INTENTOS_FIRMA:
                    self._dormir(_PAUSA_FIRMA_S)
        faltan = [t for t in p["firma"] if t not in texto]
        raise self._parar(FirmaNoCasa(
            pantalla,
            f"la pantalla no casa con el mapa (falta: {', '.join(f'«{t}»' for t in faltan)}). "
            "Puede que haya cambiado: no toco nada. Abre tú la pantalla y avisa.",
        ))

    def _en(self, pantalla: str, escribir: bool) -> None:
        """Sigo en `pantalla`, con sesión, host permitido y firma vigente (si no, `Parada`)."""
        if self._actual != pantalla:
            raise self._parar(FirmaNoCasa(
                pantalla, f"no estoy en «{pantalla}» (o la última comprobación falló): primero hay que ir a ella."
            ))
        self._comprobar_url(pantalla)
        if escribir:
            palabra = palabra_prohibida(self.page.url)
            if palabra:
                raise self._parar(ZonaProhibida(
                    pantalla, f"la página actual parece de cobros o datos sensibles («{palabra}»): aquí nunca escribo."
                ))
        self._texto_con_firma(pantalla)

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
        """Navega a la pantalla (respetando la espera por dominio) y devuelve el texto visible si casa."""
        p = self._pantalla(pantalla)
        self._actual = None
        for clave, valor in valores_url.items():
            if not _VALOR_URL.fullmatch(str(valor)):
                raise ValueError(f"valor no válido para «{clave}» en la URL de «{pantalla}»: solo letras, dígitos, . _ ~ -")
        url = p["url"].format(**valores_url)
        host = (urlparse(url).hostname or "").lower()
        if host not in self._hosts:
            raise self._parar(HostNoPermitido(pantalla, f"la URL de «{pantalla}» va a «{host}», fuera de los hosts del mapa."))
        esperar_entre_navegaciones(host, ahora=self._ahora, dormir=self._dormir)
        try:
            self.page.goto(url, wait_until="load", timeout=30_000)
        except Exception as exc:  # errores de Playwright: red, tiempo, página cerrada
            raise NavegadorError(f"no se pudo cargar «{pantalla}» ({type(exc).__name__}); revisa tu conexión") from exc
        self._comprobar_url(pantalla)
        texto = self._texto_con_firma(pantalla)
        self._actual = pantalla
        return texto

    def leer(self, pantalla: str, nombre: str) -> str | bool | None:
        """Valor actual del control, leído del DOM (`None` para un archivo: no se puede releer)."""
        c = control(self.mapa, pantalla, nombre)
        if c.secreto:
            raise ControlSecreto(pantalla, f"«{nombre}» es secreto: no se lee; usa configurado() para saber si tiene valor.")
        if c.tipo == "boton":
            raise TypeError(f"«{nombre}» es un botón: no tiene valor que leer")
        self._en(pantalla, escribir=False)
        loc = self._uno(c)
        if c.tipo in _CON_VALOR:
            return loc.input_value()
        if c.tipo == "select":
            return loc.evaluate(_JS_OPCION)
        if c.tipo == "interruptor":
            return loc.is_checked()
        return None  # archivo

    def configurado(self, pantalla: str, nombre: str) -> bool:
        """True si el control tiene valor no vacío. El valor nunca sale del navegador."""
        c = control(self.mapa, pantalla, nombre)
        if c.tipo == "boton":
            raise TypeError(f"«{nombre}» es un botón: no tiene valor")
        self._en(pantalla, escribir=False)
        loc = self._uno(c)
        if c.tipo == "interruptor":
            return bool(loc.is_checked())
        if c.tipo == "select":
            return loc.evaluate(_JS_OPCION) is not None
        return bool(loc.evaluate(_JS_TIENE_VALOR))

    def poner(self, pantalla: str, nombre: str, valor: str | bool | Path) -> None:
        """Escribe `valor` en el control, solo si todas las comprobaciones pasan."""
        c = self._para_escribir(pantalla, nombre)
        valor = _validar_valor(c, valor)
        self._en(pantalla, escribir=True)
        loc = self._uno(c)
        if c.tipo in _CON_VALOR:
            loc.fill(valor)
        elif c.tipo == "select":
            loc.select_option(label=valor)
        elif c.tipo == "interruptor":
            loc.check() if valor else loc.uncheck()
        else:  # archivo
            loc.set_input_files(valor)

    def pulsar(self, pantalla: str, nombre: str) -> None:
        """Pulsa un control `boton`, con las mismas guardas que `poner`."""
        c = self._para_escribir(pantalla, nombre)
        if c.tipo != "boton":
            raise TypeError(f"«{nombre}» es de tipo {c.tipo}: solo se pulsan botones (usa poner())")
        self._en(pantalla, escribir=True)
        self._uno(c).click()

    def capturar(self, ruta: Path) -> Path:
        """Captura de la página (modo 0600) con todos los controles secretos del mapa y las contraseñas tapados."""
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(ruta, os.O_WRONLY | os.O_CREAT, 0o600))
        ruta.chmod(0o600)
        mascaras = [
            self._localizador(c)
            for nombre in self.mapa["pantallas"]
            for c in controles_de(self.mapa, nombre)
            if c.secreto
        ]
        mascaras.append(self.page.locator("input[type=password]"))
        self.page.screenshot(path=str(ruta), mask=mascaras)
        ruta.chmod(0o600)
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
