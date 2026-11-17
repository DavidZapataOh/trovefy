"""Página falsa de Playwright para probar el conductor sin navegador.

`acciones` registra solo lo que escribe o pulsa (fill, check, uncheck, select_option, set_input_files, click);
las visitas (`goto`) van aparte en `visitas`. Los elementos se buscan por la etiqueta (get_by_label /
get_by_role con name) o por el CSS (locator); cada clave apunta a una lista de `ElementoFalso`.

Como en Playwright, `element_handle()` fija el elemento concreto: si después la página lo sustituye (otra
pantalla), las acciones sobre el manejador fallan («not attached») en vez de caer en el elemento nuevo.
Ganchos para simular carreras: `al_fijar(pagina, clave)` justo después de fijar, `al_actuar(pagina, clave,
accion)` justo después de aplicar una acción, `al_pulsar(pagina, clave)` tras un clic, `al_capturar(pagina)`
tras la captura; `fallar` = claves cuya acción lanza una excepción a mitad.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(eq=False)
class ElementoFalso:
    valor: str = ""
    marcado: bool = False
    opcion: str | None = None  # texto de la opción seleccionada (select)


class ErrorFalso(Exception):
    """Lo que lanzaría Playwright (elemento desconectado, tiempo agotado…)."""


class ManejadorFalso:
    """ElementHandle falso: apunta a un elemento concreto, no vuelve a buscar."""

    def __init__(self, pagina: PaginaFalsa, clave: str, elemento: ElementoFalso):
        self.pagina, self.clave, self.elemento = pagina, clave, elemento

    def _vivo(self) -> ElementoFalso:
        if not any(e is self.elemento for e in self.pagina.elementos.get(self.clave, [])):
            raise ErrorFalso("Element is not attached to the DOM")
        return self.elemento

    def _accion(self, accion: str, *args, timeout=None) -> ElementoFalso:
        self.pagina.timeouts.append(timeout)
        e = self._vivo()
        if self.clave in self.pagina.fallar:
            raise ErrorFalso(f"Timeout {timeout}ms exceeded")
        return e

    def _anota(self, accion: str, *args) -> None:
        self.pagina.acciones.append((accion, self.clave, *args))
        if self.pagina.al_actuar is not None:
            self.pagina.al_actuar(self.pagina, self.clave, accion)

    def input_value(self, timeout=None) -> str:
        return self._vivo().valor

    def is_checked(self) -> bool:
        return self._vivo().marcado

    def evaluate(self, expresion: str):
        e = self._vivo()
        if "selectedIndex" in expresion:
            return e.opcion
        if "length" in expresion:
            return bool(e.valor.strip())
        raise AssertionError(f"expresión no prevista: {expresion}")

    def fill(self, valor: str, timeout=None) -> None:
        self._accion("fill", timeout=timeout).valor = valor
        self._anota("fill", valor)

    def check(self, timeout=None) -> None:
        self._accion("check", timeout=timeout).marcado = True
        self._anota("check")

    def uncheck(self, timeout=None) -> None:
        self._accion("uncheck", timeout=timeout).marcado = False
        self._anota("uncheck")

    def select_option(self, label: str, timeout=None) -> None:
        self._accion("select_option", timeout=timeout).opcion = label
        self._anota("select_option", label)

    def set_input_files(self, ruta: str, timeout=None) -> None:
        self._accion("set_input_files", timeout=timeout).valor = ruta
        self._anota("set_input_files", ruta)

    def click(self, timeout=None) -> None:
        self._accion("click", timeout=timeout)
        self._anota("click")
        if self.pagina.al_pulsar is not None:
            self.pagina.al_pulsar(self.pagina, self.clave)


class LocalizadorFalso:
    def __init__(self, pagina: PaginaFalsa, clave: str, rol: str | None = None):
        self.pagina, self.clave, self.rol = pagina, clave, rol

    @property
    def _elementos(self) -> list[ElementoFalso]:
        return self.pagina.elementos.get(self.clave, [])

    def count(self) -> int:
        return len(self._elementos)

    def element_handle(self, timeout=None) -> ManejadorFalso:
        if len(self._elementos) != 1:
            raise ErrorFalso(f"strict mode violation: «{self.clave}» ({len(self._elementos)} elementos)")
        self.pagina.fijados.append((self.clave, timeout))
        h = ManejadorFalso(self.pagina, self.clave, self._elementos[0])
        if self.pagina.al_fijar is not None:
            self.pagina.al_fijar(self.pagina, self.clave)
        return h

    # El conductor actúa siempre sobre el manejador fijado, nunca sobre el localizador (que volvería a buscar
    # y podría caer en otra pantalla): si lo intenta, el test falla.
    def __getattr__(self, nombre):
        if nombre in {"fill", "check", "uncheck", "select_option", "set_input_files", "click", "input_value",
                      "is_checked", "evaluate"}:
            raise AssertionError(f"acción «{nombre}» sobre el localizador de «{self.clave}» en vez del elemento fijado")
        raise AttributeError(nombre)


class PaginaFalsa:
    def __init__(self, texto: str = "", url: str = "about:blank", elementos=None, destinos=None, al_pulsar=None,
                 al_fijar=None, al_actuar=None, al_capturar=None):
        self.texto = texto
        self.url = url
        self.elementos: dict[str, list[ElementoFalso]] = elementos or {}
        self.destinos: dict[str, str] = destinos or {}  # url pedida → url final (redirecciones)
        self.al_pulsar = al_pulsar
        self.al_fijar = al_fijar
        self.al_actuar = al_actuar
        self.al_capturar = al_capturar
        self.fallar: set[str] = set()
        self.acciones: list[tuple] = []
        self.visitas: list[str] = []
        self.fijados: list[tuple] = []
        self.timeouts: list = []
        self.timeout_por_defecto: float | None = None
        self.mascaras: list[str] | None = None
        self.capturas: list[str | None] = []

    def set_default_timeout(self, ms: float) -> None:
        self.timeout_por_defecto = ms

    def goto(self, url: str, **_kw) -> None:
        self.visitas.append(url)
        self.url = self.destinos.get(url, url)

    def inner_text(self, selector: str, **_kw) -> str:
        assert selector == "body"
        return self.texto

    def get_by_label(self, etiqueta: str, exact: bool = False) -> LocalizadorFalso:
        assert exact is True
        return LocalizadorFalso(self, etiqueta)

    def get_by_role(self, rol: str, name: str, exact: bool = False) -> LocalizadorFalso:
        assert exact is True
        return LocalizadorFalso(self, name, rol)

    def locator(self, css: str) -> LocalizadorFalso:
        return LocalizadorFalso(self, css)

    def screenshot(self, path: str | None = None, mask=None, **_kw) -> bytes:
        self.mascaras = [m.clave for m in (mask or [])]
        self.capturas.append(path)
        datos = b"\x89PNG falso"
        if path is not None:
            with open(path, "wb") as f:
                f.write(datos)
        if self.al_capturar is not None:
            self.al_capturar(self)
        return datos
