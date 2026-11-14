"""Esquema de ``productos/<p-id>/modelar.yaml``: dataclasses, validación y guardas.

``modelar.yaml`` lo escribe Claude en /modelar. Aquí se valida entero y se informan **todos** los
errores a la vez, cada uno con su ruta YAML (``core.bonos: hacen falta 3–5, hay 2``). Dos guardas
transversales: material ajeno (HTML, CSS, medios o texto copiado del original) y secretos
(``trovefy.secretos.buscar_secreto`` sobre el archivo entero y, tras leerlo, sobre cada clave y cada
texto ya desescapado; si la revisión no está disponible, ``RevisionSecretosNoDisponible`` se propaga y
no se sigue).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from trovefy.economia.escalera import PASOS
from trovefy.modelar.autopsia import EJES, EjeValorado
from trovefy.secretos import buscar_secreto

# Vocabulario del teardown del original (plan 16).
TIPOS_TEARDOWN = ("hero", "problema", "verdad_incomoda", "no_fue_tu_culpa", "metodo", "stack", "garantia", "faq",
                  "cta", "prueba", "bonos", "otro")
# Vocabulario de ``estructura_landing`` (plan 18, resolución 5): el plan 18 lo reexporta desde aquí.
TIPOS_SECCION = ("hero", "problema", "villano", "mecanismo", "que_incluye", "formato", "vista_previa",
                 "prueba_social", "bonos", "para_quien", "no_es_para", "autor", "comparativa", "garantia", "precio",
                 "faq", "cta_final")
# Dato técnico: subconjunto de fuente que necesita cada idioma (idioma sin entrada → latin).
ALFABETO = {
    "bg": "cyrillic", "ru": "cyrillic", "uk": "cyrillic", "sr": "cyrillic", "mk": "cyrillic", "be": "cyrillic",
    "ro": "latin-ext", "cs": "latin-ext", "hu": "latin-ext", "pl": "latin-ext", "sk": "latin-ext",
    "sl": "latin-ext", "hr": "latin-ext", "lt": "latin-ext", "lv": "latin-ext", "et": "latin-ext",
    "tr": "latin-ext", "el": "greek",
}
USOS_TIPOGRAFIA = ("titulos", "texto")
IMPACTOS = ("alto", "medio", "bajo")
TOKENS_OBLIGATORIOS = ("--color-primario", "--fuente-titulos", "--fuente-texto")

# Límites del esquema (forma del archivo, no números de negocio).
_BONOS = (3, 5)
_SECCIONES_LANDING = (14, 16)
_PALABRAS_MECANISMO = (2, 4)
_CAMBIOS_MIN = 3
_COLORES_MIN = 3
_LARGO_COPIADO = 280
_LETRAS_MARCA = 4

_HTML = re.compile(r"<[a-zA-Z/!]|&(?:lt|gt|#0*6[02]|#x0*3[ce]);", re.IGNORECASE)
_CSS = re.compile(r"\{[^}]*:[^}]*(?:;|\})")
# Estilo en línea sin llaves: dos o más declaraciones «propiedad: valor;» con nombres de CSS (en ASCII,
# así «Incluye: 30 fichas; 5 bonos» o la prosa búlgara no saltan).
_PROPIEDAD_CSS = (r"(?:[a-z]+-[a-z-]+|color|background|margin|padding|border|display|width|height|font|position"
                  r"|top|left|right|bottom|opacity|transform|float|overflow|content|gap|flex|grid|outline|filter)")
_ESTILO_EN_LINEA = re.compile(rf"(?:(?<![\w-]){_PROPIEDAD_CSS}\s*:\s*[^:;{{}}]+;\s*){{2,}}")
_EXT_MEDIO = r"png|jpe?g|webp|avif|gif|svg|ico|mp4|webm|mov|m3u8|mp3|woff2?|ttf|otf|css"
_MEDIO = re.compile(rf"\.(?:{_EXT_MEDIO})(?:[?#]|$)", re.IGNORECASE)
# ``.js`` solo cuenta en una URL o ruta absoluta: «Next.js» o «React/Next.js» son nombres, no archivos.
_SCRIPT = re.compile(r"^(?:[a-z]+:)?//|^\.?/", re.IGNORECASE)
_JS = re.compile(r"\.js(?:[?#]|$)", re.IGNORECASE)
_PROPIO = "entregable/"  # rutas del vault a nuestro propio material
_CLAVE_TOKEN = re.compile(r"^--[a-z0-9-]+$")
_CLAVE_PALETA = re.compile(r"^[a-z0-9_-]+$")
_VALOR_TOKEN_PROHIBIDO = re.compile(r"[{};<>]")
# Lista blanca de valores de ``tokens_css`` (van tal cual a un ``:root {}`` de la landing): nada que pueda
# cargar recursos (``url(``, ``image-set(``), abrir comentarios, escapar, encadenar reglas o romper el bloque.
_TOKEN_PROHIBIDO = re.compile(r"\(|/\*|\\|@|!|[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_TOKEN_COLOR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})")
_FAMILIA = r"(?:'[\w \-]+'|[\w\-]+)"
_TOKEN_FUENTE = re.compile(rf"{_FAMILIA}(?:\s*,\s*{_FAMILIA})*")
_TOKEN_OTRO = re.compile(r"-?\d+(?:\.\d+)?(?:px|rem|em|%|vh|vw|vmin|vmax|ch|ex|pt|fr|s|ms|deg)?"
                         r"|#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})")
_IMPORTE = re.compile(r"^\d+(?:\.\d{1,2})?$")
_PAGINAS = re.compile(r"p[aá]gina|page|страниц", re.IGNORECASE)
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MONEDA = re.compile(r"^[A-Z]{3}$")


class ModeladoInvalido(ValueError):
    """``modelar.yaml`` no cumple el esquema; ``errores`` los trae todos, con su ruta YAML."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = list(errores)
        super().__init__("modelar.yaml no es válido:\n" + "\n".join(f"- {e}" for e in self.errores))


@dataclass(frozen=True)
class Seccion:
    n: int
    tipo: str
    objetivo: str
    palabras_aprox: int
    objeciones: tuple[str, ...]
    prueba: str | None
    cta: bool


@dataclass(frozen=True)
class Teardown:
    url: str
    anunciante: str
    fecha_lectura: str
    checkout: dict
    promesa: str
    mecanismo: str
    avatar: str
    villano: str | None
    secciones: tuple[Seccion, ...]


@dataclass(frozen=True)
class Bono:
    nombre: str
    objecion: str


@dataclass(frozen=True)
class CoreOffer:
    promesa_h1: str
    plazo: str
    sin: tuple[str, str, str]
    unidad_venta: str
    big_idea: str
    villano: str
    mecanismo_nombre: str
    mecanismo_pasos: tuple[str, str, str]
    entregables: tuple[str, ...]
    bonos: tuple[Bono, ...]
    garantia_dias: int
    garantia_como: str
    formato: str
    avatar: str
    angulo: str


@dataclass(frozen=True)
class PiezaEscalera:
    paso: str
    titulo: str
    entregable: str


@dataclass(frozen=True)
class SeccionLanding:
    orden: int
    tipo: str
    palabras: int
    cta: bool


@dataclass(frozen=True)
class Brandbook:
    nombre_local: str
    idioma: str
    significado: str
    paleta: dict[str, str]
    tipografias: tuple[dict, ...]
    tono: str
    iconografia: str
    mockup: str
    tokens_css: dict[str, str]


@dataclass(frozen=True)
class Cambio:
    que: str
    por_que: str
    impacto: str


@dataclass(frozen=True)
class Modelado:
    producto: str
    pais: str
    teardown: Teardown
    ejes_original: dict[str, EjeValorado]
    ejes_nuestra: dict[str, EjeValorado]
    angulos_referencia: tuple[str, ...]
    core: CoreOffer
    brandbook: Brandbook
    mapa_cambios: tuple[Cambio, ...]
    comparativa: tuple[tuple[str, str, str], ...]
    escalera_piezas: tuple[PiezaEscalera, ...]
    estructura_landing: tuple[SeccionLanding, ...]


def token_css_inseguro(clave: str, valor: object) -> str | None:
    """Motivo si el token CSS no está en la lista blanca; ``None`` si es seguro de copiar a ``:root {}``.

    ``--color-*``: ``#RRGGBB`` o ``#RGB``. ``--fuente-*``: familias (entre comillas simples o sin ellas)
    separadas por comas, con la genérica al final. Otro token: un número con unidad CSS o un ``#hex``.
    Nunca ``(``, ``/*``, ``\\``, ``@``, ``!``, ``{ } ; < >`` ni caracteres de control o saltos de línea.
    """
    if not isinstance(clave, str) or not _CLAVE_TOKEN.match(clave):
        return "las claves son --minusculas-numeros-y-guiones"
    if not isinstance(valor, str):
        return "tiene que ser texto"
    if not valor.strip():
        return "está vacío"
    if _VALOR_TOKEN_PROHIBIDO.search(valor) or _TOKEN_PROHIBIDO.search(valor):
        return "no puede llevar ( /* \\ @ ! { } ; < > ni saltos de línea: solo el valor del token"
    if clave.startswith("--color-"):
        if not _TOKEN_COLOR.fullmatch(valor):
            return "tiene que ser un color #RRGGBB (o #RGB)"
    elif clave.startswith("--fuente-"):
        if not _TOKEN_FUENTE.fullmatch(valor):
            return "tiene que ser una lista de familias ('Noto Sans', sans-serif)"
    elif not _TOKEN_OTRO.fullmatch(valor):
        return "tiene que ser un número con unidad CSS (8px, 1.5rem) o un color #hex"
    return None


# --- material ajeno --------------------------------------------------------------------------------


def material_ajeno(texto: str, *, de_teardown: bool = False) -> str | None:
    """Motivo si ``texto`` parece material del original (HTML, CSS, medio o texto copiado); si no, None.

    Cada palabra se mira como posible archivo o URL (imagen, vídeo, audio, fuente, hoja de estilo);
    ``.js`` solo cuenta en URL o rutas absolutas, para no confundir «Next.js» con un archivo, y las
    rutas ``entregable/…`` son material propio. El largo (más de 280 caracteres) solo cuenta en campos
    del teardown.
    """
    if _HTML.search(texto):
        return "parece HTML (etiquetas <…> o &lt;…&gt;): describe la sección con tus palabras"
    if _CSS.search(texto) or _ESTILO_EN_LINEA.search(texto):
        return "parece CSS ({ propiedad: valor; }): guarda solo la estructura"
    for palabra in texto.split():
        palabra = palabra.strip(".,;:()«»\"'")
        if palabra.startswith(_PROPIO):
            continue
        if _MEDIO.search(palabra) or (_JS.search(palabra) and _SCRIPT.search(palabra)):
            return "parece un archivo, URL o estilo: aquí solo va texto propio"
    if de_teardown and len(texto.strip()) > _LARGO_COPIADO:
        return f"más de {_LARGO_COPIADO} caracteres seguidos: parece texto copiado, resúmelo con tus palabras"
    return None


def _textos(nodo: Any, ruta: str) -> Iterator[tuple[str, str]]:
    """Cada texto del árbol con su ruta YAML, también las claves de los bloques."""
    if isinstance(nodo, str):
        yield ruta, nodo
    elif isinstance(nodo, dict):
        for clave, valor in nodo.items():
            sub = f"{ruta}.{clave}" if ruta else str(clave)
            if isinstance(clave, str):
                yield sub, clave
            yield from _textos(valor, sub)
    elif isinstance(nodo, list):
        for i, valor in enumerate(nodo):
            yield from _textos(valor, f"{ruta}[{i}]")


# --- lector con errores acumulados -----------------------------------------------------------------


class _Lector:
    def __init__(self) -> None:
        self.errores: list[str] = []

    def error(self, ruta: str, motivo: str) -> None:
        self.errores.append(f"{ruta}: {motivo}")

    def claves(self, nodo: Any, permitidas: tuple[str, ...], ruta: str) -> None:
        """Una clave que el esquema no conoce es un error con su ruta (p. ej. el resto de un texto con coma
        sin comillas dentro de un mapa en flujo, que YAML convierte en otra clave)."""
        if not isinstance(nodo, dict):
            return
        for clave in nodo:
            if clave not in permitidas:
                donde = f"{ruta}.{clave}" if ruta else str(clave)
                self.error(donde, f"clave desconocida (se esperan: {', '.join(permitidas)}); "
                                  "si es el resto de un texto con comas, ponlo entre comillas")

    def mapa(self, nodo: Any, clave: str, ruta: str) -> dict:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if not isinstance(valor, dict):
            self.error(ruta, "falta (tiene que ser un bloque de claves)")
            return {}
        return valor

    def lista(self, nodo: Any, clave: str, ruta: str) -> list:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if not isinstance(valor, list):
            self.error(ruta, "falta (tiene que ser una lista)")
            return []
        return valor

    def texto(self, nodo: Any, clave: str, ruta: str, *, nulo: bool = False) -> str | None:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if valor is None and nulo:
            return None
        if not isinstance(valor, str) or not valor.strip():
            self.error(ruta, "falta o está vacío (texto)")
            return ""
        return valor.strip()

    def entero(self, nodo: Any, clave: str, ruta: str, *, minimo: int = 0, nulo: bool = False) -> int | None:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if valor is None and nulo:
            return None
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
            self.error(ruta, f"tiene que ser un número entero >= {minimo}")
            return minimo
        return valor

    def booleano(self, nodo: Any, clave: str, ruta: str) -> bool:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if not isinstance(valor, bool):
            self.error(ruta, "tiene que ser true o false")
            return False
        return valor

    def importe(self, nodo: Any, clave: str, ruta: str) -> Decimal | None:
        valor = nodo.get(clave) if isinstance(nodo, dict) else None
        if valor is None:
            return None
        # Texto con hasta 2 decimales o entero; un float de YAML (13.9) o un booleano no valen.
        es_entero = isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0
        if not es_entero and not (isinstance(valor, str) and _IMPORTE.match(valor.strip())):
            self.error(ruta, "tiene que ser un importe como texto con hasta 2 decimales (\"13.90\"), "
                             "un entero o null")
            return None
        try:
            return Decimal(str(valor).strip())
        except InvalidOperation:  # pragma: no cover - el patrón ya lo impide
            self.error(ruta, "tiene que ser un importe como texto (\"13.90\") o null")
            return None

    def textos(self, nodo: Any, clave: str, ruta: str) -> tuple[str, ...]:
        resultado = []
        for i, valor in enumerate(self.lista(nodo, clave, ruta)):
            if not isinstance(valor, str) or not valor.strip():
                self.error(f"{ruta}[{i}]", "falta o está vacío (texto)")
            else:
                resultado.append(valor.strip())
        return tuple(resultado)


# --- bloques ---------------------------------------------------------------------------------------


def _checkout(lec: _Lector, nodo: dict) -> dict:
    r = "teardown.checkout"
    lec.claves(nodo, ("plataforma", "precio", "moneda", "bump", "upsells", "garantia_dias"), r)
    moneda = nodo.get("moneda")
    if moneda is not None and (not isinstance(moneda, str) or not _MONEDA.match(moneda)):
        lec.error(f"{r}.moneda", "tiene que ser un código ISO de 3 letras (EUR, USD…) o null si no se midió")
        moneda = None
    upsells = []
    for i, valor in enumerate(lec.lista(nodo, "upsells", f"{r}.upsells")):
        if valor is None:
            lec.error(f"{r}.upsells[{i}]", "tiene que ser un importe como texto (\"13.90\")")
            continue
        upsells.append(lec.importe({"v": valor}, "v", f"{r}.upsells[{i}]"))
    return {
        "plataforma": lec.texto(nodo, "plataforma", f"{r}.plataforma"),
        "precio": lec.importe(nodo, "precio", f"{r}.precio"),
        "moneda": moneda,
        "bump": lec.importe(nodo, "bump", f"{r}.bump"),
        "upsells": upsells,
        "garantia_dias": lec.entero(nodo, "garantia_dias", f"{r}.garantia_dias", nulo=True),
    }


def _teardown(lec: _Lector, datos: dict) -> Teardown:
    nodo = lec.mapa(datos, "teardown", "teardown")
    lec.claves(nodo, ("url", "anunciante", "fecha_lectura", "checkout", "promesa", "mecanismo", "avatar", "villano",
                      "secciones"), "teardown")
    secciones = []
    for i, s in enumerate(lec.lista(nodo, "secciones", "teardown.secciones")):
        r = f"teardown.secciones[{i}]"
        if not isinstance(s, dict):
            lec.error(r, "tiene que ser un bloque de claves")
            continue
        lec.claves(s, ("n", "tipo", "objetivo", "palabras_aprox", "objeciones", "prueba", "cta"), r)
        tipo = lec.texto(s, "tipo", f"{r}.tipo")
        if tipo and tipo not in TIPOS_TEARDOWN:
            lec.error(f"{r}.tipo", f"tipo desconocido; usa uno de: {', '.join(TIPOS_TEARDOWN)}")
        secciones.append(Seccion(
            n=lec.entero(s, "n", f"{r}.n", minimo=1), tipo=tipo, objetivo=lec.texto(s, "objetivo", f"{r}.objetivo"),
            palabras_aprox=lec.entero(s, "palabras_aprox", f"{r}.palabras_aprox", minimo=1),
            objeciones=lec.textos(s, "objeciones", f"{r}.objeciones"),
            prueba=lec.texto(s, "prueba", f"{r}.prueba", nulo=True), cta=lec.booleano(s, "cta", f"{r}.cta")))
    if not secciones and isinstance(nodo.get("secciones"), list):
        lec.error("teardown.secciones", "hace falta al menos una sección")
    if [s.n for s in secciones] != list(range(1, len(secciones) + 1)):
        lec.error("teardown.secciones", "el campo n tiene que ir de 1 a N, en orden y sin huecos")
    return Teardown(
        url=lec.texto(nodo, "url", "teardown.url"), anunciante=lec.texto(nodo, "anunciante", "teardown.anunciante"),
        fecha_lectura=_fecha(lec, nodo, "fecha_lectura", "teardown.fecha_lectura"),
        checkout=_checkout(lec, lec.mapa(nodo, "checkout", "teardown.checkout")),
        promesa=lec.texto(nodo, "promesa", "teardown.promesa"),
        mecanismo=lec.texto(nodo, "mecanismo", "teardown.mecanismo"),
        avatar=lec.texto(nodo, "avatar", "teardown.avatar"),
        villano=lec.texto(nodo, "villano", "teardown.villano", nulo=True), secciones=tuple(secciones))


def _fecha(lec: _Lector, nodo: dict, clave: str, ruta: str) -> str:
    valor = nodo.get(clave)
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        try:
            return date.fromisoformat(valor).isoformat()
        except ValueError:
            pass
    lec.error(ruta, "tiene que ser una fecha real AAAA-MM-DD")
    return ""


def _ejes(lec: _Lector, datos: dict, clave: str) -> dict[str, EjeValorado]:
    nodo = lec.mapa(datos, clave, clave)
    if not isinstance(datos.get(clave), dict):
        return {}
    faltan = [e for e in EJES if e not in nodo]
    sobran = [str(e) for e in nodo if e not in EJES]
    if faltan:
        lec.error(clave, f"faltan ejes: {', '.join(faltan)} (van los 8 exactos)")
    if sobran:
        lec.error(clave, f"ejes desconocidos: {', '.join(sobran)} (van los 8 exactos)")
    ejes = {}
    for eje in EJES:
        if eje not in nodo:
            continue
        valor = nodo[eje]
        r = f"{clave}.{eje}"
        if not isinstance(valor, dict):
            lec.error(r, "tiene que ser {nota, porque}")
            continue
        lec.claves(valor, ("nota", "porque"), r)
        porque = lec.texto(valor, "porque", f"{r}.porque")
        nota = valor.get("nota")
        try:
            ejes[eje] = EjeValorado(eje, nota, porque)
        except ValueError:
            lec.error(f"{r}.nota", "tiene que ser un entero de 0 a 10, o null si no se pudo valorar")
    return ejes


def _core(lec: _Lector, datos: dict) -> CoreOffer:
    nodo = lec.mapa(datos, "core", "core")
    lec.claves(nodo, ("promesa_h1", "plazo", "sin", "unidad_venta", "big_idea", "villano", "mecanismo_nombre",
                      "mecanismo_pasos", "entregables", "bonos", "garantia_dias", "garantia_como", "formato",
                      "avatar", "angulo"), "core")
    sin = lec.textos(nodo, "sin", "core.sin")
    if isinstance(nodo.get("sin"), list) and len(nodo["sin"]) != 3:
        lec.error("core.sin", f"hacen falta exactamente 3, hay {len(nodo['sin'])}")
    unidad = lec.texto(nodo, "unidad_venta", "core.unidad_venta")
    if unidad and _PAGINAS.search(unidad):
        lec.error("core.unidad_venta", "no se vende por páginas: di qué resultado o plan compra")
    nombre = lec.texto(nodo, "mecanismo_nombre", "core.mecanismo_nombre")
    minimo, maximo = _PALABRAS_MECANISMO
    if nombre and not minimo <= len(nombre.split()) <= maximo:
        lec.error("core.mecanismo_nombre", f"tiene que tener {minimo}–{maximo} palabras, tiene {len(nombre.split())}")
    pasos = lec.textos(nodo, "mecanismo_pasos", "core.mecanismo_pasos")
    if isinstance(nodo.get("mecanismo_pasos"), list) and len(nodo["mecanismo_pasos"]) != 3:
        lec.error("core.mecanismo_pasos", f"hacen falta exactamente 3, hay {len(nodo['mecanismo_pasos'])}")
    entregables = lec.textos(nodo, "entregables", "core.entregables")
    if not entregables and isinstance(nodo.get("entregables"), list):
        lec.error("core.entregables", "hace falta al menos un entregable")
    bonos = []
    lista_bonos = lec.lista(nodo, "bonos", "core.bonos")
    for i, b in enumerate(lista_bonos):
        r = f"core.bonos[{i}]"
        if not isinstance(b, dict):
            lec.error(r, "tiene que ser {nombre, objecion}")
            continue
        if "id" in b:
            lec.error(r, f"los bonos no llevan id: su id es bono-{i + 1}")
        lec.claves({k: v for k, v in b.items() if k != "id"}, ("nombre", "objecion"), r)
        bonos.append(Bono(lec.texto(b, "nombre", f"{r}.nombre"), lec.texto(b, "objecion", f"{r}.objecion")))
    if isinstance(nodo.get("bonos"), list) and not _BONOS[0] <= len(lista_bonos) <= _BONOS[1]:
        lec.error("core.bonos", f"hacen falta {_BONOS[0]}–{_BONOS[1]}, hay {len(lista_bonos)}")
    return CoreOffer(
        promesa_h1=lec.texto(nodo, "promesa_h1", "core.promesa_h1"), plazo=lec.texto(nodo, "plazo", "core.plazo"),
        sin=sin, unidad_venta=unidad, big_idea=lec.texto(nodo, "big_idea", "core.big_idea"),
        villano=lec.texto(nodo, "villano", "core.villano"), mecanismo_nombre=nombre, mecanismo_pasos=pasos,
        entregables=entregables, bonos=tuple(bonos),
        garantia_dias=lec.entero(nodo, "garantia_dias", "core.garantia_dias", minimo=1),
        garantia_como=lec.texto(nodo, "garantia_como", "core.garantia_como"),
        formato=lec.texto(nodo, "formato", "core.formato"), avatar=lec.texto(nodo, "avatar", "core.avatar"),
        angulo=lec.texto(nodo, "angulo", "core.angulo"))


def _escalera_piezas(lec: _Lector, datos: dict) -> tuple[PiezaEscalera, ...]:
    piezas = []
    for i, p in enumerate(lec.lista(datos, "escalera_piezas", "escalera_piezas")):
        r = f"escalera_piezas[{i}]"
        if not isinstance(p, dict):
            lec.error(r, "tiene que ser {paso, titulo, entregable}")
            continue
        lec.claves(p, ("paso", "titulo", "entregable"), r)
        paso = lec.texto(p, "paso", f"{r}.paso")
        if paso and paso not in PASOS:
            lec.error(f"{r}.paso", f"paso desconocido; usa uno de: {', '.join(PASOS)}")
        piezas.append(PiezaEscalera(paso, lec.texto(p, "titulo", f"{r}.titulo"),
                                    lec.texto(p, "entregable", f"{r}.entregable")))
    if isinstance(datos.get("escalera_piezas"), list):
        vistos = [p.paso for p in piezas]
        faltan = [p for p in PASOS if p not in vistos]
        repetidos = sorted({p for p in vistos if p and vistos.count(p) > 1})
        if faltan:
            lec.error("escalera_piezas", f"faltan pasos: {', '.join(faltan)} (van los 6, uno por paso)")
        if repetidos:
            lec.error("escalera_piezas", f"pasos repetidos: {', '.join(repetidos)}")
    return tuple(sorted(piezas, key=lambda p: PASOS.index(p.paso) if p.paso in PASOS else len(PASOS)))


def _estructura_landing(lec: _Lector, datos: dict) -> tuple[SeccionLanding, ...]:
    secciones = []
    lista = lec.lista(datos, "estructura_landing", "estructura_landing")
    for i, s in enumerate(lista):
        r = f"estructura_landing[{i}]"
        if not isinstance(s, dict):
            lec.error(r, "tiene que ser {orden, tipo, palabras, cta}")
            continue
        lec.claves(s, ("orden", "tipo", "palabras", "cta"), r)
        tipo = lec.texto(s, "tipo", f"{r}.tipo")
        if tipo and tipo not in TIPOS_SECCION:
            lec.error(f"{r}.tipo", f"tipo desconocido; usa uno de: {', '.join(TIPOS_SECCION)}")
        secciones.append(SeccionLanding(lec.entero(s, "orden", f"{r}.orden", minimo=1), tipo,
                                        lec.entero(s, "palabras", f"{r}.palabras", minimo=1),
                                        lec.booleano(s, "cta", f"{r}.cta")))
    if not isinstance(datos.get("estructura_landing"), list):
        return tuple(secciones)
    minimo, maximo = _SECCIONES_LANDING
    if not minimo <= len(lista) <= maximo:
        lec.error("estructura_landing", f"hacen falta {minimo}–{maximo}, hay {len(lista)}")
    if [s.orden for s in secciones] != list(range(1, len(secciones) + 1)):
        lec.error("estructura_landing", "el orden tiene que ir de 1 a N, en orden y sin huecos")
    if secciones and not any(s.cta for s in secciones):
        lec.error("estructura_landing", "ninguna sección lleva cta: hace falta al menos una")
    return tuple(secciones)


def _brandbook(lec: _Lector, datos: dict, idioma: str, anunciante: str) -> Brandbook:
    nodo = lec.mapa(datos, "brandbook", "brandbook")
    lec.claves(nodo, ("nombre_local", "idioma", "significado", "paleta", "tipografias", "tono", "iconografia",
                      "mockup", "tokens_css"), "brandbook")
    nombre = lec.texto(nodo, "nombre_local", "brandbook.nombre_local")
    marca = sorted({p for p in re.findall(r"\w+", (anunciante or "").casefold()) if len(p) >= _LETRAS_MARCA})
    choca = [p for p in marca if p in (nombre or "").casefold()]
    if choca:
        lec.error("brandbook.nombre_local", f"se parece al nombre del anunciante original ({', '.join(choca)}): "
                                            "elige un nombre propio")
    idioma_bb = lec.texto(nodo, "idioma", "brandbook.idioma")
    if idioma_bb and idioma_bb != idioma:
        lec.error("brandbook.idioma", f"dice «{idioma_bb}» y el país habla «{idioma}»")
    paleta = lec.mapa(nodo, "paleta", "brandbook.paleta")
    for nombre_color, color in paleta.items():
        if not isinstance(nombre_color, str) or not _CLAVE_PALETA.match(nombre_color):
            lec.error("brandbook.paleta", f"nombre de color no válido: {nombre_color!s} (solo a-z, 0-9, _ y -)")
            continue
        if not isinstance(color, str) or not _COLOR.match(color):
            lec.error(f"brandbook.paleta.{nombre_color}", "tiene que ser un color #RRGGBB")
    if isinstance(nodo.get("paleta"), dict) and len(paleta) < _COLORES_MIN:
        lec.error("brandbook.paleta", f"hacen falta al menos {_COLORES_MIN} colores, hay {len(paleta)}")
    alfabeto = ALFABETO.get(idioma, "latin")
    tipografias = []
    lista = lec.lista(nodo, "tipografias", "brandbook.tipografias")
    for i, t in enumerate(lista):
        r = f"brandbook.tipografias[{i}]"
        if not isinstance(t, dict):
            lec.error(r, "tiene que ser {familia, uso, subconjuntos, licencia}")
            continue
        lec.claves(t, ("familia", "uso", "subconjuntos", "licencia"), r)
        uso = lec.texto(t, "uso", f"{r}.uso")
        if uso and uso not in USOS_TIPOGRAFIA:
            lec.error(f"{r}.uso", f"tiene que ser {' o '.join(USOS_TIPOGRAFIA)}")
        subconjuntos = lec.textos(t, "subconjuntos", f"{r}.subconjuntos")
        if isinstance(t.get("subconjuntos"), list) and alfabeto not in subconjuntos:
            lec.error(f"{r}.subconjuntos", f"falta {alfabeto} (idioma {idioma}): elige una familia que lo tenga")
        tipografias.append({"familia": lec.texto(t, "familia", f"{r}.familia"), "uso": uso,
                            "subconjuntos": list(subconjuntos), "licencia": lec.texto(t, "licencia", f"{r}.licencia")})
    if isinstance(nodo.get("tipografias"), list):
        usos = [t["uso"] for t in tipografias]
        if sorted(usos) != sorted(USOS_TIPOGRAFIA):
            lec.error("brandbook.tipografias", "hace falta exactamente una con uso: titulos y otra con uso: texto")
    tokens = lec.mapa(nodo, "tokens_css", "brandbook.tokens_css")
    raras = [str(k) for k in tokens if not isinstance(k, str) or not _CLAVE_TOKEN.match(k)]
    if raras:
        lec.error("brandbook.tokens_css", f"las claves son --minusculas-numeros-y-guiones: {', '.join(raras)}")
    for clave, valor in tokens.items():
        if str(clave) in raras:
            continue
        motivo = token_css_inseguro(clave, valor)
        if motivo:
            lec.error(f"brandbook.tokens_css.{clave}", motivo)
    faltan = [t for t in TOKENS_OBLIGATORIOS if t not in tokens]
    if isinstance(nodo.get("tokens_css"), dict) and faltan:
        lec.error("brandbook.tokens_css", f"faltan {', '.join(faltan)}")
    return Brandbook(
        nombre_local=nombre, idioma=idioma_bb, significado=lec.texto(nodo, "significado", "brandbook.significado"),
        paleta=dict(paleta), tipografias=tuple(tipografias), tono=lec.texto(nodo, "tono", "brandbook.tono"),
        iconografia=lec.texto(nodo, "iconografia", "brandbook.iconografia"),
        mockup=lec.texto(nodo, "mockup", "brandbook.mockup"), tokens_css={str(k): v for k, v in tokens.items()})


def _mapa_cambios(lec: _Lector, datos: dict) -> tuple[Cambio, ...]:
    cambios = []
    lista = lec.lista(datos, "mapa_cambios", "mapa_cambios")
    for i, c in enumerate(lista):
        r = f"mapa_cambios[{i}]"
        if not isinstance(c, dict):
            lec.error(r, "tiene que ser {que, por_que, impacto}")
            continue
        lec.claves(c, ("que", "por_que", "impacto"), r)
        impacto = lec.texto(c, "impacto", f"{r}.impacto")
        if impacto and impacto not in IMPACTOS:
            lec.error(f"{r}.impacto", f"tiene que ser {', '.join(IMPACTOS)}")
        cambios.append(Cambio(lec.texto(c, "que", f"{r}.que"), lec.texto(c, "por_que", f"{r}.por_que"), impacto))
    if isinstance(datos.get("mapa_cambios"), list) and len(lista) < _CAMBIOS_MIN:
        lec.error("mapa_cambios", f"hacen falta al menos {_CAMBIOS_MIN}, hay {len(lista)}")
    return tuple(cambios)


def _comparativa(lec: _Lector, datos: dict) -> tuple[tuple[str, str, str], ...]:
    filas = []
    lista = lec.lista(datos, "comparativa", "comparativa")
    for i, f in enumerate(lista):
        r = f"comparativa[{i}]"
        if not isinstance(f, dict):
            lec.error(r, "tiene que ser {aspecto, original, nuestra}")
            continue
        lec.claves(f, ("aspecto", "original", "nuestra"), r)
        filas.append((lec.texto(f, "aspecto", f"{r}.aspecto"), lec.texto(f, "original", f"{r}.original"),
                      lec.texto(f, "nuestra", f"{r}.nuestra")))
    if isinstance(datos.get("comparativa"), list) and not lista:
        lec.error("comparativa", "hace falta al menos una fila")
    return tuple(filas)


# --- carga -----------------------------------------------------------------------------------------


def cargar_modelado(ruta: Path, p_id: str, pais: str, idioma: str) -> Modelado:
    """Lee y valida ``modelar.yaml``. Lanza ``ModeladoInvalido`` con todos los errores juntos.

    Si el archivo trae un secreto se para ahí, con un único error que nombra el patrón (nunca el valor).
    ``RevisionSecretosNoDisponible`` se propaga: sin revisión de secretos no se sigue.
    """
    texto = Path(ruta).read_text(encoding="utf-8")
    patron = buscar_secreto(texto)
    if patron:
        raise ModeladoInvalido([f"secreto en modelar.yaml: {patron} (quítalo; nunca se guarda)"])
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        marca = getattr(exc, "problem_mark", None)
        donde = f" (línea {marca.line + 1})" if marca is not None else ""
        raise ModeladoInvalido([f"modelar.yaml: no es YAML válido{donde}"]) from None
    except ValueError:  # p. ej. una fecha sin comillas que no existe (2026-02-30)
        raise ModeladoInvalido(["modelar.yaml: no es YAML válido (hay una fecha o un valor que no existe)"]) from None
    if not isinstance(datos, dict):
        raise ModeladoInvalido(["modelar.yaml: tiene que ser un bloque de claves"])
    # Tras leerlo, los escapes (\x45, \u…, «\» de continuación) ya están resueltos: se revisa otra vez.
    patron = buscar_secreto("\n".join(valor for _, valor in _textos(datos, "")))
    if patron:
        raise ModeladoInvalido([f"secreto en modelar.yaml: {patron} (quítalo; nunca se guarda)"])

    lec = _Lector()
    lec.claves(datos, ("producto", "pais", "teardown", "ejes_original", "ejes_nuestra", "angulos_referencia", "core",
                       "escalera_piezas", "estructura_landing", "brandbook", "mapa_cambios", "comparativa"), "")
    producto = lec.texto(datos, "producto", "producto")
    if producto and producto != p_id:
        lec.error("producto", f"dice «{producto}» y se está modelando «{p_id}»")
    pais_yaml = lec.texto(datos, "pais", "pais")
    if pais_yaml and pais_yaml != pais:
        lec.error("pais", f"dice «{pais_yaml}» y se está modelando «{pais}»")
    teardown = _teardown(lec, datos)
    ejes_original = _ejes(lec, datos, "ejes_original")
    ejes_nuestra = _ejes(lec, datos, "ejes_nuestra")
    angulos = lec.textos(datos, "angulos_referencia", "angulos_referencia")
    core = _core(lec, datos)
    escalera_piezas = _escalera_piezas(lec, datos)
    estructura = _estructura_landing(lec, datos)
    brandbook = _brandbook(lec, datos, idioma, teardown.anunciante)
    cambios = _mapa_cambios(lec, datos)
    comparativa = _comparativa(lec, datos)
    for ruta_texto, valor in _textos(datos, ""):
        motivo = material_ajeno(valor, de_teardown=ruta_texto.startswith("teardown."))
        if motivo:
            lec.error(ruta_texto, motivo)
    if lec.errores:
        raise ModeladoInvalido(lec.errores)
    return Modelado(
        producto=producto, pais=pais_yaml, teardown=teardown, ejes_original=ejes_original,
        ejes_nuestra=ejes_nuestra, angulos_referencia=angulos, core=core, brandbook=brandbook,
        mapa_cambios=cambios, comparativa=comparativa, escalera_piezas=escalera_piezas,
        estructura_landing=estructura)
