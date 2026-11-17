"""Página falsa de Playwright para probar el conductor sin navegador.

`acciones` registra solo lo que escribe o pulsa (fill, check, uncheck, select_option, set_input_files, click);
las visitas (`goto`) van aparte en `visitas`. Los elementos se buscan por la etiqueta (get_by_label /
get_by_role con name) o por el CSS (locator); cada clave apunta a una lista de `ElementoFalso`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ElementoFalso:
    valor: str = ""
    marcado: bool = False
    opcion: str | None = None  # texto de la opción seleccionada (select)


class LocalizadorFalso:
    def __init__(self, pagina: PaginaFalsa, clave: str, rol: str | None = None):
        self.pagina, self.clave, self.rol = pagina, clave, rol

    @property
    def _elementos(self) -> list[ElementoFalso]:
        return self.pagina.elementos.get(self.clave, [])

    def _uno(self) -> ElementoFalso:
        if len(self._elementos) != 1:
            raise AssertionError(f"acción a ciegas sobre «{self.clave}» ({len(self._elementos)} elementos)")
        return self._elementos[0]

    def _anota(self, accion: str, *args) -> None:
        self.pagina.acciones.append((accion, self.clave, *args))

    def count(self) -> int:
        return len(self._elementos)

    def input_value(self) -> str:
        return self._uno().valor

    def is_checked(self) -> bool:
        return self._uno().marcado

    def evaluate(self, expresion: str):
        e = self._uno()
        if "selectedIndex" in expresion:
            return e.opcion
        if "length" in expresion:
            return bool(e.valor.strip())
        raise AssertionError(f"expresión no prevista: {expresion}")

    def fill(self, valor: str) -> None:
        self._uno().valor = valor
        self._anota("fill", valor)

    def check(self) -> None:
        self._uno().marcado = True
        self._anota("check")

    def uncheck(self) -> None:
        self._uno().marcado = False
        self._anota("uncheck")

    def select_option(self, label: str) -> None:
        self._uno().opcion = label
        self._anota("select_option", label)

    def set_input_files(self, ruta: str) -> None:
        self._uno().valor = ruta
        self._anota("set_input_files", ruta)

    def click(self) -> None:
        self._uno()
        self._anota("click")
        if self.pagina.al_pulsar is not None:
            self.pagina.al_pulsar(self.pagina, self.clave)


class PaginaFalsa:
    def __init__(self, texto: str = "", url: str = "about:blank", elementos=None, destinos=None, al_pulsar=None):
        self.texto = texto
        self.url = url
        self.elementos: dict[str, list[ElementoFalso]] = elementos or {}
        self.destinos: dict[str, str] = destinos or {}  # url pedida → url final (redirecciones)
        self.al_pulsar = al_pulsar
        self.acciones: list[tuple] = []
        self.visitas: list[str] = []
        self.mascaras: list[str] | None = None
        self.capturas: list[str] = []

    def goto(self, url: str, **_kw) -> None:
        self.visitas.append(url)
        self.url = self.destinos.get(url, url)

    def inner_text(self, selector: str) -> str:
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

    def screenshot(self, path: str, mask=None, **_kw) -> bytes:
        self.mascaras = [m.clave for m in (mask or [])]
        self.capturas.append(path)
        with open(path, "wb") as f:
            f.write(b"\x89PNG falso")
        return b""
